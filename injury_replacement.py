"""Historical injury-replacement screening from dated team box scores."""
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from threading import Lock
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from buy_low import ET, _minutes, _number, _pair, fetch_game_log, parse_games, rounded, today_et
from tools import ToolError, fetch_projections, normalize_name, validate_weights

_cache = {}
_lock = Lock()
BASE = 'https://site.api.espn.com/apis/site/v2/sports/basketball/nba/'


def fetch_json(path):
    with _lock:
        cached = _cache.get(path)
        if cached and time.monotonic()-cached[0] < 3600:
            return cached[1]
    try:
        with urlopen(Request(BASE+path, headers={'Accept': 'application/json'}), timeout=15) as response:
            data = json.load(response)
    except HTTPError as exc:
        raise ToolError('ESPN_REPLACEMENT_DATA_UNAVAILABLE', f'ESPN returned HTTP {exc.code} for historical team data.',
                        'Retry later or choose another historical date. Do not invent rosters or replacements.', exc.code == 429 or exc.code >= 500) from exc
    except (URLError, TimeoutError) as exc:
        raise ToolError('ESPN_CONNECTION_ERROR', 'The historical team-data request could not connect.', 'Retry later.', True) from exc
    except (ValueError, UnicodeError) as exc:
        raise ToolError('ESPN_INVALID_RESPONSE', 'Historical team data was not valid JSON.', 'The developer must check the data feed.') from exc
    if not isinstance(data, dict):
        raise ToolError('ESPN_FORMAT_CHANGED', 'Unexpected historical team-data format.', 'The developer must update the parser.')
    with _lock:
        if len(_cache) >= 180:
            _cache.pop(next(iter(_cache)))
        _cache[path] = (time.monotonic(), data)
    return data


def event_date(stamp):
    parsed = datetime.fromisoformat(stamp.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('missing timestamp timezone')
    return parsed.astimezone(ET).date()


def select_team_events(schedule, season, cutoff):
    events = schedule.get('events')
    if not isinstance(events, list):
        raise ToolError('SCHEDULE_FORMAT_CHANGED', 'ESPN did not return a team schedule.', 'The developer must inspect the schedule parser.')
    selected = {}
    for event in events:
        if event.get('season', {}).get('year') != season or str(event.get('seasonType', {}).get('type')) != '2':
            continue
        try:
            day = event_date(event['date'])
            competitions = event['competitions']
            completed = competitions[0]['status']['type']['completed']
            event_id = str(event['id'])
            if not event_id.isdigit():
                raise ValueError('invalid event ID')
        except (ValueError, KeyError, TypeError, IndexError, AttributeError) as exc:
            raise ToolError('INVALID_SCHEDULE_EVENT', 'A historical game has missing date/status fields.', 'The developer must check the schedule before computing ranks.') from exc
        if day <= cutoff and completed:
            selected[event_id] = {'event_id': event_id, 'date': day.isoformat()}
    result = sorted(selected.values(), key=lambda g: (g['date'], g['event_id']))
    if len(result) > 85:
        raise ToolError('UNEXPECTED_SEASON_LENGTH', 'The regular-season schedule contains too many games.', 'Check for duplicated games or mixed seasons.')
    if len(result) < 5:
        raise ToolError('INSUFFICIENT_TEAM_HISTORY', 'Fewer than five completed regular-season games precede the cutoff.', 'Choose a later historical date.')
    return result


def parse_box(data, game, team_id, season, weights):
    try:
        header = data['header']
        if header['season']['year'] != season or int(header['season']['type']) != 2:
            raise ValueError('wrong season')
        if str(header['id']) != game['event_id'] or event_date(header['competitions'][0]['date']).isoformat() != game['date']:
            raise ValueError('wrong game/date')
        if not header['competitions'][0]['status']['type']['completed']:
            raise ValueError('incomplete game')
        blocks = data['boxscore']['players']
        block = next(b for b in blocks if str(b['team']['id']) == str(team_id))
        records = {}
        for group in block['statistics']:
            labels = group['labels']
            for row in group['athletes']:
                athlete = row['athlete']
                pid = int(athlete['id'])
                record = {'player_id': pid, 'name': athlete['displayName'],
                          'position': athlete.get('position', {}).get('abbreviation', 'Unknown'),
                          'played': False, 'minutes': 0.0, 'fantasy_points': None,
                          'dnp_reason': row.get('reason') if row.get('didNotPlay') else None}
                if not row.get('didNotPlay'):
                    if len(row['stats']) != len(labels):
                        raise ValueError('missing counting stats')
                    stats = dict(zip(labels, row['stats']))
                    if stats['MIN'] == '--':
                        # ESPN sometimes marks a zero-stat non-participant as
                        # didNotPlay=false with a missing minute value.
                        # Accept only a fully verified zero counting-stat row.
                        for key in ('FG', '3PT', 'FT'):
                            if _pair(stats[key]) != (0, 0):
                                raise ValueError('missing minutes with recorded production')
                        for key in ('PTS', 'REB', 'AST', 'STL', 'BLK', 'TO', 'OREB', 'DREB', 'PF'):
                            if key in stats and _number(stats[key]) != 0:
                                raise ValueError('missing minutes with recorded production')
                        record['dnp_reason'] = row.get('reason')
                        records[pid] = record
                        continue
                    minutes = _minutes(stats['MIN'])
                    if minutes > 0:
                        fgm, fga = _pair(stats['FG']); tpm, tpa = _pair(stats['3PT']); ftm, fta = _pair(stats['FT'])
                        numbers = {key: _number(stats[key]) for key in ('PTS', 'REB', 'AST', 'STL', 'BLK', 'TO')}
                        numbers.update(FGM=fgm, FGA=fga, FTM=ftm, FTA=fta,
                                       **{'3PM': tpm, '3PA': tpa, 'FGMI': fga-fgm, 'FTMI': fta-ftm, '3PMI': tpa-tpm})
                        record.update(played=True, minutes=minutes,
                                      fantasy_points=sum(numbers[key]*weight for key, weight in weights.items()))
                records[pid] = record
        if not records:
            raise ValueError('empty box score')
        return {**game, 'players': records, 'team': block['team'],
                'article': data.get('article'),
                'source_url': 'https://www.espn.com/nba/boxscore/_/gameId/'+game['event_id']}
    except (ValueError, TypeError, KeyError, StopIteration, AttributeError) as exc:
        raise ToolError('INCOMPLETE_TEAM_BOX_SCORE', f'Historical box score {game["event_id"]} could not be verified or parsed.',
                        'Do not calculate a partial team ranking. The developer must inspect the box-score fields.') from exc


def dated_articles(boxes, player_name, cutoff):
    result, seen = [], set()
    surname = player_name.split()[-1].casefold()
    for box in boxes:
        article = box.get('article')
        if not isinstance(article, dict) or article.get('id') in seen:
            continue
        headline, description = article.get('headline', ''), article.get('description', '')
        text = (headline+' '+description).casefold()
        if not re.search(r'\b'+re.escape(surname)+r'\b', text):
            continue
        try:
            posted = article['published']
            if event_date(posted) > cutoff:
                continue
            if article.get('lastModified') and event_date(article['lastModified']) > cutoff:
                continue
            article_id = int(article['id'])
        except (ValueError, TypeError, KeyError, AttributeError):
            continue
        seen.add(article_id)
        result.append({'headline': headline, 'description': description[:600], 'published': posted,
                       'url': 'https://www.espn.com/nba/story/_/id/'+str(article_id),
                       'mentions_injury': bool(re.search(r'\b(injur\w*|sprain\w*|strain\w*|fractur\w*|surgery|torn)\b', text))})
    return sorted(result, key=lambda a: a['published'], reverse=True)[:5]


def screen_replacements(boxes, target_id):
    totals = {}
    for box in boxes:
        for pid, record in box['players'].items():
            if not record['played']:
                continue
            total = totals.setdefault(pid, {'player_id': pid, 'name': record['name'], 'position': record['position'],
                                           'games': 0, 'points': 0.0, 'minutes': 0.0})
            total['games'] += 1; total['points'] += record['fantasy_points']; total['minutes'] += record['minutes']
    ranking = sorted(totals.values(), key=lambda p: (-p['points']/p['games'], p['name']))
    for rank, player in enumerate(ranking, 1):
        player.update(team_rank=rank, fantasy_points_per_game=player['points']/player['games'],
                      minutes_per_game=player['minutes']/player['games'])
    if len(ranking) <= 6:
        raise ToolError('INSUFFICIENT_TEAM_PLAYERS', 'At most six players have usable team-season stats.', 'Choose a later date; do not bypass the top-six exclusion.')
    excluded = ranking[:6]
    excluded_ids = {p['player_id'] for p in excluded}
    latest_roster = boxes[-1]['players']
    candidates = []
    # Matched recent window reduces old-rotation effects; all games end before cutoff.
    comparison_boxes = boxes[-20:]
    with_target = [b for b in comparison_boxes if b['players'].get(target_id, {}).get('played')]
    without_target = [b for b in comparison_boxes if not b['players'].get(target_id, {}).get('played')]
    for player in ranking:
        pid = player['player_id']
        if pid in excluded_ids or pid == target_id or pid not in latest_roster:
            continue
        latest = latest_roster[pid]
        reason = latest.get('dnp_reason') or ''
        if not latest['played'] and re.search(r'injur|illness|sprain|strain|surgery|fractur', reason, re.I):
            continue
        recent = [b['players'][pid] for b in boxes[-4:] if b['players'].get(pid, {}).get('played')]
        if not recent:
            continue
        def group_stats(group):
            observed = [b['players'].get(pid, {}) for b in group]
            appearances = [p for p in observed if p.get('played')]
            return {'team_games': len(group), 'appearances': len(appearances),
                    'minutes_per_team_game': sum(p.get('minutes', 0) for p in observed)/len(group) if group else None,
                    'minutes_per_appearance': sum(p['minutes'] for p in appearances)/len(appearances) if appearances else None,
                    'fantasy_points_per_appearance': sum(p['fantasy_points'] for p in appearances)/len(appearances) if appearances else None}
        present, absent = group_stats(with_target), group_stats(without_target)
        enough = len(with_target) >= 3 and len(without_target) >= 3 and present['appearances'] >= 3 and absent['appearances'] >= 3
        delta = absent['minutes_per_team_game']-present['minutes_per_team_game'] if enough else None
        candidates.append({k: player[k] for k in ('player_id', 'name', 'position', 'team_rank', 'games', 'fantasy_points_per_game', 'minutes_per_game')} | {
            'recent_4_team_games_appearances': len(recent),
            'recent_minutes_per_appearance': sum(p['minutes'] for p in recent)/len(recent),
            'recent_fantasy_points_per_appearance': sum(p['fantasy_points'] for p in recent)/len(recent),
            'target_present': present, 'target_absent': absent,
            'observed_minutes_difference_per_team_game': delta,
            'evidence_level': 'observed_absence_comparison' if enough else 'rotation_watch_only_insufficient_comparison',
            'latest_dnp_reason': latest.get('dnp_reason'),
            'latest_appearance': next(b['date'] for b in reversed(boxes) if b['players'].get(pid, {}).get('played')),
        })
    candidates.sort(key=lambda p: (p['observed_minutes_difference_per_team_game'] is not None and p['observed_minutes_difference_per_team_game'] > 0,
                                   p['observed_minutes_difference_per_team_game'] or 0,
                                   p['recent_minutes_per_appearance']), reverse=True)
    return candidates[:3], excluded, {'start_date': comparison_boxes[0]['date'], 'end_date': comparison_boxes[-1]['date'],
                                     'target_present_team_games': len(with_target), 'target_absent_team_games': len(without_target)}


def analyze_injury_replacements(injured_player, scoring_weights, as_of_date=None, season=2026):
    try:
        weights = validate_weights(scoring_weights)
        if season != 2026 or type(season) is not int:
            raise ToolError('UNSUPPORTED_REPLACEMENT_SEASON', 'This first version supports 2025–26 only (ending year 2026).', 'Use season=2026 for historical injury-replacement analysis.')
        if not isinstance(injured_player, str) or not injured_player.strip() or len(injured_player) > 100:
            raise ToolError('INVALID_PLAYER_NAME', 'Provide a full injured-player name.', 'Ask who needs an injury replacement.')
        if as_of_date is None:
            as_of_date = '2026-06-30'
        try:
            if not isinstance(as_of_date, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', as_of_date):
                raise ValueError('bad date')
            cutoff = date.fromisoformat(as_of_date)
        except ValueError as exc:
            raise ToolError('INVALID_AS_OF_DATE', 'Use a real YYYY-MM-DD cutoff.', 'Provide the historical injury date.') from exc
        if not date(2025, 7, 1) <= cutoff <= date(2026, 6, 30) or cutoff > today_et():
            raise ToolError('DATE_OUTSIDE_SEASON', 'Choose a past cutoff in the 2025–26 season.', 'Provide a date from July 2025 through June 2026.')
        players, _, _ = fetch_projections(2026)
        matches = [p.get('player', p) for p in players if normalize_name(p.get('player', p).get('fullName', '')) == normalize_name(injured_player)]
        if len(matches) != 1 or type(matches[0].get('id')) is not int:
            raise ToolError('PLAYER_NOT_FOUND', 'No unique ESPN player matches this full name.', 'Use the full name listed by ESPN.')
        target = matches[0]
        log, _, _ = fetch_game_log(target['id'], 2026)
        target_games, _ = parse_games(log, 2026, cutoff, weights)
        if not target_games:
            raise ToolError('NO_TARGET_APPEARANCE', 'No target appearances precede the cutoff, so historical team identity cannot be verified.', 'Choose a later cutoff or another player; do not guess from the current roster.')
        latest_event = log['events'][target_games[-1]['event_id']]
        team_id = str(latest_event.get('team', {}).get('id', ''))
        if not team_id.isdigit():
            raise ToolError('HISTORICAL_TEAM_UNKNOWN', 'The game log does not identify the player’s historical team.', 'The developer must inspect team identity before suggesting replacements.')
        schedule = fetch_json(f'teams/{team_id}/schedule?season=2026&seasontype=2')
        events = select_team_events(schedule, 2026, cutoff)
        def load(game):
            return parse_box(fetch_json('summary?event='+game['event_id']), game, team_id, 2026, weights)
        # Fail rather than compute ranks from a partial season if any request fails.
        with ThreadPoolExecutor(max_workers=4) as pool:
            boxes = list(pool.map(load, events))
        candidates, excluded, comparison = screen_replacements(boxes, target['id'])
        articles = dated_articles(boxes[-10:], target['fullName'], cutoff)
        target_played_latest = boxes[-1]['players'].get(target['id'], {}).get('played', False)
        warnings = [
            'Historical 2025–26 analysis only; not current injury status, current FA availability, or a verified current roster.',
            'Top six are ranked by custom actual FP/G among all team-season participants through the cutoff, including past team participants; candidate membership uses the latest dated box score, not an archived complete roster.',
            'Target absence is not automatically injury; it may reflect rest, a trade, or omission from the game roster. Verify the dated report and user scenario.',
            'Observed teammate minutes differences do not prove who absorbed the target’s minutes; concurrent injuries, opponents, overtime and changing rotations can confound the comparison.',
            'No minutes are allocated or projected, and no return date is invented. With fewer than three appearances in each comparison group, candidates are rotation watch only.',
            'Excluding the team’s top six is a waiver-candidate heuristic, not proof anyone is a free agent in your league.',
        ]
        if target_played_latest:
            warnings.append('The target played in the latest completed game. Treat this as an injury scenario, not a confirmed ongoing absence.')
        if not any(a['mentions_injury'] for a in articles):
            warnings.append('No verified injury mention was found in the available pre-cutoff game recaps. The injury premise remains user-provided.')
        if not candidates:
            warnings.append('No eligible lower-ranked rotation candidates remain after the top-six exclusion; no substitutes are invented.')
        return rounded({'ok': True, 'mode': 'historical_injury_scenario', 'season': 2026, 'season_label': '2025–26',
                        'as_of_date': as_of_date, 'date_timezone': 'America/New_York',
                        'injured_player': {'name': target['fullName'], 'player_id': target['id'],
                                           'last_appearance_by_cutoff': target_games[-1]['date'],
                                           'played_latest_team_game': target_played_latest},
                        'team': {'id': team_id, 'name': boxes[-1]['team'].get('displayName')},
                        'scoring_weights': weights, 'team_games_analyzed': len(boxes),
                        'ranking_basis': 'actual team-season fantasy points per played appearance through cutoff',
                        'excluded_top_six': [{k:p[k] for k in ('name','player_id','team_rank','games','fantasy_points_per_game')} for p in excluded],
                        'comparison_window': comparison, 'candidates': candidates,
                        'dated_game_reports': articles,
                        'source': {'name': 'ESPN historical regular-season team box scores',
                                   'url': f'https://www.espn.com/nba/team/schedule/_/name/{boxes[-1]["team"].get("abbreviation", "").lower()}?season=2026',
                                   'latest_box_score_url': boxes[-1]['source_url'],
                                   'fetched_at_utc': datetime.now(timezone.utc).isoformat()},
                        'warnings': warnings})
    except ToolError as exc:
        return exc.result


def analyze_current_injury_scenario(injured_player, scoring_weights, season=2027, available_players=None):
    """Current-roster hypothetical screen; historical evidence never becomes a forecast."""
    from tools import build_rankings, error
    try:
        weights = validate_weights(scoring_weights)
        if type(season) is not int or season != 2027:
            raise ToolError('UNSUPPORTED_SCENARIO_SEASON', 'Current scenario mode supports 2026–27 only.', 'Use season=2027, or the historical replacement tool for 2025–26.')
        if not isinstance(injured_player, str) or not injured_player.strip():
            raise ToolError('INVALID_PLAYER_NAME', 'A full injured-player name is required.', 'Provide the ESPN full name.')
        if available_players is not None and (not isinstance(available_players, list) or len(available_players) > 100 or any(not isinstance(n, str) or not n.strip() for n in available_players)):
            raise ToolError('INVALID_FA_LIST', 'available_players must be a list of up to 100 player names.', 'Supply full names copied from your FA list.')
        pool, fetched, _ = fetch_projections(season)
        players = [r.get('player', r) for r in pool]
        matches = [p for p in players if normalize_name(p.get('fullName', '')) == normalize_name(injured_player)]
        if len(matches) != 1:
            raise ToolError('PLAYER_NOT_FOUND', 'The name does not uniquely match the projection player pool.', 'Use the full ESPN player name.')
        target = matches[0]
        team_id = str(target.get('proTeamId', ''))
        if not team_id.isdigit() or team_id == '0':
            raise ToolError('CURRENT_TEAM_UNKNOWN', 'The player has no verifiable current team.', 'Try another player or wait for ESPN to update its roster.')
        roster = fetch_json(f'teams/{team_id}/roster')
        athletes = roster.get('athletes', [])
        if roster.get('season', {}).get('year') != season or not any(str(a.get('id')) == str(target['id']) for a in athletes):
            raise ToolError('CURRENT_ROSTER_MISMATCH', 'The current ESPN roster does not verify this player in the requested season.', 'Do not use a historical roster as current. Retry after ESPN updates its data.')
        ids = {int(a['id']) for a in athletes}
        ranked, _ = build_rankings([p for p in players if p.get('id') in ids], season, weights)
        if len(ranked) < 7:
            raise ToolError('INSUFFICIENT_TEAM_PROJECTIONS', 'Fewer than seven current roster players have complete scoring projections.', 'Cannot safely apply the top-six exclusion. Try later or another team.')
        excluded = ranked[:6]
        roster_by_id = {int(a['id']): a for a in athletes}
        projected_ids = {p['player_id'] for p in ranked}
        allowed = None if available_players is None else {normalize_name(n) for n in available_players}
        known_names = {normalize_name(p.get('fullName', '')) for p in players}
        if allowed is not None and allowed - known_names:
            raise ToolError('UNKNOWN_FA_NAMES', 'Some supplied FA names are not recognized: '+', '.join(n for n in available_players if normalize_name(n) not in known_names), 'Correct the full player names; no partial FA filter was applied.')
        candidates = []
        for team_rank, p in enumerate(ranked, 1):
            if team_rank <= 6 or p['player_id'] == target['id'] or (allowed is not None and normalize_name(p['name']) not in allowed):
                continue
            p = dict(p, team_rank=team_rank)
            a = roster_by_id[p['player_id']]
            p['current_injury_snapshot'] = [{'status': q.get('status'), 'date': q.get('date')} for q in a.get('injuries', [])]
            if any(str(q.get('status', '')).casefold() in ('out', 'injured reserve', 'suspension') for q in a.get('injuries', [])):
                continue
            target_pos = target.get('defaultPositionId')
            target_label = {1:'PG', 2:'SG', 3:'SF', 4:'PF', 5:'C'}.get(target_pos)
            eligible = set(p['eligible_positions']) | {p['position']}
            p['position_fit'] = 'same_position' if target_label in eligible else ('adjacent_frontcourt' if target_label in ('C','PF') and eligible & {'C','PF'} else 'indirect_rotation_watch')
            p['historical_evidence'] = None
            candidates.append(p)
        # Missing forecasts do not erase a verified rotation player. Keep these
        # as watch-only candidates and require actual same-team absence evidence.
        from tools import POSITIONS, SLOTS
        for player in players:
            pid = player.get('id')
            if pid not in ids or pid in projected_ids or pid == target['id']:
                continue
            if allowed is not None and normalize_name(player.get('fullName', '')) not in allowed:
                continue
            a = roster_by_id[pid]
            injuries = [{'status': q.get('status'), 'date': q.get('date')} for q in a.get('injuries', [])]
            if any(str(q.get('status', '')).casefold() in ('out', 'injured reserve', 'suspension') for q in injuries):
                continue
            position = POSITIONS.get(player.get('defaultPositionId'), 'Unknown')
            eligible = {SLOTS[slot] for slot in player.get('eligibleSlots', []) if slot in SLOTS} | {position}
            target_label = POSITIONS.get(target.get('defaultPositionId'))
            fit = 'same_position' if target_label in eligible else ('adjacent_frontcourt' if target_label in ('C','PF') and eligible & {'C','PF'} else 'indirect_rotation_watch')
            if fit == 'indirect_rotation_watch':
                continue
            candidates.append({'player_id': pid, 'name': player['fullName'], 'position': position,
                               'eligible_positions': sorted(eligible), 'team_rank': None,
                               'projected_fantasy_points_per_game': None,
                               'projection_status': 'unavailable_watch_only_not_ranked',
                               'position_fit': fit, 'current_injury_snapshot': injuries,
                               'historical_evidence': None})
        warnings = [
            'Hypothetical current-roster scenario; this does not assert the target is injured.',
            'Top six are excluded by complete 2026–27 custom projected FP/G, not guaranteed actual FA availability.',
            'Position fit is a screening heuristic, not a verified depth-chart order or allocation of vacated minutes.',
            'Projection FP/G is the original healthy-role forecast, NOT an injury-adjusted forecast.',
            'Roster injury snapshots are not full news reports; no coach statements or return dates are inferred.',
            'Historical absences may reflect rest or other causes; teammates, trades and rotations changed across seasons.',
        ]
        # Historical evidence is optional and explicitly separated from current projections.
        try:
            cutoff = date(2026, 6, 30)
            schedule = select_team_events(fetch_json(f'teams/{team_id}/schedule?season=2026&seasontype=2'), 2026, cutoff)
            team_dates = {g['date'] for g in schedule}
            def team_games(pid):
                log, _, _ = fetch_game_log(pid, 2026)
                games, _ = parse_games(log, 2026, cutoff, weights)
                return [g for g in games if g['date'] in team_dates and str(log.get('events', {}).get(g['event_id'], {}).get('team', {}).get('id')) == team_id]
            present_dates = {g['date'] for g in team_games(target['id'])}
            if not present_dates:
                raise ToolError('NO_PREVIOUS_TEAM_HISTORY', 'No target appearances on this team last season.', 'Use position-based watch candidates only.')
            for p in candidates:
                try:
                    games = team_games(p['player_id'])
                    present = [g for g in games if g['date'] in present_dates]
                    absent = [g for g in games if g['date'] not in present_dates]
                    enough = len(present) >= 3 and len(absent) >= 3
                    def avg(group, key):
                        return sum(g['stats']['MIN'] if key == 'minutes' else g[key] for g in group)/len(group) if group else None
                    p['historical_evidence'] = {
                        'season': 2026, 'basis': '2025–26 same-team played appearances; whole regular season',
                        'target_present_appearances': len(present), 'target_absent_appearances': len(absent),
                        'minutes_with_target': avg(present, 'minutes'), 'minutes_without_target': avg(absent, 'minutes'),
                        'fantasy_points_without_target': avg(absent, 'fantasy_points'),
                        'observed_minutes_difference_per_appearance': avg(absent, 'minutes')-avg(present, 'minutes') if enough else None,
                        'evidence_level': 'historical_comparison' if enough else 'insufficient_sample',
                    }
                except ToolError as exc:
                    p['historical_evidence'] = {'evidence_level': 'unavailable', 'message': exc.result['message']}
        except ToolError as exc:
            warnings.append('Optional historical evidence unavailable: '+exc.result['message'])
        def priority(p):
            evidence = p.get('historical_evidence') or {}
            delta = evidence.get('observed_minutes_difference_per_appearance')
            return (p['position_fit'] != 'same_position', p['position_fit'] == 'indirect_rotation_watch', -(delta if delta is not None else 0), -(p['projected_fantasy_points_per_game'] if p['projected_fantasy_points_per_game'] is not None else 0))
        candidates = [p for p in candidates if p.get('projection_status') != 'unavailable_watch_only_not_ranked' or (p.get('historical_evidence') or {}).get('evidence_level') == 'historical_comparison']
        candidates.sort(key=priority)
        # Do not fill a center-replacement list with unrelated guards/wings.
        indirect = [p['name'] for p in candidates if p['position_fit'] == 'indirect_rotation_watch']
        candidates = [p for p in candidates if p['position_fit'] != 'indirect_rotation_watch']
        if indirect:
            warnings.append('Unrelated-position candidates were not used to fill three choices: '+', '.join(indirect))
        missing = [a.get('fullName', a.get('displayName')) for a in athletes if int(a['id']) not in projected_ids]
        if missing:
            warnings.append('Roster players without complete projections cannot be ranked; position-fit players with sufficient historical comparison may be watch-only candidates. Top-six exclusion covers projected players only: '+', '.join(missing))
        if not candidates:
            warnings.append('No candidates remain after top-six, target, current-out-status and optional FA-list exclusions.')
        return rounded({'ok': True, 'mode': 'current_hypothetical_injury', 'season': season,
                        'as_of_date': today_et().isoformat(), 'team': roster['team'],
                        'injured_player': {'name': target['fullName'], 'player_id': target['id']},
                        'scoring_weights': weights, 'excluded_top_six': excluded, 'candidates': candidates[:3],
                        'availability_basis': 'user-provided FA list' if allowed is not None else 'unknown; verify in your league',
                        'unprojected_roster_players': missing, 'warnings': warnings,
                        'source': {'roster_url': BASE+f'teams/{team_id}/roster', 'projection_fetched_at_utc': fetched,
                                   'fetched_at_utc': datetime.now(timezone.utc).isoformat(),
                                   'historical_schedule_url': BASE+f'teams/{team_id}/schedule?season=2026&seasontype=2'}})
    except ToolError as exc:
        return exc.result
