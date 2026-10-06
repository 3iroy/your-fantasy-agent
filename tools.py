"""ESPN-backed, deterministic points-league ranking tool.

Projection stat IDs reference espn-api/basketball/constant.py. We use season
totals only (source=1, split=0), never ESPN's league-specific applied points.
"""

import json
import logging
import math
import time
import unicodedata
from datetime import datetime, timezone
from threading import Lock
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)
STAT_IDS = {
    'PTS': '0', 'REB': '6', 'AST': '3', 'STL': '2', 'BLK': '1',
    'TO': '11', 'FGM': '13', 'FGA': '14', 'FTM': '15', 'FTA': '16',
    '3PM': '17', '3PA': '18', 'FGMI': '23', 'FTMI': '24', '3PMI': '25',
}
STAT_DESCRIPTIONS = {
    'PTS': 'Points scored', 'REB': 'Total rebounds', 'AST': 'Assists',
    'STL': 'Steals', 'BLK': 'Blocks', 'TO': 'Turnovers (usually negative)',
    'FGM': 'Field goals made', 'FGA': 'Field goals attempted (often negative)',
    'FTM': 'Free throws made', 'FTA': 'Free throws attempted (often negative)',
    '3PM': 'Three-point field goals made', '3PA': 'Three-point attempts',
    'FGMI': 'Field goals missed', 'FTMI': 'Free throws missed',
    '3PMI': 'Three-point field goals missed',
}
POSITIONS = {1: 'PG', 2: 'SG', 3: 'SF', 4: 'PF', 5: 'C'}
SLOTS = {0: 'PG', 1: 'SG', 2: 'SF', 3: 'PF', 4: 'C'}
SOURCE_PAGE = 'https://fantasy.espn.com/basketball/players/projections'
CACHE_TTL = 900
_cache = {}
_cache_lock = Lock()


class ToolError(Exception):
    def __init__(self, code, message, next_step, retryable=False):
        super().__init__(message)
        self.result = {'ok': False, 'error': code, 'message': message,
                       'next_step': next_step, 'retryable': retryable}


def error(code, message, next_step, retryable=False):
    return ToolError(code, message, next_step, retryable).result


def validate_weights(weights):
    if not isinstance(weights, dict) or not weights:
        raise ToolError('MISSING_SCORING', 'No scoring rules were provided.',
                        'Ask the user for points per statistic or explicit permission to use ESPN defaults.')
    unsupported = set(weights) - set(STAT_IDS)
    if unsupported:
        raise ToolError('UNSUPPORTED_METRICS', f'Unsupported metrics: {", ".join(sorted(unsupported))}.',
                        f'Use only {", ".join(STAT_IDS)}. Percentage scoring and double/triple-double bonuses are not supported yet; do not silently omit them.')
    if any(isinstance(value, bool) or not isinstance(value, (int, float))
           or not math.isfinite(value) or abs(value) > 100 for value in weights.values()):
        raise ToolError('INVALID_WEIGHTS', 'Each scoring weight must be a finite number between -100 and 100.',
                        'Ask for numeric scoring weights; a turnover penalty should be negative.')
    if not any(weights.values()):
        raise ToolError('ZERO_SCORING', 'All scoring weights are zero.',
                        'Ask the user for at least one nonzero scoring weight.')
    return {key: float(value) for key, value in weights.items() if value != 0}


def fetch_projections(season):
    """Fetch the entire player pool; ESPN's unfiltered response only has 50 rows."""
    with _cache_lock:
        cached = _cache.get(season)
        if cached and time.monotonic() - cached['cached_at'] < CACHE_TTL:
            return cached['players'], cached['fetched_at'], True
        endpoint = f'https://lm-api-reads.fantasy.espn.com/apis/v3/games/fba/seasons/{season}/players'
        filters = {'players': {'limit': 5000, 'filterStatsForTopScoringPeriodIds': {
            'value': 1, 'additionalValue': [f'10{season}']}}}
        req = Request(endpoint + '?view=kona_player_info', headers={
            'x-fantasy-filter': json.dumps(filters), 'Accept': 'application/json',
        })
        try:
            with urlopen(req, timeout=20) as response:
                data = json.load(response)
        except HTTPError as exc:
            if exc.code in (401, 403):
                raise ToolError('ESPN_ACCESS_DENIED', 'ESPN denied access to its public projection feed.',
                                'Tell the user projections are unavailable. Do not ask for account cookies or invent rankings.') from exc
            if exc.code == 404:
                raise ToolError('SEASON_UNAVAILABLE', f'ESPN has no accessible feed for season {season}.',
                                'Ask the user to select a season with published projections.') from exc
            if exc.code == 429:
                raise ToolError('ESPN_RATE_LIMIT', 'ESPN is limiting requests.',
                                'Ask the user to wait before retrying.', True) from exc
            raise ToolError('ESPN_SERVICE_ERROR', f'ESPN returned HTTP {exc.code}.',
                            'Tell the user the data source is temporarily unavailable and suggest retrying later.', True) from exc
        except (TimeoutError, URLError) as exc:
            raise ToolError('ESPN_CONNECTION_ERROR', 'The ESPN projection request timed out or could not connect.',
                            'Tell the user to retry later; do not use fabricated projections.', True) from exc
        except (ValueError, UnicodeError) as exc:
            raise ToolError('ESPN_INVALID_RESPONSE', 'ESPN did not return valid JSON.',
                            'Tell the user the feed format needs checking before rankings can be produced.') from exc
        players = data if isinstance(data, list) else data.get('players') if isinstance(data, dict) else None
        if not isinstance(players, list) or not players or any(not isinstance(row, dict) for row in players):
            raise ToolError('ESPN_FORMAT_CHANGED', 'ESPN returned an unexpected player-data format.',
                            'Report that the feed parser needs updating; do not invent player data.')
        if len(players) >= 5000:
            raise ToolError('INCOMPLETE_PLAYER_POOL', 'The ESPN response reached the requested player limit.',
                            'The developer must add pagination before claiming a complete ranking.')
        fetched_at = datetime.now(timezone.utc).isoformat()
        # Bounded cache: no persisted data or credentials are written to the repo.
        if len(_cache) >= 3:
            _cache.pop(next(iter(_cache)))
        _cache[season] = {'players': players, 'fetched_at': fetched_at, 'cached_at': time.monotonic()}
        return players, fetched_at, False


def normalize_name(name):
    return ''.join(char for char in unicodedata.normalize('NFKD', name).casefold()
                   if char.isalnum())


def build_rankings(players, season, weights):
    ranked, skipped = [], 0
    seen = set()
    for row in players:
        player = row.get('player', row)
        if not isinstance(player, dict) or not isinstance(player.get('fullName'), str):
            skipped += 1
            continue
        stats = player.get('stats', [])
        if not isinstance(stats, list):
            skipped += 1
            continue
        block = next((item for item in stats if isinstance(item, dict)
                      and item.get('seasonId') == season and item.get('statSourceId') == 1
                      and item.get('statSplitTypeId') == 0), None)
        if not block or not isinstance(block.get('stats'), dict):
            skipped += 1
            continue
        totals = block['stats']
        gp = totals.get('42')
        needed = {key: totals.get(STAT_IDS[key]) for key in weights}
        numbers = [gp, *needed.values()]
        if any(isinstance(value, bool) or not isinstance(value, (int, float))
               or not math.isfinite(value) or value < 0 for value in numbers) or not 0 < gp <= 82:
            skipped += 1
            continue
        player_id = player.get('id')
        if player_id in seen:
            continue
        seen.add(player_id)
        contributions = {key: value / gp * weights[key] for key, value in needed.items()}
        total = sum(value * weights[key] for key, value in needed.items())
        ranked.append({
            'player_id': player_id, 'name': player['fullName'],
            'position': POSITIONS.get(player.get('defaultPositionId'), 'Unknown'),
            'eligible_positions': [SLOTS[slot] for slot in player.get('eligibleSlots', []) if slot in SLOTS],
            'projected_games': gp,
            'projected_fantasy_points_per_game': total / gp,
            'projected_fantasy_points_total': round(total, 3),
            'projected_stats_per_game': {key: round(value / gp, 3) for key, value in needed.items()},
            'fantasy_points_contributions_per_game': {key: round(value, 3) for key, value in contributions.items()},
        })
    # Sort on unrounded scores. Names provide a stable tie breaker.
    ranked.sort(key=lambda player: (-player['projected_fantasy_points_per_game'], player['name']))
    for rank, player in enumerate(ranked, 1):
        player['rank'] = rank
        player['projected_fantasy_points_per_game'] = round(player['projected_fantasy_points_per_game'], 3)
    return ranked, skipped


def rank_players_for_league(scoring_weights, season=2027, overall_pick=None,
                            drafted_players=None, top_n=20):
    """Rank projected per-game points, optionally returning exactly 3 draft choices.

    season is ESPN's ending year: 2027 means the 2026–27 NBA season.
    drafted_players=None uses an explicit hypothetical rank-based draft board.
    An actual list (even []) instead means only those named players are gone.
    """
    try:
        weights = validate_weights(scoring_weights)
        if type(season) is not int or not 2020 <= season <= 2035:
            raise ToolError('INVALID_SEASON', 'season must be an integer from 2020 to 2035.',
                            'Use 2027 for the 2026–2027 season.')
        if type(top_n) is not int or not 1 <= top_n <= 50:
            raise ToolError('INVALID_LIMIT', 'top_n must be an integer from 1 to 50.', 'Choose a smaller ranking limit.')
        if overall_pick is not None and (type(overall_pick) is not int or not 1 <= overall_pick <= 500):
            raise ToolError('INVALID_PICK', 'overall_pick must be a positive integer from 1 to 500.',
                            'Ask for the overall pick number, not just a round number.')
        if drafted_players is not None and (not isinstance(drafted_players, list)
                or len(drafted_players) > 500 or any(not isinstance(name, str) or not name.strip() for name in drafted_players)):
            raise ToolError('INVALID_DRAFT_BOARD', 'drafted_players must be a list of full player names.',
                            'Ask the user for the already-drafted players by full name.')
        players, fetched_at, cache_hit = fetch_projections(season)
        ranked, skipped = build_rankings(players, season, weights)
        if not ranked:
            raise ToolError('NO_USABLE_PROJECTIONS', 'No complete season projections match these scoring metrics.',
                            'Check that ESPN has published the requested season and all required statistical fields. Do not substitute zero for missing data.')
        by_name = {normalize_name(player['name']): player for player in ranked}
        exclusions = {normalize_name(name) for name in (drafted_players or [])}
        unknown = [name for name in (drafted_players or []) if normalize_name(name) not in by_name]
        if unknown:
            raise ToolError('UNKNOWN_DRAFTED_PLAYERS', f'No usable projection found for: {", ".join(unknown)}.',
                            'Ask for corrected full names or explain that these players lack usable projections before making draft recommendations.')
        candidates, assumption = [], None
        if overall_pick is not None:
            if drafted_players is None:
                available = ranked[overall_pick - 1:]
                assumption = (f'Hypothetical draft only: assume the first {overall_pick - 1} players in this custom ranking '
                              'have already been selected. This is not ESPN ADP and does not predict real availability.')
            else:
                available = [player for player in ranked if normalize_name(player['name']) not in exclusions]
                assumption = 'Only the user-provided drafted players are excluded. No other availability is inferred from the pick number.'
            if len(available) < 3:
                raise ToolError('INSUFFICIENT_CANDIDATES', 'Fewer than three projected players remain under this draft scenario.',
                                'Ask for an earlier pick, a corrected drafted-player list, or a season with more projections.')
            candidates = available[:3]
        warnings = [
            'These are ESPN forecasts, not guaranteed performance. Ranking optimizes projected per-game points only.',
            'Projected games are shown separately; injury risk, ADP, positional scarcity, and roster fit are not modeled.',
            'Omitted metrics count as zero. No hidden default weights are added.',
        ]
        if overall_pick is not None and drafted_players is not None and len(exclusions) != overall_pick - 1:
            warnings.append('The drafted list length does not equal pick minus one; it may be a partial board. Ask whether it is complete.')
        return {
            'ok': True, 'source': {'name': 'ESPN season projections', 'url': SOURCE_PAGE,
                                  'fetched_at_utc': fetched_at, 'cache_hit': cache_hit},
            'season': season, 'season_label': f'{season - 1}–{season}',
            'ranking_basis': 'projected fantasy points per game',
            'formula': 'sum(projected season stat total × scoring weight) / projected games played',
            'scoring_weights': weights, 'ranked_player_count': len(ranked),
            'excluded_records_without_complete_projection': skipped,
            'rankings': ranked[:top_n], 'overall_pick': overall_pick,
            'drafted_players': drafted_players, 'availability_assumption': assumption,
            'draft_candidates': candidates, 'warnings': warnings,
        }
    except ToolError as exc:
        return exc.result


def get_player_outlooks(player_ids, season=2027):
    """Read ESPN season analysis without inventing news, dates, or missing text."""
    try:
        if type(season) is not int or not 2020 <= season <= 2035:
            raise ToolError('INVALID_SEASON', 'season must be an integer from 2020 to 2035.',
                            'Use the same ESPN ending year as the ranking tool.')
        if (not isinstance(player_ids, list) or not 1 <= len(player_ids) <= 10
                or any(type(value) is not int or value <= 0 for value in player_ids)):
            raise ToolError('INVALID_PLAYER_IDS', 'Provide 1–10 positive integer ESPN player IDs.',
                            'Copy player_id values from rank_players_for_league, not rank numbers or player names.')
        players, fetched_at, cache_hit = fetch_projections(season)
        by_id = {}
        for row in players:
            if not isinstance(row, dict):
                continue
            player = row.get('player', row)
            if isinstance(player, dict) and type(player.get('id')) is int:
                by_id[player['id']] = player
        outlooks, unavailable = [], []
        for player_id in dict.fromkeys(player_ids):
            player = by_id.get(player_id)
            text = player.get('seasonOutlook') if player else None
            if not isinstance(text, str) or not text.strip():
                unavailable.append({'player_id': player_id,
                                    'reason': 'No published season outlook in the ESPN response.' if player
                                    else 'Player ID not found in the requested ESPN season.'})
                continue
            outlooks.append({'player_id': player_id, 'name': player.get('fullName'),
                             'season_outlook': text.strip(), 'published_at': None})
        if not outlooks:
            raise ToolError('NO_PLAYER_OUTLOOKS', 'No ESPN season outlook was available for the requested players.',
                            'Use the ranking statistics for brief Pros/Cons and disclose that ESPN commentary is unavailable. Do not invent roster changes or expert opinions.')
        return {'ok': True, 'season': season, 'season_label': f'{season - 1}–{season}',
                'source': {'name': 'ESPN Fantasy season outlooks', 'url': SOURCE_PAGE,
                           'fetched_at_utc': fetched_at, 'cache_hit': cache_hit},
                'outlooks': outlooks, 'unavailable_players': unavailable,
                'limitations': [
                    'Season outlooks are editorial analysis, not a real-time transaction feed.',
                    'ESPN does not supply an outlook publication timestamp here. Fetch time is not publication time.',
                    'Paraphrase briefly and attribute ESPN. Only discuss roster changes stated in the source; do not infer current news.',
                    'Commentary does not change custom scoring, projections, or candidate order.',
                ]}
    except ToolError as exc:
        return exc.result


TOOL_DEFINITIONS = [{
    'type': 'function',
    'function': {
        'name': 'rank_players_for_league',
        'description': (
            'Fetch ESPN season projections and calculate a custom NBA points-league ranking using exact user scoring weights. '
            'Use for rankings, projected fantasy points, or draft-pick advice. If overall_pick is provided, return exactly three candidates. '
            'Without an actual drafted list, explicitly assume the top pick-minus-one players in this custom ranking are gone; '
            'this is a hypothetical scenario, not ADP. Ask for scoring rules before calling; never silently invent weights. '
            'Do not use for category leagues. Returns ok=false with actionable next_step on failure.'
        ),
        'parameters': {
            'type': 'object',
            'properties': {
                'scoring_weights': {
                    'type': 'object',
                    'description': 'Fantasy points awarded per unit of each statistic, from the user. Omitted fields are zero. Penalties are negative. No percentage or double/triple-double bonuses.',
                    'properties': {key: {'type': 'number', 'description': description + '; points per occurrence, -100 to 100.'}
                                   for key, description in STAT_DESCRIPTIONS.items()},
                    'additionalProperties': False,
                },
                'season': {'type': 'integer', 'description': 'ESPN season ENDING year. 2027 is 2026–2027; defaults to 2027.'},
                'overall_pick': {'type': 'integer', 'description': 'Overall draft selection number, not round. E.g. 10 returns three choices for overall pick 10. Omit for a general ranking.'},
                'drafted_players': {'type': 'array', 'items': {'type': 'string'},
                                    'description': 'Actual already-selected full names, e.g. ["Nikola Jokic"]. Omit if unknown. [] explicitly means nobody has been selected; never pass [] to represent an unknown board.'},
                'top_n': {'type': 'integer', 'description': 'Number of ranked players to return, 1–50; default 20. Does not restrict the pool used to find draft candidates.'},
            },
            'required': ['scoring_weights'],
            'additionalProperties': False,
        },
    },
}]


TOOL_DEFINITIONS.append({
    'type': 'function',
    'function': {
        'name': 'get_player_outlooks',
        'description': 'Fetch ESPN Fantasy season outlook commentary for specific NBA players. Use after ranking to add brief, attributed Pros/Cons about role, opportunity, and risks. Not a live news or transaction feed; never adjust scores or invent missing commentary. Partial coverage is reported; failures include actionable next_step.',
        'parameters': {
            'type': 'object',
            'properties': {
                'player_ids': {'type': 'array', 'items': {'type': 'integer'}, 'minItems': 1, 'maxItems': 10,
                               'description': '1–10 ESPN player_id integers returned by rank_players_for_league. These are player IDs, not ranking positions.'},
                'season': {'type': 'integer', 'description': 'ESPN season ending year; 2027 means 2026–27. Use the same season as the ranking, defaults to 2027.'},
            },
            'required': ['player_ids'], 'additionalProperties': False,
        },
    },
})



TOOL_DEFINITIONS.append({
    'type': 'function',
    'function': {
        'name': 'analyze_buy_low_sell_high',
        'description': 'Analyze ACTUAL NBA regular-season performances as of a specified historical date using user points-league rules. Compare last 4 and 10 played games to a disjoint earlier baseline; screen efficiency slumps/spikes versus opportunity declines. Not projections, live news, usage rate or a guarantee of future performance. Requires 20 appearances by the cutoff. Errors contain actionable next_step. Omitted cutoff defaults to today in America/New_York; omitted season is inferred from cutoff. No current-season data means an explicit unavailable/sample error, never a silent fallback to last season.',
        'parameters': {
            'type': 'object',
            'properties': {
                'player_name': {'type': 'string', 'description': 'Full ESPN NBA player name, e.g. Anthony Edwards. Do not pass a team name or guess an ID.'},
                'scoring_weights': TOOL_DEFINITIONS[0]['function']['parameters']['properties']['scoring_weights'],
                'as_of_date': {'type': 'string', 'description': 'Inclusive YYYY-MM-DD cutoff in America/New_York. Omit for now/today/current requests; the server supplies today. Use an explicit date for historical tests; never use later games or current news as past evidence.'},
                'season': {'type': 'integer', 'description': 'ESPN season ENDING year. Omit to infer from cutoff (July–June season convention). 2026 means 2025–26; 2027 means 2026–27. Must match cutoff. Never silently select last season for current requests.'},
            },
            'required': ['player_name', 'scoring_weights'], 'additionalProperties': False,
        },
    },
})



TOOL_DEFINITIONS.append({
    'type': 'function',
    'function': {
        'name': 'analyze_injury_replacements',
        'description': 'Historical 2025–26 same-team injury replacement screen. Fetch actual dated team box scores, exclude the top SIX team participants by user-weighted actual FP/G, and return up to three lower-ranked rotation candidates. Compare teammate minutes with the target present versus absent in last 20 completed team games; absence is not necessarily injury and differences are not causal projections. Dated pre-cutoff game recaps may support the injury premise. Does not access your league FA list or current injury status. Returns actionable errors on incomplete data.',
        'parameters': {
            'type': 'object',
            'properties': {
                'injured_player': {'type': 'string', 'description': 'Full ESPN name of the injured NBA player, e.g. Nikola Jokic. Historical injury scenario only.'},
                'scoring_weights': TOOL_DEFINITIONS[0]['function']['parameters']['properties']['scoring_weights'],
                'as_of_date': {'type': 'string', 'description': 'Historical YYYY-MM-DD cutoff in the 2025–26 season. Supply the injury-scenario date to avoid future data. Omitted date defaults to 2026-06-30 for season-end retrospective screening, NOT a live claim.'},
                'season': {'type': 'integer', 'description': 'First version supports ending year 2026 only, meaning 2025–26. Defaults to 2026.'},
            },
            'required': ['injured_player', 'scoring_weights'], 'additionalProperties': False,
        },
    },
})

TOOL_DEFINITIONS.append({
    'type': 'function', 'function': {
        'name': 'analyze_current_injury_scenario',
        'description': 'Hypothetical 2026–27 injury replacement watch using verified current ESPN roster and user-weighted projections. Excludes top SIX projected teammates and target; prioritizes position fit with optional previous-season same-team absence evidence. Not a verified depth chart, injury-adjusted projection, news analysis or real FA list. Optional available_players restricts to user-provided FAs. Returns up to three unranked guidance candidates with explicit uncertainty and actionable errors. A current roster player missing projections may be watch-only if position fit and at least three prior-season same-team appearances with and without the target support consideration; their current projected score and rank remain null.',
        'parameters': {'type': 'object', 'properties': {
            'injured_player': {'type': 'string', 'description': 'Full ESPN player name whose hypothetical absence to analyze.'},
            'scoring_weights': TOOL_DEFINITIONS[0]['function']['parameters']['properties']['scoring_weights'],
            'season': {'type': 'integer', 'description': 'Ending year 2027 (2026–27), defaults to 2027; current scenario mode only.'},
            'available_players': {'type': 'array', 'items': {'type': 'string'}, 'description': 'Optional list of up to 100 full names of actual available players copied from user league. Omit when unknown; [] means none are available. Limits recommendations to these names, still excluding the projected top six.'},
        }, 'required': ['injured_player', 'scoring_weights'], 'additionalProperties': False},
    },
})


def execute_tool(name, args):
    """Allowlisted dispatch with validation and non-secret, actionable errors."""
    from buy_low import analyze_buy_low_sell_high
    from injury_replacement import analyze_injury_replacements, analyze_current_injury_scenario
    functions = {
        'analyze_current_injury_scenario': (analyze_current_injury_scenario,
            {'injured_player', 'scoring_weights', 'season', 'available_players'},
            ('injured_player', 'scoring_weights')),
        'rank_players_for_league': (rank_players_for_league,
            {'scoring_weights', 'season', 'overall_pick', 'drafted_players', 'top_n'}, 'scoring_weights'),
        'get_player_outlooks': (get_player_outlooks, {'player_ids', 'season'}, 'player_ids'),
        'analyze_injury_replacements': (analyze_injury_replacements,
            {'injured_player', 'scoring_weights', 'as_of_date', 'season'},
            ('injured_player', 'scoring_weights')),
        'analyze_buy_low_sell_high': (analyze_buy_low_sell_high,
            {'player_name', 'scoring_weights', 'as_of_date', 'season'},
            ('player_name', 'scoring_weights')),
    }
    if name not in functions:
        return error('UNKNOWN_TOOL', f'Tool {name} is not available.',
                     'Use a tool listed in the supplied tool schema.')
    if not isinstance(args, dict):
        return error('INVALID_ARGUMENTS', 'Tool arguments must be a JSON object.',
                     'Retry with a JSON object matching the tool schema.')
    function, allowed, required = functions[name]
    required_keys = (required,) if isinstance(required, str) else required
    if set(args) - allowed or any(key not in args for key in required_keys):
        return error('INVALID_ARGUMENTS', f'Missing {required} or unexpected argument names.',
                     f'Supply {required} and only the named optional arguments from the schema.')
    try:
        return function(**args)
    except Exception:
        logger.exception('Unexpected error executing tool %s', name)
        return error('TOOL_INTERNAL_ERROR', 'The tool encountered an unexpected problem.',
                     'Tell the user this data is unavailable right now. The developer should inspect server logs; do not fabricate results.')
