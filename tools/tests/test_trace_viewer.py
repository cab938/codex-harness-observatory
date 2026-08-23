import contextlib
import io
import json
import pathlib
import tempfile
import threading
import unittest
import urllib.request

from tools import trace_viewer


FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "teaching_trace.jsonl"
BROKEN_FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "broken_trace.jsonl"


class TraceViewerTest(unittest.TestCase):
    def run_viewer(self, *arguments):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            code = trace_viewer.main([str(FIXTURE), *arguments])
        return code, output.getvalue()

    def test_timeline_preserves_raw_sequence_and_hides_contents(self):
        code, output = self.run_viewer("--details")
        self.assertEqual(code, 0)
        self.assertEqual([line.split()[0] for line in output.splitlines()], [str(number) for number in range(1, 35)])
        self.assertIn('"prompt":"<redacted>"', output)
        self.assertNotIn("sensitive child result", output)

    def test_filters_support_step_and_repeatable_correlation(self):
        code, output = self.run_viewer("--harness-only", "--category", "decision", "--correlation", "guardian_review_id=review-7", "--correlation", "tool_call_id=tool-9")
        self.assertEqual(code, 0)
        self.assertEqual(len(output.splitlines()), 2)
        self.assertIn("phase=requested", output)
        self.assertIn("phase=completed", output)

    def test_summary_counts_and_matched_durations(self):
        code, output = self.run_viewer("--summary")
        self.assertEqual(code, 0)
        self.assertIn("harness_event_observed: 30", output)
        self.assertIn("decision.guardian_review: 2", output)
        self.assertIn("decision.guardian_review: 1 matched, total=20ms", output)
        self.assertIn("tool.tool_dispatch: 1 matched, total=15ms", output)
        self.assertIn("multi_agent.agent_spawn: 1 matched, total=10ms", output)

    def test_check_accepts_the_complete_teaching_fixture(self):
        code, output = self.run_viewer("--check")
        self.assertEqual(code, 0)
        self.assertEqual(output, "trace integrity: clean\n")

    def test_check_reports_ordering_orphans_and_required_metadata_without_details(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            code = trace_viewer.main([str(BROKEN_FIXTURE), "--check"])
        self.assertEqual(code, 1)
        report = output.getvalue()
        self.assertIn("seq=2: seq must be strictly after prior seq=3", report)
        self.assertIn("seq=2: orphan terminal supervision.hook_invocation completed", report)
        self.assertIn("seq=3: event requires a non-empty step_id", report)
        self.assertIn("seq=4: event requires correlation guardian_review_id", report)
        self.assertIn("unfinished opening context.step_context_capture", report)
        self.assertNotIn("not printed", report)

    def test_eviction_skipped_is_a_standalone_decision_or_terminal_when_requested(self):
        def eviction(seq, phase, task_thread_id):
            return {
                "seq": seq,
                "payload": {
                    "type": "harness_event_observed",
                    "event": {
                        "category": "multi_agent",
                        "name": "agent_eviction",
                        "phase": phase,
                        "correlations": {
                            "root_thread_id": "thread-root",
                            "task_thread_id": task_thread_id,
                        },
                        "details": {"implementation": "v2"},
                    },
                },
            }

        trace = [
            eviction(1, "skipped", "thread-not-resident"),
            eviction(2, "requested", "thread-raced"),
            eviction(3, "skipped", "thread-raced"),
        ]
        self.assertEqual(trace_viewer.integrity_findings(iter(trace)), [])

    def test_turn_input_disposition_precedes_step_context(self):
        trace = [
            {
                "seq": 1,
                "payload": {
                    "type": "harness_event_observed",
                    "event": {
                        "category": "agent_loop",
                        "name": "turn_input_disposition",
                        "phase": "decided",
                        "outcome": "start",
                    },
                },
            }
        ]
        self.assertEqual(trace_viewer.integrity_findings(iter(trace)), [])

    def test_skipped_approval_requirement_precedes_approval_identity(self):
        trace = [
            {
                "seq": 1,
                "payload": {
                    "type": "harness_event_observed",
                    "event": {
                        "category": "decision",
                        "name": "approval_requirement",
                        "phase": "decided",
                        "step_id": "step-1",
                        "outcome": "skip",
                        "correlations": {"tool_call_id": "tool-1"},
                    },
                },
            }
        ]
        self.assertEqual(trace_viewer.integrity_findings(iter(trace)), [])

    def test_v2_reservation_can_be_correlated_by_requesting_parent(self):
        trace = [
            {
                "seq": phase_index,
                "payload": {
                    "type": "harness_event_observed",
                    "event": {
                        "category": "multi_agent",
                        "name": "agent_residency",
                        "phase": phase,
                        "correlations": {"parent_thread_id": "thread-root"},
                        "details": {"implementation": "v2"},
                    },
                },
            }
            for phase_index, phase in enumerate(("requested", "reserved"), start=1)
        ]
        self.assertEqual(trace_viewer.integrity_findings(iter(trace)), [])

    def test_mailbox_enqueue_without_tool_call_is_a_standalone_fact(self):
        trace = [
            {
                "seq": 1,
                "payload": {
                    "type": "harness_event_observed",
                    "event": {
                        "category": "multi_agent",
                        "name": "agent_message",
                        "phase": "enqueued",
                        "details": {"trigger_turn": True},
                    },
                },
            }
        ]
        self.assertEqual(trace_viewer.integrity_findings(iter(trace)), [])

    def test_malformed_line_reports_its_number(self):
        with tempfile.TemporaryDirectory() as directory:
            trace = pathlib.Path(directory) / "trace.jsonl"
            trace.write_text("\nnot json\n", encoding="utf-8")
            output = io.StringIO()
            with contextlib.redirect_stderr(output):
                code = trace_viewer.main([str(trace), "--check"])
        self.assertEqual(code, 2)
        self.assertIn(":2: malformed JSONL", output.getvalue())

    def test_browser_event_redacts_details_and_exposes_only_payload_reference_metadata(self):
        fixture_events = list(trace_viewer.events(FIXTURE))
        provenance = trace_viewer.viewer_event(fixture_events[2])
        guardian = trace_viewer.viewer_event(fixture_events[9])
        inference = trace_viewer.viewer_event(fixture_events[6])
        child_result = trace_viewer.viewer_event(fixture_events[32])

        self.assertEqual(
            provenance["harness"]["correlations"]["source"],
            "developer_instructions",
        )
        self.assertEqual(guardian["harness"]["details"]["prompt"], "<redacted>")
        self.assertEqual(
            inference["payload_references"],
            [{"field": "request_payload", "path": "payloads/request.json"}],
        )
        self.assertNotIn("message", child_result["payload_metadata"])
        self.assertNotIn("sensitive child result", json.dumps(child_result))

    def test_tail_delivers_initial_and_appended_events_without_losing_order(self):
        with tempfile.TemporaryDirectory() as directory:
            trace = pathlib.Path(directory) / "trace.jsonl"
            trace.write_text(self.raw_event_line(1), encoding="utf-8")
            stopped = threading.Event()
            updates = trace_viewer.tail_updates(
                trace,
                poll_interval=0.001,
                stop_event=stopped,
            )
            self.assertEqual(next(updates)["event"]["seq"], 1)
            with trace.open("a", encoding="utf-8") as stream:
                stream.write(self.raw_event_line(2))
                stream.flush()
            self.assertEqual(next(updates)["event"]["seq"], 2)
            stopped.set()
            updates.close()

    def test_tail_reports_a_malformed_appended_line(self):
        with tempfile.TemporaryDirectory() as directory:
            trace = pathlib.Path(directory) / "trace.jsonl"
            trace.write_text(self.raw_event_line(1), encoding="utf-8")
            stopped = threading.Event()
            updates = trace_viewer.tail_updates(
                trace,
                poll_interval=0.001,
                stop_event=stopped,
            )
            self.assertEqual(next(updates)["kind"], "event")
            with trace.open("a", encoding="utf-8") as stream:
                stream.write("not-json\n")
                stream.flush()
            error = next(updates)
            self.assertEqual(error["kind"], "error")
            self.assertIn("trace.jsonl:2: malformed JSONL", error["message"])

    def test_manifest_and_http_header_expose_safe_stream_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle = pathlib.Path(directory)
            trace = bundle / "trace.jsonl"
            trace.write_text(self.raw_event_line(1), encoding="utf-8")
            (bundle / "manifest.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "trace_id": "trace-demo",
                        "rollout_id": "rollout-demo",
                        "root_thread_id": "thread-root",
                        "started_at_unix_ms": 1000,
                        "raw_event_log": "/private/location/trace.jsonl",
                        "payloads_dir": "/private/location/payloads",
                    }
                ),
                encoding="utf-8",
            )
            server = trace_viewer.make_viewer_server(trace, "127.0.0.1", 0)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                host, port = server.server_address[:2]
                with urllib.request.urlopen(f"http://{host}:{port}/api/header") as response:
                    metadata = json.load(response)
                    self.assertEqual(response.headers["Content-Type"], "application/json; charset=utf-8")
                with urllib.request.urlopen(f"http://{host}:{port}/") as response:
                    page = response.read().decode("utf-8")
                    self.assertIn("default-src 'self'", response.headers["Content-Security-Policy"])
                self.assertEqual(metadata["trace_id"], "trace-demo")
                self.assertEqual(metadata["raw_schema_version"], 2)
                self.assertEqual(metadata["raw_event_log"], "trace.jsonl")
                self.assertEqual(metadata["payloads_dir"], "payloads")
                self.assertNotIn("/private/location", json.dumps(metadata))
                self.assertIn("Harness Observatory", page)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    @staticmethod
    def raw_event_line(seq):
        return json.dumps(
            {
                "schema_version": 2,
                "seq": seq,
                "wall_time_unix_ms": 1000 + seq,
                "rollout_id": "rollout-demo",
                "thread_id": "thread-root",
                "codex_turn_id": "turn-1",
                "payload": {"type": "codex_turn_started", "codex_turn_id": "turn-1"},
            },
            separators=(",", ":"),
        ) + "\n"


if __name__ == "__main__":
    unittest.main()
