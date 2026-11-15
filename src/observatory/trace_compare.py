"""Compare evidence coverage in two captures without comparing model wording or counts."""

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from observatory import trace_viewer as viewer
from observatory.lecture_2_app_server_trace_check import frame_from, paired_frames


def inspect_capture(source: str) -> dict[str, Any]:
    path = viewer.trace_path(source).resolve()
    header = viewer.manifest_metadata(path, recorded=True)
    raw = list(viewer.events(path, enforce_sequence=False))
    findings = [finding.render() for finding in viewer.integrity_findings(iter(raw))]
    families: Counter[str] = Counter()
    payload_roles: set[str] = set()
    payloads: dict[str, str] = {}
    ledger = viewer.TaskLedger()
    starts: dict[tuple[str, str], int] = {}
    intervals: list[tuple[str, int, int]] = []
    root_sources: dict[str, bool] = {}
    delegated_children: set[str] = set()
    desktop_mcp = False
    run_ended = False
    frames = [frame for event in raw if (frame := frame_from(event)) is not None]
    pairs, _, wire_findings = paired_frames(frames)
    findings.extend(finding.render() for finding in wire_findings)
    for expected, event in enumerate(raw, 1):
        seq = event["seq"]
        if seq != expected:
            findings.append(
                f"seq={seq}: expected contiguous writer sequence {expected}"
            )
        ledger.apply(event)
        payload = event["payload"]
        kind = payload["type"]
        item = viewer.harness(event)
        family = (
            f"harness:{item['category']}.{item['name']}:{item['phase']}"
            if item
            else f"raw:{kind}"
        )
        families[family] += 1
        root = event.get("task_root_thread_id")
        thread = event.get("thread_id") or payload.get("thread_id")
        turn = event.get("codex_turn_id") or payload.get("codex_turn_id")
        if (
            4 <= event.get("schema_version", 0) < 6
            and thread
            and not root
            and (item or kind.startswith(("inference_", "tool_call_", "codex_turn_")))
        ):
            findings.append(f"seq={seq}: task event has no task_root_thread_id")
        if kind == "codex_turn_started" and root and root == thread and turn:
            starts[(root, turn)] = seq
        if kind == "codex_turn_ended" and (root, turn) in starts:
            intervals.append((root, starts.pop((root, turn)), seq))
        if kind in {"run_ended", "rollout_ended"}:
            run_ended = True
            if starts:
                findings.append(
                    f"seq={seq}: run closed while root turns were still active"
                )
            if seq != raw[-1]["seq"]:
                findings.append(f"seq={seq}: run ended before the final event")
        if (
            kind == "mcp_frame_observed"
            and payload.get("server_name") == "codex_app"
            and payload.get("method") == "tools/call"
        ):
            desktop_mcp = True
            if event.get("schema_version", 0) < 6 and (
                not root or not thread or not turn or not payload.get("mcp_call_id")
            ):
                findings.append(
                    f"seq={seq}: Desktop MCP tool frame has incomplete task/call attribution"
                )
        if kind == "app_server_frame_observed" and frame_from(event) is None:
            findings.append(
                f"seq={seq}: App Server frame has incomplete protocol metadata"
            )
        frame = frame_from(event)
        if frame and frame.method == "thread/start" and frame.frame_kind == "request":
            response = pairs.get(frame.seq)
            if (
                response
                and response.frame_kind == "response"
                and response.new_thread_id
            ):
                reference = payload.get("frame_payload", {})
                try:
                    packet = viewer.artifact_payload(path, reference.get("path", ""))[
                        "content"
                    ]
                    root_sources[response.new_thread_id] = (
                        packet.get("params", {}).get("ephemeral") is True
                    )
                except (viewer.TraceInputError, AttributeError) as error:
                    findings.append(
                        f"seq={seq}: cannot classify Desktop thread/start: {error}"
                    )
        if (
            item
            and item.get("name") == "agent_spawn"
            and item.get("phase") == "completed"
        ):
            child = (item.get("correlations") or {}).get("child_thread_id")
            if child and item.get("outcome") == "created":
                delegated_children.add(child)
        references = viewer.payload_references(payload, safe_paths=False)
        if isinstance(event.get("_raw_wrapper"), dict):
            references.extend(
                viewer.payload_references(
                    event["_raw_wrapper"]["payload"], safe_paths=False
                )
            )
        for reference in references:
            if "raw_payload_id" not in reference and not reference["field"].endswith(
                ("payload", "payloads")
            ):
                continue
            relative = reference["path"]
            payload_roles.add(reference["field"])
            if relative in payloads:
                continue
            try:
                artifact = viewer.artifact_payload(path, relative)
                payloads[relative] = hashlib.sha256(
                    (path.parent / artifact["path"]).read_bytes()
                ).hexdigest()
            except viewer.TraceInputError as error:
                findings.append(f"seq={seq}: {error}")
    tasks = ledger.metadata()["tasks"]
    overlap = any(
        left[0] != right[0] and max(left[1], right[1]) < min(left[2], right[2])
        for index, left in enumerate(intervals)
        for right in intervals[index + 1 :]
    )
    desktop_roots = {root for root, ephemeral in root_sources.items() if not ephemeral}
    desktop_intervals = [
        interval for interval in intervals if interval[0] in desktop_roots
    ]
    desktop_overlap = any(
        left[0] != right[0] and max(left[1], right[1]) < min(left[2], right[2])
        for index, left in enumerate(desktop_intervals)
        for right in desktop_intervals[index + 1 :]
    )
    return {
        "source": str(path),
        "raw_schema_version": header.get("raw_schema_version"),
        "manifest_schema_version": header.get("manifest_schema_version"),
        "events": len(raw),
        "event_families": dict(sorted(families.items())),
        "payload_roles": sorted(payload_roles),
        "payload_sha256": payloads,
        "roots": len(tasks),
        "child_threads": sum(len(task["threads"]) - 1 for task in tasks),
        "overlapping_root_turns": overlap,
        "desktop_roots": len(desktop_roots),
        "ephemeral_roots": sum(root_sources.values()),
        "delegated_children": len(delegated_children),
        "overlapping_desktop_root_turns": desktop_overlap,
        "desktop_mcp_tool_call": desktop_mcp,
        "run_ended": run_ended,
        "findings": findings,
    }


def compare_captures(
    baseline: dict[str, Any], candidate: dict[str, Any], scenario: str
) -> list[str]:
    findings = [f"baseline: {finding}" for finding in baseline["findings"]]
    findings.extend(f"candidate: {finding}" for finding in candidate["findings"])
    for label, capture in (("baseline", baseline), ("candidate", candidate)):
        if not capture["run_ended"]:
            findings.append(f"{label}: capture has no closing run event")
        if not capture["desktop_mcp_tool_call"]:
            findings.append(f"{label}: no real codex_app tools/call frame")
        if scenario == "review":
            if capture["desktop_roots"] < 2 or capture["delegated_children"] < 2:
                findings.append(
                    f"{label}: review requires two Desktop roots and two successful review agents"
                )
            if not capture["overlapping_desktop_root_turns"]:
                findings.append(f"{label}: no overlap between independent root turns")
    missing_families = set(baseline["event_families"]) - set(
        candidate["event_families"]
    )
    findings.extend(
        f"candidate: missing evidence family {family}"
        for family in sorted(missing_families)
    )
    missing_roles = set(baseline["payload_roles"]) - set(candidate["payload_roles"])
    findings.extend(
        f"candidate: missing full payload role {role}" for role in sorted(missing_roles)
    )
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", help="baseline bundle directory or trace.jsonl")
    parser.add_argument("candidate", help="upgraded bundle directory or trace.jsonl")
    parser.add_argument("--scenario", choices=("build", "review"), required=True)
    parser.add_argument(
        "--report", type=Path, help="write the metadata-only comparison as JSON"
    )
    args = parser.parse_args(argv)
    try:
        baseline = inspect_capture(args.baseline)
        candidate = inspect_capture(args.candidate)
        findings = compare_captures(baseline, candidate, args.scenario)
    except (viewer.TraceInputError, OSError) as error:
        print(f"trace-compare: {error}", file=sys.stderr)
        return 2
    report = {
        "scenario": args.scenario,
        "baseline": baseline,
        "candidate": candidate,
        "findings": findings,
    }
    if args.report:
        args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        "trace parity: clean"
        if not findings
        else "trace parity: " + str(len(findings)) + " finding(s)"
    )
    for finding in findings:
        print(f"  {finding}")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
