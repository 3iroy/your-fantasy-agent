"""Checks for historical exclusion, matched minutes evidence, and dated news."""
import copy
import unittest
from datetime import date
from unittest.mock import patch

import injury_replacement as injury
import tools


def boxes_fixture():
    boxes = []
    for day in range(1, 21):
        present = day <= 10
        players = {}
        for pid in range(1, 10):
            played = pid != 1 or present
            minutes = 20 if pid <= 6 else 10 + (10 - pid) * (5 if not present else 0)
            players[pid] = {'player_id': pid, 'name': f'Player {pid}', 'position': 'C',
                            'played': played, 'minutes': minutes if played else 0,
                            'fantasy_points': 100 - pid*8 if played else None,
                            'dnp_reason': None}
        boxes.append({'event_id': str(day), 'date': f'2025-11-{day:02d}', 'players': players})
    return boxes


class InjuryReplacementTests(unittest.TestCase):
    def test_top_six_excludes_stars_and_sorts_observed_minutes_gain(self):
        candidates, excluded, comparison = injury.screen_replacements(boxes_fixture(), 1)
        self.assertEqual([p['player_id'] for p in excluded], [1, 2, 3, 4, 5, 6])
        self.assertEqual([p['player_id'] for p in candidates], [7, 8, 9])
        self.assertTrue(all(p['team_rank'] > 6 for p in candidates))
        self.assertEqual(candidates[0]['observed_minutes_difference_per_team_game'], 15)
        self.assertEqual(comparison['target_absent_team_games'], 10)
        self.assertEqual(candidates[0]['evidence_level'], 'observed_absence_comparison')

    def test_no_fabricated_minutes_when_comparison_sample_is_small(self):
        boxes = boxes_fixture()
        for box in boxes[10:18]:
            box['players'][1].update(played=True, minutes=20, fantasy_points=92)
        candidates, _, _ = injury.screen_replacements(boxes, 1)
        self.assertTrue(all(p['observed_minutes_difference_per_team_game'] is None for p in candidates))
        self.assertTrue(all('insufficient' in p['evidence_level'] for p in candidates))

    def test_candidates_use_latest_snapshot_and_do_not_fill_with_top_six(self):
        boxes = boxes_fixture()
        del boxes[-1]['players'][7]
        boxes[-1]['players'][8].update(played=False, minutes=0, fantasy_points=None, dnp_reason='ANKLE INJURY')
        candidates, excluded, _ = injury.screen_replacements(boxes, 1)
        self.assertEqual([p['player_id'] for p in candidates], [9])
        self.assertEqual(len(excluded), 6)

    def test_schedule_filters_dates_seasons_completion_and_preseason(self):
        def event(day, year=2026, kind=2, completed=True):
            return {'id': str(day), 'date': f'2025-11-{day:02d}T20:00:00Z',
                    'season': {'year': year}, 'seasonType': {'type': kind},
                    'competitions': [{'status': {'type': {'completed': completed}}}]}
        schedule = {'events': [event(i) for i in range(1, 8)] +
                    [event(8, kind=1), event(9, year=2027), event(10, completed=False)]}
        selected = injury.select_team_events(schedule, 2026, date(2025, 11, 5))
        self.assertEqual([p['event_id'] for p in selected], ['1', '2', '3', '4', '5'])

    def test_news_excludes_future_and_later_updated_reports(self):
        def article(pid, posted, modified=None):
            return {'article': {'id': pid, 'headline': 'Jokic sidelined with knee injury',
                    'description': 'Historical game report.', 'published': posted,
                    'lastModified': modified or posted}}
        reports = injury.dated_articles([
            article(1, '2025-11-10T20:00:00Z'), article(2, '2025-11-21T20:00:00Z'),
            article(3, '2025-11-10T20:00:00Z', '2025-11-21T20:00:00Z')],
            'Nikola Jokic', date(2025, 11, 20))
        self.assertEqual(len(reports), 1)
        self.assertTrue(reports[0]['mentions_injury'])

    def test_box_score_uses_custom_weights_and_dnp_is_not_zero_gp(self):
        record = {'athlete': {'id': '1', 'displayName': 'Player', 'position': {'abbreviation': 'C'}},
                  'didNotPlay': False, 'stats': ['30', '20', '8-15', '2-4', '2-3', '10', '3', '2', '1', '1']}
        labels = ['MIN', 'PTS', 'FG', '3PT', 'FT', 'REB', 'AST', 'TO', 'STL', 'BLK']
        data = {'header': {'id': '10', 'season': {'year': 2026, 'type': 2},
                 'competitions': [{'date': '2025-11-10T20:00:00Z', 'status': {'type': {'completed': True}}}]},
                 'boxscore': {'players': [{'team': {'id': '7'}, 'statistics': [{'labels': labels, 'athletes': [record]}]}]}}
        game = {'event_id': '10', 'date': '2025-11-10'}
        result = injury.parse_box(data, game, '7', 2026, {'PTS': 1, 'REB': 3, 'TO': -2})
        self.assertEqual(result['players'][1]['fantasy_points'], 46)
        record.update(stats=['--', '0', '0-0', '0-0', '0-0', '0', '0', '0', '0', '0'], reason="COACH'S DECISION")
        result = injury.parse_box(data, game, '7', 2026, {'PTS': 1})
        self.assertFalse(result['players'][1]['played'])
        self.assertIsNone(result['players'][1]['fantasy_points'])
        record['stats'][1] = '2'
        with self.assertRaises(tools.ToolError):
            injury.parse_box(data, game, '7', 2026, {'PTS': 1})
        record.update(didNotPlay=True, stats=[], reason='KNEE INJURY')
        result = injury.parse_box(data, game, '7', 2026, {'PTS': 1})
        self.assertIsNone(result['players'][1]['fantasy_points'])
        self.assertFalse(result['players'][1]['played'])
        record.update(didNotPlay=False, stats=['bad'])
        with self.assertRaises(tools.ToolError):
            injury.parse_box(data, game, '7', 2026, {'PTS': 1})

    def test_invalid_inputs_and_dispatch_are_actionable(self):
        self.assertEqual(injury.analyze_injury_replacements('Nikola Jokic', {'PTS': 1}, season=2027)['error'], 'UNSUPPORTED_REPLACEMENT_SEASON')
        self.assertEqual(injury.analyze_injury_replacements('Nikola Jokic', {'PTS': 1}, as_of_date='2026-13-01')['error'], 'INVALID_AS_OF_DATE')
        self.assertEqual(injury.analyze_injury_replacements('Nikola Jokic', {'PTS': 1}, as_of_date='2026-10-06')['error'], 'DATE_OUTSIDE_SEASON')
        self.assertEqual(tools.execute_tool('analyze_injury_replacements', {'injured_player': 'Nikola Jokic'})['error'], 'INVALID_ARGUMENTS')
        with patch.object(injury, 'fetch_projections', side_effect=tools.ToolError('ESPN_RATE_LIMIT', 'Unavailable.', 'Retry.')):
            self.assertEqual(injury.analyze_injury_replacements('Nikola Jokic', {'PTS': 1})['error'], 'ESPN_RATE_LIMIT')


if __name__ == '__main__':
    unittest.main()
