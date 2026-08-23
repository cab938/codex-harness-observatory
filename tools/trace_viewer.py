#!/usr/bin/env python3
"""Print a compact, privacy-conscious view of a raw Codex rollout trace."""

import argparse
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Sequence


OPENING_PHASES = {"requested", "started", "dispatched", "enqueued"}
TERMINAL_PHASES = {
    "completed", "resolved", "failed", "cancelled", "dequeued", "delivered", "rejected", "raced",
}
PAIR_CORRELATION_KEYS = (
    "message_id",
    "guardian_review_id",
    "approval_id",
    "tool_call_id",
    "target_thread_id",
    "child_thread_id",
    "parent_thread_id",
    "task_thread_id",
    "hook_run_id",
)
SENSITIVE_DETAIL_KEYS = {
    "argument", "arguments", "command", "content", "file", "files", "message",
    "messages", "output", "path", "paths", "payload", "payloads", "prompt",
    "result", "results", "source", "text",
}

# The trace envelope intentionally accepts new string-valued event names.  The
# checker therefore validates only pairs Core currently promises to emit, rather
# than treating every decision-shaped event as a span.  Each entry is
# ``(category, name): (opening phases, terminal phases, identity correlation)``.
# ``step_id`` is a special identity supplied by the harness envelope.
KNOWN_LIFECYCLES = {
    ("agent_loop", "agent_step"): ({"started"}, {"completed", "failed", "cancelled"}, "step_id"),
    ("agent_loop", "sampling_request"): ({"requested"}, {"completed", "failed", "cancelled"}, "step_id"),
    ("context", "step_context_capture"): ({"started"}, {"completed", "failed", "cancelled"}, "step_id"),
    ("context", "compaction_application"): ({"started"}, {"completed", "failed", "cancelled"}, "step_id"),
    ("decision", "guardian_review"): ({"requested"}, {"completed", "failed", "cancelled"}, "guardian_review_id"),
    ("tool", "tool_dispatch"): ({"dispatched"}, {"completed", "failed", "cancelled"}, "tool_call_id"),
    ("supervision", "hook_invocation"): ({"requested"}, {"completed", "failed", "cancelled"}, "hook_run_id"),
    ("multi_agent", "agent_spawn"): ({"requested"}, {"completed", "failed", "cancelled"}, "tool_call_id"),
    ("multi_agent", "agent_wait"): ({"requested"}, {"resolved", "failed", "cancelled"}, "tool_call_id"),
    ("multi_agent", "agent_interrupt"): ({"requested"}, {"resolved", "failed", "cancelled"}, "tool_call_id"),
    ("multi_agent", "agent_close"): ({"requested"}, {"resolved", "failed", "cancelled"}, "tool_call_id"),
    ("multi_agent", "agent_message"): ({"requested"}, {"enqueued", "rejected", "failed", "cancelled"}, "tool_call_id"),
    ("multi_agent", "agent_eviction"): ({"requested"}, {"completed", "failed", "skipped"}, "task_thread_id"),
    ("multi_agent", "agent_reload"): ({"requested"}, {"completed", "raced", "failed"}, "task_thread_id"),
}

STEP_REQUIRED_EVENTS = {
    ("context", "step_context_capture"),
    ("context", "prompt_assembly"),
    ("context", "compaction_application"),
    ("context", "compaction_decision"),
    ("supervision", "stop_supervision"),
}

TOOL_CALL_REQUIRED_EVENTS = {
    "tool_catalog",
    "tool_handler_resolution",
    "tool_parallelism",
    "tool_dispatch",
    "patch_parse",
    "patch_safety",
    "patch_commit",
}
APPROVAL_REQUIRED_EVENTS = {
    "approval_requirement",
    "approval_cache",
    "approval_reviewer",
    "approval_resolution",
}
DECISION_STEP_REQUIRED_EVENTS = APPROVAL_REQUIRED_EVENTS | {
    "sandbox_selection",
    "sandbox_attempt",
    "sandbox_escalation",
}
MULTI_AGENT_TOOL_EVENTS = {
    "agent_spawn",
    "agent_spawn_admission",
    "agent_wait",
    "agent_interrupt",
    "agent_close",
}


class TraceInputError(Exception):
    """A trace file cannot be safely read as a raw event stream."""


@dataclass(frozen=True)
class TraceIntegrityFinding:
    seq: int | None
    invariant: str

    def render(self) -> str:
        location = f"seq={self.seq}" if self.seq is not None else "trace"
        return f"{location}: {self.invariant}"


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


def events(path: Path, *, enforce_sequence: bool = True) -> Iterator[dict[str, Any]]:
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
            if enforce_sequence and previous_seq is not None and seq <= previous_seq:
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


def nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value)


def correlations_for(item: dict[str, Any]) -> dict[str, str]:
    correlations = item.get("correlations")
    if not isinstance(correlations, dict):
        return {}
    return {
        key: value
        for key, value in correlations.items()
        if isinstance(key, str) and isinstance(value, str) and value
    }


def is_v2_event(item: dict[str, Any]) -> bool:
    details = item.get("details")
    return isinstance(details, dict) and details.get("implementation") == "v2"


def lifecycle_identity(item: dict[str, Any], identity_key: str) -> str | None:
    if identity_key == "step_id":
        value = item.get("step_id")
        return value if nonempty_string(value) else None
    return correlations_for(item).get(identity_key)


def required_step(item: dict[str, Any]) -> bool:
    category = item.get("category")
    name = item.get("name")
    phase = item.get("phase")
    if category in {"agent_loop", "tool"}:
        return True
    if category == "decision" and name in DECISION_STEP_REQUIRED_EVENTS:
        return True
    if (category, name) in STEP_REQUIRED_EVENTS:
        return True
    if category == "multi_agent" and name in MULTI_AGENT_TOOL_EVENTS:
        return True
    return category == "multi_agent" and name == "agent_message" and phase in {"requested", "rejected"}


def required_correlations(item: dict[str, Any]) -> tuple[str, ...]:
    category = item.get("category")
    name = item.get("name")
    phase = item.get("phase")
    if category == "tool" and name in TOOL_CALL_REQUIRED_EVENTS:
        return ("tool_call_id",)
    if category == "decision" and name in APPROVAL_REQUIRED_EVENTS:
        return ("tool_call_id", "approval_id")
    if category == "decision" and name == "guardian_review":
        return ("guardian_review_id",)
    if category == "multi_agent" and name in MULTI_AGENT_TOOL_EVENTS:
        base = ("parent_thread_id", "tool_call_id")
        if name == "agent_spawn" and phase == "completed":
            return base + ("child_thread_id",)
        if name == "agent_spawn_admission" and phase == "resolved":
            return base + ("child_thread_id",)
        if name in {"agent_interrupt", "agent_close"}:
            return base + ("target_thread_id",)
        return base
    if category == "multi_agent" and name == "agent_message" and phase in {"requested", "rejected"}:
        return ("parent_thread_id", "target_thread_id", "tool_call_id")
    if category == "multi_agent" and name == "agent_message" and phase == "enqueued":
        correlations = correlations_for(item)
        if "tool_call_id" in correlations:
            return ("parent_thread_id", "target_thread_id", "tool_call_id", "message_id")
    if category == "multi_agent" and name == "agent_result_delivery":
        if phase == "enqueued":
            return ("parent_thread_id", "child_thread_id", "message_id")
        if phase == "delivered":
            return ("parent_thread_id", "child_thread_id")
    if category == "multi_agent" and is_v2_event(item):
        if name == "agent_residency" and phase in {"requested", "reserved", "rejected"}:
            return ("root_thread_id",)
        if name in {"agent_identity", "agent_eviction", "agent_reload"} or (
            name == "agent_residency" and phase in {"touched", "released", "selected_for_eviction"}
        ):
            return ("root_thread_id", "task_thread_id")
        return ("root_thread_id",)
    return ()


def integrity_findings(event_stream: Iterator[dict[str, Any]]) -> list[TraceIntegrityFinding]:
    findings: list[TraceIntegrityFinding] = []
    openings: dict[tuple[str, str, str], list[int]] = defaultdict(list)
    previous_seq: int | None = None
    for event in event_stream:
        seq = event["seq"]
        if previous_seq is not None and seq <= previous_seq:
            findings.append(
                TraceIntegrityFinding(seq, f"seq must be strictly after prior seq={previous_seq}")
            )
        previous_seq = seq

        payload = event["payload"]
        if payload.get("type") != "harness_event_observed":
            continue
        item = payload.get("event")
        if not isinstance(item, dict):
            findings.append(TraceIntegrityFinding(seq, "harness event must be an object"))
            continue
        if not all(nonempty_string(item.get(field)) for field in ("category", "name", "phase")):
            findings.append(
                TraceIntegrityFinding(seq, "harness event requires non-empty category, name, and phase")
            )
            continue
        if "correlations" in item and not isinstance(item["correlations"], dict):
            findings.append(TraceIntegrityFinding(seq, "harness correlations must be an object"))
            continue
        if required_step(item) and not nonempty_string(item.get("step_id")):
            findings.append(TraceIntegrityFinding(seq, "event requires a non-empty step_id"))
        correlations = correlations_for(item)
        for key in required_correlations(item):
            if key not in correlations:
                findings.append(TraceIntegrityFinding(seq, f"event requires correlation {key}"))

        category = item["category"]
        name = item["name"]
        lifecycle = KNOWN_LIFECYCLES.get((category, name))
        if lifecycle is None:
            continue
        opening_phases, terminal_phases, identity_key = lifecycle
        identity = lifecycle_identity(item, identity_key)
        phase = item["phase"]
        if phase not in opening_phases | terminal_phases:
            continue
        if identity is None:
            findings.append(
                TraceIntegrityFinding(
                    seq,
                    f"{category}.{name} {phase} requires lifecycle identity {identity_key}",
                )
            )
            continue
        key = (category, name, identity)
        if phase in opening_phases:
            if (category, name) == ("supervision", "hook_invocation") and openings[key]:
                continue
            openings[key].append(seq)
        elif openings[key]:
            openings[key].pop(0)
        elif (category, name, phase) == ("multi_agent", "agent_eviction", "skipped"):
            # Residency may decide not to evict an LRU candidate before an
            # eviction span opens (for example, it is no longer resident).
            # The same phase closes a requested eviction that lost a later
            # remove-thread race, so it is intentionally conditional.
            continue
        else:
            findings.append(
                TraceIntegrityFinding(
                    seq,
                    f"orphan terminal {category}.{name} {phase} for {identity_key}={identity}",
                )
            )
    for (category, name, identity), seqs in sorted(openings.items()):
        for seq in seqs:
            findings.append(
                TraceIntegrityFinding(seq, f"unfinished opening {category}.{name} for identity {identity}")
            )
    return findings


def check(event_stream: Iterator[dict[str, Any]]) -> int:
    findings = integrity_findings(event_stream)
    if not findings:
        print("trace integrity: clean")
        return 0
    print(f"trace integrity: {len(findings)} finding(s)")
    for finding in findings:
        print(f"  {finding.render()}")
    return 1


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
        epilog=(
            "normal exit status: 0 = matched events, 1 = no match, 2 = malformed or unreadable input; "
            "--check exit status: 0 = clean, 1 = integrity findings, 2 = malformed or unreadable input"
        ),
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
    parser.add_argument(
        "--check",
        action="store_true",
        help="validate known lifecycle, step, correlation, and sequence invariants",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    filters = Filters(
        set(args.payload_type), set(args.thread), set(args.turn), set(args.step),
        set(args.category), set(args.name), set(args.phase), tuple(args.correlation), args.harness_only,
    )
    try:
        path = trace_path(args.input)
        if args.check:
            return check(events(path, enforce_sequence=False))
        matched = summary(events(path), filters) if args.summary else timeline(events(path), filters, args.details)
    except TraceInputError as error:
        print(f"trace-viewer: error: {error}", file=sys.stderr)
        return 2
    return 0 if matched else 1


if __name__ == "__main__":
    raise SystemExit(main())
