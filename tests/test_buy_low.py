"""Verify historical windows, custom scoring, signal rules and look-ahead protection."""
import copy
import unittest
from datetime import date
from unittest.mock import patch
from urllib.error import HTTPError

import buy_low
import tools

LABELS = ['MIN', 'FG', 'FG%', '3PT', '3P%', 'FT', 'FT%', 'REB', 'AST', 'BLK', 'STL', 'PF', 'TO', 'PTS']


def fixture():
    events, entries = {}, []
    for i in range(1, 22):
        event_id = str(i)
        events[event_id] = {'gameDate': f'2025-11-{i:02d}T20:00:00Z'}
        made, points = (8, 20) if i <= 10 else (4, 12)
        if i == 21:
            made, points = 16, 999
        entries.append({'eventId': event_id, 'stats': ['30', f'{made}-16', '0', '2-6', '0', '2-3', '0', '5', '4', '1', '1', '2', '2', str(points)]})
    return {'labels': LABELS, 'events': events, 'seasonTypes': [
        {'displayName': '2025-26 Regular Season', 'categories': [{'events': entries}]},
        {'displayName': '2025-26 Preseason', 'categories': [{'events': entries}]},
        {'displayName': '2025-26 Postseason', 'categories': [{'events': entries}]}]}


class HistoricalAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.data = fixture()

    def analyze(self, data=None, **kwargs):
        args = {'player_name': 'Anthony Edwards', 'scoring_weights': {'PTS': 1},
                'as_of_date': '2025-11-20', 'season': 2026}
        args.update(kwargs)
        with patch.object(buy_low, 'fetch_projections', return_value=(
                [{'id': 4594268, 'fullName': 'Anthony Edwards'}], 'time', False)), patch.object(
                buy_low, 'fetch_game_log', return_value=(data or self.data, 'time', False)):
            return buy_low.analyze_buy_low_sell_high(**args)

    def test_live_shape_math_disjoint_windows_and_no_future_leakage(self):
        result = self.analyze()
        self.assertTrue(result['ok'])
        self.assertEqual(result['games_used'], 20)
        self.assertEqual(len(result['game_history']), 20)
        self.assertTrue(all(g['date'] <= result['as_of_date'] for g in result['game_history']))
        self.assertEqual(result['game_history'][-1]['fantasy_points'], 12)
        self.assertEqual(result['baseline_before_last_10']['games'], 10)
        self.assertEqual(result['baseline_before_last_10']['end_date'], '2025-11-10')
        self.assertEqual(result['last_10']['start_date'], '2025-11-11')
        self.assertEqual(result['last_10']['fantasy_points_per_game'], 12)
        self.assertEqual(result['last_4']['games'], 4)
        self.assertEqual(result['last_4']['start_date'], '2025-11-17')
        self.assertEqual(result['season_to_date']['fantasy_points_per_game'], 16)
        self.assertEqual(result['last_10_vs_baseline']['fantasy_points_percent'], -40)
        self.assertEqual(result['signal'], 'potential_buy_low')
        self.assertTrue(all(g['date'] <= result['as_of_date'] for g in result['recent_games']))
        # Even malformed or drastically different FUTURE stats cannot affect past signals.
        altered = copy.deepcopy(self.data)
        altered['seasonTypes'][0]['categories'][0]['events'][-1]['stats'] = ['bad data']
        self.assertEqual(self.analyze(altered), result)

    def test_custom_weights_recompute_actual_stats_and_derived_misses(self):
        result = self.analyze(scoring_weights={'PTS': 1, 'REB': 3, 'TO': -2, 'FGMI': -1})
        self.assertTrue(result['ok'])
        self.assertEqual(result['baseline_before_last_10']['fantasy_points_per_game'], 23)
        self.assertEqual(result['last_10']['fantasy_points_per_game'], 11)
        self.assertEqual(result['last_10']['stats_per_game']['FGMI'], 12)
        contributions = result['last_10_vs_baseline']['scoring_contribution_changes_per_game']
        self.assertEqual(sum(contributions.values()), -12)
        self.assertEqual(contributions['PTS'], -8)
        self.assertEqual(contributions['FGMI'], -4)

    def test_samples_missing_metrics_and_dates_are_actionable(self):
        self.assertEqual(self.analyze(as_of_date='2025-11-19')['error'], 'INSUFFICIENT_HISTORY')
        self.assertEqual(self.analyze(as_of_date='2025-02-01')['error'], 'DATE_OUTSIDE_SEASON')
        self.assertEqual(self.analyze(as_of_date='not a date')['error'], 'INVALID_AS_OF_DATE')
        self.assertEqual(self.analyze(as_of_date='2025-02-30')['error'], 'INVALID_AS_OF_DATE')
        self.assertEqual(self.analyze(scoring_weights={'PTS': 0})['error'], 'ZERO_SCORING')
        self.assertEqual(self.analyze(scoring_weights={'DD': 2})['error'], 'UNSUPPORTED_METRICS')
        self.data['seasonTypes'][0]['categories'][0]['events'][0]['stats'][-1] = '--'
        self.assertEqual(self.analyze()['error'], 'INCOMPLETE_GAME_STATS')

    def test_et_calendar_dates_dnp_and_duplicate_filtering(self):
        self.data['events']['21']['gameDate'] = '2025-11-21T01:00:00Z'  # Nov 20 ET
        entries = self.data['seasonTypes'][0]['categories'][0]['events']
        entries.append(copy.deepcopy(entries[0]))
        entries[1]['stats'][0] = '0'
        games, dnp = buy_low.parse_games(self.data, 2026, date(2025, 11, 20), {'PTS': 1})
        self.assertEqual(len(games), 20)
        self.assertEqual(dnp, 1)
        self.assertEqual(games[-1]['date'], '2025-11-20')
        self.assertEqual(games[-1]['event_id'], '21')

    def test_efficiency_patterns_are_distinct_from_opportunity_changes(self):
        def signal(fp, minutes, shots, fg):
            return buy_low.classify({'fantasy_points_percent': fp, 'MIN_percent': minutes,
                                     'FGA_percent': shots, 'fg_percentage_points': fg})[0]
        self.assertEqual(signal(-25, 0, 0, -10), 'potential_buy_low')
        self.assertEqual(signal(-25, -20, -20, -10), 'opportunity_decline')
        self.assertEqual(signal(25, 0, 0, 10), 'potential_sell_high')
        self.assertEqual(signal(25, 25, 25, 10), 'improvement_needs_context')
        self.assertEqual(signal(2, 0, 0, 0), 'no_clear_signal')
        self.assertEqual(signal(None, 0, 0, 0), 'insufficient_signal')

    def test_percentages_use_attempt_weighted_totals(self):
        games, _ = buy_low.parse_games(self.data, 2026, date(2025, 11, 20), {'PTS': 1})
        two = games[:2]
        two[0]['stats'].update(FGM=1, FGA=1)
        two[1]['stats'].update(FGM=0, FGA=9)
        self.assertEqual(buy_low.summarize(two)['fg_percentage'], 10)

    def test_today_default_infers_season_and_historical_date_still_works(self):
        with patch.object(buy_low, 'today_et', return_value=date(2025, 11, 20)):
            result = self.analyze(as_of_date=None, season=None)
        self.assertTrue(result['ok'])
        self.assertEqual(result['as_of_date'], '2025-11-20')
        self.assertEqual(result['season'], 2026)
        self.assertEqual(result['mode'], 'as_of_today')
        historic = self.analyze(season=None)
        self.assertEqual(historic['season'], 2026)
        with patch.object(buy_low, 'today_et', return_value=date(2026, 10, 5)), patch.object(
                buy_low, 'fetch_projections', return_value=([{'id': 4594268, 'fullName': 'Anthony Edwards'}], 'time', False)) as pool, patch.object(
                buy_low, 'fetch_game_log', return_value=({'labels': LABELS, 'events': {},
                    'seasonTypes': [{'displayName': '2026-27 Regular Season', 'categories': []}]}, 'time', False)) as logs:
            missing = buy_low.analyze_buy_low_sell_high('Anthony Edwards', {'PTS': 1})
        self.assertEqual(missing['error'], 'INSUFFICIENT_HISTORY')
        self.assertIn('2026-10-05', missing['message'])
        pool.assert_called_once_with(2027)
        logs.assert_called_once_with(4594268, 2027)

    def test_api_errors_and_dispatch_validation(self):
        buy_low._cache.clear()
        with patch.object(buy_low, 'urlopen', side_effect=HTTPError('url', 429, '', {}, None)):
            with self.assertRaises(tools.ToolError) as caught:
                buy_low.fetch_game_log(4594268, 2026)
            self.assertEqual(caught.exception.result['error'], 'ESPN_RATE_LIMIT')
        result = tools.execute_tool('analyze_buy_low_sell_high', {'player_name': 'Anthony Edwards'})
        self.assertEqual(result['error'], 'INVALID_ARGUMENTS')


if __name__ == '__main__':
    unittest.main()
