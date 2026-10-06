"""Current scenarios must respect roster, custom scoring, FA filters and uncertainty."""
import unittest
from unittest.mock import patch
import injury_replacement as injury


class CurrentScenarioTests(unittest.TestCase):
    def run_scenario(self, **kwargs):
        pool = [{'id': i, 'fullName': f'Player {i}', 'proTeamId': 7,
                 'defaultPositionId': 5, 'eligibleSlots': [4],
                 'stats': [{'seasonId': 2027, 'statSourceId': 1, 'statSplitTypeId': 0,
                            'stats': {'42': 10, '0': 100-i}}]} for i in range(1, 10)]
        missing = kwargs.pop('missing_ids', [])
        history = kwargs.pop('with_history', False)
        for player in pool:
            if player['id'] in missing:
                player['stats'] = []
            if player['id'] in kwargs.get('unrelated_ids', []):
                player.update(defaultPositionId=1, eligibleSlots=[0])
        kwargs.pop('unrelated_ids', None)
        roster = {'season': {'year': kwargs.pop('roster_season', 2027)},
                  'team': {'id': '7', 'displayName': 'Test Team'},
                  'athletes': [{'id': str(i), 'fullName': f'Player {i}', 'injuries': []} for i in range(1, 10)]}
        with patch.object(injury, 'fetch_projections', return_value=(pool, 'test-time', False)), \
             patch.object(injury, 'fetch_json', return_value=roster), \
             patch.object(injury, 'select_team_events', side_effect=None if history else injury.ToolError('NO_HISTORY', 'No history.', 'Watch only.'), return_value=[{'date': f'2026-01-{i:02d}'} for i in range(1,9)]), \
             patch.object(injury, 'fetch_game_log', side_effect=lambda pid, season: ({'pid': pid, 'events': {str(i): {'team': {'id': '7'}} for i in range(1,9)}}, 'test', False)), \
             patch.object(injury, 'parse_games', side_effect=lambda log, *args: ([{'date': f'2026-01-{i:02d}', 'event_id': str(i), 'stats': {'MIN': 10 if i <= 4 else 20}, 'fantasy_points': 15} for i in range(1,5 if log['pid'] == 1 else 9)], [])):
            return injury.analyze_current_injury_scenario('Player 1', kwargs.pop('weights', {'PTS': 1}), **kwargs)

    def test_exclusion_and_optional_history_failure(self):
        r = self.run_scenario()
        self.assertTrue(r['ok'])
        self.assertEqual([p['player_id'] for p in r['excluded_top_six']], [1,2,3,4,5,6])
        self.assertEqual([p['player_id'] for p in r['candidates']], [7,8,9])
        self.assertTrue(all(p['historical_evidence'] is None for p in r['candidates']))
        self.assertEqual(r['candidates'][0]['projected_fantasy_points_per_game'], 9.3)
        self.assertTrue(any('Optional historical' in w for w in r['warnings']))

    def test_fa_filter_cannot_restore_excluded_star(self):
        r = self.run_scenario(available_players=['Player 1', 'Player 8'])
        self.assertEqual([p['player_id'] for p in r['candidates']], [8])
        self.assertEqual(self.run_scenario(available_players=[])['candidates'], [])

    def test_does_not_fill_center_choices_with_unrelated_guards(self):
        r = self.run_scenario(unrelated_ids=[8, 9])
        self.assertEqual([p['player_id'] for p in r['candidates']], [7])

    def test_missing_projection_watch_requires_historical_evidence(self):
        r = self.run_scenario(missing_ids=[7], with_history=True)
        p = next(p for p in r['candidates'] if p['player_id'] == 7)
        self.assertIsNone(p['projected_fantasy_points_per_game'])
        self.assertIsNone(p['team_rank'])
        self.assertEqual(p['historical_evidence']['observed_minutes_difference_per_appearance'], 10)
        self.assertNotIn(7, [p['player_id'] for p in self.run_scenario(missing_ids=[7])['candidates']])

    def test_scoring_changes_top_six(self):
        r = self.run_scenario(weights={'PTS': -1})
        self.assertEqual([p['player_id'] for p in r['excluded_top_six']], [9,8,7,6,5,4])
        self.assertEqual({p['player_id'] for p in r['candidates']}, {2,3})

    def test_roster_mismatch_and_unknown_fa_fail_actionably(self):
        self.assertEqual(self.run_scenario(roster_season=2026)['error'], 'CURRENT_ROSTER_MISMATCH')
        self.assertEqual(self.run_scenario(available_players=['Imaginary Player'])['error'], 'UNKNOWN_FA_NAMES')
        self.assertEqual(self.run_scenario(available_players='Player 8')['error'], 'INVALID_FA_LIST')
        self.assertEqual(self.run_scenario(season=2026)['error'], 'UNSUPPORTED_SCENARIO_SEASON')
