"""Offline native/candidate equivalence and optional App Server collection probe."""

import argparse
from collections import Counter
import gzip
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import threading
import time


TOOL_TEXT = "complete backend result " + "0123456789abcdef" * 12000
TOOL_SPEC = {
    "type": "function",
    "name": "observatory_probe",
    "description": "Return the deterministic validation result.",
    "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
}


def sse(events):
    return "".join("data: " + json.dumps(event) + "\n\n" for event in events).encode()


class Provider(ThreadingHTTPServer):
    def __init__(self):
        super().__init__(("127.0.0.1", 0), Handler)
        self.requests = []


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        body = b'{"data":[]}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        if self.headers.get("Content-Encoding") == "gzip":
            body = gzip.decompress(body)
        value = json.loads(body)
        self.server.requests.append({"path": self.path, "body": value})
        number = len(self.server.requests)
        if number == 1:
            item = {
                "type": "function_call",
                "name": "observatory_probe",
                "call_id": "call-probe",
                "arguments": "{}",
            }
        else:
            item = {
                "type": "message",
                "id": "message-probe",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "Probe completed."}],
            }
        data = sse(
            [
                {"type": "response.created", "response": {"id": f"response-{number}"}},
                {"type": "response.output_item.added", "item": item},
                {"type": "response.output_item.done", "item": item},
                {
                    "type": "response.completed",
                    "response": {"id": f"response-{number}"},
                },
            ]
        )
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class Rpc:
    def __init__(self, process):
        self.process = process
        self.messages = []
        self.pending = []
        self.lines = queue.Queue()
        threading.Thread(target=self._reader, daemon=True).start()

    def _reader(self):
        for line in self.process.stdout:
            self.lines.put(line)
        self.lines.put(None)

    def send(self, message):
        self.process.stdin.write(json.dumps(message) + "\n")
        self.process.stdin.flush()

    def read(self, predicate, timeout=60):
        for index, item in enumerate(self.pending):
            if predicate(item):
                return self.pending.pop(index)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            line = self.lines.get(timeout=max(0.01, deadline - time.monotonic()))
            if line is None:
                raise RuntimeError("App Server closed before expected message")
            item = json.loads(line)
            self.messages.append(item)
            if "id" in item and item.get("method") == "item/tool/call":
                self.send(
                    {
                        "id": item["id"],
                        "result": {
                            "success": True,
                            "contentItems": [{"type": "inputText", "text": TOOL_TEXT}],
                        },
                    }
                )
                continue
            if predicate(item):
                return item
            self.pending.append(item)
        raise TimeoutError("App Server response timeout")

    def request(self, identity, method, params):
        self.send({"id": identity, "method": method, "params": params})
        response = self.read(
            lambda m: (
                type(m.get("id")) is type(identity)
                and m.get("id") == identity
                and "method" not in m
            )
        )
        if "error" in response:
            raise RuntimeError(f"{method}: {response['error']}")
        return response["result"]


def normalized_requests(requests, home):
    """Normalize generated identities while preserving all model text and tool data."""
    identities = {}

    def identity(value):
        return identities.setdefault(value, f"generated-{len(identities) + 1}")

    result = json.loads(json.dumps(requests))
    identity_keys = {
        "installation_id",
        "session_id",
        "thread_id",
        "turn_id",
        "root_turn_id",
        "context_window_id",
        "window_id",
        "x-codex-installation-id",
        "x-codex-window-id",
    }
    for request in result:
        body = request["body"]
        if "prompt_cache_key" in body:
            body["prompt_cache_key"] = identity(body["prompt_cache_key"])
        for item in body.get("input", []):
            if item.get("id", "").startswith(("msg_", "fc_", "fco_")):
                item["id"] = identity(item["id"])
        metadata = body.get("client_metadata", {})
        for key in sorted(identity_keys & metadata.keys()):
            metadata[key] = identity(metadata[key])
        if "x-codex-turn-metadata" in metadata:
            turn = json.loads(metadata["x-codex-turn-metadata"])
            for key in sorted(identity_keys & turn.keys()):
                turn[key] = identity(turn[key])
            if "turn_started_at_unix_ms" in turn:
                turn["turn_started_at_unix_ms"] = 0
            metadata["x-codex-turn-metadata"] = json.dumps(turn, sort_keys=True)
    return json.loads(
        json.dumps(result, sort_keys=True).replace(str(home), "<TEST_HOME>")
    )


def run(binary, label, traced, provider, root, descriptor):
    run_dir = root / label
    run_dir.mkdir()
    home = root / "profile"
    if home.exists():
        shutil.rmtree(home)
    home.mkdir(mode=0o700)
    workspace = root / "workspace"
    workspace.mkdir(exist_ok=True)
    (home / "config.toml").write_text(f"""model = "mock-model"
approval_policy = "never"
sandbox_mode = "read-only"
model_provider = "mock_provider"
[features]
code_mode = false
[model_providers.mock_provider]
name = "Mock provider for validation"
base_url = "http://127.0.0.1:{provider.server_port}/v1"
wire_api = "responses"
request_max_retries = 0
stream_max_retries = 0
""")
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("CODEX_", "OPENAI_", "XDG_", "OBSERVATORY_"))
    }
    env.update(
        {
            "HOME": str(home),
            "CODEX_HOME": str(home),
            "CODEX_INTERNAL_APP_SERVER_REMOTE_CONTROL_DISABLED": "1",
        }
    )
    for name in ("CONFIG", "DATA", "CACHE", "STATE"):
        env[f"XDG_{name}_HOME"] = str(home / name.lower())
    if traced:
        env.update(
            {
                "CODEX_ROLLOUT_TRACE_ROOT": str(run_dir / "traces"),
                "CODEX_ROLLOUT_TRACE_SHARED_RUN": "1",
                "CODEX_OBSERVATORY_BUILD_DESCRIPTOR": str(descriptor),
            }
        )
    provider.requests = []
    with (run_dir / "stderr.log").open("w") as stderr:
        process = subprocess.Popen(
            [str(binary), "app-server"],
            cwd=workspace,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=stderr,
            text=True,
            bufsize=1,
        )
        rpc = Rpc(process)
        try:
            rpc.request(
                0,
                "initialize",
                {
                    "clientInfo": {
                        "name": "observatory_validation",
                        "version": "0.3.0",
                    },
                    "capabilities": {
                        "experimentalApi": True,
                        "optOutNotificationMethods": ["thread/tokenUsage/updated"],
                    },
                },
            )
            rpc.send({"method": "initialized"})
            # Concurrent, type-distinct IDs; then sequential reuse. Unknown semantic JSON must survive the tap.
            for identity in (7, "7"):
                rpc.send(
                    {
                        "id": identity,
                        "method": "config/read",
                        "params": {"includeLayers": False},
                        "observatoryUnknownMember": {
                            "retained": True,
                            "integer": 9007199254740993,
                        },
                    }
                )
            for identity in (7, "7"):
                response = rpc.read(
                    lambda m: (
                        type(m.get("id")) is type(identity)
                        and m.get("id") == identity
                        and "method" not in m
                    )
                )
                assert "result" in response, response
            rpc.request(7, "config/read", {"includeLayers": False})
            rpc.send({"id": "unknown", "method": "observatory/unknown", "params": {}})
            invalid = rpc.read(lambda m: m.get("id") == "unknown" and "error" in m)
            started = rpc.request(
                2,
                "thread/start",
                {
                    "cwd": str(workspace),
                    "model": "mock-model",
                    "experimentalRawEvents": True,
                    "dynamicTools": [TOOL_SPEC],
                },
            )
            thread = started["thread"]["id"]
            rpc.request(
                3,
                "turn/start",
                {
                    "threadId": thread,
                    "input": [
                        {
                            "type": "text",
                            "text": "Run observatory_probe once, then answer.",
                        }
                    ],
                },
            )
            completed = rpc.read(lambda m: m.get("method") == "turn/completed")
            assert completed["params"]["turn"]["status"] == "completed", completed
            process.stdin.close()
            return_code = process.wait(timeout=30)
            assert return_code == 0, return_code
            requests = list(provider.requests)
            assert len(requests) == 2, len(requests)
            summary = {
                "label": label,
                "binary": str(binary),
                "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
                "provider_requests": requests,
                "normalized_requests": normalized_requests(requests, home),
                "turn_status": completed["params"]["turn"]["status"],
                "unknown_method_error": invalid["error"]["code"],
                "methods": dict(
                    Counter(m.get("method", "response") for m in rpc.messages)
                ),
                "tool_result_characters": len(TOOL_TEXT),
            }
            (run_dir / "result.json").write_text(json.dumps(summary, indent=2) + "\n")
            (run_dir / "messages.jsonl").write_text(
                "".join(json.dumps(m) + "\n" for m in rpc.messages)
            )
            return summary
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=30)


def validate_trace(run_dir, requests):
    from observatory.trace_viewer import events

    bundles = list((run_dir / "traces").iterdir())
    assert len(bundles) == 1, bundles
    bundle = bundles[0]
    observed = list(events(bundle / "trace.jsonl"))
    frames = [
        e["payload"]
        for e in observed
        if e["payload"]["type"] == "app_server_frame_observed"
    ]
    inference = [
        e["payload"] for e in observed if e["payload"]["type"] == "inference_started"
    ]
    retained = [
        json.loads((bundle / event["request_payload"]["path"]).read_text())
        for event in inference
    ]
    assert retained == [r["body"] for r in requests], (
        "Prepared model bodies differ from actual provider requests"
    )
    config = [
        f
        for f in frames
        if f["method"] == "config/read" and f["frame_kind"] == "request"
    ]
    assert [f["request_id"] for f in config] == [7, "7", 7]
    assert len({f["exchange_id"] for f in config}) == 3
    for frame in config:
        paired = [
            f
            for f in frames
            if f["exchange_id"] == frame["exchange_id"]
            and f["frame_kind"] == "response"
        ]
        assert len(paired) == 1
        assert type(paired[0]["request_id"]) is type(frame["request_id"])
    for frame in config[:2]:
        value = json.loads((bundle / frame["frame_payload"]["path"]).read_text())
        assert value["observatoryUnknownMember"] == {
            "retained": True,
            "integer": 9007199254740993,
        }
    result_frames = [
        json.loads((bundle / f["frame_payload"]["path"]).read_text())
        for f in frames
        if f["method"] == "item/tool/call" and f["frame_kind"] == "response"
    ]
    assert result_frames[0]["result"]["contentItems"][0]["text"] == TOOL_TEXT
    assert not any(f["method"] == "thread/tokenUsage/updated" for f in frames)
    assert any(f["method"] == "rawResponseItem/completed" for f in frames)
    manifest = json.loads((bundle / "manifest.json").read_text())
    assert manifest["capture_health"]["status"] == "clean", manifest["capture_health"]
    assert manifest["capture_health"]["run_state"] == "closed"
    return {
        "prepared_requests_match_received": True,
        "typed_and_reused_exchanges": len(config),
        "unknown_members_and_large_integer_preserved": True,
        "tool_result_characters": len(TOOL_TEXT),
        "negotiated_notification_filter_honored": True,
        "optional_raw_events_observed": True,
        "capture_health": manifest["capture_health"],
        "bundle": str(bundle),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--descriptor", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(mode=0o700, parents=True, exist_ok=False)
    provider = Provider()
    threading.Thread(target=provider.serve_forever, daemon=True).start()
    try:
        results = [
            run(
                args.native.resolve(),
                "native",
                False,
                provider,
                args.output,
                args.descriptor,
            ),
            run(
                args.candidate.resolve(),
                "candidate-untraced",
                False,
                provider,
                args.output,
                args.descriptor,
            ),
            run(
                args.candidate.resolve(),
                "candidate-traced",
                True,
                provider,
                args.output,
                args.descriptor,
            ),
        ]
        fidelity = validate_trace(
            args.output / "candidate-traced", results[-1]["provider_requests"]
        )
        baseline = results[0]["normalized_requests"]
        equivalent = all(
            result["normalized_requests"] == baseline for result in results
        )
        report = {
            "equivalent": equivalent,
            "fidelity": fidelity,
            "normalization": [
                "generated cache/session/turn/context/install/window IDs",
                "generated message/function/output item IDs with consistent aliases",
                "turn_started_at_unix_ms",
                "private test home path",
            ],
            "request_counts": [len(result["provider_requests"]) for result in results],
            "turn_statuses": [result["turn_status"] for result in results],
            "large_tool_result_characters": len(TOOL_TEXT),
            "scope": "Deterministic dynamic tool call, full result, final answer, optional raw events and notification filter. Other behavior is covered separately; this is not universal equivalence.",
        }
        (args.output / "equivalence.json").write_text(
            json.dumps(report, indent=2) + "\n"
        )
        print(json.dumps(report))
        return 0 if equivalent else 1
    finally:
        provider.shutdown()
        provider.server_close()


if __name__ == "__main__":
    raise SystemExit(main())
