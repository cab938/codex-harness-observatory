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

    def test_safe_event_projection_redacts_details_and_exposes_only_payload_reference_metadata(self):
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

    def test_mcp_wire_frames_support_teaching_filters_and_safe_metadata(self):
        wire_event = {
            "schema_version": 3,
            "seq": 1,
            "wall_time_unix_ms": 1200,
            "rollout_id": "demo-rollout",
            "thread_id": "thread-1",
            "codex_turn_id": "turn-1",
            "payload": {
                "type": "mcp_frame_observed",
                "server_name": "filesystem",
                "transport": "stdio",
                "direction": "server_to_client",
                "frame_kind": "response",
                "method": "tools/call",
                "request_id": "7",
                "mcp_call_id": "mcp-call-1",
                "frame_payload": {
                    "raw_payload_id": "raw_payload:1",
                    "kind": "mcp_frame",
                    "path": "payloads/1.json",
                },
            },
        }
        filters = trace_viewer.Filters(
            payload_type=set(),
            thread=set(),
            turn=set(),
            step=set(),
            category={"mcp"},
            name={"tools/call"},
            phase={"response"},
            correlations=(("mcp_call_id", "mcp-call-1"),),
            harness_only=False,
        )

        self.assertTrue(trace_viewer.matches(wire_event, filters))
        browser_event = trace_viewer.viewer_event(wire_event)
        self.assertEqual(browser_event["payload_metadata"]["method"], "tools/call")
        self.assertEqual(browser_event["payload_metadata"]["direction"], "server_to_client")
        self.assertEqual(browser_event["payload_metadata"]["server_name"], "filesystem")
        self.assertEqual(
            browser_event["payload_references"],
            [
                {
                    "field": "frame_payload",
                    "path": "payloads/1.json",
                    "raw_payload_id": "raw_payload:1",
                    "kind": "mcp_frame",
                }
            ],
        )

    def test_app_server_metadata_is_safe_searchable_and_pairable(self):
        def frame(seq, direction, frame_kind, request_id, **extra):
            return {
                "schema_version": 4,
                "seq": seq,
                "wall_time_unix_ms": 1000 + seq,
                "rollout_id": "shared-run",
                "thread_id": "thread-outer",
                "codex_turn_id": "turn-outer",
                "payload": {
                    "type": "app_server_frame_observed",
                    "connection_id": "connection-1",
                    "request_id": request_id,
                    "method": "thread/start",
                    "direction": direction,
                    "frame_kind": frame_kind,
                    "session_id": "session-1",
                    "source_thread_id": "source-thread-1",
                    "new_thread_id": "new-thread-1",
                    "item_id": "item-1",
                    "forked_from_id": "fork-1",
                    "frame_payload": {"path": "payloads/frame.json"},
                    **extra,
                },
            }

        request = frame(1, "client_to_server", "request", "request-1")
        response = frame(2, "server_to_client", "response", "request-1")
        server_request = frame(3, "server_to_client", "request", "request-2")
        server_response = frame(4, "client_to_server", "response", "request-2")

        projected = trace_viewer.viewer_event(request)
        self.assertEqual(
            {
                key: projected["payload_metadata"][key]
                for key in (
                    "connection_id", "request_id", "method", "direction", "frame_kind",
                    "session_id", "source_thread_id", "new_thread_id", "item_id", "forked_from_id",
                )
            },
            {
                "connection_id": "connection-1",
                "request_id": "request-1",
                "method": "thread/start",
                "direction": "client_to_server",
                "frame_kind": "request",
                "session_id": "session-1",
                "source_thread_id": "source-thread-1",
                "new_thread_id": "new-thread-1",
                "item_id": "item-1",
                "forked_from_id": "fork-1",
            },
        )
        self.assertEqual(projected["app_server_pairing"]["role"], "request")
        self.assertEqual(
            projected["app_server_pairing"]["key"],
            "connection-1\x1frequest-1",
        )
        self.assertNotIn("frame_payload", projected["payload_metadata"])
        self.assertNotIn("payload", projected)

        response_projected = trace_viewer.viewer_event(response)
        server_request_projected = trace_viewer.viewer_event(server_request)
        server_response_projected = trace_viewer.viewer_event(server_response)
        self.assertEqual(response_projected["app_server_pairing"]["role"], "response")
        self.assertEqual(server_request_projected["app_server_pairing"]["role"], "request")
        self.assertEqual(server_response_projected["app_server_pairing"]["role"], "response")

        filters = trace_viewer.Filters(
            payload_type=set(),
            thread=set(),
            turn=set(),
            step=set(),
            category={"app_server"},
            name={"thread/start"},
            phase={"request"},
            correlations=(("source_thread_id", "source-thread-1"),),
            harness_only=False,
        )
        self.assertTrue(trace_viewer.matches(request, filters))
        self.assertFalse(trace_viewer.matches(response, filters))

    def test_teaching_mode_exposes_full_event_content_and_names_internal_patch_tool(self):
        fixture_events = list(trace_viewer.events(FIXTURE))
        guardian = trace_viewer.viewer_event(fixture_events[9], show_content=True)
        patch = trace_viewer.viewer_event(fixture_events[11], show_content=True)

        self.assertEqual(guardian["harness"]["details"]["prompt"], "secret")
        self.assertEqual(guardian["payload"]["event"]["details"]["prompt"], "secret")
        self.assertEqual(patch["tool"]["name"], "apply_patch")
        self.assertEqual(patch["tool"]["kind"], "apply_patch")
        self.assertEqual(patch["tool"]["classification"], "internal_codex_tool")
        self.assertIn("not shell or MCP", patch["tool"]["classification_label"])

        code_cell = trace_viewer.viewer_event(
            {
                "schema_version": 2,
                "seq": 99,
                "wall_time_unix_ms": 1200,
                "rollout_id": "demo-rollout",
                "payload": {
                    "type": "code_cell_ended",
                    "runtime_cell_id": "cell-4",
                    "status": "completed",
                },
            },
            show_content=True,
        )
        self.assertEqual(code_cell["tool"]["name"], "code_mode")
        self.assertEqual(code_cell["tool"]["call_id"], "cell-4")

    def test_task_ledger_tracks_concurrent_roots_children_and_session_frames(self):
        session_frame = self.shared_event(
            1,
            {
                "type": "app_server_frame_observed",
                "direction": "client_to_server",
                "frame_kind": "request",
                "method": "initialize",
            },
            task_root_thread_id=None,
        )
        root_a_started = self.shared_event(
            2,
            {
                "type": "thread_started",
                "thread_id": "root-a",
                "agent_path": "/root/a",
            },
            task_root_thread_id="root-a",
            thread_id="root-a",
        )
        root_b_started = self.shared_event(
            3,
            {
                "type": "thread_started",
                "thread_id": "root-b",
                "agent_path": "/root/b",
            },
            include_task_root=False,
            thread_id="root-b",
        )
        root_b_started["taskRootThreadId"] = "root-b"
        child_a_started = self.shared_event(
            4,
            {
                "type": "thread_started",
                "thread_id": "child-a",
                "agent_path": "/root/a/worker",
            },
            task_root_thread_id="root-a",
            thread_id="child-a",
        )
        child_a_spawned = self.shared_event(
            5,
            {
                "type": "harness_event_observed",
                "event": {
                    "category": "multi_agent",
                    "name": "agent_spawn",
                    "phase": "completed",
                    "correlations": {
                        "parent_thread_id": "root-a",
                        "child_thread_id": "child-a",
                        "tool_call_id": "spawn-a",
                    },
                },
            },
            task_root_thread_id="root-a",
            thread_id="root-a",
        )
        root_a_ended = self.shared_event(
            6,
            {"type": "thread_ended", "thread_id": "root-a", "status": "completed"},
            task_root_thread_id="root-a",
            thread_id="root-a",
        )
        root_b_ended = self.shared_event(
            7,
            {"type": "thread_ended", "thread_id": "root-b", "status": "failed"},
            task_root_thread_id="root-b",
            thread_id="root-b",
        )

        ledger = trace_viewer.TaskLedger()
        session_task = ledger.apply(session_frame)
        ledger.apply(root_a_started)
        root_b_task = ledger.apply(root_b_started)
        for event in (child_a_started, child_a_spawned, root_a_ended, root_b_ended):
            ledger.apply(event)

        self.assertEqual(session_task["scope"], "session")
        self.assertIsNone(session_task["rootThreadId"])
        self.assertEqual(root_b_task["rootThreadId"], "root-b")
        self.assertEqual(root_b_task["concurrency"]["activeTaskCount"], 2)

        metadata = ledger.metadata()
        tasks = {task["rootThreadId"]: task for task in metadata["tasks"]}
        self.assertEqual(tasks["root-a"]["status"], "completed")
        self.assertEqual(tasks["root-b"]["status"], "failed")
        child = next(
            thread
            for thread in tasks["root-a"]["threads"]
            if thread["threadId"] == "child-a"
        )
        self.assertEqual(child["parentThreadId"], "root-a")
        self.assertEqual(child["agentPath"], "/root/a/worker")
        self.assertEqual(
            metadata["concurrency"],
            {
                "activeTaskCount": 0,
                "activeRootThreadIds": [],
                "maxActiveTaskCount": 2,
            },
        )

    def test_tail_preserves_order_and_assigns_legacy_events_to_one_task_root(self):
        legacy_events = [
            self.shared_event(
                1,
                {
                    "type": "thread_started",
                    "thread_id": "legacy-root",
                    "agent_path": "/root",
                },
                include_task_root=False,
                thread_id="legacy-root",
            ),
            self.shared_event(
                2,
                {
                    "type": "thread_started",
                    "thread_id": "legacy-child",
                    "agent_path": "/root/child",
                },
                include_task_root=False,
                thread_id="legacy-child",
            ),
            self.shared_event(
                3,
                {
                    "type": "harness_event_observed",
                    "event": {
                        "category": "multi_agent",
                        "name": "agent_spawn",
                        "phase": "completed",
                        "correlations": {
                            "parent_thread_id": "legacy-root",
                            "child_thread_id": "legacy-child",
                            "tool_call_id": "legacy-spawn",
                        },
                    },
                },
                include_task_root=False,
                thread_id="legacy-root",
            ),
            self.shared_event(
                4,
                {
                    "type": "thread_ended",
                    "thread_id": "legacy-root",
                    "status": "completed",
                },
                include_task_root=False,
                thread_id="legacy-root",
            ),
        ]
        with tempfile.TemporaryDirectory() as directory:
            trace = pathlib.Path(directory) / "trace.jsonl"
            trace.write_text(
                "".join(json.dumps(event, separators=(",", ":")) + "\n" for event in legacy_events),
                encoding="utf-8",
            )
            updates = list(trace_viewer.tail_updates(trace, follow=False))
            header = trace_viewer.manifest_metadata(trace)

        delivered = [update["event"] for update in updates]
        self.assertEqual([event["seq"] for event in delivered], [1, 2, 3, 4])
        self.assertEqual(
            [event["task_root_thread_id"] for event in delivered],
            ["legacy-root", "legacy-root", "legacy-root", "legacy-root"],
        )
        self.assertEqual(delivered[1]["task"]["agentPath"], "/root/child")
        self.assertEqual(delivered[3]["task"]["status"], "completed")
        self.assertEqual(header["tasks"][0]["rootThreadId"], "legacy-root")

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
                self.assertEqual(metadata["content_mode"], "full")
                self.assertTrue(metadata["full_content"])
                self.assertNotIn("/private/location", json.dumps(metadata))
                self.assertIn("Harness Observatory", page)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    def test_teaching_server_opens_bundle_payload_artifacts(self):
        server = trace_viewer.make_viewer_server(
            FIXTURE,
            "127.0.0.1",
            0,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            host, port = server.server_address[:2]
            with urllib.request.urlopen(f"http://{host}:{port}/api/header") as response:
                metadata = json.load(response)
            with urllib.request.urlopen(
                f"http://{host}:{port}/api/artifact?path=payloads%2Ftool-input.json"
            ) as response:
                artifact = json.load(response)
            with urllib.request.urlopen(
                f"http://{host}:{port}/api/stream?after=9",
                timeout=2,
            ) as response:
                self.assertEqual(response.readline().decode("utf-8"), "id: 10\n")
                self.assertEqual(response.readline().decode("utf-8"), "event: trace\n")
                streamed = json.loads(response.readline().decode("utf-8")[6:])

            self.assertEqual(metadata["content_mode"], "full")
            self.assertTrue(metadata["full_content"])
            self.assertEqual(artifact["path"], "payloads/tool-input.json")
            self.assertEqual(artifact["content"]["tool_name"], "apply_patch")
            self.assertIn("*** Update File: hello.txt", artifact["content"]["payload"]["input"])
            self.assertEqual(
                streamed["event"]["payload"]["event"]["details"]["prompt"],
                "secret",
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_header_discovers_new_task_roots_in_a_growing_shared_ledger(self):
        with tempfile.TemporaryDirectory() as directory:
            trace = pathlib.Path(directory) / "trace.jsonl"
            root_a = self.shared_event(
                1,
                {
                    "type": "thread_started",
                    "thread_id": "root-a",
                    "agent_path": "/root/a",
                },
                task_root_thread_id="root-a",
                thread_id="root-a",
            )
            root_b = self.shared_event(
                2,
                {
                    "type": "thread_started",
                    "thread_id": "root-b",
                    "agent_path": "/root/b",
                },
                task_root_thread_id="root-b",
                thread_id="root-b",
            )
            trace.write_text(json.dumps(root_a, separators=(",", ":")) + "\n", encoding="utf-8")
            server = trace_viewer.make_viewer_server(trace, "127.0.0.1", 0)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                host, port = server.server_address[:2]
                with urllib.request.urlopen(f"http://{host}:{port}/api/header") as response:
                    initial = json.load(response)
                with trace.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(root_b, separators=(",", ":")) + "\n")
                    stream.flush()
                with urllib.request.urlopen(f"http://{host}:{port}/api/header") as response:
                    updated = json.load(response)

                self.assertEqual(
                    [task["rootThreadId"] for task in initial["tasks"]],
                    ["root-a"],
                )
                self.assertEqual(
                    [task["rootThreadId"] for task in updated["tasks"]],
                    ["root-a", "root-b"],
                )
                self.assertEqual(updated["concurrency"]["activeTaskCount"], 2)
                self.assertEqual(updated["concurrency"]["maxActiveTaskCount"], 2)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    def test_server_defaults_to_full_content_with_explicit_redaction_opt_in(self):
        parser = trace_viewer.build_parser()
        self.assertTrue(parser.parse_args([str(FIXTURE), "--serve"]).show_content)
        self.assertFalse(
            parser.parse_args([str(FIXTURE), "--serve", "--redact-content"]).show_content
        )

    def test_waiting_server_binds_before_the_first_bundle_exists(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            server = trace_viewer.make_viewer_server(
                root,
                "127.0.0.1",
                0,
                wait_for_bundle=True,
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                host, port = server.server_address[:2]
                with urllib.request.urlopen(f"http://{host}:{port}/api/header") as response:
                    waiting = json.load(response)
                self.assertEqual(waiting["stream_mode"], "waiting_for_trace_bundle")

                bundle = root / "trace-demo"
                bundle.mkdir()
                (bundle / "trace.jsonl").write_text(self.raw_event_line(1), encoding="utf-8")
                (bundle / "manifest.json").write_text(
                    json.dumps({"trace_id": "trace-after-start"}),
                    encoding="utf-8",
                )

                with urllib.request.urlopen(f"http://{host}:{port}/api/header") as response:
                    active = json.load(response)
                self.assertEqual(active["trace_id"], "trace-after-start")
                self.assertEqual(active["stream_mode"], "append_only_jsonl")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    def test_discovery_prefers_primary_task_over_lexically_first_subagent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)

            def write_bundle(name, trace_id, started_at, session_source):
                bundle = root / name
                payloads = bundle / "payloads"
                payloads.mkdir(parents=True)
                (bundle / "manifest.json").write_text(
                    json.dumps(
                        {
                            "trace_id": trace_id,
                            "started_at_unix_ms": started_at,
                        }
                    ),
                    encoding="utf-8",
                )
                (payloads / "1.json").write_text(
                    json.dumps({"session_source": session_source}),
                    encoding="utf-8",
                )
                events = [
                    json.loads(self.raw_event_line(1)),
                    {
                        "schema_version": 2,
                        "seq": 2,
                        "wall_time_unix_ms": started_at,
                        "rollout_id": trace_id,
                        "thread_id": trace_id,
                        "codex_turn_id": None,
                        "payload": {
                            "type": "thread_started",
                            "thread_id": trace_id,
                            "metadata_payload": {"path": "payloads/1.json"},
                        },
                    },
                ]
                (bundle / "trace.jsonl").write_text(
                    "".join(
                        json.dumps(event, separators=(",", ":")) + "\n"
                        for event in events
                    ),
                    encoding="utf-8",
                )
                return bundle / "trace.jsonl"

            write_bundle(
                "trace-a-guardian",
                "guardian",
                1001,
                {"subagent": {"other": "guardian"}},
            )
            primary = write_bundle("trace-z-primary", "primary", 1000, "vscode")

            self.assertEqual(trace_viewer.discover_trace(root), primary)

    @staticmethod
    def shared_event(
        seq,
        payload,
        *,
        task_root_thread_id=None,
        include_task_root=True,
        thread_id=None,
    ):
        event = {
            "schema_version": 4,
            "seq": seq,
            "wall_time_unix_ms": 1000 + seq,
            "rollout_id": "shared-rollout",
            "thread_id": thread_id,
            "codex_turn_id": None,
            "payload": payload,
        }
        if include_task_root:
            event["task_root_thread_id"] = task_root_thread_id
        return event

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
