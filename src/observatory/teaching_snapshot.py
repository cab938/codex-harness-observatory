"""Content and provenance projection from recorded prompt and history artifacts."""

import json
import math
from collections import Counter
from typing import Any

from .trace_viewer import TraceInputError, artifact_payload, safe_reference_path

CATEGORIES = {
    'base_instructions': 'Base instructions', 'tool_definitions': 'Tool definitions',
    'human_messages': 'Human messages', 'injected_context': 'Injected context',
    'skill_instructions': 'Skill instructions', 'assistant_messages': 'Assistant messages',
    'tool_results': 'Tool results', 'unknown': 'Unknown',
}


def load(path, reference):
    if not isinstance(reference, dict) or not isinstance(reference.get('path'), str):
        return None
    try:
        return artifact_payload(path, reference['path'])['content']
    except (TraceInputError, OSError):
        return None


def category(role, kind, provenance):
    if provenance == 'user':
        return 'human_messages'
    if provenance == 'skills':
        return 'skill_instructions'
    if provenance in ('agents_md', 'developer_instructions', 'harness'):
        return 'injected_context'
    if provenance == 'tool' or kind in ('function_call_output', 'custom_tool_call_output', 'tool_search_output'):
        return 'tool_results'
    if role == 'assistant' or kind in ('agent_message', 'function_call', 'custom_tool_call', 'reasoning'):
        return 'assistant_messages'
    return 'unknown'


def text_and_media(value):
    """Count declared text only; media and opaque bodies have unknown size."""
    if isinstance(value, str):
        return value, 0
    if isinstance(value, list):
        parts = [text_and_media(v) for v in value]
        return '\n'.join(s for s, _ in parts if s), sum(n for _, n in parts)
    if isinstance(value, dict):
        kind = str(value.get('type', ''))
        if any(x in kind for x in ('image', 'audio', 'video')) or value.get('encrypted_content'):
            return '', 1
        if isinstance(value.get('text'), str):
            return value['text'], 0
        if isinstance(value.get('output'), str):
            return value['output'], 0
        if isinstance(value.get('arguments'), str):
            return value['arguments'], 0
        return text_and_media(value.get('content', []))
    return '', 0


def build_snapshot(path, *, ref, seq, thread_id, request_id, source, model, usage, budget, show_content):
    obj = load(path, ref)
    identity = (ref or {}).get('raw_payload_id') or f'{source}:{seq}'
    rows, tools, contents = [], [], {}
    public_ref = {**ref, 'path': safe_reference_path(ref['path'])} if isinstance(ref, dict) and isinstance(ref.get('path'), str) else ref
    media_count = 0

    def add(value, pointer, group, role=None, provenance=None, schema=False, source_kind=None):
        nonlocal media_count
        if schema:
            text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
            media = 0
        else:
            text, media = text_and_media(value)
        media_count += media
        ident = f'{identity}:{pointer}'
        # One fixed four-token structural allowance per recorded part.
        explicit_empty_text = (isinstance(value, str) or
                               isinstance(value, dict) and isinstance(value.get('text'), str))
        tokens = math.ceil(len(text) / 4) + 4 if text else 0 if explicit_empty_text else None
        row = {'id': ident, 'category': group, 'role': role, 'source': provenance or 'unknown',
               'source_kind': source_kind, 'stage': obj.get('stage') or source if isinstance(obj, dict) else source, 'tokens': tokens, 'preview': text[:240] if show_content else None,
               'seqs': [seq], 'payload_ref': public_ref, 'json_pointer': pointer, 'change': None}
        contents[ident] = value
        (tools if schema else rows).append(row)

    if isinstance(obj, dict):
        base = obj.get('base_instructions', obj.get('instructions'))
        if base is not None:
            add(base, '/base_instructions' if 'base_instructions' in obj else '/instructions', 'base_instructions', provenance='base_instructions')
        inputs = obj.get('items') if source == 'history_snapshot' else obj.get('input')
        if isinstance(inputs, list):
            for i, envelope in enumerate(inputs):
                value = envelope.get('item') if source == 'history_snapshot' and isinstance(envelope, dict) else envelope
                prefix = f'/items/{i}/item' if source == 'history_snapshot' else f'/input/{i}'
                if not isinstance(value, dict):
                    add(value, prefix, 'unknown')
                    continue
                role, kind = value.get('role'), value.get('type')
                if kind == 'additional_tools' and isinstance(value.get('tools'), list):
                    for j, tool in enumerate(value['tools']):
                        add(tool, f'{prefix}/tools/{j}', 'tool_definitions', role=role,
                            provenance='additional_tools', schema=True)
                    continue
                metadata = value.get('internal_chat_message_metadata_passthrough') or {}
                meta = metadata.get('content_item_metadata') if isinstance(metadata, dict) else None
                kinds = metadata.get('content_item_kinds') if isinstance(metadata, dict) else None
                content = value.get('content')
                if isinstance(content, list) and content:
                    for j, part in enumerate(content):
                        attribution = meta[j] if isinstance(meta, list) and j < len(meta) else {}
                        provenance = attribution.get('provenance', {}) if isinstance(attribution, dict) else {}
                        prov = provenance.get('type') if isinstance(provenance, dict) else provenance
                        source_kind = kinds[j] if isinstance(kinds, list) and j < len(kinds) else None
                        add(part, f'{prefix}/content/{j}', category(role, kind, prov), role, prov, source_kind=source_kind)
                else:
                    add(value, prefix, category(role, kind, None), role)
        for i, tool in enumerate(obj.get('tools', []) if isinstance(obj.get('tools'), list) else []):
            add(tool, f'/tools/{i}', 'tool_definitions', provenance='recorded_tool_schema', schema=True)
    exists = isinstance(obj, dict)
    counts = Counter(r['category'] for r in rows + tools)
    composition = [{'key': k, 'label': label,
                    'tokens': sum(r['tokens'] or 0 for r in rows + tools if r['category'] == k) if exists else None,
                    'count': counts[k] if exists else None} for k, label in CATEGORIES.items()]
    unknown = counts['unknown'] if exists else None
    coverage = {'state': 'partial' if exists else 'unavailable',
                'description': ('Observed history only; the next request can differ.' if source == 'history_snapshot' else 'Recorded snapshot; source and opaque portions may be unknown.') if exists else 'Recorded payload unavailable.',
                'unknown_items': unknown, 'unknown_source_items': sum(row['source'] == 'unknown' for row in rows + tools) if exists else None, 'media_items': media_count if exists else None,
                'recorded_fields': {'base_instructions': exists and ('base_instructions' in obj or 'instructions' in obj),
                                    'tool_definitions': exists and isinstance(obj.get('tools'), list)},
                'estimate_method': 'Declared text or JSON schema characters / 4, rounded up, plus 4 tokens per nonempty part; media and opaque content excluded.'}
    snapshot = {'id': identity, 'request_id': request_id, 'thread_id': thread_id, 'seq': seq,
                'stage': obj.get('stage') if exists else None, 'source': source,
                'estimated_tokens': sum(c['tokens'] for c in composition) if exists else None,
                'reported_input_tokens': usage.get('input_tokens') if isinstance(usage, dict) and source != 'history_snapshot' else None,
                'model': model, 'context_window': (budget or {}).get('full_context_window_limit'), 'budget': budget,
                'composition': composition, 'items': rows, 'tools': tools, 'coverage': coverage}
    return snapshot, contents
