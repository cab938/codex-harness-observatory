import contextlib
import copy
import io
import pathlib
import unittest

from tools import lecture_2_app_server_trace_check as lecture_check
from tools.trace_viewer import events


FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "lecture_2_app_server_trace"


class LectureTwoAppServerTraceCheckTest(unittest.TestCase):
    def test_fixture_is_accepted_from_bundle_path(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = lecture_check.main([str(FIXTURE)])

        self.assertEqual(code, 0)
        self.assertEqual(output.getvalue(), "lecture-2 protocol: accepted\n")

    def test_steer_does_not_open_a_second_turn(self):
        trace = list(events(FIXTURE / "trace.jsonl"))
        second_started = copy.deepcopy(trace[5])
        second_started["seq"] = 10
        trace.insert(10, second_started)

        findings = lecture_check.validate(trace)

        self.assertEqual(
            [finding.message for finding in findings],
            ["turn/steer must not start a second turn"],
        )

    def test_server_initiated_request_can_reuse_a_client_request_id(self):
        trace = list(events(FIXTURE / "trace.jsonl"))
        server_request = copy.deepcopy(trace[0])
        server_request["seq"] = 15
        server_request["payload"].update(
            direction="server_to_client",
            method="item/commandExecution/requestApproval",
        )
        client_response = copy.deepcopy(trace[1])
        client_response["seq"] = 16
        client_response["payload"].update(
            direction="client_to_server",
            method="item/commandExecution/requestApproval",
        )
        trace.extend([server_request, client_response])

        self.assertEqual(lecture_check.validate(trace), [])


if __name__ == "__main__":
    unittest.main()
