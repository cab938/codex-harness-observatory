#!/usr/bin/env python3
"""Accept the compact App Server lifecycle used in Lecture 2."""

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

try:
    from observatory.trace_viewer import TraceInputError, events, trace_path
except ModuleNotFoundError:
    # Direct execution needs the parent of the observatory package on sys.path.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from observatory.trace_viewer import TraceInputError, events, trace_path


@dataclass(frozen=True)
class Finding:
    seq: int | None
    message: str

    def render(self) -> str:
        location = "trace" if self.seq is None else f"seq={self.seq}"
        return f"{location}: {self.message}"


@dataclass(frozen=True)
class Frame:
    seq: int
    connection_id: str
    direction: str
    frame_kind: str
    method: str
    request_id: str | int | float | None
    source_thread_id: str | None
    new_thread_id: str | None
    item_id: str | None
    forked_from_id: str | None
    session_id: str | None
    thread_id: str | None
    codex_turn_id: str | None
    schema_version: int = 0
    connection_instance_id: str | None = None
    exchange_id: str | None = None


def text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def frame_from(event: dict[str, Any]) -> Frame | None:
    payload = event.get("payload")
    if (
        not isinstance(payload, dict)
        or payload.get("type") != "app_server_frame_observed"
    ):
        return None
    seq = event.get("seq")
    connection_id = text(payload.get("connection_id"))
    direction = text(payload.get("direction"))
    frame_kind = text(payload.get("frame_kind"))
    method = text(payload.get("method"))
    if not isinstance(seq, int) or None in (connection_id, direction, frame_kind):
        return None
    return Frame(
        seq=seq,
        connection_id=connection_id,
        direction=direction,
        frame_kind=frame_kind,
        method=method or "",
        request_id=payload.get("request_id")
        if type(payload.get("request_id")) in (str, int, float)
        else None,
        source_thread_id=text(payload.get("source_thread_id")),
        new_thread_id=text(payload.get("new_thread_id")),
        item_id=text(payload.get("item_id")),
        forked_from_id=text(payload.get("forked_from_id")),
        session_id=text(payload.get("session_id")),
        thread_id=text(event.get("thread_id")),
        codex_turn_id=text(event.get("codex_turn_id")),
        schema_version=event.get("schema_version")
        if type(event.get("schema_version")) is int
        else 0,
        connection_instance_id=text(payload.get("connection_instance_id")),
        exchange_id=text(payload.get("exchange_id")),
    )


def frame_key(frame: Frame) -> tuple[Any, ...] | None:
    """Use explicit exchange identity, or legacy typed IDs scoped to a direction."""
    if frame.schema_version >= 6:
        if not frame.connection_instance_id or not frame.exchange_id:
            return None
        return ("app_server", frame.connection_instance_id, frame.exchange_id)
    if frame.request_id is None or frame.request_id == "":
        return None
    request_direction = frame.direction
    if frame.frame_kind in {"response", "error"}:
        request_direction = {
            "client_to_server": "server_to_client",
            "server_to_client": "client_to_server",
        }.get(frame.direction, "")
    if request_direction not in {"client_to_server", "server_to_client"}:
        return None
    id_type = "string" if isinstance(frame.request_id, str) else "number"
    return (
        "legacy_app_server",
        frame.connection_id,
        request_direction,
        id_type,
        frame.request_id,
    )


def paired_frames(
    frames: Iterable[Frame],
) -> tuple[dict[int, Frame], dict[tuple[Any, ...], Frame], list[Finding]]:
    pairs: dict[int, Frame] = {}
    requests: dict[tuple[Any, ...], Frame] = {}
    ambiguous: dict[tuple[Any, ...], int] = {}
    findings: list[Finding] = []
    for frame in frames:
        if frame.frame_kind not in {"request", "response", "error"}:
            continue
        if frame.direction not in {"client_to_server", "server_to_client"}:
            findings.append(
                Finding(
                    frame.seq,
                    f"{frame.method} {frame.frame_kind} has unknown direction {frame.direction}",
                )
            )
            continue
        key = frame_key(frame)
        if key is None:
            # New captures explicitly preserve unknown correlation. Do not infer
            # it from a matching ID, method, or nearby frame.
            if frame.schema_version < 6 and frame.request_id is None:
                findings.append(
                    Finding(
                        frame.seq,
                        f"{frame.method} {frame.frame_kind} has no request_id",
                    )
                )
            continue
        if frame.frame_kind == "request":
            if key in requests or key in ambiguous:
                if key in requests:
                    requests.pop(key)
                    ambiguous[key] = 2
                else:
                    ambiguous[key] += 1
                findings.append(
                    Finding(frame.seq, f"duplicate outstanding request identity {key}")
                )
            else:
                requests[key] = frame
            continue
        if key in ambiguous:
            # Neither overlapping request can be chosen without inventing a match.
            ambiguous[key] -= 1
            if ambiguous[key] == 0:
                del ambiguous[key]
            continue
        request = requests.pop(key, None)
        if request is None:
            findings.append(
                Finding(
                    frame.seq,
                    f"{frame.method or 'unknown'} {frame.frame_kind} has no matching request",
                )
            )
        elif request.direction == frame.direction:
            findings.append(
                Finding(frame.seq, "request and response have the same direction")
            )
        elif request.method and frame.method and request.method != frame.method:
            findings.append(
                Finding(
                    frame.seq,
                    f"response method {frame.method} does not match request {request.method}",
                )
            )
        else:
            pairs[request.seq] = frame
            pairs[frame.seq] = request
    return pairs, requests, findings


def request_response_pairs(
    frames: Iterable[Frame],
) -> tuple[dict[tuple[Any, ...], Frame], list[Finding]]:
    _, requests, findings = paired_frames(frames)
    return requests, findings


def matching_pair(
    frames: Sequence[Frame],
    method: str,
    after: int,
    findings: list[Finding],
) -> tuple[Frame, Frame] | None:
    pairs, _, _ = paired_frames(frames)
    for request in frames[after:]:
        if request.method != method or request.frame_kind != "request":
            continue
        if request.direction != "client_to_server":
            findings.append(
                Finding(request.seq, f"{method} request must be client_to_server")
            )
            return None
        response = pairs.get(request.seq)
        if response is None:
            findings.append(
                Finding(request.seq, f"{method} request has no matching response")
            )
            return None
        if response.frame_kind == "error":
            findings.append(Finding(response.seq, f"{method} returned an error"))
            return None
        return request, response
    findings.append(Finding(None, f"missing {method} request and response"))
    return None


def notification(
    frames: Sequence[Frame], method: str, after: int, findings: list[Finding]
) -> tuple[int, Frame] | None:
    for index in range(after, len(frames)):
        frame = frames[index]
        if frame.method == method and frame.frame_kind == "notification":
            if frame.direction != "server_to_client":
                findings.append(
                    Finding(
                        frame.seq, f"{method} notification must be server_to_client"
                    )
                )
                return None
            return index, frame
    findings.append(Finding(None, f"missing {method} notification"))
    return None


def require(
    value: str | None, label: str, frame: Frame, findings: list[Finding]
) -> str | None:
    if value is None:
        findings.append(Finding(frame.seq, f"{label} is required"))
    return value


def validate(raw_events: Iterable[dict[str, Any]]) -> list[Finding]:
    frames = [frame for event in raw_events if (frame := frame_from(event)) is not None]
    findings: list[Finding] = []
    _, pair_findings = request_response_pairs(frames)
    findings.extend(pair_findings)

    start_pair = matching_pair(frames, "thread/start", 0, findings)
    if start_pair is None:
        return findings
    _, start_response = start_pair
    source_thread_id = require(
        start_response.new_thread_id,
        "thread/start response new_thread_id",
        start_response,
        findings,
    )
    root_started = notification(
        frames, "thread/started", frames.index(start_response) + 1, findings
    )
    if root_started is None or source_thread_id is None:
        return findings
    root_index, root_notification = root_started
    if root_notification.thread_id != source_thread_id:
        findings.append(
            Finding(
                root_notification.seq,
                "initial thread/started outer thread_id does not match thread/start new_thread_id",
            )
        )
    if (
        root_notification.session_id != start_response.session_id
        or root_notification.session_id is None
    ):
        findings.append(
            Finding(
                root_notification.seq,
                "initial thread/started must retain the start session_id",
            )
        )

    turn_pair = matching_pair(frames, "turn/start", root_index + 1, findings)
    if turn_pair is None:
        return findings
    turn_request, turn_response = turn_pair
    if turn_request.source_thread_id != source_thread_id:
        findings.append(
            Finding(
                turn_request.seq, "turn/start must identify the active source_thread_id"
            )
        )
    turn_started = notification(
        frames, "turn/started", frames.index(turn_response) + 1, findings
    )
    if turn_started is None:
        return findings
    turn_index, turn_notification = turn_started
    active_turn_id = require(
        turn_notification.codex_turn_id,
        "turn/started outer codex_turn_id",
        turn_notification,
        findings,
    )
    if turn_notification.thread_id != source_thread_id:
        findings.append(
            Finding(
                turn_notification.seq,
                "turn/started outer thread_id must be the source thread",
            )
        )

    item_started = notification(frames, "item/started", turn_index + 1, findings)
    if item_started is None:
        return findings
    item_index, item_start_notification = item_started
    item_id = require(
        item_start_notification.item_id,
        "item/started item_id",
        item_start_notification,
        findings,
    )
    item_completed = notification(frames, "item/completed", item_index + 1, findings)
    if item_completed is None:
        return findings
    item_completed_index, item_completed_notification = item_completed
    if item_id is not None and item_completed_notification.item_id != item_id:
        findings.append(
            Finding(
                item_completed_notification.seq,
                "item/completed item_id does not match item/started",
            )
        )
    if (
        active_turn_id is not None
        and item_completed_notification.codex_turn_id != active_turn_id
    ):
        findings.append(
            Finding(
                item_completed_notification.seq,
                "item/completed is not on the active turn",
            )
        )

    steer_pair = matching_pair(frames, "turn/steer", item_completed_index + 1, findings)
    if steer_pair is None:
        return findings
    steer_request, steer_response = steer_pair
    if active_turn_id is not None and (
        steer_request.codex_turn_id != active_turn_id
        or steer_response.codex_turn_id != active_turn_id
    ):
        findings.append(
            Finding(
                steer_request.seq, "turn/steer must use the active outer codex_turn_id"
            )
        )
    if steer_request.source_thread_id != source_thread_id:
        findings.append(
            Finding(
                steer_request.seq, "turn/steer must use the active source_thread_id"
            )
        )

    completion = notification(
        frames, "turn/completed", frames.index(steer_response) + 1, findings
    )
    if completion is None:
        return findings
    completion_index, completion_notification = completion
    if (
        active_turn_id is not None
        and completion_notification.codex_turn_id != active_turn_id
    ):
        findings.append(
            Finding(
                completion_notification.seq, "turn/completed is not for the active turn"
            )
        )
    for frame in frames[frames.index(steer_response) + 1 : completion_index]:
        if (
            frame.method == "turn/started"
            and frame.frame_kind == "notification"
            and frame.codex_turn_id == active_turn_id
        ):
            findings.append(
                Finding(frame.seq, "turn/steer must not start a second turn")
            )

    fork_pair = matching_pair(frames, "thread/fork", completion_index + 1, findings)
    if fork_pair is None:
        return findings
    fork_request, fork_response = fork_pair
    if fork_request.source_thread_id != source_thread_id:
        findings.append(
            Finding(
                fork_request.seq,
                "thread/fork must identify the completed source_thread_id",
            )
        )
    new_thread_id = require(
        fork_response.new_thread_id,
        "thread/fork response new_thread_id",
        fork_response,
        findings,
    )
    if fork_response.forked_from_id != source_thread_id:
        findings.append(
            Finding(
                fork_response.seq,
                "thread/fork response forked_from_id must identify the source thread",
            )
        )
    fork_started = notification(
        frames, "thread/started", frames.index(fork_response) + 1, findings
    )
    if fork_started is None or new_thread_id is None:
        return findings
    _, fork_notification = fork_started
    if (
        fork_notification.thread_id != new_thread_id
        or new_thread_id == source_thread_id
    ):
        findings.append(
            Finding(
                fork_notification.seq,
                "forked thread/started must have a distinct outer thread_id",
            )
        )
    if fork_notification.forked_from_id != source_thread_id:
        findings.append(
            Finding(
                fork_notification.seq,
                "forked thread/started must retain forked_from_id",
            )
        )
    if (
        fork_notification.session_id != fork_response.session_id
        or fork_notification.session_id is None
    ):
        findings.append(
            Finding(
                fork_notification.seq,
                "forked thread/started must retain the fork response session_id",
            )
        )
    return findings


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", help="trace bundle directory or trace.jsonl")
    args = parser.parse_args(argv)
    try:
        findings = validate(events(trace_path(args.input)))
    except TraceInputError as error:
        print(f"lecture-2-trace-check: error: {error}", file=sys.stderr)
        return 2
    if findings:
        for finding in findings:
            print(finding.render())
        return 1
    print("lecture-2 protocol: accepted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
