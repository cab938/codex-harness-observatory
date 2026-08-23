#!/usr/bin/env python3
"""Print a compact, privacy-conscious view of a raw Codex rollout trace."""

import argparse
import json
import sys
import threading
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterator, Sequence
from urllib.parse import parse_qs, urlparse


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
SENSITIVE_CORRELATION_KEYS = {
    "argument", "command", "content", "file", "message", "output", "path",
    "payload", "prompt", "result", "text",
}
RAW_SAFE_KEYS = {
    "status", "model", "provider_name", "kind", "event_type", "trace_id",
    "root_thread_id", "agent_path",
}
MANIFEST_SAFE_KEYS = {
    "schema_version", "trace_id", "rollout_id", "root_thread_id",
    "started_at_unix_ms", "raw_event_log", "payloads_dir",
}
WEB_ASSET_DIR = Path(__file__).with_name("trace_viewer_web")

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
APPROVAL_ID_REQUIRED_EVENTS = APPROVAL_REQUIRED_EVENTS - {"approval_requirement"}
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


def trace_root_path(input_path: str) -> Path:
    path = Path(input_path)
    if not path.is_dir():
        raise TraceInputError(f"trace root directory not found: {path}")
    return path


def discover_trace(root: Path) -> Path | None:
    try:
        candidates = sorted(
            child / "trace.jsonl"
            for child in root.iterdir()
            if child.is_dir() and (child / "trace.jsonl").is_file()
        )
    except OSError as error:
        raise TraceInputError(f"cannot inspect trace root: {error}") from error
    return candidates[0] if candidates else None


def parse_event_line(
    line: str,
    *,
    source: Path,
    line_number: int,
    previous_seq: int | None,
    enforce_sequence: bool,
) -> dict[str, Any] | None:
    if not line.strip():
        return None
    try:
        event = json.loads(line)
    except json.JSONDecodeError as error:
        raise TraceInputError(
            f"{source}:{line_number}: malformed JSONL: {error.msg}"
        ) from error
    if not isinstance(event, dict):
        raise TraceInputError(f"{source}:{line_number}: raw event must be a JSON object")
    seq = event.get("seq")
    if not isinstance(seq, int):
        raise TraceInputError(f"{source}:{line_number}: raw event has no integer seq")
    if enforce_sequence and previous_seq is not None and seq <= previous_seq:
        raise TraceInputError(
            f"{source}:{line_number}: seq {seq} is not after prior seq {previous_seq}"
        )
    payload = event.get("payload")
    if not isinstance(payload, dict) or not isinstance(payload.get("type"), str):
        raise TraceInputError(f"{source}:{line_number}: raw event has no typed payload")
    return event


def events(path: Path, *, enforce_sequence: bool = True) -> Iterator[dict[str, Any]]:
    previous_seq: int | None = None
    try:
        stream = path.open(encoding="utf-8")
    except OSError as error:
        raise TraceInputError(f"cannot open {path}: {error}") from error
    with stream:
        for line_number, line in enumerate(stream, 1):
            event = parse_event_line(
                line,
                source=path,
                line_number=line_number,
                previous_seq=previous_seq,
                enforce_sequence=enforce_sequence,
            )
            if event is None:
                continue
            previous_seq = event["seq"]
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
    # Turn admission is decided before Core has constructed a StepContext.
    # The selected turn is still correlated by the outer trace envelope.
    if category == "agent_loop":
        return name != "turn_input_disposition"
    if category == "tool":
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
    if category == "decision" and name == "approval_requirement":
        return ("tool_call_id",)
    if category == "decision" and name in APPROVAL_ID_REQUIRED_EVENTS:
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
            # A reservation happens before the child identity exists. Depending
            # on session setup, Core may know either the root or just the
            # requesting parent at this boundary; integrity_findings checks
            # that at least one is present.
            return ()
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
        if (
            is_v2_event(item)
            and item.get("name") == "agent_residency"
            and item.get("phase") in {"requested", "reserved", "rejected"}
            and not ({"root_thread_id", "parent_thread_id"} & correlations.keys())
        ):
            findings.append(
                TraceIntegrityFinding(
                    seq,
                    "event requires correlation root_thread_id or parent_thread_id",
                )
            )

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
            if (category, name, phase) == ("multi_agent", "agent_message", "enqueued"):
                # InputQueue also emits a standalone mailbox fact for initial
                # child input and completion notification. Model-requested
                # message spans carry tool_call_id and are still paired.
                continue
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


def safe_correlations(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {
        str(key): "<redacted>"
        if str(key).lower() in SENSITIVE_CORRELATION_KEYS
        else safe_detail(child, "correlation_value")
        for key, child in value.items()
    }


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
    for key in sorted(payload):
        if key in RAW_SAFE_KEYS or key.endswith("_id"):
            value = payload[key]
            if isinstance(value, (str, int, float, bool)):
                fields.append(f"{key}={value}")
    for label, value in (("thread", event.get("thread_id")), ("turn", event.get("codex_turn_id"))):
        if value is not None:
            fields.append(f"{label}={value}")
    return " ".join(fields)


def safe_reference_path(value: str) -> str:
    candidate = Path(value)
    if candidate.is_absolute() or ".." in candidate.parts:
        return candidate.name
    return candidate.as_posix()


def payload_references(value: Any, field: str = "payload") -> list[dict[str, Any]]:
    references: list[dict[str, Any]] = []

    def collect(item: Any, parent: str) -> None:
        if isinstance(item, dict):
            path = item.get("path")
            looks_like_reference = isinstance(path, str) and (
                parent.endswith("payload")
                or parent.endswith("payloads")
                or "raw_payload_id" in item
                or "kind" in item
            )
            if looks_like_reference:
                reference: dict[str, Any] = {
                    "field": parent,
                    "path": safe_reference_path(path),
                }
                raw_payload_id = item.get("raw_payload_id")
                if isinstance(raw_payload_id, str):
                    reference["raw_payload_id"] = raw_payload_id[:120]
                kind = item.get("kind")
                if isinstance(kind, (str, int, float, bool, dict)):
                    reference["kind"] = safe_detail(kind, "kind")
                references.append(reference)
                return
            for key, child in item.items():
                collect(child, str(key))
        elif isinstance(item, list):
            for child in item:
                collect(child, parent)

    collect(value, field)
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for reference in references:
        identity = compact_value(reference)
        if identity not in seen:
            seen.add(identity)
            unique.append(reference)
    return unique


def viewer_event(event: dict[str, Any]) -> dict[str, Any]:
    payload = event["payload"]
    item = harness(event)
    payload_metadata: dict[str, Any] = {}
    for key, value in payload.items():
        if (key in RAW_SAFE_KEYS or key.endswith("_id")) and isinstance(
            value, (str, int, float, bool)
        ):
            payload_metadata[key] = safe_detail(value, key)
    safe_event: dict[str, Any] = {
        "schema_version": event.get("schema_version"),
        "seq": event["seq"],
        "wall_time_unix_ms": event.get("wall_time_unix_ms"),
        "rollout_id": event.get("rollout_id"),
        "thread_id": event.get("thread_id"),
        "codex_turn_id": event.get("codex_turn_id"),
        "payload_type": payload["type"],
        "payload_metadata": payload_metadata,
        "payload_references": payload_references(payload),
    }
    if item is not None:
        safe_event["harness"] = {
            "category": item.get("category"),
            "name": item.get("name"),
            "phase": item.get("phase"),
            "step_id": item.get("step_id"),
            "outcome": item.get("outcome"),
            "reason": item.get("reason"),
            "correlations": safe_correlations(item.get("correlations")),
            "details": safe_detail(item.get("details")),
        }
    return safe_event


def manifest_metadata(path: Path) -> dict[str, Any]:
    manifest_path = path.parent / "manifest.json"
    manifest: dict[str, Any] = {}
    if manifest_path.is_file():
        try:
            parsed = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise TraceInputError(f"cannot read bundle manifest: {error}") from error
        if not isinstance(parsed, dict):
            raise TraceInputError("bundle manifest must be a JSON object")
        for key in MANIFEST_SAFE_KEYS:
            value = parsed.get(key)
            if isinstance(value, (str, int, float, bool)):
                manifest[key] = value
        if "schema_version" in manifest:
            manifest["manifest_schema_version"] = manifest["schema_version"]
    try:
        first_event = next(events(path), None)
    except TraceInputError:
        first_event = None
    if first_event is not None:
        if not manifest:
            manifest = {
                "schema_version": first_event.get("schema_version"),
                "rollout_id": first_event.get("rollout_id"),
                "root_thread_id": first_event.get("thread_id"),
                "started_at_unix_ms": first_event.get("wall_time_unix_ms"),
                "raw_event_log": path.name,
                "raw_schema_version": first_event.get("schema_version"),
            }
            payload = first_event["payload"]
            if payload.get("type") == "rollout_started":
                manifest["trace_id"] = payload.get("trace_id")
                manifest["root_thread_id"] = payload.get("root_thread_id")
        else:
            manifest["raw_schema_version"] = first_event.get("schema_version")
    for key in ("raw_event_log", "payloads_dir"):
        if isinstance(manifest.get(key), str):
            manifest[key] = safe_reference_path(manifest[key])
    manifest["source_name"] = path.parent.name if path.name == "trace.jsonl" else path.name
    manifest["stream_mode"] = "append_only_jsonl"
    return manifest


def safe_stream_error(error: Exception, path: Path) -> str:
    return str(error).replace(str(path), path.name)[:240]


def tail_updates(
    path: Path,
    *,
    after_seq: int = 0,
    follow: bool = True,
    poll_interval: float = 0.15,
    stop_event: threading.Event | None = None,
) -> Iterator[dict[str, Any]]:
    position = 0
    buffered = b""
    line_number = 0
    previous_seq: int | None = None
    last_heartbeat = time.monotonic()
    while stop_event is None or not stop_event.is_set():
        try:
            size = path.stat().st_size
            if size < position:
                yield {"kind": "error", "message": "trace.jsonl was truncated while viewing"}
                return
            if size > position:
                with path.open("rb") as stream:
                    stream.seek(position)
                    chunk = stream.read(size - position)
                position += len(chunk)
                buffered += chunk
                while b"\n" in buffered:
                    encoded_line, buffered = buffered.split(b"\n", 1)
                    line_number += 1
                    try:
                        line = encoded_line.decode("utf-8")
                    except UnicodeDecodeError as error:
                        yield {
                            "kind": "error",
                            "message": f"line {line_number}: invalid UTF-8: {error.reason}",
                        }
                        return
                    try:
                        event = parse_event_line(
                            line,
                            source=path,
                            line_number=line_number,
                            previous_seq=previous_seq,
                            enforce_sequence=True,
                        )
                    except TraceInputError as error:
                        yield {"kind": "error", "message": safe_stream_error(error, path)}
                        return
                    if event is None:
                        continue
                    previous_seq = event["seq"]
                    if event["seq"] > after_seq:
                        yield {"kind": "event", "event": viewer_event(event)}
                    last_heartbeat = time.monotonic()
                continue
        except OSError as error:
            yield {
                "kind": "error",
                "message": f"cannot tail trace.jsonl: {error.strerror or 'read failed'}",
            }
            return
        if not follow:
            return
        if time.monotonic() - last_heartbeat >= 10:
            yield {"kind": "heartbeat"}
            last_heartbeat = time.monotonic()
        if stop_event is not None:
            stop_event.wait(poll_interval)
        else:
            time.sleep(poll_interval)


class TraceViewerHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        address: tuple[str, int],
        trace: Path | None,
        trace_root: Path | None = None,
    ):
        self.trace_path = trace
        self.trace_root = trace_root
        self.trace_lock = threading.Lock()
        self.stop_event = threading.Event()
        super().__init__(address, TraceViewerRequestHandler)

    def resolve_trace_path(self) -> Path | None:
        with self.trace_lock:
            if self.trace_path is None and self.trace_root is not None:
                self.trace_path = discover_trace(self.trace_root)
            return self.trace_path

    def server_close(self) -> None:
        self.stop_event.set()
        super().server_close()


class TraceViewerRequestHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    @property
    def viewer_server(self) -> TraceViewerHTTPServer:
        return self.server  # type: ignore[return-value]

    def log_message(self, format_string: str, *args: Any) -> None:
        return

    def send_common_headers(self, content_type: str, length: int | None = None) -> None:
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "connect-src 'self'; img-src 'self' data:; object-src 'none'; "
            "base-uri 'none'; frame-ancestors 'none'",
        )
        if length is not None:
            self.send_header("Content-Length", str(length))

    def send_bytes(self, body: bytes, content_type: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        self.send_response(status)
        self.send_common_headers(content_type, len(body))
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, value: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(value, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
        self.send_bytes(body, "application/json; charset=utf-8", status)

    def serve_asset(self, name: str, content_type: str) -> None:
        path = WEB_ASSET_DIR / name
        try:
            body = path.read_bytes()
        except OSError as error:
            self.send_json(
                {"error": f"viewer asset unavailable: {error.strerror or 'read failed'}"},
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )
            return
        self.send_bytes(body, content_type)

    def stream_events(self, query: dict[str, list[str]]) -> None:
        requested_after = query.get("after", [self.headers.get("Last-Event-ID", "0")])[0]
        try:
            after_seq = int(requested_after or "0")
        except ValueError:
            self.send_json({"error": "after must be an integer sequence"}, HTTPStatus.BAD_REQUEST)
            return
        self.send_response(HTTPStatus.OK)
        self.send_common_headers("text/event-stream; charset=utf-8")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        try:
            trace_path = self.viewer_server.resolve_trace_path()
            waiting_for_bundle = trace_path is None
            last_heartbeat = time.monotonic()
            while trace_path is None and not self.viewer_server.stop_event.is_set():
                if time.monotonic() - last_heartbeat >= 10:
                    self.wfile.write(b": waiting for first trace bundle\n\n")
                    self.wfile.flush()
                    last_heartbeat = time.monotonic()
                self.viewer_server.stop_event.wait(0.15)
                trace_path = self.viewer_server.resolve_trace_path()
            if trace_path is None:
                return
            if waiting_for_bundle:
                update = {"kind": "source", "metadata": manifest_metadata(trace_path)}
                data = json.dumps(update, separators=(",", ":"), ensure_ascii=True)
                self.wfile.write(f"event: trace-source\ndata: {data}\n\n".encode("utf-8"))
                self.wfile.flush()
            for update in tail_updates(
                trace_path,
                after_seq=after_seq,
                stop_event=self.viewer_server.stop_event,
            ):
                kind = update["kind"]
                if kind == "heartbeat":
                    packet = b": heartbeat\n\n"
                else:
                    data = json.dumps(update, separators=(",", ":"), ensure_ascii=True)
                    if kind == "event":
                        seq = update["event"]["seq"]
                        packet = f"id: {seq}\nevent: trace\ndata: {data}\n\n".encode("utf-8")
                    else:
                        packet = f"event: trace-error\ndata: {data}\n\n".encode("utf-8")
                self.wfile.write(packet)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            return

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self.serve_asset("index.html", "text/html; charset=utf-8")
        elif parsed.path == "/assets/app.js":
            self.serve_asset("app.js", "text/javascript; charset=utf-8")
        elif parsed.path == "/assets/styles.css":
            self.serve_asset("styles.css", "text/css; charset=utf-8")
        elif parsed.path == "/favicon.ico":
            self.send_bytes(b"", "image/x-icon", HTTPStatus.NO_CONTENT)
        elif parsed.path == "/api/header":
            try:
                trace_path = self.viewer_server.resolve_trace_path()
                if trace_path is None:
                    trace_root = self.viewer_server.trace_root
                    self.send_json(
                        {
                            "source_name": trace_root.name if trace_root else "pending",
                            "stream_mode": "waiting_for_trace_bundle",
                            "raw_event_log": "trace.jsonl",
                        }
                    )
                else:
                    self.send_json(manifest_metadata(trace_path))
            except TraceInputError as error:
                source = self.viewer_server.trace_root or Path("trace.jsonl")
                self.send_json(
                    {"error": safe_stream_error(error, source)},
                    HTTPStatus.UNPROCESSABLE_ENTITY,
                )
        elif parsed.path == "/api/stream":
            self.stream_events(parse_qs(parsed.query))
        else:
            self.send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)


def make_viewer_server(
    path: Path,
    host: str,
    port: int,
    *,
    wait_for_bundle: bool = False,
) -> TraceViewerHTTPServer:
    try:
        return TraceViewerHTTPServer(
            (host, port),
            None if wait_for_bundle else path,
            path if wait_for_bundle else None,
        )
    except OSError as error:
        raise TraceInputError(f"cannot bind viewer at {host}:{port}: {error}") from error


def serve_viewer(path: Path, host: str, port: int, *, wait_for_bundle: bool = False) -> int:
    server = make_viewer_server(path, host, port, wait_for_bundle=wait_for_bundle)
    bound_host, bound_port = server.server_address[:2]
    display_host = "127.0.0.1" if bound_host in {"0.0.0.0", "::"} else bound_host
    print(f"Codex Harness Observatory: http://{display_host}:{bound_port}", flush=True)
    if bound_host not in {"127.0.0.1", "localhost", "::1"}:
        print("trace-viewer: warning: viewer is not bound exclusively to loopback", file=sys.stderr)
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


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
    parser.add_argument("input", help="trace bundle directory, trace.jsonl, or trace root with --wait-for-bundle")
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
    parser.add_argument(
        "--serve",
        action="store_true",
        help="serve the unified live viewer and tail appended events",
    )
    parser.add_argument(
        "--wait-for-bundle",
        action="store_true",
        help="bind immediately and wait for the first trace bundle under INPUT (requires --serve)",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="viewer bind host (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="viewer port, or 0 to choose an available port (default: 8765)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not 0 <= args.port <= 65535:
        print("trace-viewer: error: port must be between 0 and 65535", file=sys.stderr)
        return 2
    if args.wait_for_bundle and not args.serve:
        print("trace-viewer: error: --wait-for-bundle requires --serve", file=sys.stderr)
        return 2
    filters = Filters(
        set(args.payload_type), set(args.thread), set(args.turn), set(args.step),
        set(args.category), set(args.name), set(args.phase), tuple(args.correlation), args.harness_only,
    )
    try:
        if args.wait_for_bundle:
            root = trace_root_path(args.input)
            return serve_viewer(
                root,
                args.host,
                args.port,
                wait_for_bundle=True,
            )
        path = trace_path(args.input)
        if args.serve:
            return serve_viewer(path, args.host, args.port)
        if args.check:
            return check(events(path, enforce_sequence=False))
        matched = summary(events(path), filters) if args.summary else timeline(events(path), filters, args.details)
    except TraceInputError as error:
        print(f"trace-viewer: error: {error}", file=sys.stderr)
        return 2
    return 0 if matched else 1


if __name__ == "__main__":
    raise SystemExit(main())
