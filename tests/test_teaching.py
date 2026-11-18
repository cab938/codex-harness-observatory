import json
import tempfile
import unittest
from pathlib import Path

from observatory.teaching import project_trace


class TeachingProjectionTests(unittest.TestCase):
    def test_trajectory_uses_recorded_call_and_frame_identities(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'payloads').mkdir()
            def artifact(name, obj):
                (root / 'payloads' / f'{name}.json').write_text(json.dumps(obj))
                return {'raw_payload_id': name, 'path': f'payloads/{name}.json'}
            frame = artifact('frame', {'params': {'threadId': 'root', 'turnId': 'turn-two',
                                                   'input': [{'type': 'text', 'text': 'steer'}]}})
            response = artifact('response', {'output_items': [
                {'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text', 'text': 'hello'}]},
                {'type': 'function_call', 'call_id': 'model-call'},
                {'type': 'custom_tool_call', 'call_id': 'model-cell'}]})
            def event(seq, payload, *, thread='root', turn='turn-two'):
                return {'schema_version': 6, 'seq': seq, 'wall_time_unix_ms': seq * 10,
                        'thread_id': thread, 'task_root_thread_id': 'root', 'codex_turn_id': turn, 'payload': payload}
            raw = [
                event(1, {'type': 'app_server_frame_observed', 'direction': 'client_to_server',
                          'method': 'turn/steer', 'frame_payload': frame}, thread=None, turn=None),
                event(2, {'type': 'inference_started', 'inference_call_id': 'r', 'step_id': 'step'}),
                event(3, {'type': 'inference_completed', 'inference_call_id': 'r', 'response_payload': response}),
                event(4, {'type': 'tool_call_started', 'tool_call_id': 'tool', 'model_visible_call_id': 'model-call',
                          'kind': {'type': 'exec_command'}, 'requester': {'type': 'model'}}),
                event(5, {'type': 'code_cell_started', 'runtime_cell_id': 'cell', 'model_visible_call_id': 'model-cell'}),
                event(6, {'type': 'tool_call_started', 'tool_call_id': 'child', 'kind': {'type': 'exec_command'},
                          'requester': {'type': 'code_cell', 'runtime_cell_id': 'cell'}}),
                event(7, {'type': 'history_item_accepted', 'item_id': 'accepted'}),
            ]
            trace = root / 'trace.jsonl'
            trace.write_text(''.join(json.dumps(e) + '\n' for e in raw))
            result = project_trace(trace, thread='root')
            rows = {row['id']: row for row in result['trajectory']}
            self.assertEqual((rows['user:1']['thread_id'], rows['user:1']['turn_id'], rows['user:1']['step_id']),
                             ('root', 'turn-two', None))
            self.assertEqual(rows['output:r:0']['parent_id'], 'request:r')
            self.assertEqual(rows['tool:tool']['parent_id'], 'request:r')
            self.assertEqual(rows['cell:cell']['parent_id'], 'request:r')
            self.assertEqual((rows['tool:child']['parent_id'], rows['tool:child']['request_id']), ('cell:cell', 'r'))
            self.assertNotIn('event:7', rows)

    def test_user_turn_from_exact_recorded_exchange(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'start.json').write_text(json.dumps({'params': {'threadId': 'root', 'input': [{'type': 'text', 'text': 'go'}]}}))
            (root / 'response.json').write_text(json.dumps({'result': {'turn': {'id': 'turn-id'}}}))
            common = {'type': 'app_server_frame_observed', 'method': 'turn/start', 'connection_instance_id': 'connection', 'exchange_id': 'exchange', 'source_thread_id': 'root'}
            raw = [
                {'schema_version': 6, 'seq': 1, 'thread_id': 'root', 'task_root_thread_id': 'root', 'payload': {**common, 'direction': 'client_to_server', 'frame_kind': 'request', 'frame_payload': {'path': 'start.json'}}},
                {'schema_version': 6, 'seq': 2, 'thread_id': 'root', 'task_root_thread_id': 'root', 'payload': {**common, 'direction': 'server_to_client', 'frame_kind': 'response', 'frame_payload': {'path': 'response.json'}}},
            ]
            trace = root / 'trace.jsonl'
            trace.write_text(''.join(json.dumps(e) + '\n' for e in raw))
            row = project_trace(trace, thread='root')['trajectory'][0]
            self.assertEqual((row['turn_id'], row['step_id'], row['seqs']), ('turn-id', None, [1, 2]))
            self.assertIsNone(project_trace(trace, thread='root', until=1)['trajectory'][0]['turn_id'])

    def test_failed_patch_attempt_and_nonzero_process_exit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def artifact(name, obj):
                (root / f'{name}.json').write_text(json.dumps(obj))
                return {'path': f'{name}.json'}
            patch = artifact('patch', {'payload': {'type': 'function', 'arguments': json.dumps({'command': '*** Begin Patch\n*** Update File: a.txt\n*** End Patch'})}})
            command = artifact('command', {'payload': {'type': 'function', 'arguments': json.dumps({'cmd': 'false'})}})
            runtime = artifact('runtime', {'process_id': '42', 'exit_code': 7, 'aggregated_output': ''})
            def event(seq, payload):
                return {'schema_version': 6, 'seq': seq, 'thread_id': 'root', 'task_root_thread_id': 'root', 'payload': payload}
            raw = [
                event(1, {'type': 'tool_call_started', 'tool_call_id': 'p', 'kind': {'type': 'apply_patch'}, 'invocation_payload': patch}),
                event(2, {'type': 'tool_call_ended', 'tool_call_id': 'p', 'status': 'failed'}),
                event(3, {'type': 'tool_call_started', 'tool_call_id': 'c', 'kind': {'type': 'exec_command'}, 'invocation_payload': command}),
                event(4, {'type': 'tool_call_runtime_ended', 'tool_call_id': 'c', 'runtime_payload': runtime, 'status': 'completed'}),
                event(5, {'type': 'tool_call_ended', 'tool_call_id': 'c', 'status': 'completed'}),
            ]
            trace = root / 'trace.jsonl'
            trace.write_text(''.join(json.dumps(e) + '\n' for e in raw))
            result = project_trace(trace, thread='root')
            file = result['files'][0]
            self.assertEqual((file['path'], file['operation'], file['tool_id'], file['status'], file['status_basis'], file['evidence_basis']),
                             ('a.txt', 'update', 'tool:p', 'failed', 'tool_lifecycle', 'patch_invocation'))
            command_row = result['commands'][0]
            self.assertEqual((command_row['status'], command_row['status_basis'], command_row['exit_code'], command_row['exit_code_seq']),
                             ('completed', 'tool_lifecycle', 7, 4))
            self.assertIsNone(project_trace(trace, thread='root', until=3)['commands'][0]['exit_code'])

    def test_linked_requests_history_and_missing_content(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'payloads').mkdir()
            def artifact(name, obj):
                (root / 'payloads' / f'{name}.json').write_text(json.dumps(obj))
                return {'raw_payload_id': name, 'path': f'payloads/{name}.json'}
            def message(text, source):
                return {'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text': text}],
                        'internal_chat_message_metadata_passthrough': {'content_item_metadata': [{'provenance': {'type': source}}]}}
            extra_tools = {'type': 'additional_tools', 'role': 'developer', 'tools': [{'type': 'namespace', 'name': 'extra', 'tools': [{'type': 'function', 'name': 'nested'}]}]}
            logical = artifact('logical', {'stage': 'logical_prompt_before_request_preparation',
                'input': [message('from the person', 'user'), message('skill content', 'skills'),
                          {'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text': 'legacy'}]}, extra_tools],
                'tools': [{'type': 'function', 'name': 'run', 'parameters': {'type': 'object'}}],
                'base_instructions': {'text': 'base'}})
            history = artifact('history', {'items': [{'item': message('current history', 'user'), 'metadata': {}}, {'item': extra_tools, 'metadata': {}}]})
            response = artifact('response', {'token_usage': {'input_tokens': 100, 'cached_input_tokens': 30,
                'output_tokens': 10, 'reasoning_output_tokens': 3, 'total_tokens': 110}, 'output_items': []})
            prepared = artifact('prepared', {'input': []})
            patch = artifact('patch', {'payload': {'type': 'function', 'arguments': json.dumps({'command': '*** Begin Patch\n*** Update File: a.txt\n*** End Patch'})}})
            command = artifact('command', {'payload': {'type': 'function', 'arguments': json.dumps({'command': 'echo hi'})}})
            def event(seq, payload, time=None):
                return {'schema_version': 6, 'seq': seq, 'wall_time_unix_ms': time if time is not None else seq * 10,
                        'thread_id': 'root', 'task_root_thread_id': 'root', 'codex_turn_id': 'turn', 'payload': payload}
            def h(name, phase, correlations=None, payloads=None):
                return {'type': 'harness_event_observed', 'event': {'category': 'context', 'name': name,
                    'phase': phase, 'step_id': 'step', 'correlations': correlations or {}, 'payloads': payloads or []}}
            events = [
                event(0, {'type': 'harness_event_observed', 'event': {'category': 'context', 'name': 'step_context_capture', 'phase': 'completed', 'details': {'full_context_window_limit': 1000}}}),
                event(1, h('prompt_assembly', 'completed', {'snapshot_id': 'logical'}, [logical])),
                event(2, {'type': 'inference_started', 'inference_call_id': 'failed', 'request_payload': prepared, 'model': 'm'}),
                event(3, h('inference_logical_prompt', 'observed', {'inference_call_id': 'failed', 'logical_prompt_id': 'logical'})),
                event(4, {'type': 'inference_failed', 'inference_call_id': 'failed'}),
                event(5, {'type': 'inference_started', 'inference_call_id': 'ok', 'request_payload': prepared, 'model': 'm'}, 50),
                event(6, h('inference_logical_prompt', 'observed', {'inference_call_id': 'ok', 'logical_prompt_id': 'logical'}), 60),
                event(7, {'type': 'tool_call_started', 'tool_call_id': 'tool', 'kind': {'type': 'exec_command'}}, 70),
                event(8, {'type': 'tool_call_runtime_started', 'tool_call_id': 'tool'}, 80),
                event(9, {'type': 'inference_completed', 'inference_call_id': 'ok', 'response_payload': response}, 100),
                event(10, {'type': 'tool_call_runtime_ended', 'tool_call_id': 'tool'}, 110),
                event(11, {'type': 'tool_call_ended', 'tool_call_id': 'tool', 'status': 'completed'}, 120),
                event(12, {'type': 'harness_event_observed', 'event': {'category': 'context', 'name': 'compaction_decision', 'phase': 'decided', 'details': {'phase': 'mid_turn', 'budget': {'full_context_window_limit': 800, 'active_context_tokens': 700}}}}),
                event(13, h('history_snapshot', 'observed', {'snapshot_id': 'history'}, [history])),
                event(14, {'type': 'code_cell_started', 'runtime_cell_id': 'cell'}),
                event(15, {'type': 'tool_call_started', 'tool_call_id': 'nested', 'kind': {'type': 'exec_command'}, 'requester': {'type': 'code_cell', 'runtime_cell_id': 'cell'}, 'invocation_payload': command}),
                event(16, {'type': 'tool_call_started', 'tool_call_id': 'patch', 'kind': {'type': 'apply_patch'}, 'requester': {'type': 'model'}, 'invocation_payload': patch}),

            ]
            trace = root / 'trace.jsonl'
            trace.write_text(''.join(json.dumps(e) + '\n' for e in events))
            projection = project_trace(trace, thread='root', request='ok')
            self.assertEqual([r['status'] for r in projection['requests']], ['failed', 'completed'])
            self.assertEqual(projection['summary']['usage']['total_tokens'], 110)
            self.assertEqual(projection['summary']['usage']['reported_requests'], 1)
            self.assertEqual(projection['summary']['tool_calls'], 3)
            nested = next(row for row in projection['trajectory'] if row['id'] == 'tool:nested')
            self.assertEqual(nested['parent_id'], 'cell:cell')
            self.assertEqual(projection['commands'][-1]['command'], 'echo hi')
            self.assertEqual([(f['operation'], f['path']) for f in projection['files']], [('update', 'a.txt')])
            self.assertEqual(projection['timing']['active_union_ms'], 80)
            self.assertEqual(projection['snapshot']['source'], 'logical_prompt')
            self.assertEqual(projection['snapshot']['context_window'], 1000)
            self.assertEqual(projection['snapshot']['coverage']['unknown_source_items'], 1)
            self.assertEqual([r['category'] for r in projection['snapshot']['items']],
                             ['base_instructions', 'human_messages', 'skill_instructions', 'unknown'])
            tool = next(row for row in projection['snapshot']['tools'] if row['json_pointer'] == '/tools/0')
            extra = next(row for row in projection['snapshot']['tools'] if row['json_pointer'] == '/input/3/tools/0')
            self.assertEqual(project_trace(trace, thread='root', request='ok', item=extra['id'])['selected_item']['content']['name'], 'extra')
            base = projection['snapshot']['items'][0]
            self.assertEqual(project_trace(trace, thread='root', request='ok', item=base['id'])['selected_item']['content'], {'text': 'base'})
            self.assertEqual(base['tokens'], 5)
            selected = project_trace(trace, thread='root', request='ok', item=tool['id'])['selected_item']
            self.assertEqual(selected['content']['name'], 'run')
            live = project_trace(trace, thread='root')
            self.assertEqual(live['snapshot']['source'], 'history_snapshot')
            self.assertEqual([row['category'] for row in live['snapshot']['items']], ['base_instructions', 'human_messages'])
            self.assertEqual(len(live['snapshot']['tools']), 2)
            self.assertEqual({row['json_pointer'] for row in live['snapshot']['tools']}, {'/items/1/item/tools/0', '/tools/0'})
            live_base, live_history = live['snapshot']['items']
            self.assertEqual((live_base['payload_ref']['raw_payload_id'], live_base['json_pointer'], live_base['seqs']), ('logical', '/base_instructions', [1]))
            self.assertEqual((live_history['payload_ref']['raw_payload_id'], live_history['seqs']), ('history', [13]))
            self.assertEqual(live_base['stage'], 'logical_prompt_before_request_preparation')
            self.assertEqual(project_trace(trace, thread='root', item=live['snapshot']['tools'][0]['id'])['selected_item']['content']['name'], 'extra')
            self.assertIn('last recorded', live['snapshot']['coverage']['description'])
            self.assertIsNone(live['snapshot']['reported_input_tokens'])
            self.assertEqual(live['snapshot']['budget']['active_context_tokens'], 700)
            self.assertEqual(live['snapshot']['context_window'], 800)
            self.assertEqual([i['duration_ms'] for i in live['timing']['intervals'] if i['kind'] == 'uncovered'], [10])
            paused = project_trace(trace, thread='root', until=11)
            self.assertEqual(paused['snapshot']['source'], 'logical_prompt')
            self.assertIn('not captured', paused['snapshot']['coverage']['description'])
            redacted = project_trace(trace, thread='root', request='ok', item=tool['id'], show_content=False)
            self.assertNotIn('content', redacted['selected_item'])
            self.assertIsNone(redacted['snapshot']['items'][1]['preview'])
            logical_path = root / 'payloads' / 'logical.json'
            original_logical = logical_path.read_bytes()
            empty_base = json.loads(original_logical)
            empty_base['base_instructions'] = {'text': ''}
            logical_path.write_text(json.dumps(empty_base))
            empty = project_trace(trace, thread='root', request='ok')['snapshot']['items'][0]
            self.assertEqual((empty['tokens'], empty['json_pointer']), (0, '/base_instructions'))
            logical_path.write_bytes(original_logical)
            history_path = root / 'payloads' / 'history.json'
            saved_history = history_path.read_bytes()
            history_path.unlink()
            partial = project_trace(trace, thread='root')
            components = {entry['key']: entry for entry in partial['snapshot']['composition']}
            self.assertEqual((components['base_instructions']['count'], components['tool_definitions']['count']), (1, 2))
            self.assertIsNotNone(components['base_instructions']['tokens'])
            self.assertIsNone(components['human_messages']['count'])
            self.assertIsNone(components['human_messages']['tokens'])
            self.assertIsNone(partial['snapshot']['estimated_tokens'])
            self.assertIsNone(partial['snapshot']['coverage']['unknown_items'])
            self.assertIsNone(partial['snapshot']['coverage']['unknown_source_items'])
            self.assertIsNone(partial['snapshot']['coverage']['media_items'])
            history_path.write_bytes(saved_history)
            with trace.open('a') as stream:
                stream.write('{partial')
            incomplete = project_trace(trace, thread='root', request='ok')
            self.assertTrue(incomplete['scope']['truncated'])
            self.assertIn('malformed JSONL', incomplete['scope']['diagnostic'])
            self.assertIn('Trace reading stopped', incomplete['snapshot']['coverage']['description'])
            (root / 'payloads' / 'logical.json').unlink()
            missing = project_trace(trace, thread='root', request='ok')
            self.assertEqual(missing['snapshot']['coverage']['state'], 'unavailable')
            self.assertIsNone(missing['snapshot']['estimated_tokens'])
            self.assertTrue(all(entry['count'] is None and entry['tokens'] is None for entry in missing['snapshot']['composition']))
            self.assertEqual([missing['snapshot']['coverage'][key] for key in ('unknown_items', 'unknown_source_items', 'media_items')], [None, None, None])
            missing_fallback = project_trace(trace, thread='root', until=11)
            self.assertEqual(missing_fallback['snapshot']['coverage']['state'], 'unavailable')
            self.assertIn('payload is unavailable', missing_fallback['snapshot']['coverage']['description'])


if __name__ == '__main__':
    unittest.main()
