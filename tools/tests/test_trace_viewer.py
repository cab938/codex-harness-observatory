import contextlib
import io
import pathlib
import tempfile
import unittest

from tools import trace_viewer


FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "teaching_trace.jsonl"


class TraceViewerTest(unittest.TestCase):
    def run_viewer(self, *arguments):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            code = trace_viewer.main([str(FIXTURE), *arguments])
        return code, output.getvalue()

    def test_timeline_preserves_raw_sequence_and_hides_contents(self):
        code, output = self.run_viewer("--details")
        self.assertEqual(code, 0)
        self.assertEqual([line.split()[0] for line in output.splitlines()], [str(number) for number in range(1, 13)])
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
        self.assertIn("harness_event_observed: 8", output)
        self.assertIn("decision.guardian_review: 2", output)
        self.assertIn("decision.guardian_review: 1 matched, total=20ms", output)
        self.assertIn("tool.patch_commit: 1 matched, total=10ms", output)
        self.assertIn("multi_agent.agent_spawn: 1 matched, total=10ms", output)

    def test_malformed_line_reports_its_number(self):
        with tempfile.TemporaryDirectory() as directory:
            trace = pathlib.Path(directory) / "trace.jsonl"
            trace.write_text("\nnot json\n", encoding="utf-8")
            output = io.StringIO()
            with contextlib.redirect_stderr(output):
                code = trace_viewer.main([str(trace)])
        self.assertEqual(code, 2)
        self.assertIn(":2: malformed JSONL", output.getvalue())


if __name__ == "__main__":
    unittest.main()
