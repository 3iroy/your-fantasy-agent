"""Offline checks for scoring math, draft assumptions, errors, and chat protocol."""

import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import HTTPError, URLError

import app
import tools


def fixture_player(name, pts, reb, gp=10, player_id=1):
    return {'id': player_id, 'fullName': name, 'defaultPositionId': 1, 'eligibleSlots': [0],
            'stats': [{'seasonId': 2027, 'statSourceId': 1, 'statSplitTypeId': 0,
                       'stats': {'0': pts, '6': reb, '42': gp}}]}


def mock_message(text=None, calls=None):
    class Message:
        content = text
        tool_calls = calls or []

        def model_dump(self, **kwargs):
            return {'role': 'assistant', 'tool_calls': [
                {'id': call.id, 'type': 'function',
                 'function': {'name': call.function.name, 'arguments': call.function.arguments},
                 'provider_specific_fields': {'thought_signature': 'test-signature'}} for call in self.tool_calls]}
    return SimpleNamespace(choices=[SimpleNamespace(message=Message())])


class RankingTests(unittest.TestCase):
    def setUp(self):
        self.players = [fixture_player(f'Player {i}', 100 - i * 10, i * 10, player_id=i)
                        for i in range(1, 7)]

    def rank(self, **kwargs):
        with patch.object(tools, 'fetch_projections', return_value=(self.players, 'test-time', False)):
            return tools.rank_players_for_league(**kwargs)

    def test_divides_season_totals_once_and_weights_change_rank(self):
        pts = self.rank(scoring_weights={'PTS': 1}, overall_pick=2)
        self.assertEqual(pts['rankings'][0]['projected_fantasy_points_per_game'], 9)
        self.assertEqual([p['name'] for p in pts['draft_candidates']], ['Player 2', 'Player 3', 'Player 4'])
        self.assertIn('Hypothetical', pts['availability_assumption'])
        reb = self.rank(scoring_weights={'PTS': 1, 'REB': 2})
        self.assertEqual(reb['rankings'][0]['name'], 'Player 6')
        self.assertEqual(reb['rankings'][0]['projected_fantasy_points_per_game'], 16)

    def test_actual_board_excludes_only_named_players(self):
        result = self.rank(scoring_weights={'PTS': 1}, overall_pick=2, drafted_players=['Player 2'])
        self.assertEqual(result['draft_candidates'][0]['name'], 'Player 1')
        self.assertNotIn('Player 2', [p['name'] for p in result['draft_candidates']])

    def test_missing_values_are_not_zero_and_actual_stats_not_projections(self):
        self.players[0]['stats'][0]['statSourceId'] = 0
        self.players[1]['stats'][0]['stats'].pop('6')
        result = self.rank(scoring_weights={'PTS': 1, 'REB': 1})
        self.assertEqual(result['ranked_player_count'], 4)
        self.assertEqual(result['excluded_records_without_complete_projection'], 2)

    def test_invalid_weights_and_unknown_players(self):
        for weights in [{}, {'PTS': float('nan')}, {'PTS': True}, {'DD': 5}, {'PTS': 0}]:
            result = self.rank(scoring_weights=weights)
            self.assertFalse(result['ok'])
            self.assertTrue(result['next_step'])
        result = self.rank(scoring_weights={'PTS': 1}, overall_pick=2, drafted_players=['Missing Name'])
        self.assertEqual(result['error'], 'UNKNOWN_DRAFTED_PLAYERS')
        self.assertEqual(self.rank(scoring_weights={'PTS': 1}, overall_pick=6)['error'], 'INSUFFICIENT_CANDIDATES')

    def test_api_errors_are_actionable(self):
        for exception, code in [(HTTPError('url', 429, '', {}, None), 'ESPN_RATE_LIMIT'),
                                (HTTPError('url', 403, '', {}, None), 'ESPN_ACCESS_DENIED'),
                                (URLError('timeout'), 'ESPN_CONNECTION_ERROR')]:
            tools._cache.clear()
            with patch.object(tools, 'urlopen', side_effect=exception):
                result = tools.rank_players_for_league({'PTS': 1})
                self.assertEqual(result['error'], code)
                self.assertTrue(result['next_step'])


class OutlookTests(unittest.TestCase):
    def test_partial_coverage_preserves_source_and_reports_missing_players(self):
        players = [{'id': 10, 'fullName': 'Covered Player', 'seasonOutlook': 'A larger role may improve assists.'},
                   {'id': 11, 'fullName': 'Missing Player'},
                   {'id': 12, 'fullName': 'Blank Player', 'seasonOutlook': '  '}]
        with patch.object(tools, 'fetch_projections', return_value=(players, 'test-time', True)):
            result = tools.execute_tool('get_player_outlooks', {'player_ids': [10, 11, 12, 99]})
            self.assertTrue(result['ok'])
            self.assertEqual([item['player_id'] for item in result['outlooks']], [10])
            self.assertEqual([item['player_id'] for item in result['unavailable_players']], [11, 12, 99])
            self.assertIsNone(result['outlooks'][0]['published_at'])
            self.assertEqual(result['source']['url'], tools.SOURCE_PAGE)
            absent = tools.get_player_outlooks([11])
            self.assertEqual(absent['error'], 'NO_PLAYER_OUTLOOKS')
            self.assertIn('Do not invent', absent['next_step'])

    def test_outlook_validation_and_upstream_failure_are_actionable(self):
        for ids in [[], [True], ['10'], [0], list(range(1, 12))]:
            result = tools.get_player_outlooks(ids)
            self.assertEqual(result['error'], 'INVALID_PLAYER_IDS')
        self.assertEqual(tools.get_player_outlooks([10], season='2027')['error'], 'INVALID_SEASON')
        with patch.object(tools, 'fetch_projections', side_effect=tools.ToolError(
                'ESPN_RATE_LIMIT', 'Too many requests.', 'Retry later.', True)):
            self.assertEqual(tools.get_player_outlooks([10])['error'], 'ESPN_RATE_LIMIT')
        self.assertEqual(tools.execute_tool('get_player_outlooks', {'player_ids': [10], 'extra': 1})['error'], 'INVALID_ARGUMENTS')


class ChatTests(unittest.TestCase):
    def setUp(self):
        app.sessions.clear()
        app.app.testing = True
        app.app.logger.disabled = True
        self.client = app.app.test_client()

    def test_confirmed_ui_scoring_reaches_model_and_is_remembered(self):
        captured = []
        def answer(messages):
            captured.append([dict(item) for item in messages])
            messages.append({'role': 'assistant', 'content': 'Ranking ready.'})
            return 'Ranking ready.', [], True
        with patch.object(app, 'run_agent', side_effect=answer):
            first = self.client.post('/chat', json={
                'message': 'Show ranks 10–15.', 'scoring_weights': {'PTS': 1, 'REB': 3}})
            self.assertEqual(first.status_code, 200)
            session_id = first.get_json()['session_id']
            followup = self.client.post('/chat', json={
                'message': 'Now show ranks 1–5.', 'session_id': session_id})
            self.assertEqual(followup.status_code, 200)
        self.assertIn('"REB": 3.0', captured[0][-1]['content'])
        self.assertIn('Show ranks 10–15.', captured[0][-1]['content'])
        self.assertEqual(captured[1][-1]['content'], 'Now show ranks 1–5.')
        self.assertIn('"REB": 3.0', captured[1][1]['content'])
        visible = self.client.get('/sessions/' + session_id).get_json()['messages']
        self.assertEqual(visible[0]['content'], 'Show ranks 10–15.')
        invalid = self.client.post('/chat', json={
            'message': 'Rank players.', 'scoring_weights': {'REB': 'bad'}})
        self.assertEqual(invalid.status_code, 400)

    def test_round_trip_preserves_trace_and_history(self):
        args = {'scoring_weights': {'PTS': 1}, 'overall_pick': 10}
        call = SimpleNamespace(id='call1', function=SimpleNamespace(
            name='rank_players_for_league', arguments=json.dumps(args)))
        result = {'ok': True, 'draft_candidates': [{'name': 'A'}, {'name': 'B'}, {'name': 'C'}]}
        with patch.object(app, 'completion', side_effect=[mock_message(calls=[call]), mock_message('Choose A, B, or C.')]) as model, patch.object(app, 'execute_tool', return_value=result):
            response = self.client.post('/chat', json={'message': 'Recommend three players.'})
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(set(data), {'response', 'session_id', 'tool_calls'})
        self.assertEqual(data['tool_calls'], [{'name': 'rank_players_for_league', 'args': args, 'result': result}])
        protocol = app.sessions[data['session_id']]['messages']
        self.assertEqual(protocol[-2]['role'], 'tool')
        self.assertEqual(json.loads(protocol[-2]['content']), result)
        self.assertEqual(protocol[-3]['tool_calls'][0]['provider_specific_fields']['thought_signature'], 'test-signature')
        visible = self.client.get('/sessions/' + data['session_id']).get_json()['messages']
        self.assertEqual(len(visible), 2)
        self.assertEqual(visible[1]['tool_calls'], data['tool_calls'])
        with patch.object(app, 'completion', return_value=mock_message('Still here.')) as followup:
            self.client.post('/chat', json={'message': 'Same rules, next pick?', 'session_id': data['session_id']})
            self.assertIn(protocol[-2], followup.call_args.kwargs['messages'])
        with patch.object(app, 'completion', return_value=mock_message('New league.')) as fresh:
            second = self.client.post('/chat', json={'message': 'New conversation.'}).get_json()
            self.assertNotEqual(second['session_id'], data['session_id'])
            self.assertEqual(len(fresh.call_args.kwargs['messages']), 2)
            self.assertIn('Current date in America/New_York:', fresh.call_args.kwargs['messages'][0]['content'])

    def test_failure_returns_calls_without_committing_partial_history(self):
        call = SimpleNamespace(id='call1', function=SimpleNamespace(name='rank_players_for_league', arguments='not json'))
        with patch.object(app, 'completion', side_effect=[mock_message(calls=[call]), RuntimeError('outage')]):
            response = self.client.post('/chat', json={'message': 'Try ranking.'})
        self.assertEqual(response.status_code, 502)
        data = response.get_json()
        self.assertEqual(data['tool_calls'][0]['result']['error'], 'INVALID_JSON')
        self.assertEqual(len(app.sessions[data['session_id']]['messages']), 1)

    def test_tool_error_reaches_model_and_ui(self):
        call = SimpleNamespace(id='call1', function=SimpleNamespace(name='rank_players_for_league', arguments='{"scoring_weights": {}}'))
        with patch.object(app, 'completion', side_effect=[mock_message(calls=[call]), mock_message('Please provide scoring weights.')]):
            response = self.client.post('/chat', json={'message': 'Rank players.'}).get_json()
        self.assertFalse(response['tool_calls'][0]['result']['ok'])
        self.assertEqual(response['tool_calls'][0]['result']['error'], 'MISSING_SCORING')


if __name__ == '__main__':
    unittest.main()
