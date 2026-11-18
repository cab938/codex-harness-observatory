"""Read-only, prefix-replayable teaching projection of the raw Observatory trace."""

import json
import re
from pathlib import Path

from . import teaching_snapshot as snapshots
from .trace_viewer import TaskLedger, TraceInputError, events, harness, payload_references, safe_detail, safe_stream_error, wire_pairing


def _ref(value):
    refs = payload_references(value, safe_paths=False)
    return refs[0] if refs else None


def _refs(value):
    return payload_references(value, safe_paths=True)


def _duration(start, end):
    return end - start if isinstance(start, int) and isinstance(end, int) and end >= start else None


def _timing(rows):
    intervals = []
    for row in rows:
        if row['kind'] not in ('request', 'tool', 'code_cell'):
            continue
        if '_runtime_start_ms' in row and '_runtime_end_ms' in row:
            start, end = row['_runtime_start_ms'], row['_runtime_end_ms']
        else:
            start, end = row.get('time_ms'), row.get('_end_ms')
        duration = _duration(start, end)
        interval_kind = 'observable_wait' if row['kind'] == 'tool' and row['title'] in ('wait', 'wait_agent') else row['kind']
        intervals.append({'id': row['id'], 'kind': interval_kind, 'start_ms': start,
                          'end_ms': end, 'duration_ms': duration, 'seqs': row['seqs']})
    known = sorted((x['start_ms'], x['end_ms']) for x in intervals if x['duration_ms'] is not None)
    merged = []
    for start, end in known:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    active = sum(end - start for start, end in merged) if merged else None
    span = known[-1][1] - known[0][0] if known else None
    if known:
        span = max(end for _, end in known) - min(start for start, _ in known)
    waits = [{'id': f'wait:{a[1]}:{b[0]}', 'kind': 'uncovered', 'start_ms': a[1],
              'end_ms': b[0], 'duration_ms': b[0] - a[1], 'seqs': []}
             for a, b in zip(merged, merged[1:]) if b[0] > a[1]]
    return {'intervals': intervals + waits, 'active_union_ms': active,
            'observed_span_ms': span, 'uncovered_ms': span - active if span is not None else None,
            'incomplete_intervals': sum(interval['duration_ms'] is None for interval in intervals)}


def project_trace(trace_path, *, thread=None, root=None, descendants=False, until=None,
                  request='live', item=None, show_content=True):
    """Build a semantic view without modifying or supplementing the recording."""
    path = Path(trace_path)
    ledger, recorded = TaskLedger(), []
    truncated = False
    diagnostic = None
    iterator = events(path)
    while True:
        try:
            event = next(iterator)
        except StopIteration:
            break
        except TraceInputError as error:
            truncated = True
            diagnostic = safe_stream_error(error, path)
            break
        if until is not None and event['seq'] > until:
            break
        ledger.apply(event)
        recorded.append(event)
    threads = []
    for root_id, task in ledger.tasks.items():
        for thread_id, info in task.threads.items():
            threads.append({'id': thread_id, 'root_thread_id': root_id,
                            'parent_thread_id': info.parent_thread_id, 'agent_path': info.agent_path,
                            'model': None, 'status': info.status})
    selected = {thread} if thread else ({root} if root else None)
    if root and not thread and descendants:
        selected = {t['id'] for t in threads if t['root_thread_id'] == root}
    elif thread and descendants:
        while True:
            expanded = selected | {t['id'] for t in threads if t['parent_thread_id'] in selected}
            if expanded == selected:
                break
            selected = expanded
    def in_scope(event):
        payload = event['payload']
        tid = event.get('thread_id') or payload.get('thread_id') or payload.get('source_thread_id')
        if tid is None and payload.get('type') == 'app_server_frame_observed' and payload.get('method') in ('turn/start', 'turn/steer'):
            frame = snapshots.load(path, payload.get('frame_payload'))
            params = frame.get('params') if isinstance(frame, dict) else None
            tid = params.get('threadId') if isinstance(params, dict) else None
        return selected is None or tid in selected
    scoped = [event for event in recorded if in_scope(event)]
    requests, trajectory, context_events, files, commands = [], [], [], [], []
    by_request, by_tool, by_cell, logical, links = {}, {}, {}, {}, {}
    model_calls = {}
    pending_users = {}
    latest_history = {}
    budget_by_thread = {}
    turns, steps = set(), set()
    active_step = {}
    latest_request = {}
    for event in scoped:
        seq, payload = event['seq'], event['payload']
        kind, time = payload['type'], event.get('wall_time_unix_ms')
        tid = event.get('thread_id') or payload.get('thread_id') or payload.get('source_thread_id')
        turn = event.get('codex_turn_id') or payload.get('codex_turn_id')
        frame = None
        if kind == 'app_server_frame_observed' and payload.get('direction') == 'client_to_server' and payload.get('method') in ('turn/start', 'turn/steer'):
            frame = snapshots.load(path, payload.get('frame_payload'))
            params = frame.get('params') if isinstance(frame, dict) else None
            if isinstance(params, dict):
                tid = tid or params.get('threadId')
                turn = turn or params.get('turnId')
        if turn:
            turns.add((tid, turn))
        h = harness(event)
        if h and h.get('step_id'):
            active_step[(tid, turn)] = h['step_id']
            steps.add((tid, h['step_id']))
        step = payload.get('step_id') or (h or {}).get('step_id') or active_step.get((tid, turn))
        corr = (h or {}).get('correlations') or {}
        refs = _refs(payload)
        def row(identifier, kind_name, title):
            return {'id': identifier, 'kind': kind_name, 'seq': seq, 'seqs': [seq],
                    'thread_id': tid, 'turn_id': turn, 'step_id': step,
                    'request_id': latest_request.get(tid), 'parent_id': None,
                    'title': title, 'summary': None, 'status': 'observed', 'time_ms': time,
                    'duration_ms': None, 'usage': None, 'payload_refs': refs}
        if h and h.get('category') == 'context':
            details = h.get('details') if isinstance(h.get('details'), dict) else {}
            context_events.append({'id': f'context:{seq}', 'seq': seq, 'thread_id': tid,
                                   'name': h.get('name'), 'phase': h.get('phase'),
                                   'outcome': h.get('outcome'), 'details': details if show_content else safe_detail(details),
                                   'payload_refs': refs})
            if h.get('name') == 'compaction_decision':
                budget = details.get('budget')
                budget_by_thread[tid] = budget if isinstance(budget, dict) else details
            elif h.get('name') == 'step_context_capture' and h.get('phase') == 'completed':
                budget = {k: details[k] for k in ('nominal_context_window', 'effective_context_window_percent',
                          'full_context_window_limit', 'auto_compact_scope', 'auto_compact_scope_limit') if k in details}
                if budget:
                    budget_by_thread[tid] = budget
            if h.get('name') == 'prompt_assembly' and corr.get('snapshot_id'):
                logical[corr['snapshot_id']] = (event, _ref(h))
            elif h.get('name') == 'inference_logical_prompt':
                links[corr.get('inference_call_id')] = (corr.get('logical_prompt_id'), seq)
            elif h.get('name') == 'history_snapshot':
                latest_history[tid] = (event, _ref(h))
        if kind == 'app_server_frame_observed' and payload.get('direction') == 'client_to_server' and payload.get('method') in ('turn/start', 'turn/steer'):
            params = frame.get('params') if isinstance(frame, dict) else None
            inputs = params.get('input') if isinstance(params, dict) else None
            if isinstance(inputs, list) and inputs:
                r = row(f'user:{seq}', 'user', 'User input')
                r['request_id'] = None
                text, _ = snapshots.text_and_media(inputs)
                r['summary'] = text[:240] if show_content else None
                trajectory.append(r)
                pairing = wire_pairing(payload, event.get('schema_version'))
                if pairing and pairing.get('basis') == 'exchange' and pairing.get('role') == 'request':
                    pending_users[pairing['key']] = r
        elif kind == 'app_server_frame_observed' and payload.get('direction') == 'server_to_client' and payload.get('method') in ('turn/start', 'turn/steer'):
            pairing = wire_pairing(payload, event.get('schema_version'))
            user_row = pending_users.get(pairing.get('key')) if pairing and pairing.get('basis') == 'exchange' and pairing.get('role') == 'response' else None
            if user_row and (tid is None or user_row['thread_id'] == tid):
                response = snapshots.load(path, payload.get('frame_payload'))
                result = response.get('result') if isinstance(response, dict) else None
                response_turn = result.get('turn') if isinstance(result, dict) else None
                response_id = response_turn.get('id') if isinstance(response_turn, dict) else (result.get('turnId') if isinstance(result, dict) else None)
                if isinstance(response_id, str) and (not user_row['turn_id'] or user_row['turn_id'] == response_id):
                    user_row['turn_id'] = response_id
                    user_row['seqs'].append(seq)
                    user_row['payload_refs'].extend(refs)
                    turns.add((user_row['thread_id'], response_id))
        if kind == 'inference_started':
            ident = payload.get('inference_call_id')
            if not ident:
                continue
            latest_request[tid] = ident
            record = {'id': ident, 'seq': seq, 'end_seq': None, 'thread_id': tid,
                      'turn_id': turn, 'step_id': step, 'model': payload.get('model'),
                      'provider': payload.get('provider_name'), 'status': 'started', 'time_ms': time,
                      'duration_ms': None, 'usage': None, 'estimated_tokens': None, 'composition': [],
                      '_event': event, '_ref': payload.get('logical_request_payload') or payload.get('request_payload'),
                      '_source': 'logical_request' if payload.get('logical_request_payload') else 'prepared_request',
                      '_budget': budget_by_thread.get(tid)}
            requests.append(record); by_request[ident] = record
            r = row(f'request:{ident}', 'request', 'Model request'); r['request_id'] = ident
            trajectory.append(r); record['_row'] = r
            for t in threads:
                if t['id'] == tid:
                    t['model'] = payload.get('model') or t['model']
        elif kind in ('inference_completed', 'inference_failed', 'inference_cancelled'):
            record = by_request.get(payload.get('inference_call_id'))
            if record:
                content = snapshots.load(path, payload.get('response_payload') or payload.get('partial_response_payload'))
                usage = content.get('token_usage') if isinstance(content, dict) else None
                record.update(end_seq=seq, status=kind.removeprefix('inference_'), duration_ms=_duration(record['time_ms'], time), usage=usage)
                r = record['_row']; r.update(status=record['status'], duration_ms=record['duration_ms'], usage=usage, _end_ms=time)
                r['seqs'].append(seq); r['payload_refs'].extend(refs)
                if isinstance(content, dict):
                    for i, output in enumerate(content.get('output_items') or []):
                        if not isinstance(output, dict):
                            continue
                        out = row(f'output:{record["id"]}:{i}', 'assistant', output.get('type', 'output'))
                        out['request_id'] = record['id']; out['parent_id'] = f'request:{record["id"]}'
                        out['thread_id'], out['turn_id'], out['step_id'] = record['thread_id'], record['turn_id'], record['step_id']
                        out['payload_refs'] = refs
                        call_id = output.get('call_id')
                        if isinstance(call_id, str) and call_id:
                            model_calls.setdefault((record['thread_id'], call_id), set()).add(record['id'])
                        text, _ = snapshots.text_and_media(output)
                        out['summary'] = text[:240] if show_content else None
                        trajectory.append(out)
        elif kind in ('tool_call_started', 'code_cell_started'):
            ident = payload.get('tool_call_id') if kind == 'tool_call_started' else payload.get('runtime_cell_id')
            if not ident:
                continue
            is_tool = kind == 'tool_call_started'
            name = (payload.get('kind') or {}).get('type', 'tool') if is_tool else 'Code cell'
            r = row(('tool:' if is_tool else 'cell:') + ident, 'tool' if is_tool else 'code_cell', name)
            r['request_id'] = None
            r['_model_visible_call_id'] = payload.get('model_visible_call_id')
            requester = payload.get('requester') or {}
            if isinstance(requester, dict):
                parent = requester.get('runtime_cell_id')
                r['parent_id'] = f'cell:{parent}' if parent else None
            summary = payload.get('summary') or {}
            r['summary'] = summary.get('input_preview') if show_content and isinstance(summary, dict) else None
            trajectory.append(r); (by_tool if is_tool else by_cell)[ident] = r
            if is_tool and name == 'apply_patch':
                inv = snapshots.load(path, payload.get('invocation_payload'))
                invocation = inv.get('payload') if isinstance(inv, dict) else None
                body = invocation.get('input') if isinstance(invocation, dict) else None
                args = invocation.get('arguments') if isinstance(invocation, dict) else None
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except ValueError:
                        args = None
                if body is None and isinstance(args, dict):
                    body = args.get('command')
                if isinstance(body, str):
                    for operation, filename in re.findall(r'^\*\*\* (Add|Update|Delete) File: (.+)$', body, re.MULTILINE):
                        files.append({'id': f'{r["id"]}:{len(files)}', 'seq': seq, 'thread_id': tid,
                                      'path': filename if show_content else None, 'operation': operation.lower(),
                                      'tool_id': r['id'], 'status': 'started', 'status_basis': 'tool_lifecycle',
                                      'evidence_basis': 'patch_invocation', 'payload_refs': refs})
            if is_tool and name == 'exec_command':
                inv = snapshots.load(path, payload.get('invocation_payload'))
                args = (inv.get('payload') or {}).get('arguments') if isinstance(inv, dict) else None
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except ValueError:
                        args = None
                commands.append({'id': r['id'], 'seq': seq, 'thread_id': tid,
                                 'command': (args.get('cmd') or args.get('command')) if show_content and isinstance(args, dict) else None,
                                 'status': 'started', 'status_basis': 'tool_lifecycle', 'exit_code': None,
                                 'exit_code_seq': None, 'duration_ms': None, 'payload_refs': refs})
        elif kind in ('tool_call_ended', 'tool_call_runtime_started', 'tool_call_runtime_ended', 'code_cell_ended', 'code_cell_initial_response'):
            ident = payload.get('tool_call_id') or payload.get('runtime_cell_id')
            r = by_tool.get(ident) or by_cell.get(ident)
            if r:
                r['seqs'].append(seq); r['payload_refs'].extend(refs)
                if kind == 'tool_call_runtime_started':
                    r['_runtime_start_ms'] = time
                elif kind == 'tool_call_runtime_ended':
                    r['_runtime_end_ms'] = time
                    runtime = snapshots.load(path, payload.get('runtime_payload'))
                    exit_code = runtime.get('exit_code') if isinstance(runtime, dict) else None
                    if type(exit_code) is int:
                        for cmd in commands:
                            if cmd['id'] == r['id']:
                                cmd.update(exit_code=exit_code, exit_code_seq=seq, payload_refs=r['payload_refs'])
                if kind in ('tool_call_ended', 'code_cell_ended'):
                    r.update(status=payload.get('status') or 'completed', duration_ms=_duration(r['time_ms'], time), _end_ms=time)
                    for cmd in commands:
                        if cmd['id'] == r['id']:
                            cmd.update(status=r['status'], duration_ms=r['duration_ms'], payload_refs=r['payload_refs'])
                    for file in files:
                        if file['tool_id'] == r['id']:
                            file.update(status=r['status'], payload_refs=r['payload_refs'])
        elif kind.startswith('compaction_') or kind == 'agent_result_observed':
            r = row(f'event:{seq}', 'context' if kind.startswith('compaction_') else 'agent', kind.replace('_', ' '))
            r['status'] = payload.get('status') or 'observed'; trajectory.append(r)
    # Only native model-visible IDs prove a generated call belongs to an attempt.
    # A reused ID across attempts remains ambiguous rather than selecting by proximity.
    for r in list(by_cell.values()) + list(by_tool.values()):
        matches = model_calls.get((r['thread_id'], r.get('_model_visible_call_id')), set())
        if len(matches) == 1:
            r['request_id'] = next(iter(matches))
            if not r['parent_id']:
                r['parent_id'] = f'request:{r["request_id"]}'
        elif r['parent_id'] and r['parent_id'].startswith('cell:'):
            cell = by_cell.get(r['parent_id'][5:])
            if cell:
                r['request_id'] = cell['request_id']
    contents_by_request = {}
    for record in requests:
        link, link_seq = links.get(record['id'], (None, None))
        assembly = logical.get(link)
        if assembly:
            source_event, ref = assembly
            record['_ref'], record['_source'] = ref, 'logical_prompt'
            record['_row']['seqs'] = sorted(set(record['_row']['seqs'] + [source_event['seq'], link_seq]))
            record['_row']['payload_refs'].extend(_refs(source_event['payload']))
        else:
            source_event = record['_event']
        snap, contents = snapshots.build_snapshot(path, ref=record['_ref'], seq=source_event['seq'],
            thread_id=record['thread_id'], request_id=record['id'], source=record['_source'],
            model=record['model'], usage=record['usage'], budget=record['_budget'], show_content=show_content)
        record['estimated_tokens'], record['composition'] = snap['estimated_tokens'], snap['composition']
        contents_by_request[record['id']] = (snap, contents)
    target = by_request.get(request) if request != 'live' else None
    live_thread = thread or root or (requests[-1]['thread_id'] if requests else next(reversed(latest_history), None))
    if request == 'live' and live_thread in latest_history:
        event, ref = latest_history[live_thread]
        recent = next((r for r in reversed(requests) if r['thread_id'] == live_thread), None)
        snapshot, content = snapshots.build_snapshot(path, ref=ref, seq=event['seq'], thread_id=live_thread,
            request_id=None, source='history_snapshot', model=recent['model'] if recent else None,
            usage=None, budget=budget_by_thread.get(live_thread), show_content=show_content)
        # Prefix components are separately observed; each keeps its original stage and reference.
        candidates = []
        for logical_event, logical_ref in logical.values():
            logical_tid = logical_event.get('thread_id') or logical_event['payload'].get('thread_id')
            if logical_tid == live_thread:
                prefix, prefix_content = snapshots.build_snapshot(path, ref=logical_ref, seq=logical_event['seq'],
                    thread_id=live_thread, request_id=None, source='logical_prompt', model=None,
                    usage=None, budget=None, show_content=show_content)
                candidates.append((logical_event['seq'], prefix, prefix_content))
        for record in requests:
            if record['thread_id'] == live_thread:
                prefix, prefix_content = contents_by_request[record['id']]
                candidates.append((prefix['seq'], prefix, prefix_content))
        prefix_info = {}
        history_available = snapshot['coverage']['state'] != 'unavailable'
        for group in ('base_instructions', 'tool_definitions'):
            candidate = next(((prefix, bodies) for _, prefix, bodies in sorted(candidates, key=lambda x: x[0], reverse=True)
                              if prefix['coverage']['recorded_fields'][group]), None)
            if candidate:
                prefix, bodies = candidate
                if group == 'tool_definitions':
                    # Current history owns additional_tools items; only add the earlier
                    # prompt's separate top-level catalog to avoid duplicating them.
                    chosen = [row for row in prefix['tools'] if row['json_pointer'].startswith('/tools/')] if history_available else prefix['tools']
                    snapshot['tools'].extend(chosen)
                else:
                    chosen = [row for row in prefix['items'] if row['category'] == group]
                    snapshot['items'] = chosen + snapshot['items']
                content.update({row['id']: bodies[row['id']] for row in chosen})
                prefix_info[group] = {'seq': prefix['seq'], 'source': prefix['source'], 'stage': prefix['stage']}
        for component in snapshot['composition']:
            key = component['key']
            known = key in prefix_info if key in ('base_instructions', 'tool_definitions') else history_available
            rows = [row for row in snapshot['items'] + snapshot['tools'] if row['category'] == key]
            component.update(tokens=sum(row['tokens'] or 0 for row in rows) if known else None,
                             count=len(rows) if known else None)
        if all(component['tokens'] is not None for component in snapshot['composition']):
            snapshot['estimated_tokens'] = sum(component['tokens'] for component in snapshot['composition'])
        else:
            snapshot['estimated_tokens'] = None
        if history_available:
            snapshot['coverage']['unknown_source_items'] = sum(row['source'] == 'unknown' for row in snapshot['items'] + snapshot['tools'])
        snapshot['coverage']['prefix'] = prefix_info
        snapshot['coverage']['description'] = (
            'Current observed history, with base instructions and the top-level tool catalog from their last recorded prompt or request when available. '
            'Prefix components may be older; the next request can differ.'
            if snapshot['coverage']['state'] != 'unavailable' else
            'Current history payload unavailable; any base instructions and tool definitions shown are from an earlier recorded prompt or request.')
    elif target:
        snapshot, content = contents_by_request[target['id']]
    elif request == 'live' and requests:
        target = next((r for r in reversed(requests) if not live_thread or r['thread_id'] == live_thread), None)
        snapshot, content = contents_by_request[target['id']] if target else (None, {})
        if snapshot:
            unavailable = snapshot['coverage']['state'] == 'unavailable'
            snapshot = {**snapshot, 'coverage': {**snapshot['coverage'], 'state': 'unavailable' if unavailable else 'partial',
                'description': ('Latest request payload is unavailable; current history was not captured.' if unavailable else
                                'Latest recorded request; current history was not captured.')}}
    else:
        snapshot, content = None, {}
    if snapshot and diagnostic:
        snapshot = {**snapshot, 'coverage': {**snapshot['coverage'], 'state': 'unavailable' if snapshot['coverage']['state'] == 'unavailable' else 'partial',
                    'description': snapshot['coverage']['description'] + ' Trace reading stopped: ' + diagnostic}}
    selected_item = None
    if item and snapshot:
        selected_item = next((dict(row) for row in snapshot['items'] + snapshot['tools'] if row['id'] == item), None)
        if selected_item and show_content:
            selected_item['content'] = content.get(item)
    usage_keys = ('input_tokens', 'cached_input_tokens', 'output_tokens', 'reasoning_output_tokens', 'total_tokens')
    with_usage = [r['usage'] for r in requests if isinstance(r['usage'], dict)]
    usage_totals = {key: sum(u[key] for u in with_usage if isinstance(u.get(key), int)) if any(isinstance(u.get(key), int) for u in with_usage) else None for key in usage_keys}
    usage_totals.update(reported_requests=len(with_usage), total_requests=len(requests))
    result = {'version': 1, 'content_mode': 'full' if show_content else 'redacted',
              'last_seq': recorded[-1]['seq'] if recorded else None,
              'scope': {'thread': thread, 'root': root, 'descendants': descendants, 'until': until, 'truncated': truncated, 'diagnostic': diagnostic},
              'threads': threads, 'summary': {'threads': len(selected) if selected is not None else len(threads),
              'turns': len(turns), 'steps': len(steps), 'requests': len(requests), 'tool_calls': len(by_tool), 'usage': usage_totals},
              'requests': [{k: v for k, v in r.items() if not k.startswith('_')} for r in requests],
              'selected_request': target['id'] if target else None, 'snapshot': snapshot,
              'trajectory': [{k: v for k, v in r.items() if not k.startswith('_')} for r in sorted(trajectory, key=lambda r: r['seq'])],
              'context_events': context_events, 'files': files, 'commands': commands,
              'timing': _timing(trajectory), 'selected_item': selected_item}
    return result
