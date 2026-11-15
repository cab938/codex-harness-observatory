"""Check an installed wheel's recorded replay without live-capture dependencies."""

import argparse
import importlib.abc
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from unittest import mock
from urllib.request import ProxyHandler, build_opener
import venv
import zipfile


FIXTURE = (
    Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "teaching_trace.jsonl"
)


def check_installed(fixture: Path, environment: Path, scratch: Path) -> None:
    class BlockCaptureImports(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname == "observatory.desktop" or fullname in {"termios", "tty"}:
                raise AssertionError(
                    f"replay imported a capture-only module: {fullname}"
                )
            return None

    sys.meta_path.insert(0, BlockCaptureImports())
    import launch
    from observatory import trace_viewer

    for module in (launch, trace_viewer):
        if not Path(module.__file__).resolve().is_relative_to(environment.resolve()):
            raise AssertionError(
                f"module was not loaded from the installed wheel: {module.__file__}"
            )

    bundle = scratch / "bundle"
    (bundle / "payloads").mkdir(parents=True)
    files = {
        "manifest.json": b'{"schema_version":4,"format":"codex-harness-observatory","root_thread_id":null}\n',
        "trace.jsonl": fixture.read_bytes(),
        "payloads/request.json": b'{"synthetic":"request"}\r\n',
        "payloads/tool-input.json": b'{"synthetic":"tool input"}\n',
        "payloads/result.json": b'{"synthetic":"result"}\n',
    }
    for name, data in files.items():
        (bundle / name).write_bytes(data)
    archive = scratch / "capture.zip"
    with zipfile.ZipFile(archive, "w") as exported:
        for name, data in files.items():
            exported.writestr(name, data)

    original_serve = trace_viewer.TraceViewerHTTPServer.serve_forever
    served_roots = []
    opener = build_opener(ProxyHandler({}))

    def bounded_serve(server, poll_interval=0.2):
        trace = server.resolve_trace_path()
        if trace is None:
            raise AssertionError("recorded viewer did not open its trace")
        served_roots.append(trace.parent)
        for name, data in files.items():
            if (trace.parent / name).read_bytes() != data:
                raise AssertionError(f"opened capture changed file bytes: {name}")
        thread = threading.Thread(
            target=original_serve,
            args=(server,),
            kwargs={"poll_interval": 0.05},
            daemon=True,
        )
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_address[1]}"
            with opener.open(base + "/", timeout=10) as response:
                if b"<html" not in response.read().lower():
                    raise AssertionError("installed viewer did not serve its HTML")
            with opener.open(base + "/api/header", timeout=10) as response:
                if json.load(response).get("stream_mode") != "recorded_jsonl":
                    raise AssertionError("viewer did not open a recorded trace")
            with opener.open(base + "/api/stream", timeout=10) as response:
                stream = response.read()
                if (
                    b"event: trace\n" not in stream
                    or b"event: trace-complete" not in stream
                ):
                    raise AssertionError(
                        "viewer did not complete the recorded event stream"
                    )
            with opener.open(
                base + "/api/artifact?path=payloads/request.json", timeout=10
            ) as response:
                payload = json.load(response)
                if (
                    payload.get("raw_text", "").encode("utf-8")
                    != files["payloads/request.json"]
                ):
                    raise AssertionError(
                        "viewer did not serve the synthetic payload intact"
                    )
        finally:
            server.shutdown()
            thread.join(timeout=10)
            if thread.is_alive():
                raise AssertionError("viewer did not shut down")

    with mock.patch.object(
        trace_viewer.TraceViewerHTTPServer, "serve_forever", bounded_serve
    ):
        for source in (bundle, bundle / "trace.jsonl", archive):
            if launch.main(["replay", str(source)]) != 0:
                raise AssertionError(f"installed replay could not open {source.name}")

    if len(served_roots) != 3 or served_roots[:2] != [bundle, bundle]:
        raise AssertionError("directory and JSONL replay opened the wrong capture")
    if served_roots[2].exists():
        raise AssertionError("ZIP extraction survived after the viewer exited")
    if any(name in sys.modules for name in ("observatory.desktop", "termios", "tty")):
        raise AssertionError("replay loaded a capture-only module")
    home = Path(os.environ["HOME"])
    if any(home.iterdir()):
        raise AssertionError("replay wrote to the isolated home directory")
    print(
        "Portable installed replay passed: directory, JSONL, ZIP, stream, assets, bytes, cleanup"
    )


def main() -> int:
    if len(sys.argv) == 5 and sys.argv[1] == "--check-installed":
        check_installed(*(Path(value) for value in sys.argv[2:]))
        return 0
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "wheel", type=Path, help="built wheel file or directory containing one wheel"
    )
    args = parser.parse_args()
    source = args.wheel.resolve()
    wheels = sorted(source.glob("*.whl")) if source.is_dir() else [source]
    if len(wheels) != 1 or not wheels[0].is_file() or wheels[0].suffix != ".whl":
        parser.error("expected exactly one built wheel")
    with tempfile.TemporaryDirectory(prefix="observatory-portable-") as temporary:
        root = Path(temporary)
        environment = root / "venv"
        home = root / "home"
        scratch = root / "scratch"
        home.mkdir()
        scratch.mkdir()
        venv.EnvBuilder(with_pip=True).create(environment)
        python = environment / (
            "Scripts/python.exe" if os.name == "nt" else "bin/python"
        )
        env = os.environ.copy()
        for key in (
            "PYTHONPATH",
            "PYTHONHOME",
            "CODEX_HOME",
            "CODEX_CONFIGURE_HOME",
            "OPENAI_API_KEY",
        ):
            env.pop(key, None)
        env.update(
            {
                "PIP_DISABLE_PIP_VERSION_CHECK": "1",
                "PIP_NO_INDEX": "1",
                "PIP_NO_CACHE_DIR": "1",
                "PYTHONNOUSERSITE": "1",
            }
        )
        subprocess.run(
            [str(python), "-m", "pip", "install", str(wheels[0])],
            check=True,
            cwd=scratch,
            env=env,
        )
        env.update(
            {
                "HOME": str(home),
                "USERPROFILE": str(home),
                "APPDATA": str(home),
                "LOCALAPPDATA": str(home),
                "XDG_CONFIG_HOME": str(home / "config"),
                "XDG_DATA_HOME": str(home / "data"),
                "XDG_CACHE_HOME": str(home / "cache"),
                "XDG_STATE_HOME": str(home / "state"),
                "XDG_RUNTIME_DIR": str(home / "runtime"),
            }
        )
        subprocess.run(
            [
                str(python),
                "-I",
                str(Path(__file__).resolve()),
                "--check-installed",
                str(FIXTURE),
                str(environment),
                str(scratch),
            ],
            check=True,
            cwd=scratch,
            env=env,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
