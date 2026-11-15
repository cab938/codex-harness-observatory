import json
import pathlib
import tempfile
import unittest

from observatory import trace_compare
from observatory import trace_viewer
from observatory.lecture_2_app_server_trace_check import frame_from, request_response_pairs


FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "teaching_trace.jsonl"


class TraceCompareTest(unittest.TestCase):
    def test_checks_legacy_payload_availability_and_preserves_source(self):
        original = FIXTURE.read_bytes()
        report = trace_compare.inspect_capture(str(FIXTURE))
        self.assertEqual(report["findings"], [])
        self.assertEqual(len(report["payload_sha256"]), 3)
        self.assertEqual(FIXTURE.read_bytes(), original)
        with tempfile.TemporaryDirectory() as directory:
            trace = pathlib.Path(directory) / "trace.jsonl"
            trace.write_bytes(original)
            missing = trace_compare.inspect_capture(str(trace))
            self.assertEqual(len(missing["findings"]), 3)
            self.assertTrue(
                all(
                    "artifact is unavailable" in finding
                    for finding in missing["findings"]
                )
            )

    def test_comparison_uses_evidence_families_and_overlap_not_event_counts(self):
        baseline = trace_compare.inspect_capture(str(FIXTURE))
        baseline.update(
            run_ended=True,
            desktop_mcp_tool_call=True,
            roots=2,
            child_threads=2,
            overlapping_root_turns=True,
            desktop_roots=2,
            delegated_children=2,
            overlapping_desktop_root_turns=True,
        )
        candidate = {
            **baseline,
            "events": 9999,
            "event_families": {
                key: count * 2 for key, count in baseline["event_families"].items()
            },
        }
        self.assertEqual(
            trace_compare.compare_captures(baseline, candidate, "review"), []
        )
        candidate["overlapping_desktop_root_turns"] = False
        candidate["event_families"].pop("raw:inference_started")
        findings = trace_compare.compare_captures(baseline, candidate, "review")
        self.assertEqual(len(findings), 2)
        self.assertIn(
            "candidate: missing evidence family raw:inference_started", findings
        )

    def test_wire_pairing_scopes_ids_to_connections_and_allows_completed_id_reuse(self):
        frames = []
        for connection, direction, kind in (
            ("a", "client_to_server", "request"),
            ("b", "client_to_server", "request"),
            ("a", "server_to_client", "response"),
            ("a", "client_to_server", "request"),
            ("b", "server_to_client", "response"),
            ("a", "server_to_client", "response"),
        ):
            frames.append(
                frame_from(
                    {
                        "seq": len(frames) + 1,
                        "payload": {
                            "type": "app_server_frame_observed",
                            "connection_id": connection,
                            "direction": direction,
                            "frame_kind": kind,
                            "method": "thread/read",
                            "request_id": "1",
                        },
                    }
                )
            )
        self.assertEqual(request_response_pairs(frames), ({}, []))

    def test_schema_six_pairs_exchange_identity_typed_ids_errors_and_reuse(self):
        from observatory.lecture_2_app_server_trace_check import paired_frames

        def frame(seq, kind, direction, request_id, exchange, method="thread/read"):
            return frame_from(
                {
                    "schema_version": 6,
                    "seq": seq,
                    "payload": {
                        "type": "app_server_frame_observed",
                        "connection_id": "same-name",
                        "connection_instance_id": "instance",
                        "exchange_id": exchange,
                        "direction": direction,
                        "frame_kind": kind,
                        "request_id": request_id,
                        "method": method,
                    },
                }
            )

        frames = [
            frame(1, "request", "client_to_server", 1, "number"),
            frame(2, "request", "client_to_server", "1", "string"),
            frame(3, "error", "server_to_client", "1", "string", None),
            frame(4, "response", "server_to_client", 1, "number"),
            frame(5, "request", "client_to_server", 1, "reused"),
            frame(6, "response", "server_to_client", 1, None),
            frame(7, "response", "server_to_client", 1, "reused"),
        ]
        pairs, pending, findings = paired_frames(frames)
        self.assertEqual(findings, [])
        self.assertEqual(pending, {})
        self.assertEqual(
            {seq: other.seq for seq, other in pairs.items()},
            {1: 4, 4: 1, 2: 3, 3: 2, 5: 7, 7: 5},
        )
        self.assertNotIn(6, pairs)
        number = trace_viewer.viewer_event(
            {
                "schema_version": 6,
                "seq": 1,
                "payload": {
                    "type": "mcp_frame_observed",
                    "direction": "client_to_server",
                    "frame_kind": "request",
                    "request_id": 1,
                    "connection_instance_id": "instance",
                    "exchange_id": "mcp-exchange",
                },
            }
        )
        self.assertEqual(number["wire_pairing"]["basis"], "exchange")
        self.assertEqual(number["wire_pairing"]["request_id"], 1)
        self.assertEqual(
            trace_viewer.viewer_event(
                {
                    "schema_version": 6,
                    "seq": 2,
                    "payload": {
                        "type": "mcp_frame_observed",
                        "direction": "server_to_client",
                        "frame_kind": "response",
                        "request_id": 1,
                        "connection_instance_id": "instance",
                        "exchange_id": None,
                    },
                }
            )["wire_pairing"]["basis"],
            "unknown",
        )

    def test_overlapping_legacy_id_reuse_stays_unpaired_then_recovers(self):
        from observatory.lecture_2_app_server_trace_check import paired_frames

        frames = []
        for seq, kind in enumerate(
            ("request", "request", "response", "response", "request", "response"), 1
        ):
            frames.append(
                frame_from(
                    {
                        "schema_version": 5,
                        "seq": seq,
                        "payload": {
                            "type": "app_server_frame_observed",
                            "connection_id": "c",
                            "request_id": 0,
                            "method": "thread/read",
                            "frame_kind": kind,
                            "direction": "client_to_server"
                            if kind == "request"
                            else "server_to_client",
                        },
                    }
                )
            )
        pairs, _, findings = paired_frames(frames)
        self.assertEqual({seq: other.seq for seq, other in pairs.items()}, {5: 6, 6: 5})
        self.assertEqual(len(findings), 1)

    def test_overlap_is_derived_from_root_turn_intervals(self):
        with tempfile.TemporaryDirectory() as directory:
            trace = pathlib.Path(directory) / "trace.jsonl"

            def event(root, thread, turn, kind, **fields):
                return {
                    "schema_version": 4,
                    "task_root_thread_id": root,
                    "thread_id": thread,
                    "codex_turn_id": turn,
                    "payload": {"type": kind, **fields},
                }

            start_a = event("a", "a", "turn-a", "codex_turn_started", thread_id="a")
            end_a = event("a", "a", "turn-a", "codex_turn_ended", status="completed")
            start_b = event("b", "b", "turn-b", "codex_turn_started", thread_id="b")
            end_b = event("b", "b", "turn-b", "codex_turn_ended", status="completed")
            children = [
                event(
                    "a",
                    child,
                    None,
                    "thread_started",
                    thread_id=child,
                    agent_path="/a/" + child,
                )
                for child in ("review-evidence", "review-accessibility")
            ]
            for turns, expected_overlap in (
                ([start_a, *children, start_b, end_b, end_a], True),
                ([start_a, *children, end_a, start_b, end_b], False),
            ):
                raw = [
                    event(None, None, None, "run_started", trace_id="demo"),
                    *turns,
                    event(None, None, None, "run_ended", status="completed"),
                ]
                for seq, record in enumerate(raw, 1):
                    record["seq"] = seq
                trace.write_text("\n".join(json.dumps(record) for record in raw))
                report = trace_compare.inspect_capture(str(trace))
                self.assertEqual(report["findings"], [])
                self.assertEqual(
                    (
                        report["roots"],
                        report["child_threads"],
                        report["overlapping_root_turns"],
                    ),
                    (2, 2, expected_overlap),
                )

    def test_ephemeral_overlap_is_not_independent_desktop_chat_overlap(self):
        with tempfile.TemporaryDirectory() as directory:
            trace = pathlib.Path(directory) / "trace.jsonl"
            records = []
            for number, ephemeral in enumerate((False, True), 1):
                request_path = f"start-{number}.json"
                (trace.parent / request_path).write_text(
                    json.dumps({"params": {"ephemeral": ephemeral}})
                )
                for kind, direction, fields in (
                    (
                        "request",
                        "client_to_server",
                        {"frame_payload": {"path": request_path}},
                    ),
                    (
                        "response",
                        "server_to_client",
                        {"new_thread_id": f"root-{number}"},
                    ),
                ):
                    records.append(
                        {
                            "payload": {
                                "type": "app_server_frame_observed",
                                "connection_id": "desktop",
                                "request_id": str(number),
                                "method": "thread/start",
                                "frame_kind": kind,
                                "direction": direction,
                                **fields,
                            }
                        }
                    )
            for kind, number in (
                ("started", 1),
                ("started", 2),
                ("ended", 2),
                ("ended", 1),
            ):
                root = f"root-{number}"
                records.append(
                    {
                        "task_root_thread_id": root,
                        "thread_id": root,
                        "codex_turn_id": f"turn-{number}",
                        "payload": {"type": f"codex_turn_{kind}"},
                    }
                )
            for seq, record in enumerate(records, 1):
                record["schema_version"] = 4
                record["seq"] = seq
            trace.write_text("\n".join(json.dumps(record) for record in records))
            report = trace_compare.inspect_capture(str(trace))
            self.assertEqual(report["findings"], [])
            self.assertEqual(
                (
                    report["desktop_roots"],
                    report["ephemeral_roots"],
                    report["overlapping_root_turns"],
                    report["overlapping_desktop_root_turns"],
                ),
                (1, 1, True, False),
            )

    def test_unknown_events_remain_visible_without_weakening_schema_validation(self):
        event = {
            "schema_version": 5,
            "seq": 1,
            "payload": {"type": "new_native_event", "kind": "teaching"},
        }
        parsed = trace_viewer.parse_event_line(
            json.dumps(event),
            source=FIXTURE,
            line_number=1,
            previous_seq=None,
            enforce_sequence=True,
        )
        self.assertEqual(
            trace_viewer.viewer_event(parsed, show_content=True)["payload"],
            event["payload"],
        )


if __name__ == "__main__":
    unittest.main()
