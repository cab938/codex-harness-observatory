#!/usr/bin/env python3
"""Inspect a raw Codex rollout trace as a timeline or local teaching viewer."""

import argparse
import base64
import json
import sys
import threading
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterator, Sequence
from urllib.parse import parse_qs, urlparse


OPENING_PHASES = {"requested", "started", "dispatched", "enqueued"}
TERMINAL_PHASES = {
    "completed",
    "resolved",
    "failed",
    "cancelled",
    "dequeued",
    "delivered",
    "rejected",
    "raced",
    "accepted",
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
    "argument",
    "arguments",
    "command",
    "content",
    "file",
    "files",
    "message",
    "messages",
    "output",
    "path",
    "paths",
    "payload",
    "payloads",
    "prompt",
    "result",
    "results",
    "source",
    "text",
}
SENSITIVE_CORRELATION_KEYS = {
    "argument",
    "command",
    "content",
    "file",
    "message",
    "output",
    "path",
    "payload",
    "prompt",
    "result",
    "text",
}
RAW_SAFE_KEYS = {
    "status",
    "model",
    "provider_name",
    "kind",
    "event_type",
    "original_type",
    "trace_id",
    "root_thread_id",
    "agent_path",
    "direction",
    "frame_kind",
    "method",
    "server_name",
    "transport",
    "connection_id",
    "connection_instance_id",
    "exchange_id",
    "observation_stage",
    "stage",
    "reason",
    "protocol",
    "request_id",
    "session_id",
    "source_thread_id",
    "new_thread_id",
    "item_id",
    "forked_from_id",
}
APP_SERVER_METADATA_KEYS = (
    "connection_id",
    "connection_instance_id",
    "exchange_id",
    "observation_stage",
    "stage",
    "reason",
    "protocol",
    "request_id",
    "method",
    "direction",
    "frame_kind",
    "source_thread_id",
    "new_thread_id",
    "item_id",
    "forked_from_id",
    "session_id",
)
MANIFEST_SAFE_KEYS = {
    "schema_version",
    "trace_id",
    "rollout_id",
    "root_thread_id",
    "started_at_unix_ms",
    "raw_event_log",
    "payloads_dir",
    "shared_run",
}
TASK_ROOT_ID_FIELDS = (
    "task_root_thread_id",
    "taskRootThreadId",
    "root_task_thread_id",
    "rootTaskThreadId",
)
TERMINAL_TASK_STATUSES = {"completed", "failed", "cancelled", "aborted"}
WEB_ASSET_DIR = Path(__file__).with_name("web")
TRACE_FORMAT = "codex-harness-observatory"
MAX_RAW_SCHEMA = 6
MAX_MANIFEST_SCHEMA = 4

# The trace envelope intentionally accepts new string-valued event names.  The
# checker therefore validates only pairs Core currently promises to emit, rather
# than treating every decision-shaped event as a span.  Each entry is
# ``(category, name): (opening phases, terminal phases, identity correlation)``.
# ``step_id`` is a special identity supplied by the harness envelope.
KNOWN_LIFECYCLES = {
    ("agent_loop", "agent_step"): (
        {"started"},
        {"completed", "failed", "cancelled"},
        "step_id",
    ),
    ("agent_loop", "sampling_request"): (
        {"requested"},
        {"completed", "failed", "cancelled"},
        "step_id",
    ),
    ("context", "step_context_capture"): (
        {"started"},
        {"completed", "failed", "cancelled"},
        "step_id",
    ),
    ("context", "compaction_application"): (
        {"started"},
        {"completed", "failed", "cancelled"},
        "step_id",
    ),
    ("decision", "guardian_review"): (
        {"requested"},
        {"completed", "failed", "cancelled"},
        "guardian_review_id",
    ),
    ("tool", "tool_dispatch"): (
        {"dispatched"},
        {"completed", "failed", "cancelled"},
        "tool_call_id",
    ),
    ("supervision", "hook_invocation"): (
        {"requested"},
        {"completed", "failed", "cancelled"},
        "hook_run_id",
    ),
    ("multi_agent", "agent_spawn"): (
        {"requested"},
        {"completed", "failed", "cancelled"},
        "tool_call_id",
    ),
    ("multi_agent", "agent_wait"): (
        {"requested"},
        {"resolved", "failed", "cancelled"},
        "tool_call_id",
    ),
    ("multi_agent", "agent_interrupt"): (
        {"requested"},
        {"resolved", "failed", "cancelled"},
        "tool_call_id",
    ),
    ("multi_agent", "agent_close"): (
        {"requested"},
        {"resolved", "failed", "cancelled"},
        "tool_call_id",
    ),
    ("multi_agent", "agent_message"): (
        {"requested"},
        {"accepted", "enqueued", "rejected", "failed", "cancelled"},
        "tool_call_id",
    ),
    ("multi_agent", "agent_eviction"): (
        {"requested"},
        {"completed", "failed", "skipped"},
        "task_thread_id",
    ),
    ("multi_agent", "agent_reload"): (
        {"requested"},
        {"completed", "raced", "failed"},
        "task_thread_id",
    ),
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
    task_root: set[str] = field(default_factory=set)


@dataclass
class TaskThread:
    """One thread discovered in a shared-run task tree."""

    thread_id: str
    status: str = "observed"
    parent_thread_id: str | None = None
    agent_path: str | None = None
    residency: str | None = None

    def metadata(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "threadId": self.thread_id,
            "status": self.status,
            "lifecycle": "ended"
            if self.status in TERMINAL_TASK_STATUSES
            else self.status,
        }
        if self.parent_thread_id is not None:
            result["parentThreadId"] = self.parent_thread_id
        if self.agent_path is not None:
            result["agentPath"] = self.agent_path
        if self.residency is not None:
            result["residency"] = self.residency
        return result


@dataclass
class TaskState:
    """Incremental, presentation-only state derived from raw trace order."""

    root_thread_id: str
    status: str = "observed"
    threads: dict[str, TaskThread] = field(default_factory=dict)

    def metadata(self) -> dict[str, Any]:
        return {
            "rootThreadId": self.root_thread_id,
            "status": self.status,
            "lifecycle": "ended"
            if self.status in TERMINAL_TASK_STATUSES
            else self.status,
            "threads": [thread.metadata() for thread in self.threads.values()],
        }


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
        raise TraceInputError(
            f"expected a bundle directory or a .jsonl file: {input_path}"
        )
    if not path.is_file():
        raise TraceInputError(f"trace file not found: {path}")
    return path


def trace_root_path(input_path: str) -> Path:
    path = Path(input_path)
    if not path.is_dir():
        raise TraceInputError(f"trace root directory not found: {path}")
    return path


def trace_discovery_key(path: Path) -> tuple[int, int, str]:
    """Prefer the primary Codex task over Guardian or other subagent bundles."""
    started_at = sys.maxsize
    manifest_path = path.parent / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest_started_at = manifest.get("started_at_unix_ms")
        if isinstance(manifest_started_at, int):
            started_at = manifest_started_at
    except (OSError, json.JSONDecodeError, AttributeError):
        pass

    session_source: Any = None
    try:
        for event in events(path):
            payload = event["payload"]
            if payload.get("type") != "thread_started":
                continue
            metadata_reference = payload.get("metadata_payload")
            metadata_path_value = (
                metadata_reference.get("path")
                if isinstance(metadata_reference, dict)
                else None
            )
            if not isinstance(metadata_path_value, str):
                break
            metadata_path = Path(metadata_path_value)
            if metadata_path.is_absolute() or ".." in metadata_path.parts:
                break
            metadata = json.loads(
                (path.parent / metadata_path).read_text(encoding="utf-8")
            )
            if isinstance(metadata, dict):
                session_source = metadata.get("session_source")
            break
    except (OSError, json.JSONDecodeError, TraceInputError):
        pass

    if isinstance(session_source, dict) and "subagent" in session_source:
        session_rank = 2
    elif session_source is None:
        session_rank = 1
    else:
        session_rank = 0
    return session_rank, started_at, path.parent.name


def discover_trace(root: Path) -> Path | None:
    direct_trace = root / "trace.jsonl"
    if direct_trace.is_file():
        return direct_trace
    try:
        candidates = [
            child / "trace.jsonl"
            for child in root.iterdir()
            if child.is_dir() and (child / "trace.jsonl").is_file()
        ]
    except OSError as error:
        raise TraceInputError(f"cannot inspect trace root: {error}") from error
    return min(candidates, key=trace_discovery_key) if candidates else None


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
        raise TraceInputError(
            f"{source}:{line_number}: raw event must be a JSON object"
        )
    version = event.get("schema_version")
    if version is not None and (
        type(version) is not int or not 1 <= version <= MAX_RAW_SCHEMA
    ):
        raise TraceInputError(
            f"{source}:{line_number}: unsupported raw trace schema: {version}"
        )
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


def expand_oversized_event(event: dict[str, Any], trace_path: Path) -> dict[str, Any]:
    """Expand an externalized payload, retaining the original raw wrapper."""
    wrapper = event.get("payload")
    if not isinstance(wrapper, dict) or wrapper.get("type") != "oversized_event":
        return event
    reference = wrapper.get("event_payload")
    original_type = wrapper.get("original_type")
    if (
        not isinstance(reference, dict)
        or not isinstance(reference.get("path"), str)
        or not nonempty_string(original_type)
    ):
        raise TraceInputError(
            f"seq={event.get('seq')}: oversized event has invalid metadata reference"
        )
    artifact = artifact_payload(trace_path, reference["path"])
    payload = artifact["content"]
    if (
        not isinstance(payload, dict)
        or payload.get("type") != original_type
        or original_type == "oversized_event"
    ):
        raise TraceInputError(
            f"seq={event.get('seq')}: oversized event payload does not match original type"
        )
    return {**event, "payload": payload, "_raw_wrapper": event}


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
            yield expand_oversized_event(event, path)


def harness(event: dict[str, Any]) -> dict[str, Any] | None:
    payload = event["payload"]
    contained = payload.get("event")
    return (
        contained
        if payload.get("type") == "harness_event_observed"
        and isinstance(contained, dict)
        else None
    )


def teaching_category(event: dict[str, Any], item: dict[str, Any] | None = None) -> str:
    payload_type = event["payload"]["type"]
    if payload_type == "app_server_frame_observed":
        return "app_server"
    if payload_type == "mcp_frame_observed":
        return "mcp"
    if item is not None and isinstance(item.get("category"), str):
        return item["category"]
    return "raw"


def filter_correlations(
    payload: dict[str, Any], item: dict[str, Any] | None
) -> dict[str, Any]:
    correlations = item.get("correlations") if item is not None else None
    matched = dict(correlations) if isinstance(correlations, dict) else {}
    for key, value in app_server_metadata(payload).items():
        matched[key] = str(value)
    for key, value in payload.items():
        if key.endswith("_id") and isinstance(value, (str, int)):
            matched[key] = str(value)
    return matched


def app_server_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    """Project stable App Server frame metadata without including its payload."""
    if payload.get("type") not in {"app_server_frame_observed", "mcp_frame_observed"}:
        return {}
    projected: dict[str, Any] = {}
    containers = [payload]
    for key in ("metadata", "frame_metadata"):
        nested = payload.get(key)
        if isinstance(nested, dict):
            containers.append(nested)
    for container in containers:
        for key in APP_SERVER_METADATA_KEYS:
            value = container.get(key)
            if isinstance(value, (str, int, float, bool)) and value != "":
                projected[key] = safe_detail(value, key)
    return projected


def wire_pairing(
    payload: dict[str, Any], schema_version: int | None
) -> dict[str, Any] | None:
    """Describe an exact exchange or a typed legacy identity without guessing."""
    kind = payload.get("type")
    protocol = {
        "app_server_frame_observed": "app_server",
        "mcp_frame_observed": "mcp",
    }.get(kind)
    direction = payload.get("direction")
    frame_kind = payload.get("frame_kind")
    if (
        not protocol
        or direction not in {"client_to_server", "server_to_client"}
        or not isinstance(frame_kind, str)
    ):
        return None
    role = (
        "request"
        if frame_kind == "request"
        else "response"
        if frame_kind in {"response", "error"}
        else "other"
    )
    result: dict[str, Any] = {
        "protocol": protocol,
        "direction": direction,
        "frame_kind": frame_kind,
        "role": role,
    }
    request_id = payload.get("request_id")
    if type(request_id) in (str, int, float) and request_id != "":
        result["request_id"] = request_id
    if (schema_version or 0) >= 6:
        instance = payload.get("connection_instance_id")
        exchange = payload.get("exchange_id")
        if nonempty_string(instance) and nonempty_string(exchange):
            result.update(
                key=compact_value([protocol, instance, exchange]), basis="exchange"
            )
        else:
            result["basis"] = "unknown"
    else:
        connection = payload.get("connection_id")
        if nonempty_string(connection) and "request_id" in result and role != "other":
            request_direction = (
                direction
                if role == "request"
                else {
                    "client_to_server": "server_to_client",
                    "server_to_client": "client_to_server",
                }[direction]
            )
            id_type = "string" if isinstance(request_id, str) else "number"
            result.update(
                key=compact_value(
                    [protocol, connection, request_direction, id_type, request_id]
                ),
                basis="legacy_id",
            )
        else:
            result["basis"] = "unknown"
    return result


def app_server_pairing(metadata: dict[str, Any]) -> dict[str, Any] | None:
    """Compatibility helper for callers inspecting legacy App Server metadata."""
    return wire_pairing({"type": "app_server_frame_observed", **metadata}, 0)


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


def task_root_identity(event: dict[str, Any]) -> tuple[bool, str | None]:
    """Return whether an event declares a task root, preserving explicit null."""
    payload = event.get("payload")
    item = harness(event)
    correlations = item.get("correlations") if item is not None else None
    for container in (event, payload, item, correlations):
        if not isinstance(container, dict):
            continue
        for key in TASK_ROOT_ID_FIELDS:
            if key in container:
                value = container[key]
                return True, value if nonempty_string(value) else None
    return False, None


class TaskLedger:
    """Derive task lanes from one ordered raw ledger without rewriting events."""

    def __init__(self) -> None:
        self.tasks: dict[str, TaskState] = {}
        self.thread_roots: dict[str, str] = {}
        self.legacy_root_thread_id: str | None = None
        self.max_active_task_count = 0
        self.max_active_turn_count = 0
        self.active_turns: dict[tuple[str, str], str | None] = {}
        self.open_threads: set[str] = set()
        self.run_ended = False
        self.run_status: str | None = None

    def _ensure_task(self, root_thread_id: str) -> TaskState:
        task = self.tasks.get(root_thread_id)
        if task is None:
            task = TaskState(root_thread_id)
            self.tasks[root_thread_id] = task
        self._ensure_thread(task, root_thread_id)
        self.thread_roots.setdefault(root_thread_id, root_thread_id)
        return task

    def _ensure_thread(self, task: TaskState, thread_id: str) -> TaskThread:
        thread = task.threads.get(thread_id)
        if thread is None:
            thread = TaskThread(thread_id)
            task.threads[thread_id] = thread
        self.thread_roots[thread_id] = task.root_thread_id
        return thread

    @staticmethod
    def _string_from(mapping: Any, *keys: str) -> str | None:
        if not isinstance(mapping, dict):
            return None
        for key in keys:
            value = mapping.get(key)
            if nonempty_string(value):
                return value
        return None

    def _event_thread_ids(self, event: dict[str, Any]) -> list[str]:
        payload = event["payload"]
        item = harness(event)
        correlations = item.get("correlations") if item is not None else None
        values: list[str] = []
        for mapping, keys in (
            (event, ("thread_id",)),
            (
                payload,
                (
                    "thread_id",
                    "parent_thread_id",
                    "child_thread_id",
                    "task_thread_id",
                    "target_thread_id",
                ),
            ),
            (
                correlations,
                (
                    "parent_thread_id",
                    "child_thread_id",
                    "task_thread_id",
                    "target_thread_id",
                ),
            ),
        ):
            if not isinstance(mapping, dict):
                continue
            for key in keys:
                value = mapping.get(key)
                if nonempty_string(value) and value not in values:
                    values.append(value)
        return values

    def _legacy_root_for(self, event: dict[str, Any]) -> str | None:
        thread_ids = self._event_thread_ids(event)
        for thread_id in thread_ids:
            root_thread_id = self.thread_roots.get(thread_id)
            if root_thread_id is not None:
                return root_thread_id

        payload = event["payload"]
        item = harness(event)
        correlations = item.get("correlations") if item is not None else None
        root_thread_id = self._string_from(
            correlations, "root_thread_id", "rootThreadId"
        )
        if root_thread_id is None and payload.get("type") == "rollout_started":
            root_thread_id = self._string_from(
                payload, "root_thread_id", "rootThreadId"
            )
        if root_thread_id is not None:
            if self.legacy_root_thread_id is None:
                self.legacy_root_thread_id = root_thread_id
            return root_thread_id

        if self.legacy_root_thread_id is not None:
            return self.legacy_root_thread_id
        if thread_ids:
            self.legacy_root_thread_id = thread_ids[0]
            return self.legacy_root_thread_id
        return None

    def _relationship(self, event: dict[str, Any]) -> tuple[str | None, str | None]:
        payload = event["payload"]
        item = harness(event)
        correlations = item.get("correlations") if item is not None else None
        parent_thread_id = self._string_from(
            payload, "parent_thread_id"
        ) or self._string_from(
            correlations,
            "parent_thread_id",
        )
        child_thread_id = self._string_from(
            payload, "child_thread_id"
        ) or self._string_from(
            correlations,
            "child_thread_id",
        )
        return parent_thread_id, child_thread_id

    def _agent_path(self, event: dict[str, Any]) -> str | None:
        payload = event["payload"]
        item = harness(event)
        correlations = item.get("correlations") if item is not None else None
        return self._string_from(payload, "agent_path") or self._string_from(
            correlations,
            "agent_path",
        )

    def _primary_thread_id(self, event: dict[str, Any]) -> str | None:
        payload = event["payload"]
        return self._string_from(event, "thread_id") or self._string_from(
            payload, "thread_id"
        )

    def _status_update(self, event: dict[str, Any]) -> tuple[str | None, str | None]:
        payload = event["payload"]
        payload_type = payload.get("type")
        if payload_type in {"thread_started", "thread_resumed"}:
            return self._string_from(payload, "thread_id") or self._primary_thread_id(
                event
            ), "open"
        if payload_type == "thread_ended":
            return self._string_from(payload, "thread_id") or self._primary_thread_id(
                event
            ), self._string_from(payload, "status")

        item = harness(event)
        if (
            item is None
            or item.get("category") != "multi_agent"
            or item.get("name") != "agent_status_transition"
        ):
            return None, None
        correlations = item.get("correlations")
        details = item.get("details")
        thread_id = self._string_from(correlations, "task_thread_id", "child_thread_id")
        status = self._string_from(
            item, "status", "outcome", "state"
        ) or self._string_from(details, "status", "state", "to")
        return thread_id, status

    def _concurrency(self) -> dict[str, Any]:
        active_roots = sorted({root for root in self.active_turns.values() if root})
        loaded_agents = sum(
            thread.residency == "loaded" and thread.thread_id != task.root_thread_id
            for task in self.tasks.values()
            for thread in task.threads.values()
        )
        return {
            "activeTaskCount": len(active_roots),
            "activeRootThreadIds": active_roots,
            "maxActiveTaskCount": self.max_active_task_count,
            "activeTurnCount": len(self.active_turns),
            "maxActiveTurnCount": self.max_active_turn_count,
            "openThreadCount": len(self.open_threads),
            "loadedAgentCount": loaded_agents,
        }

    def _event_metadata(
        self,
        event: dict[str, Any],
        root_thread_id: str | None,
    ) -> dict[str, Any]:
        concurrency = self._concurrency()
        if root_thread_id is None:
            return {
                "rootThreadId": None,
                "scope": "session",
                "concurrency": concurrency,
            }

        task = self.tasks[root_thread_id]
        metadata: dict[str, Any] = {
            "rootThreadId": root_thread_id,
            "status": task.status,
            "lifecycle": "ended"
            if task.status in TERMINAL_TASK_STATUSES
            else task.status,
            "concurrency": concurrency,
        }
        thread_id = self._primary_thread_id(event)
        if thread_id is None:
            return metadata
        thread = task.threads.get(thread_id)
        if thread is None:
            return metadata
        metadata["threadId"] = thread.thread_id
        metadata["threadStatus"] = thread.status
        if thread.residency is not None:
            metadata["threadResidency"] = thread.residency
        if thread.parent_thread_id is not None:
            metadata["parentThreadId"] = thread.parent_thread_id
        if thread.agent_path is not None:
            metadata["agentPath"] = thread.agent_path
        return metadata

    def apply(self, event: dict[str, Any]) -> dict[str, Any]:
        declared_root, root_thread_id = task_root_identity(event)
        version = event.get("schema_version")
        if not declared_root and (type(version) is not int or version < 6):
            root_thread_id = self._legacy_root_for(event)
        kind = event["payload"].get("type")
        thread_id = self._primary_thread_id(event)
        turn_id = event.get("codex_turn_id") or event["payload"].get("codex_turn_id")
        if kind in {"run_ended", "rollout_ended"}:
            self.run_ended = True
            self.run_status = self._string_from(event["payload"], "status")
        if kind == "run_ended":
            # The shared App Server lifetime has ended, even when an individual
            # turn's final outcome was not observed. Do not invent task outcomes.
            self.active_turns.clear()
            self.open_threads.clear()
            for task in self.tasks.values():
                for thread in task.threads.values():
                    if thread.residency == "loaded":
                        thread.residency = "ended"
        if thread_id and kind in {"thread_started", "thread_resumed"}:
            self.open_threads.add(thread_id)
        elif thread_id and kind == "thread_ended":
            self.open_threads.discard(thread_id)
            self.active_turns = {
                key: root
                for key, root in self.active_turns.items()
                if key[0] != thread_id
            }
        if thread_id and nonempty_string(turn_id):
            turn_key = (thread_id, turn_id)
            if kind == "codex_turn_started":
                self.active_turns[turn_key] = root_thread_id
            elif kind == "codex_turn_ended":
                self.active_turns.pop(turn_key, None)
        self.max_active_turn_count = max(
            self.max_active_turn_count, len(self.active_turns)
        )
        active_roots = {root for root in self.active_turns.values() if root}
        self.max_active_task_count = max(self.max_active_task_count, len(active_roots))
        if root_thread_id is None:
            return self._event_metadata(event, None)

        task = self._ensure_task(root_thread_id)
        for thread_id in self._event_thread_ids(event):
            self._ensure_thread(task, thread_id)

        parent_thread_id, child_thread_id = self._relationship(event)
        if parent_thread_id is not None and child_thread_id is not None:
            self._ensure_thread(task, parent_thread_id)
            child = self._ensure_thread(task, child_thread_id)
            child.parent_thread_id = parent_thread_id

        primary_thread_id = self._primary_thread_id(event)
        agent_path = self._agent_path(event)
        if primary_thread_id is not None and agent_path is not None:
            self._ensure_thread(task, primary_thread_id).agent_path = agent_path

        if primary_thread_id is not None and event["payload"].get("type") in {
            "thread_started",
            "thread_resumed",
        }:
            self._ensure_thread(task, primary_thread_id).residency = "loaded"
        elif primary_thread_id is not None and kind == "thread_ended":
            self._ensure_thread(task, primary_thread_id).residency = "ended"
        item = harness(event)
        if item is not None and item.get("category") == "multi_agent":
            target = self._string_from(
                item.get("correlations"),
                "task_thread_id",
                "child_thread_id",
                "target_thread_id",
            )
            if target is not None:
                if (
                    item.get("name") == "agent_eviction"
                    and item.get("phase") == "completed"
                    and item.get("outcome") == "evicted"
                ):
                    self._ensure_thread(task, target).residency = "unloaded"
                elif item.get("name") == "agent_reload":
                    thread = self._ensure_thread(task, target)
                    phase = item.get("phase")
                    if phase == "materialized":
                        thread.residency = "materialized"
                    elif phase == "completed":
                        thread.residency = "loaded"
                    elif phase == "failed" and thread.residency == "materialized":
                        thread.residency = "unknown"

        status_thread_id, status = self._status_update(event)
        if status_thread_id is not None and status is not None:
            thread = self._ensure_thread(task, status_thread_id)
            thread.status = status
            if status_thread_id == root_thread_id:
                task.status = status

        return self._event_metadata(event, root_thread_id)

    def metadata(self) -> dict[str, Any]:
        return {
            "tasks": [task.metadata() for task in self.tasks.values()],
            "concurrency": self._concurrency(),
            "run_ended": self.run_ended,
            "run_status": self.run_status,
        }


def is_v2_event(item: dict[str, Any]) -> bool:
    details = item.get("details")
    return isinstance(details, dict) and details.get("implementation") == "v2"


def lifecycle_identity(item: dict[str, Any], identity_key: str) -> str | None:
    if identity_key == "step_id":
        value = item.get("step_id")
        return value if nonempty_string(value) else None
    return correlations_for(item).get(identity_key)


def request_tool_catalog(item: dict[str, Any]) -> bool:
    return (
        item.get("category"),
        item.get("name"),
        item.get("phase"),
        item.get("outcome"),
    ) == ("tool", "tool_catalog", "observed", "prepared_request")


def required_step(item: dict[str, Any]) -> bool:
    category = item.get("category")
    name = item.get("name")
    phase = item.get("phase")
    # Turn admission is decided before Core has constructed a StepContext.
    # The selected turn is still correlated by the outer trace envelope.
    if category == "agent_loop":
        return name != "turn_input_disposition"
    if category == "tool":
        return not request_tool_catalog(item)
    if category == "decision" and name in DECISION_STEP_REQUIRED_EVENTS:
        return True
    if (category, name) == ("context", "compaction_decision"):
        details = item.get("details")
        return not isinstance(details, dict) or details.get("phase") != "pre_turn"
    if (category, name) in STEP_REQUIRED_EVENTS:
        return True
    if category == "multi_agent" and name in MULTI_AGENT_TOOL_EVENTS:
        return True
    return (
        category == "multi_agent"
        and name == "agent_message"
        and phase in {"requested", "rejected"}
    )


def required_correlations(
    item: dict[str, Any], schema_version: int = 0
) -> tuple[str, ...]:
    category = item.get("category")
    name = item.get("name")
    phase = item.get("phase")
    if request_tool_catalog(item):
        return ("inference_call_id",)
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
    if (
        category == "multi_agent"
        and name == "agent_message"
        and phase in {"requested", "rejected"}
    ):
        return ("parent_thread_id", "target_thread_id", "tool_call_id")
    if category == "multi_agent" and name == "agent_message" and phase == "enqueued":
        correlations = correlations_for(item)
        if schema_version < 6 and "tool_call_id" in correlations:
            return (
                "parent_thread_id",
                "target_thread_id",
                "tool_call_id",
                "message_id",
            )
    if category == "multi_agent" and name == "agent_result_delivery":
        if phase == "enqueued":
            return (
                ("parent_thread_id", "child_thread_id")
                if schema_version >= 6
                else ("parent_thread_id", "child_thread_id", "message_id")
            )
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
            name == "agent_residency"
            and phase in {"touched", "released", "selected_for_eviction"}
        ):
            return ("root_thread_id", "task_thread_id")
        return ("root_thread_id",)
    return ()


def integrity_findings(
    event_stream: Iterator[dict[str, Any]],
) -> list[TraceIntegrityFinding]:
    findings: list[TraceIntegrityFinding] = []
    openings: dict[tuple[str, str, str], list[int]] = defaultdict(list)
    previous_seq: int | None = None
    for event in event_stream:
        seq = event["seq"]
        if previous_seq is not None and seq <= previous_seq:
            findings.append(
                TraceIntegrityFinding(
                    seq, f"seq must be strictly after prior seq={previous_seq}"
                )
            )
        previous_seq = seq

        payload = event["payload"]
        if payload.get("type") != "harness_event_observed":
            continue
        item = payload.get("event")
        if not isinstance(item, dict):
            findings.append(
                TraceIntegrityFinding(seq, "harness event must be an object")
            )
            continue
        if not all(
            nonempty_string(item.get(field)) for field in ("category", "name", "phase")
        ):
            findings.append(
                TraceIntegrityFinding(
                    seq, "harness event requires non-empty category, name, and phase"
                )
            )
            continue
        if "correlations" in item and not isinstance(item["correlations"], dict):
            findings.append(
                TraceIntegrityFinding(seq, "harness correlations must be an object")
            )
            continue
        if required_step(item) and not nonempty_string(item.get("step_id")):
            findings.append(
                TraceIntegrityFinding(seq, "event requires a non-empty step_id")
            )
        correlations = correlations_for(item)
        version = event.get("schema_version")
        schema_version = version if type(version) is int else 0
        for key in required_correlations(item, schema_version):
            if key not in correlations:
                findings.append(
                    TraceIntegrityFinding(seq, f"event requires correlation {key}")
                )
        if request_tool_catalog(item):
            payloads = item.get("payloads")
            has_request = isinstance(payloads, list) and any(
                isinstance(reference, dict)
                and nonempty_string(reference.get("raw_payload_id"))
                and nonempty_string(reference.get("path"))
                and isinstance(reference.get("kind"), dict)
                and reference["kind"].get("type") == "inference_request"
                for reference in payloads
            )
            if not has_request:
                findings.append(
                    TraceIntegrityFinding(
                        seq, "event requires prepared request payload reference"
                    )
                )
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
        if (category, name, phase) == (
            "multi_agent",
            "agent_message",
            "enqueued",
        ) and schema_version >= 6:
            # Queue admission is a separate recipient-side fact, not the
            # sender's submission receipt.
            continue
        if phase not in opening_phases | terminal_phases:
            continue
        if identity is None:
            if (
                category == "multi_agent"
                and name == "agent_message"
                and phase in {"enqueued", "accepted"}
            ):
                # Mailbox facts and lower-level submission receipts may not
                # carry the sender's tool-call identity.
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
                TraceIntegrityFinding(
                    seq, f"unfinished opening {category}.{name} for identity {identity}"
                )
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


def event_step(event: dict[str, Any]) -> str | None:
    item = harness(event)
    for value in ((item or {}).get("step_id"), event["payload"].get("step_id")):
        if nonempty_string(value):
            return value
    return None


def matches(
    event: dict[str, Any], filters: Filters, task: dict[str, Any] | None = None
) -> bool:
    if filters.task_root and (task or {}).get("rootThreadId") not in filters.task_root:
        return False
    payload = event["payload"]
    if filters.payload_type and payload["type"] not in filters.payload_type:
        return False
    if (
        filters.thread
        and (event.get("thread_id") or payload.get("thread_id")) not in filters.thread
    ):
        return False
    if (
        filters.turn
        and (event.get("codex_turn_id") or payload.get("codex_turn_id"))
        not in filters.turn
    ):
        return False
    item = harness(event)
    if filters.harness_only and item is None:
        return False
    if filters.step and event_step(event) not in filters.step:
        return False
    if filters.category and teaching_category(event, item) not in filters.category:
        return False
    event_name = item.get("name") if item is not None else payload.get("method")
    if filters.name and event_name not in filters.name:
        return False
    event_phase = item.get("phase") if item is not None else payload.get("frame_kind")
    if filters.phase and event_phase not in filters.phase:
        return False
    correlations = filter_correlations(payload, item)
    return all(correlations.get(key) == value for key, value in filters.correlations)


def safe_detail(value: Any, key: str = "") -> Any:
    if key.lower() in SENSITIVE_DETAIL_KEYS:
        return "<redacted>"
    if isinstance(value, dict):
        return {
            str(child_key): safe_detail(child, str(child_key))
            for child_key, child in value.items()
        }
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


def tool_descriptor(
    payload: dict[str, Any], item: dict[str, Any] | None
) -> dict[str, Any] | None:
    """Return the small human-readable identity shared by one tool lifecycle."""
    call_id = payload.get("tool_call_id")
    if not isinstance(call_id, str) and item is not None:
        correlations = item.get("correlations")
        if isinstance(correlations, dict):
            correlated_id = correlations.get("tool_call_id")
            if isinstance(correlated_id, str):
                call_id = correlated_id

    payload_type = payload.get("type")
    if isinstance(payload_type, str) and payload_type.startswith("code_cell_"):
        runtime_cell_id = payload.get("runtime_cell_id")
        if not isinstance(runtime_cell_id, str):
            return None
        return {
            "call_id": runtime_cell_id,
            "name": "code_mode",
            "requester": "model",
            "classification": "model_authored_code",
            "classification_label": "Model-authored JavaScript execution",
        }

    if not isinstance(call_id, str):
        return None

    descriptor: dict[str, Any] = {"call_id": call_id}
    if payload_type != "tool_call_started":
        return descriptor

    summary = payload.get("summary")
    name: str | None = None
    if isinstance(summary, dict):
        for key in ("label", "tool_name"):
            candidate = summary.get(key)
            if isinstance(candidate, str) and candidate:
                name = candidate
                break

    kind = payload.get("kind")
    kind_type: str | None = None
    if isinstance(kind, str):
        kind_type = kind
    elif isinstance(kind, dict):
        candidate = kind.get("type")
        if isinstance(candidate, str):
            kind_type = candidate
        if kind_type == "mcp":
            server = kind.get("server")
            tool = kind.get("tool")
            if isinstance(server, str) and isinstance(tool, str):
                name = f"{server}.{tool}"
        elif name is None:
            candidate = kind.get("name")
            if isinstance(candidate, str):
                name = candidate

    requester = payload.get("requester")
    requester_type = requester.get("type") if isinstance(requester, dict) else requester
    if isinstance(name, str):
        descriptor["name"] = name
    if isinstance(kind_type, str):
        descriptor["kind"] = kind_type
    if isinstance(requester_type, str):
        descriptor["requester"] = requester_type

    normalized_name = (name or kind_type or "").lower()
    if normalized_name == "apply_patch" or kind_type == "apply_patch":
        descriptor.update(
            classification="internal_codex_tool",
            classification_label="Internal Codex patch tool (not shell or MCP)",
        )
    elif kind_type == "mcp":
        descriptor.update(
            classification="mcp_tool",
            classification_label="MCP tool call",
        )
    elif requester_type == "code_cell":
        descriptor.update(
            classification="code_mode_nested_tool",
            classification_label="Tool called from model-authored JavaScript",
        )
    elif normalized_name in {"exec_command", "write_stdin", "local_shell", "shell"}:
        descriptor.update(
            classification="built_in_local_tool",
            classification_label="Built-in local execution tool",
        )
    else:
        descriptor.update(
            classification="codex_tool",
            classification_label="Codex tool call",
        )
    return descriptor


def compact_value(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def harness_line(event: dict[str, Any], item: dict[str, Any], details: bool) -> str:
    fields = [
        f"{item.get('category', '?')}.{item.get('name', '?')}",
        f"phase={item.get('phase', '?')}",
    ]
    for label, value in (
        ("outcome", item.get("outcome")),
        ("reason", item.get("reason")),
    ):
        if value is not None:
            fields.append(f"{label}={value}")
    for label, value in (
        ("thread", event.get("thread_id")),
        ("turn", event.get("codex_turn_id")),
        ("step", item.get("step_id")),
    ):
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
    for label, value in (
        ("thread", event.get("thread_id")),
        ("turn", event.get("codex_turn_id")),
    ):
        if value is not None:
            fields.append(f"{label}={value}")
    return " ".join(fields)


def safe_reference_path(value: str) -> str:
    candidate = Path(value)
    if candidate.is_absolute() or ".." in candidate.parts:
        return candidate.name
    return candidate.as_posix()


def payload_references(
    value: Any, field: str = "payload", *, safe_paths: bool = True
) -> list[dict[str, Any]]:
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
                    "path": safe_reference_path(path) if safe_paths else path,
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


def viewer_event(
    event: dict[str, Any],
    *,
    show_content: bool = False,
    task: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = event["payload"]
    item = harness(event)
    declared_task_root, task_root_thread_id = task_root_identity(event)
    if task is not None and "rootThreadId" in task:
        task_root_thread_id = task["rootThreadId"]
    elif not declared_task_root:
        task_root_thread_id = None
    payload_metadata: dict[str, Any] = {}
    for key, value in payload.items():
        if (key in RAW_SAFE_KEYS or key.endswith("_id")) and isinstance(
            value, (str, int, float, bool)
        ):
            payload_metadata[key] = safe_detail(value, key)
    payload_metadata.update(app_server_metadata(payload))
    references = payload_references(payload)
    wrapper = event.get("_raw_wrapper")
    if isinstance(wrapper, dict):
        references.extend(
            reference
            for reference in payload_references(wrapper.get("payload"))
            if reference not in references
        )
    safe_event: dict[str, Any] = {
        "schema_version": event.get("schema_version"),
        "seq": event["seq"],
        "wall_time_unix_ms": event.get("wall_time_unix_ms"),
        "rollout_id": event.get("rollout_id"),
        "thread_id": event.get("thread_id") or payload.get("thread_id"),
        "codex_turn_id": event.get("codex_turn_id") or payload.get("codex_turn_id"),
        "step_id": event_step(event),
        "step_correlation": "explicit" if event_step(event) else "unknown",
        "task_root_thread_id": task_root_thread_id,
        "payload_type": payload["type"],
        "payload_metadata": payload_metadata,
        "payload_references": references,
    }
    if isinstance(wrapper, dict):
        safe_event["externalized_payload"] = True
    pairing = wire_pairing(payload, event.get("schema_version"))
    if pairing is not None:
        safe_event["wire_pairing"] = pairing
        if payload["type"] == "app_server_frame_observed":
            safe_event["app_server_pairing"] = pairing
    if task is not None:
        safe_event["task"] = task
    descriptor = tool_descriptor(payload, item)
    if descriptor is not None:
        safe_event["tool"] = descriptor
    if show_content:
        safe_event["payload"] = payload
        safe_event["raw_event"] = wrapper if isinstance(wrapper, dict) else event
    if item is not None:
        safe_event["harness"] = {
            "category": item.get("category"),
            "name": item.get("name"),
            "phase": item.get("phase"),
            "step_id": item.get("step_id"),
            "outcome": item.get("outcome"),
            "reason": item.get("reason"),
            "correlations": item.get("correlations")
            if show_content
            else safe_correlations(item.get("correlations")),
            "details": item.get("details")
            if show_content
            else safe_detail(item.get("details")),
        }
    return safe_event


def task_metadata(path: Path) -> dict[str, Any]:
    """Read the available ordered ledger into the compact task header model."""
    ledger = TaskLedger()
    try:
        for event in events(path):
            ledger.apply(event)
    except TraceInputError:
        # Stream delivery will surface the malformed record. Retaining the
        # metadata accumulated before it keeps a live header useful while the
        # writer is repaired or the viewer reports the error.
        pass
    return ledger.metadata()


def manifest_metadata(
    path: Path, *, show_content: bool = False, recorded: bool = False
) -> dict[str, Any]:
    manifest_path = path.parent / "manifest.json"
    manifest: dict[str, Any] = {}
    if manifest_path.is_file():
        try:
            parsed = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise TraceInputError(f"cannot read bundle manifest: {error}") from error
        if not isinstance(parsed, dict):
            raise TraceInputError("bundle manifest must be a JSON object")
        version = parsed.get("schema_version")
        if version is not None and (
            type(version) is not int or not 1 <= version <= MAX_MANIFEST_SCHEMA
        ):
            raise TraceInputError(f"unsupported bundle manifest schema: {version}")
        identity = parsed.get("format")
        if identity not in (None, TRACE_FORMAT) or (
            version in (3, 4) and identity != TRACE_FORMAT
        ):
            raise TraceInputError(f"unsupported trace format: {identity!r}")
        if identity is not None:
            manifest["format"] = identity
        for key in MANIFEST_SAFE_KEYS:
            value = parsed.get(key)
            if isinstance(value, (str, int, float, bool)) or (
                key == "root_thread_id" and key in parsed and value is None
            ):
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
    if isinstance(
        parsed_health := parsed.get("capture_health")
        if manifest_path.is_file()
        else None,
        dict,
    ):
        manifest["capture_health"] = parsed_health
    if manifest_path.is_file() and isinstance(parsed.get("build_descriptor"), dict):
        manifest["build_descriptor"] = parsed["build_descriptor"]
    manifest.update(task_metadata(path))
    run_state = manifest.get("capture_health", {}).get("run_state")
    manifest["capture_status"] = (
        ("interrupted" if run_state == "interrupted" else "closed")
        if manifest["run_ended"]
        else ("partial" if recorded else "open")
    )
    manifest["source_name"] = (
        path.parent.name if path.name == "trace.jsonl" else path.name
    )
    manifest["stream_mode"] = "recorded_jsonl" if recorded else "append_only_jsonl"
    manifest["content_mode"] = "full" if show_content else "redacted"
    manifest["full_content"] = show_content
    return manifest


def resolve_artifact(trace_path: Path, requested_path: str) -> Path:
    """Resolve a referenced regular file without allowing escape from the bundle."""
    relative = Path(requested_path)
    if not requested_path or relative.is_absolute() or ".." in relative.parts:
        raise TraceInputError("artifact path must be relative to the trace bundle")
    bundle_root = trace_path.parent.resolve()
    try:
        artifact_path = (bundle_root / relative).resolve(strict=True)
        artifact_path.relative_to(bundle_root)
    except (OSError, ValueError) as error:
        raise TraceInputError(
            f"artifact is unavailable: {relative.as_posix()}"
        ) from error
    if not artifact_path.is_file():
        raise TraceInputError(f"artifact is not a file: {relative.as_posix()}")
    return artifact_path


def artifact_payload(trace_path: Path, requested_path: str) -> dict[str, Any]:
    """Load one bundle-local evidence artifact for the teaching viewer."""
    relative = Path(requested_path)
    artifact_path = resolve_artifact(trace_path, requested_path)
    try:
        raw = artifact_path.read_bytes()
    except OSError as error:
        raise TraceInputError(f"cannot read artifact: {relative.as_posix()}") from error
    try:
        text_content = raw.decode("utf-8")
    except UnicodeDecodeError:
        text_content = None
    media_type = (
        "text/plain" if text_content is not None else "application/octet-stream"
    )
    content: Any = text_content
    if text_content is not None and artifact_path.suffix.lower() == ".json":
        try:
            content = json.loads(text_content)
            media_type = "application/json"
        except json.JSONDecodeError:
            pass
    return {
        "path": relative.as_posix(),
        "media_type": media_type,
        "size_bytes": len(raw),
        "content": content,
        "raw_text": text_content,
        "raw_base64": base64.b64encode(raw).decode("ascii")
        if text_content is None
        else None,
    }


def validated_events(
    path: Path, *, enforce_sequence: bool = True
) -> Iterator[dict[str, Any]]:
    """Read expanded events and verify every discoverable bundle reference."""
    seen: set[str] = set()
    for event in events(path, enforce_sequence=enforce_sequence):
        sources = [event["payload"]]
        if isinstance(event.get("_raw_wrapper"), dict):
            sources.append(event["_raw_wrapper"]["payload"])
        for source in sources:
            for reference in payload_references(source, safe_paths=False):
                name = reference["path"]
                if name not in seen:
                    resolve_artifact(path, name)
                    seen.add(name)
        yield event
    state_path = path.parent / "state.json"
    if state_path.is_file():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise TraceInputError(f"cannot read reduced state: {error}") from error
        for reference in payload_references(state, field="state", safe_paths=False):
            name = reference["path"]
            if name not in seen:
                resolve_artifact(path, name)
                seen.add(name)


def safe_stream_error(error: Exception, path: Path) -> str:
    return str(error).replace(str(path), path.name)[:240]


def tail_updates(
    path: Path,
    *,
    after_seq: int = 0,
    follow: bool = True,
    poll_interval: float = 0.15,
    stop_event: threading.Event | None = None,
    show_content: bool = False,
) -> Iterator[dict[str, Any]]:
    position = 0
    buffered = b""
    line_number = 0
    previous_seq: int | None = None
    task_ledger = TaskLedger()
    last_heartbeat = time.monotonic()
    while stop_event is None or not stop_event.is_set():
        try:
            size = path.stat().st_size
            if size < position:
                yield {
                    "kind": "error",
                    "message": "trace.jsonl was truncated while viewing",
                }
                return
            if size > position:
                with path.open("rb") as stream:
                    stream.seek(position)
                    chunk = stream.read(size - position)
                position += len(chunk)
                buffered += chunk
                if not follow and buffered and not buffered.endswith(b"\n"):
                    buffered += b"\n"
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
                        yield {
                            "kind": "error",
                            "message": safe_stream_error(error, path),
                        }
                        return
                    if event is None:
                        continue
                    previous_seq = event["seq"]
                    try:
                        event = expand_oversized_event(event, path)
                    except TraceInputError as error:
                        yield {
                            "kind": "error",
                            "message": safe_stream_error(error, path),
                        }
                        return
                    task = task_ledger.apply(event)
                    if event["seq"] > after_seq:
                        yield {
                            "kind": "event",
                            "event": viewer_event(
                                event,
                                show_content=show_content,
                                task=task,
                            ),
                        }
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
        show_content: bool = True,
        *,
        recorded: bool = False,
    ):
        self.trace_path = trace
        self.trace_root = trace_root
        self.show_content = show_content
        self.recorded = recorded
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

    def send_bytes(
        self, body: bytes, content_type: str, status: HTTPStatus = HTTPStatus.OK
    ) -> None:
        self.send_response(status)
        self.send_common_headers(content_type, len(body))
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, value: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(value, separators=(",", ":"), ensure_ascii=True).encode(
            "utf-8"
        )
        self.send_bytes(body, "application/json; charset=utf-8", status)

    def serve_asset(self, name: str, content_type: str) -> None:
        path = WEB_ASSET_DIR / name
        try:
            body = path.read_bytes()
        except OSError as error:
            self.send_json(
                {
                    "error": f"viewer asset unavailable: {error.strerror or 'read failed'}"
                },
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )
            return
        self.send_bytes(body, content_type)

    def stream_events(self, query: dict[str, list[str]]) -> None:
        requested_after = query.get("after", [self.headers.get("Last-Event-ID", "0")])[
            0
        ]
        try:
            after_seq = int(requested_after or "0")
        except ValueError:
            self.send_json(
                {"error": "after must be an integer sequence"}, HTTPStatus.BAD_REQUEST
            )
            return
        self.send_response(HTTPStatus.OK)
        self.send_common_headers("text/event-stream; charset=utf-8")
        self.send_header(
            "Connection", "close" if self.viewer_server.recorded else "keep-alive"
        )
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
                update = {
                    "kind": "source",
                    "metadata": manifest_metadata(
                        trace_path,
                        show_content=self.viewer_server.show_content,
                        recorded=self.viewer_server.recorded,
                    ),
                }
                data = json.dumps(update, separators=(",", ":"), ensure_ascii=True)
                self.wfile.write(
                    f"event: trace-source\ndata: {data}\n\n".encode("utf-8")
                )
                self.wfile.flush()
            for update in tail_updates(
                trace_path,
                after_seq=after_seq,
                stop_event=self.viewer_server.stop_event,
                show_content=self.viewer_server.show_content,
                follow=not self.viewer_server.recorded,
            ):
                kind = update["kind"]
                if kind == "heartbeat":
                    packet = b": heartbeat\n\n"
                else:
                    data = json.dumps(update, separators=(",", ":"), ensure_ascii=True)
                    if kind == "event":
                        seq = update["event"]["seq"]
                        packet = f"id: {seq}\nevent: trace\ndata: {data}\n\n".encode(
                            "utf-8"
                        )
                    else:
                        packet = f"event: trace-error\ndata: {data}\n\n".encode("utf-8")
                self.wfile.write(packet)
                self.wfile.flush()
                if kind == "error":
                    self.close_connection = True
                    return
            if self.viewer_server.recorded:
                self.wfile.write(
                    b'event: trace-complete\ndata: {"kind":"complete"}\n\n'
                )
                self.wfile.flush()
                self.close_connection = True
        except (BrokenPipeError, ConnectionResetError):
            return

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self.serve_asset("index.html", "text/html; charset=utf-8")
        elif parsed.path.startswith("/assets/"):
            name = parsed.path.removeprefix("/assets/")
            suffix = Path(name).suffix
            if (
                Path(name).name != name
                or suffix not in {".js", ".css"}
                or not (WEB_ASSET_DIR / name).is_file()
            ):
                self.send_json({"error": "asset not found"}, HTTPStatus.NOT_FOUND)
            else:
                content_type = "text/javascript" if suffix == ".js" else "text/css"
                self.serve_asset(name, content_type + "; charset=utf-8")
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
                            "content_mode": "full"
                            if self.viewer_server.show_content
                            else "redacted",
                            "full_content": self.viewer_server.show_content,
                        }
                    )
                else:
                    self.send_json(
                        manifest_metadata(
                            trace_path,
                            show_content=self.viewer_server.show_content,
                            recorded=self.viewer_server.recorded,
                        )
                    )
            except TraceInputError as error:
                source = self.viewer_server.trace_root or Path("trace.jsonl")
                self.send_json(
                    {"error": safe_stream_error(error, source)},
                    HTTPStatus.UNPROCESSABLE_ENTITY,
                )
        elif parsed.path == "/api/teaching":
            from observatory.teaching_http import serve_teaching

            serve_teaching(self, parse_qs(parsed.query))
        elif parsed.path == "/api/stream":
            self.stream_events(parse_qs(parsed.query))
        elif parsed.path == "/api/artifact":
            if not self.viewer_server.show_content:
                self.send_json(
                    {
                        "error": "artifact content is disabled; restart without --redact-content"
                    },
                    HTTPStatus.FORBIDDEN,
                )
                return
            query = parse_qs(parsed.query)
            requested_path = query.get("path", [""])[0]
            trace_path = self.viewer_server.resolve_trace_path()
            if trace_path is None:
                self.send_json(
                    {"error": "trace bundle is not available yet"}, HTTPStatus.NOT_FOUND
                )
                return
            try:
                self.send_json(artifact_payload(trace_path, requested_path))
            except TraceInputError as error:
                self.send_json({"error": str(error)}, HTTPStatus.NOT_FOUND)
        else:
            self.send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)


def make_viewer_server(
    path: Path,
    host: str,
    port: int,
    *,
    wait_for_bundle: bool = False,
    show_content: bool = True,
    recorded: bool = False,
) -> TraceViewerHTTPServer:
    try:
        return TraceViewerHTTPServer(
            (host, port),
            None if wait_for_bundle else path,
            path if wait_for_bundle else None,
            show_content,
            recorded=recorded,
        )
    except OSError as error:
        raise TraceInputError(
            f"cannot bind viewer at {host}:{port}: {error}"
        ) from error


def serve_viewer(
    path: Path,
    host: str,
    port: int,
    *,
    wait_for_bundle: bool = False,
    show_content: bool = True,
    recorded: bool = False,
) -> int:
    server = make_viewer_server(
        path,
        host,
        port,
        wait_for_bundle=wait_for_bundle,
        show_content=show_content,
        recorded=recorded,
    )
    bound_host, bound_port = server.server_address[:2]
    display_host = "127.0.0.1" if bound_host in {"0.0.0.0", "::"} else bound_host
    print(f"Codex Harness Observatory: http://{display_host}:{bound_port}", flush=True)
    if bound_host not in {"127.0.0.1", "localhost", "::1"}:
        print(
            "trace-viewer: warning: viewer is not bound exclusively to loopback",
            file=sys.stderr,
        )
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def timeline(
    event_stream: Iterator[dict[str, Any]], filters: Filters, details: bool
) -> int:
    matched = 0
    ledger = TaskLedger()
    for event in event_stream:
        task = ledger.apply(event)
        if not matches(event, filters, task):
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
    ledger = TaskLedger()
    for event in event_stream:
        task = ledger.apply(event)
        if not matches(event, filters, task):
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
        if (
            group == ("multi_agent", "agent_message")
            and phase == "enqueued"
            and (event.get("schema_version") or 0) >= 6
        ):
            continue
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
        print(
            f"  {group[0]}.{group[1]}: {matched_durations[group]} matched, total={sum(values)}ms, min={min(values)}ms, max={max(values)}ms"
        )
    return matched


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog=(
            "normal exit status: 0 = matched events, 1 = no match, 2 = malformed or unreadable input; "
            "--check exit status: 0 = clean, 1 = integrity findings, 2 = malformed or unreadable input"
        ),
    )
    parser.add_argument(
        "input",
        help="trace bundle directory, trace.jsonl, or trace root with --wait-for-bundle",
    )
    parser.add_argument(
        "--payload-type",
        action="append",
        default=[],
        metavar="TYPE",
        help="raw payload type (repeatable)",
    )
    parser.add_argument(
        "--thread", action="append", default=[], help="thread ID (repeatable)"
    )
    parser.add_argument(
        "--task-root",
        action="append",
        default=[],
        help="task root and its child threads (repeatable)",
    )
    parser.add_argument(
        "--turn", action="append", default=[], help="Codex turn ID (repeatable)"
    )
    parser.add_argument(
        "--step", action="append", default=[], help="harness step ID (repeatable)"
    )
    parser.add_argument(
        "--category", action="append", default=[], help="teaching category (repeatable)"
    )
    parser.add_argument(
        "--name",
        action="append",
        default=[],
        help="event or protocol method name (repeatable)",
    )
    parser.add_argument(
        "--phase",
        action="append",
        default=[],
        help="event phase or frame kind (repeatable)",
    )
    parser.add_argument(
        "--correlation",
        action="append",
        default=[],
        type=parse_correlation,
        metavar="KEY=VALUE",
        help="event correlation (repeatable)",
    )
    parser.add_argument(
        "--harness-only", action="store_true", help="hide ordinary raw events"
    )
    parser.add_argument(
        "--details",
        action="store_true",
        help="include compact, redacted harness details",
    )
    parser.add_argument(
        "--summary", action="store_true", help="aggregate counts and matched durations"
    )
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
    content_mode = parser.add_mutually_exclusive_group()
    content_mode.add_argument(
        "--show-content",
        dest="show_content",
        action="store_true",
        help="send full event fields and allow bundle payloads to be opened (the default)",
    )
    content_mode.add_argument(
        "--redact-content",
        dest="show_content",
        action="store_false",
        help="hide event contents and bundle payload artifacts in the local viewer",
    )
    parser.set_defaults(show_content=True)
    parser.add_argument(
        "--recorded",
        action="store_true",
        help="read this exact capture once and mark it recorded (requires --serve)",
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
        print(
            "trace-viewer: error: --wait-for-bundle requires --serve", file=sys.stderr
        )
        return 2
    if args.recorded and (not args.serve or args.wait_for_bundle):
        print(
            "trace-viewer: error: --recorded requires --serve and an exact capture",
            file=sys.stderr,
        )
        return 2
    filters = Filters(
        set(args.payload_type),
        set(args.thread),
        set(args.turn),
        set(args.step),
        set(args.category),
        set(args.name),
        set(args.phase),
        tuple(args.correlation),
        args.harness_only,
        set(args.task_root),
    )
    try:
        if args.wait_for_bundle:
            root = trace_root_path(args.input)
            return serve_viewer(
                root,
                args.host,
                args.port,
                wait_for_bundle=True,
                show_content=args.show_content,
            )
        path = trace_path(args.input)
        if args.serve:
            if args.recorded:
                manifest_metadata(path, recorded=True)
                next(events(path), None)
            return serve_viewer(
                path,
                args.host,
                args.port,
                show_content=args.show_content,
                recorded=args.recorded,
            )
        if args.check:
            return check(validated_events(path, enforce_sequence=False))
        matched = (
            summary(events(path), filters)
            if args.summary
            else timeline(events(path), filters, args.details)
        )
    except TraceInputError as error:
        print(f"trace-viewer: error: {error}", file=sys.stderr)
        return 2
    return 0 if matched else 1


if __name__ == "__main__":
    raise SystemExit(main())
