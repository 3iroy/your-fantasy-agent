"""Historical points-league efficiency signals from actual ESPN game logs."""
import json
import math
import re
import time
from datetime import date, datetime, timezone
from threading import Lock
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from tools import ToolError, fetch_projections, normalize_name, validate_weights

_cache = {}
_lock = Lock()
ET = ZoneInfo('America/New_York')


def fetch_game_log(player_id, season):
    key = (player_id, season)
    with _lock:
        cached = _cache.get(key)
        if cached and time.monotonic() - cached[0] < 900:
            return cached[1], cached[2], True
    url = f'https://site.web.api.espn.com/apis/common/v3/sports/basketball/nba/athletes/{player_id}/gamelog?season={season}'
    try:
        with urlopen(Request(url, headers={'Accept': 'application/json'}), timeout=20) as response:
            data = json.load(response)
    except HTTPError as exc:
        if exc.code == 429:
            raise ToolError('ESPN_RATE_LIMIT', 'ESPN is limiting game-log requests.', 'Wait before retrying.', True) from exc
        if exc.code in (401, 403, 404):
            raise ToolError('GAME_LOG_UNAVAILABLE', 'ESPN game logs are unavailable for this player/season.',
                            'Check the full player name and season. Do not invent past performances.') from exc
        raise ToolError('ESPN_SERVICE_ERROR', 'ESPN could not provide game logs.', 'Retry later.', True) from exc
    except (URLError, TimeoutError) as exc:
        raise ToolError('ESPN_CONNECTION_ERROR', 'Could not reach ESPN game logs.', 'Retry later.', True) from exc
    except (ValueError, UnicodeError) as exc:
        raise ToolError('ESPN_INVALID_RESPONSE', 'ESPN returned invalid game-log JSON.', 'The developer must check the source format.') from exc
    if not isinstance(data, dict) or not isinstance(data.get('seasonTypes'), list):
        raise ToolError('GAME_LOG_FORMAT_CHANGED', 'Unexpected ESPN game-log format.', 'The developer must update the parser.')
    fetched = datetime.now(timezone.utc).isoformat()
    with _lock:
        if len(_cache) >= 64:
            _cache.pop(next(iter(_cache)))
        _cache[key] = (time.monotonic(), data, fetched)
    return data, fetched, False


def _number(raw):
    value = float(raw)
    if not math.isfinite(value) or value < 0:
        raise ValueError('invalid counting statistic')
    return value


def _minutes(raw):
    if isinstance(raw, str) and ':' in raw:
        minutes, seconds = raw.split(':')
        if not 0 <= float(seconds) < 60:
            raise ValueError('invalid seconds')
        return _number(minutes) + _number(seconds) / 60
    return _number(raw)


def _pair(raw):
    made, attempted = str(raw).split('-')
    made, attempted = _number(made), _number(attempted)
    if made > attempted:
        raise ValueError('made exceeds attempted')
    return made, attempted


def parse_games(data, season, cutoff, weights):
    """Filter by date BEFORE reading stats; never return later games to the model."""
    labels, events = data.get('labels'), data.get('events')
    if not isinstance(labels, list) or not isinstance(events, dict):
        raise ToolError('GAME_LOG_FORMAT_CHANGED', 'Game-log dates or stat labels are missing.', 'The developer must check the parser.')
    expected = f'{season - 1}-{str(season)[-2:]} Regular Season'
    sections = [s for s in data['seasonTypes'] if s.get('displayName') == expected]
    if not sections:
        raise ToolError('NO_REGULAR_SEASON_DATA', f'No {expected} game logs are available.',
                        'Use a completed season such as season=2026. Do not substitute preseason or projections.')
    games, seen, dnp = [], set(), 0
    for section in sections:
        for category in section.get('categories', []):
            for entry in category.get('events', []):
                event_id = entry.get('eventId')
                try:
                    event = events[str(event_id)]
                    stamp = datetime.fromisoformat(event['gameDate'].replace('Z', '+00:00'))
                    if stamp.tzinfo is None:
                        raise ValueError('missing time zone')
                    day = stamp.astimezone(ET).date()
                except (ValueError, TypeError, KeyError, AttributeError) as exc:
                    raise ToolError('INVALID_GAME_DATE', 'A regular-season game has no usable dated record.',
                                    'The source must supply valid dates before an as-of analysis can be trusted.') from exc
                if day > cutoff or str(event_id) in seen:
                    continue
                seen.add(str(event_id))
                try:
                    raw_stats = entry['stats']
                    if not isinstance(raw_stats, list) or len(raw_stats) != len(labels):
                        raise ValueError('stat columns do not match')
                    raw = dict(zip(labels, raw_stats))
                    minutes = _minutes(raw['MIN'])
                    if minutes == 0:
                        dnp += 1
                        continue
                    fgm, fga = _pair(raw['FG'])
                    tpm, tpa = _pair(raw['3PT'])
                    ftm, fta = _pair(raw['FT'])
                    stats = {key: _number(raw[key]) for key in ('PTS', 'REB', 'AST', 'STL', 'BLK', 'TO')}
                    stats.update(MIN=minutes, FGM=fgm, FGA=fga, FTM=ftm, FTA=fta,
                                 **{'3PM': tpm, '3PA': tpa, 'FGMI': fga-fgm, 'FTMI': fta-ftm, '3PMI': tpa-tpm})
                    score = sum(stats[key] * weight for key, weight in weights.items())
                except (ValueError, TypeError, KeyError) as exc:
                    raise ToolError('INCOMPLETE_GAME_STATS', f'Incomplete counting statistics for game {event_id} on {day}.',
                                    'Do not replace missing values with zero. The developer must inspect the game-log parser.') from exc
                games.append({'date': day.isoformat(), 'event_id': str(event_id),
                              'stats': stats, 'fantasy_points': score})
    games.sort(key=lambda g: (g['date'], g['event_id']))
    return games, dnp


def summarize(games, weights=None):
    n = len(games)
    totals = {key: sum(g['stats'][key] for g in games) for key in games[0]['stats']}
    fp = sum(g['fantasy_points'] for g in games)
    return {'games': n, 'start_date': games[0]['date'], 'end_date': games[-1]['date'],
            'fantasy_points_per_game': fp/n, 'fantasy_points_total': fp,
            'scoring_contributions_per_game': {key: totals[key]/n*weight for key, weight in (weights or {}).items()},
            'stats_per_game': {key: value/n for key, value in totals.items()},
            'fg_percentage': totals['FGM']/totals['FGA']*100 if totals['FGA'] else None,
            'three_point_percentage': totals['3PM']/totals['3PA']*100 if totals['3PA'] else None,
            'ft_percentage': totals['FTM']/totals['FTA']*100 if totals['FTA'] else None}


def pct_change(recent, baseline):
    return (recent/baseline-1)*100 if baseline > 0 else None


def compare(recent, baseline):
    changes = {'fantasy_points_percent': pct_change(recent['fantasy_points_per_game'], baseline['fantasy_points_per_game'])}
    for key in ('MIN', 'FGA', 'FTA', 'TO'):
        changes[key + '_percent'] = pct_change(recent['stats_per_game'][key], baseline['stats_per_game'][key])
    changes['fg_percentage_points'] = (recent['fg_percentage']-baseline['fg_percentage']
                                      if recent['fg_percentage'] is not None and baseline['fg_percentage'] is not None else None)
    changes['scoring_contribution_changes_per_game'] = {
        key: value - baseline['scoring_contributions_per_game'][key]
        for key, value in recent['scoring_contributions_per_game'].items()}
    return changes


def classify(changes):
    fp, minutes, shots, efficiency = [changes[key] for key in ('fantasy_points_percent', 'MIN_percent', 'FGA_percent', 'fg_percentage_points')]
    if any(value is None for value in (fp, minutes, shots, efficiency)):
        return 'insufficient_signal', 'The baseline cannot support all required percentage comparisons.'
    if fp <= -15:
        if minutes >= -10 and shots >= -10 and efficiency <= -5:
            return 'potential_buy_low', 'Scoring fell at least 15%, minutes and FGA fell no more than 10%, and FG% fell at least 5 percentage points.'
        if minutes < -10 or shots < -10:
            return 'opportunity_decline', 'Scoring declined alongside minutes or FGA; this is not a shooting-slump buy-low signal.'
        return 'decline_needs_context', 'Scoring declined, but the defined shooting-slump pattern is not present.'
    if fp >= 15:
        if abs(minutes) <= 10 and abs(shots) <= 10 and efficiency >= 5:
            return 'potential_sell_high', 'Scoring rose at least 15% with minutes/FGA within 10% of baseline and FG% up at least 5 percentage points.'
        return 'improvement_needs_context', 'Scoring improved without the defined efficiency-only sell-high pattern.'
    return 'no_clear_signal', 'Fantasy points changed by less than 15% from the disjoint earlier baseline.'


def rounded(value):
    if isinstance(value, float):
        return round(value, 3)
    if isinstance(value, dict):
        return {k: rounded(v) for k, v in value.items()}
    if isinstance(value, list):
        return [rounded(v) for v in value]
    return value


def today_et():
    return datetime.now(ET).date()


def analyze_buy_low_sell_high(player_name, scoring_weights, as_of_date=None, season=None):
    """Screen historical efficiency changes; not a prediction of future performance."""
    try:
        weights = validate_weights(scoring_weights)
        if not isinstance(player_name, str) or not player_name.strip() or len(player_name) > 100:
            raise ToolError('INVALID_PLAYER_NAME', 'Provide a full NBA player name.', 'Ask which player to analyze.')
        today = today_et()
        if as_of_date is None:
            as_of_date = today.isoformat()
        try:
            if not isinstance(as_of_date, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', as_of_date):
                raise ValueError('format')
            cutoff = date.fromisoformat(as_of_date)
        except ValueError as exc:
            raise ToolError('INVALID_AS_OF_DATE', 'as_of_date must be a real YYYY-MM-DD date.', 'Ask the user for the historical cutoff date.') from exc
        if season is None:
            season = cutoff.year + (1 if cutoff.month >= 7 else 0)
        if type(season) is not int or not 2020 <= season <= 2035:
            raise ToolError('INVALID_SEASON', 'Use an integer ESPN ending year.', 'Omit season to infer it from the cutoff, or use 2026 for 2025–26.')
        if cutoff > today:
            raise ToolError('FUTURE_AS_OF_DATE', 'Cannot analyze future actual performances.', 'Choose today or an earlier historical date.')
        if not date(season-1, 7, 1) <= cutoff <= date(season, 6, 30):
            raise ToolError('DATE_OUTSIDE_SEASON', 'The cutoff does not fall in the requested season.',
                            'Use season=2026 for dates from July 2025 through June 2026; actual regular-season games start later.')
        # Player-pool fields resolve identity ONLY, never historical projections/news.
        players, _, _ = fetch_projections(season)
        matches = [p.get('player', p) for p in players
                   if normalize_name(p.get('player', p).get('fullName', '')) == normalize_name(player_name)]
        if len(matches) != 1 or type(matches[0].get('id')) is not int:
            raise ToolError('PLAYER_NOT_FOUND', 'No unique ESPN player matches that full name in this season.',
                            'Ask for the full name as listed by ESPN; do not guess a player ID.')
        player = matches[0]
        data, fetched_at, cache_hit = fetch_game_log(player['id'], season)
        games, dnp = parse_games(data, season, cutoff, weights)
        if len(games) < 20:
            raise ToolError('INSUFFICIENT_HISTORY', f'Only {len(games)} played regular-season games are available on or before {as_of_date}.',
                            'Choose a later date with at least 20 appearances: 10 recent games and at least 10 earlier baseline games. Do not use future games to fill the window.')
        baseline = summarize(games[:-10], weights)
        recent10, recent4 = summarize(games[-10:], weights), summarize(games[-4:], weights)
        changes10, changes4 = compare(recent10, baseline), compare(recent4, baseline)
        signal, reason = classify(changes10)
        short_signal, _ = classify(changes4)
        warnings = [
            'Historical screening only; these thresholds are heuristics, not validated probabilities or proof of rebound/regression.',
            'Last 4 games are descriptive and overlap the last 10; classification uses last 10 versus the disjoint earlier baseline.',
            'FGA is an opportunity proxy, NOT usage rate. No team-possession data or usage rate is calculated.',
            'No contemporaneous news was fetched. Injury, role, opponent and schedule explanations remain unverified.',
            'Only played regular-season games count. DNPs do not count as zero-fantasy-point games; availability and weekly totals are not modeled.',
        ]
        if short_signal != signal:
            warnings.append('The last-4-game screen differs from the last-10-game screen; do not present the short fluctuation as a confirmed trend.')
        if signal in ('potential_buy_low', 'potential_sell_high') and any(key in weights for key in ('FGM', 'FGA', 'FGMI', '3PM', '3PA', '3PMI')):
            warnings.append('Shooting scoring is league-specific; this screen flags correlation and does not establish shooting efficiency as the sole cause.')
        return rounded({'ok': True, 'player': {'name': player['fullName'], 'player_id': player['id']},
                        'season': season, 'season_label': f'{season-1}–{season}',
                        'mode': 'as_of_today' if cutoff == today else 'historical_as_of', 'as_of_date': as_of_date, 'date_timezone': 'America/New_York',
                        'source': {'name': 'ESPN actual regular-season game logs',
                                   'url': f'https://www.espn.com/nba/player/gamelog/_/id/{player["id"]}?season={season}',
                                   'fetched_at_utc': fetched_at, 'cache_hit': cache_hit},
                        'scoring_weights': weights, 'formula': 'sum(actual game stat × user scoring weight)',
                        'games_used': len(games), 'zero_minute_records_excluded': dnp,
                        'baseline_before_last_10': baseline, 'last_10': recent10, 'last_4': recent4,
                        'season_to_date': summarize(games, weights), 'last_10_vs_baseline': changes10,
                        'last_4_vs_baseline': changes4, 'signal': signal, 'signal_reason': reason,
                        'thresholds': {'fantasy_points_change_percent': 15, 'opportunity_change_percent': 10,
                                       'fg_percentage_point_change': 5},
                        'recent_games': games[-10:],
                        'game_history': [{'date': g['date'], 'event_id': g['event_id'],
                                          'fantasy_points': g['fantasy_points']} for g in games],
                        'warnings': warnings})
    except ToolError as exc:
        return exc.result
