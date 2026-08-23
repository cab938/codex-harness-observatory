#!/usr/bin/env python3
"""Print a compact, privacy-conscious view of a raw Codex rollout trace."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Sequence


OPENING_PHASES = {"requested", "started", "dispatched", "enqueued"}
TERMINAL_PHASES = {
    "completed", "resolved", "failed", "cancelled", "dequeued", "delivered", "rejected",
}
PAIR_CORRELATION_KEYS = (
    "message_id",
    "guardian_review_id",
    "approval_id",
    "tool_call_id",
    "target_thread_id",
    "child_thread_id",
    "parent_thread_id",
)
SENSITIVE_DETAIL_KEYS = {
    "argument", "arguments", "command", "content", "file", "files", "message",
    "messages", "output", "path", "paths", "payload", "payloads", "prompt",
    "result", "results", "source", "text",
}


class TraceInputError(Exception):
    """A trace file cannot be safely read as a raw event stream."""


@dataclass(frozen=True)
class Filters:
    payload_type: set[str]
    thread: set[str]
    turn: set[str]
    step: set[str]
    category: set[str]
    name: set[str]
    phase: set[str]
    correlations: tuple[tuple[str, str], ...]
    harness_only: bool


def parse_correlation(value: str) -> tuple[str, str]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("correlation must be KEY=VALUE")
    key, matched = value.split("=", 1)
    if not key or not matched:
        raise argparse.ArgumentTypeError("correlation must be KEY=VALUE")
    return key, matched


def trace_path(input_path: str) -> Path:
    path = Path(input_path)
    if path.is_dir():
        path = path / "trace.jsonl"
    if path.name != "trace.jsonl" and path.suffix != ".jsonl":
        raise TraceInputError(f"expected a bundle directory or a .jsonl file: {input_path}")
    if not path.is_file():
        raise TraceInputError(f"trace file not found: {path}")
    return path


def events(path: Path) -> Iterator[dict[str, Any]]:
    previous_seq: int | None = None
    try:
        stream = path.open(encoding="utf-8")
    except OSError as error:
        raise TraceInputError(f"cannot open {path}: {error}") from error
    with stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as error:
                raise TraceInputError(
                    f"{path}:{line_number}: malformed JSONL: {error.msg}"
                ) from error
            if not isinstance(event, dict):
                raise TraceInputError(f"{path}:{line_number}: raw event must be a JSON object")
            seq = event.get("seq")
            if not isinstance(seq, int):
                raise TraceInputError(f"{path}:{line_number}: raw event has no integer seq")
            if previous_seq is not None and seq <= previous_seq:
                raise TraceInputError(
                    f"{path}:{line_number}: seq {seq} is not after prior seq {previous_seq}"
                )
            previous_seq = seq
            payload = event.get("payload")
            if not isinstance(payload, dict) or not isinstance(payload.get("type"), str):
                raise TraceInputError(f"{path}:{line_number}: raw event has no typed payload")
            yield event


def harness(event: dict[str, Any]) -> dict[str, Any] | None:
    payload = event["payload"]
    contained = payload.get("event")
    return contained if payload.get("type") == "harness_event_observed" and isinstance(contained, dict) else None


def matches(event: dict[str, Any], filters: Filters) -> bool:
    payload = event["payload"]
    if filters.payload_type and payload["type"] not in filters.payload_type:
        return False
    if filters.thread and event.get("thread_id") not in filters.thread:
        return False
    if filters.turn and event.get("codex_turn_id") not in filters.turn:
        return False
    item = harness(event)
    if filters.harness_only and item is None:
        return False
    if item is None:
        return not any((filters.step, filters.category, filters.name, filters.phase, filters.correlations))
    if filters.step and item.get("step_id") not in filters.step:
        return False
    if filters.category and item.get("category") not in filters.category:
        return False
    if filters.name and item.get("name") not in filters.name:
        return False
    if filters.phase and item.get("phase") not in filters.phase:
        return False
    correlations = item.get("correlations") or {}
    return all(correlations.get(key) == value for key, value in filters.correlations)


def safe_detail(value: Any, key: str = "") -> Any:
    if key.lower() in SENSITIVE_DETAIL_KEYS:
        return "<redacted>"
    if isinstance(value, dict):
        return {str(child_key): safe_detail(child, str(child_key)) for child_key, child in value.items()}
    if isinstance(value, list):
        return [safe_detail(child, key) for child in value[:20]]
    if isinstance(value, str) and len(value) > 120:
        return value[:117] + "..."
    return value


def compact_value(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def harness_line(event: dict[str, Any], item: dict[str, Any], details: bool) -> str:
    fields = [
        f"{item.get('category', '?')}.{item.get('name', '?')}",
        f"phase={item.get('phase', '?')}",
    ]
    for label, value in (("outcome", item.get("outcome")), ("reason", item.get("reason"))):
        if value is not None:
            fields.append(f"{label}={value}")
    for label, value in (("thread", event.get("thread_id")), ("turn", event.get("codex_turn_id")), ("step", item.get("step_id"))):
        if value is not None:
            fields.append(f"{label}={value}")
    correlations = item.get("correlations") or {}
    if correlations:
        fields.append("corr=" + compact_value(correlations))
    if details and item.get("details") not in (None, {}):
        fields.append("details=" + compact_value(safe_detail(item["details"])))
    return " ".join(fields)


def raw_line(event: dict[str, Any]) -> str:
    payload = event["payload"]
    fields = [payload["type"]]
    safe_keys = {"status", "model", "provider_name", "kind", "event_type", "trace_id", "root_thread_id"}
    for key in sorted(payload):
        if key in safe_keys or key.endswith("_id"):
            value = payload[key]
            if isinstance(value, (str, int, float, bool)):
                fields.append(f"{key}={value}")
    for label, value in (("thread", event.get("thread_id")), ("turn", event.get("codex_turn_id"))):
        if value is not None:
            fields.append(f"{label}={value}")
    return " ".join(fields)


def timeline(event_stream: Iterator[dict[str, Any]], filters: Filters, details: bool) -> int:
    matched = 0
    for event in event_stream:
        if not matches(event, filters):
            continue
        item = harness(event)
        body = harness_line(event, item, details) if item else raw_line(event)
        print(f"{event['seq']:>6} {event.get('wall_time_unix_ms', '?'):>13} {body}")
        matched += 1
    return matched


def duration_key(item: dict[str, Any]) -> tuple[str, str, str] | None:
    step = item.get("step_id")
    correlations = item.get("correlations") or {}
    identity = next(
        (
            f"{key}={correlations[key]}"
            for key in PAIR_CORRELATION_KEYS
            if isinstance(correlations.get(key), str)
        ),
        None,
    )
    if identity is None and isinstance(step, str):
        identity = "step=" + step
    if identity is None:
        return None
    return str(item.get("category", "?")), str(item.get("name", "?")), identity


def summary(event_stream: Iterator[dict[str, Any]], filters: Filters) -> int:
    raw_counts: Counter[str] = Counter()
    harness_counts: Counter[tuple[str, str]] = Counter()
    openings: dict[tuple[str, str, str], list[int]] = defaultdict(list)
    matched_durations: Counter[tuple[str, str]] = Counter()
    duration_values: defaultdict[tuple[str, str], list[int]] = defaultdict(list)
    matched = 0
    for event in event_stream:
        if not matches(event, filters):
            continue
        matched += 1
        payload = event["payload"]
        raw_counts[payload["type"]] += 1
        item = harness(event)
        if item is None:
            continue
        group = str(item.get("category", "?")), str(item.get("name", "?"))
        harness_counts[group] += 1
        key = duration_key(item)
        if key is None:
            continue
        phase = item.get("phase")
        if phase in OPENING_PHASES:
            openings[key].append(event.get("wall_time_unix_ms", 0))
        elif phase in TERMINAL_PHASES and openings[key]:
            started = openings[key].pop(0)
            elapsed = event.get("wall_time_unix_ms", 0) - started
            matched_durations[group] += 1
            duration_values[group].append(elapsed)
    print(f"matched events: {matched}")
    print("raw type counts:")
    for name, count in sorted(raw_counts.items()):
        print(f"  {name}: {count}")
    print("harness category/name counts:")
    for (category, name), count in sorted(harness_counts.items()):
        print(f"  {category}.{name}: {count}")
    print("matched durations (opening to terminal; not every decision is a span):")
    for group in sorted(matched_durations):
        values = duration_values[group]
        print(f"  {group[0]}.{group[1]}: {matched_durations[group]} matched, total={sum(values)}ms, min={min(values)}ms, max={max(values)}ms")
    return matched


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog="exit status: 0 = matched events, 1 = no match, 2 = malformed or unreadable input",
    )
    parser.add_argument("input", help="trace bundle directory or trace.jsonl")
    parser.add_argument("--payload-type", action="append", default=[], metavar="TYPE", help="raw payload type (repeatable)")
    parser.add_argument("--thread", action="append", default=[], help="thread ID (repeatable)")
    parser.add_argument("--turn", action="append", default=[], help="Codex turn ID (repeatable)")
    parser.add_argument("--step", action="append", default=[], help="harness step ID (repeatable)")
    parser.add_argument("--category", action="append", default=[], help="harness category (repeatable)")
    parser.add_argument("--name", action="append", default=[], help="harness event name (repeatable)")
    parser.add_argument("--phase", action="append", default=[], help="harness phase (repeatable)")
    parser.add_argument("--correlation", action="append", default=[], type=parse_correlation, metavar="KEY=VALUE", help="harness correlation (repeatable)")
    parser.add_argument("--harness-only", action="store_true", help="hide ordinary raw events")
    parser.add_argument("--details", action="store_true", help="include compact, redacted harness details")
    parser.add_argument("--summary", action="store_true", help="aggregate counts and matched durations")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    filters = Filters(
        set(args.payload_type), set(args.thread), set(args.turn), set(args.step),
        set(args.category), set(args.name), set(args.phase), tuple(args.correlation), args.harness_only,
    )
    try:
        path = trace_path(args.input)
        matched = summary(events(path), filters) if args.summary else timeline(events(path), filters, args.details)
    except TraceInputError as error:
        print(f"trace-viewer: error: {error}", file=sys.stderr)
        return 2
    return 0 if matched else 1


if __name__ == "__main__":
    raise SystemExit(main())
