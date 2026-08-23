import contextlib
import io
import pathlib
import tempfile
import unittest

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

    def test_malformed_line_reports_its_number(self):
        with tempfile.TemporaryDirectory() as directory:
            trace = pathlib.Path(directory) / "trace.jsonl"
            trace.write_text("\nnot json\n", encoding="utf-8")
            output = io.StringIO()
            with contextlib.redirect_stderr(output):
                code = trace_viewer.main([str(trace), "--check"])
        self.assertEqual(code, 2)
        self.assertIn(":2: malformed JSONL", output.getvalue())


if __name__ == "__main__":
    unittest.main()
