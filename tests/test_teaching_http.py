import json
from pathlib import Path
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import urlopen

from observatory.trace_viewer import make_viewer_server


FIXTURE = Path(__file__).parent / "fixtures" / "teaching_trace.jsonl"


class TeachingHTTPTest(unittest.TestCase):
    def test_projection_prefix_and_existing_evidence_are_both_accessible(self):
        server = make_viewer_server(FIXTURE, "127.0.0.1", 0, recorded=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            with urlopen(base + "/api/teaching?until=6", timeout=5) as response:
                prefix = json.load(response)
            self.assertEqual(prefix["requests"], [])
            self.assertEqual(prefix["last_seq"], 6)
            with urlopen(base + "/api/teaching?until=7", timeout=5) as response:
                request = json.load(response)
            self.assertEqual([row["id"] for row in request["requests"]], ["inf-1"])
            with urlopen(base + "/api/artifact?path=payloads/request.json", timeout=5) as response:
                artifact = json.load(response)
            self.assertEqual(artifact["raw_text"], (FIXTURE.parent / "payloads/request.json").read_text())
            with urlopen(base + "/assets/app.js", timeout=5) as response:
                self.assertIn(b"selectedSeq", response.read())
            with self.assertRaises(HTTPError) as missing:
                urlopen(base + "/assets/../release.json", timeout=5)
            self.assertEqual(missing.exception.code, 404)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
