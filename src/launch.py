"""Run the telemetry-enabled Codex harness from an installed package."""

import argparse
import json
import os
import platform
import re
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from uuid import uuid4
from pathlib import Path
from typing import Sequence
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from observatory.release import (
    RELEASE,
    descriptor_path,
)

CORE_VERSION = RELEASE["core"]["version"]
CORE_TARGET = RELEASE["core"]["target"]
EXPECTED_PACKAGE = {
    "layoutVersion": 1,
    "version": CORE_VERSION,
    "target": CORE_TARGET,
    "variant": "codex",
    "entrypoint": "bin/codex",
    "execServer": "bin/codex-exec-server",
    "resourcesDir": "codex-resources",
    "pathDir": "codex-path",
}
REQUIRED_PACKAGE_FILES = (
    "codex-package.json",
    "bin/codex",
    "bin/codex-code-mode-host",
    "bin/codex-exec-server",
    "codex-resources/bwrap",
    "codex-path/rg",
)


class ObservatoryError(RuntimeError):
    """A user-facing launcher or installation error."""


def _validate_package_dir(package_dir: Path) -> Path:
    metadata_path = package_dir / "codex-package.json"
    if not metadata_path.is_file() or metadata_path.is_symlink():
        raise ObservatoryError(
            f"Installed Core is missing canonical metadata: {metadata_path}"
        )
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ObservatoryError(
            f"Installed Core metadata is unreadable: {metadata_path}"
        ) from exc
    if metadata != EXPECTED_PACKAGE:
        raise ObservatoryError(
            "Installed Core metadata does not match the pinned observatory package."
        )
    for relative in REQUIRED_PACKAGE_FILES:
        path = package_dir / relative
        if not path.is_file() or path.is_symlink():
            raise ObservatoryError(
                f"Installed Core package file is missing or unsafe: {path}"
            )
        if relative != "codex-package.json" and not os.access(path, os.X_OK):
            raise ObservatoryError(
                f"Installed Core package file is not executable: {path}"
            )
    binary = package_dir / "bin" / "codex"
    return binary


def _verify_binary(binary: Path, home: Path) -> None:
    try:
        result = subprocess.run(
            [str(binary), "--version"],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
            env={**os.environ, "CODEX_HOME": str(home)},
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ObservatoryError(f"Could not execute the patched Core: {binary}") from exc
    expected = f"codex-cli {CORE_VERSION}"
    if result.stdout.strip() != expected:
        raise ObservatoryError(
            f"Patched Core reported {result.stdout.strip()!r}; expected {expected!r}."
        )


def _require_capture_platform() -> None:
    if sys.platform != "linux" or platform.machine().lower() not in {"amd64", "x86_64"}:
        raise ObservatoryError(
            "Live capture currently supports Linux x86_64 only; recorded captures can be viewed on any supported Python platform."
        )


def _terminate(process: subprocess.Popen[object] | None) -> None:
    if process is None or process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + 5
    while process.poll() is None and time.monotonic() < deadline:
        time.sleep(0.1)
    if process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    process.wait()


def _wait_for_service(
    label: str,
    url: str,
    process: subprocess.Popen[object],
    log_path: Path,
    timeout: float,
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            recent = log_path.read_text(encoding="utf-8", errors="replace")[-4000:]
            raise ObservatoryError(f"{label} exited before readiness:\n{recent}")
        try:
            with urlopen(url, timeout=1):
                time.sleep(0.1)
                if process.poll() is None:
                    return
        except (HTTPError, URLError, OSError):
            pass
        time.sleep(0.1)
    recent = log_path.read_text(encoding="utf-8", errors="replace")[-4000:]
    raise ObservatoryError(f"Timed out waiting for {label} at {url}.\n{recent}")


def _wait_for_bound_url(
    label: str,
    scheme: str,
    process: subprocess.Popen[object],
    log_path: Path,
    timeout: float,
) -> str:
    pattern = re.compile(rf"\b{re.escape(scheme)}://(?:\[[^\]\s]+\]|[^:/\s]+):[0-9]+\b")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        contents = log_path.read_text(encoding="utf-8", errors="replace")
        match = pattern.search(contents)
        if match:
            return match.group(0)
        if process.poll() is not None:
            recent = contents[-4000:]
            raise ObservatoryError(
                f"{label} exited before reporting its address:\n{recent}"
            )
        time.sleep(0.1)
    recent = log_path.read_text(encoding="utf-8", errors="replace")[-4000:]
    raise ObservatoryError(
        f"Timed out waiting for {label} to report its address.\n{recent}"
    )


def _app_server_ready_url(app_url: str) -> str:
    if not app_url.startswith("ws://"):
        raise ObservatoryError(
            f"Codex app server reported an invalid address: {app_url}"
        )
    return f"http://{app_url.removeprefix('ws://')}/readyz"



def _absolute_path(value: str) -> Path:
    # Explicit paths are literal, including a leading tilde.
    return Path(os.path.abspath(value))


def _start_viewer(trace_root: Path, cwd: Path, environment: dict[str, str], log_path: Path):
    command = [sys.executable, '-m', 'observatory.trace_viewer', str(trace_root),
               '--serve', '--wait-for-bundle', '--show-content', '--host', '127.0.0.1', '--port', '0']
    viewer_environment = environment.copy()
    package_root = str(Path(__file__).resolve().parent)
    existing = viewer_environment.get('PYTHONPATH')
    viewer_environment['PYTHONPATH'] = os.pathsep.join((package_root, existing)) if existing else package_root
    with log_path.open('w', encoding='utf-8') as log:
        process = subprocess.Popen(command, cwd=cwd, env=viewer_environment, stdout=log,
                                   stderr=subprocess.STDOUT, start_new_session=True)
    try:
        url = _wait_for_bound_url('Observatory viewer', 'http', process, log_path, 15)
        _wait_for_service('Observatory viewer', url + '/', process, log_path, 15)
        return process, url
    except BaseException:
        _terminate(process)
        raise


def _wait_for_capture(run_dir: Path, process: subprocess.Popen, log_path: Path) -> None:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if (run_dir / 'manifest.json').is_file() and (run_dir / 'trace.jsonl').is_file() and (run_dir / 'payloads').is_dir():
            return
        if process.poll() is not None:
            break
        time.sleep(0.1)
    recent = log_path.read_text(encoding='utf-8', errors='replace')[-4000:]
    raise ObservatoryError(f'Native capture did not start in {run_dir}:\n{recent}')


def _run(client: str, home: Path, runs: Path) -> int:
    from observatory._process_cleanup import stop_owned_descendants

    _require_capture_platform()
    cwd = Path.cwd()
    home.mkdir(mode=0o700, parents=True, exist_ok=True)
    runs.mkdir(mode=0o700, parents=True, exist_ok=True)
    root = descriptor_path().parent
    core = _validate_package_dir(root / RELEASE['runtime']['core'])
    _verify_binary(core, home)
    desktop = None
    if client == 'desktop':
        from observatory.desktop import DesktopError, resolve_desktop_candidate, start_desktop, stop_desktop
        try:
            desktop = resolve_desktop_candidate(str(root / RELEASE['runtime']['desktop'] / 'start.sh'), CORE_VERSION)
        except DesktopError as exc:
            raise ObservatoryError(str(exc)) from exc
    run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid4().hex
    run_dir = runs / run_id
    run_dir.mkdir(mode=0o700)
    trace_root = run_dir
    env = os.environ.copy()
    env.pop('CODEX_ROLLOUT_TRACE_ROOT', None)
    env.pop('CODEX_ROLLOUT_TRACE_SHARED_RUN', None)
    env.update({'CODEX_HOME': str(home), 'OBSERVATORY_CODEX_HOME': str(home),
                'CODEX_ROLLOUT_TRACE_RUN_DIR': str(trace_root),
                'CODEX_OBSERVATORY_BUILD_DESCRIPTOR': str(descriptor_path()),
                'CODEX_INTERNAL_APP_SERVER_REMOTE_CONTROL_DISABLED': '1'})
    app = viewer = desktop_process = None
    old_handlers = {}
    def interrupt(signum, frame):
        raise KeyboardInterrupt
    try:
        for sig in (signal.SIGTERM, signal.SIGHUP):
            old_handlers[sig] = signal.signal(sig, interrupt)
        viewer, viewer_url = _start_viewer(trace_root, cwd, env, run_dir / 'viewer.log')
        print(f'Observatory: {viewer_url}', flush=True)
        print(f'Run artifacts: {run_dir}', flush=True)
        if desktop is not None:
            try:
                desktop_process, _ = start_desktop(
                    desktop, bridge_template=Path(__file__).parent / 'observatory' / 'desktop_core_bridge.sh',
                    codex_bin=core, run_dir=run_dir, trace_root=trace_root, workspace=cwd,
                    environment=env, log_path=run_dir / 'desktop.log', timeout=15)
            except DesktopError as exc:
                raise ObservatoryError(str(exc)) from exc
            _wait_for_capture(run_dir, desktop_process, run_dir / 'desktop.log')
            return desktop_process.wait()
        app_log = run_dir / 'app-server.log'
        with app_log.open('w', encoding='utf-8') as log:
            app = subprocess.Popen([str(core), 'app-server', '--listen', 'ws://127.0.0.1:0'],
                                   cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT,
                                   start_new_session=True)
        url = _wait_for_bound_url('Codex app server', 'ws', app, app_log, 15)
        _wait_for_service('Codex app server', _app_server_ready_url(url), app, app_log, 15)
        _wait_for_capture(run_dir, app, app_log)
        return subprocess.run([str(core), '--remote', url, '-C', str(cwd)], cwd=cwd, env=env).returncode
    finally:
        if desktop_process is not None:
            stop_desktop(desktop_process)
        if app is not None:
            with stop_owned_descendants(app):
                _terminate(app)
        _terminate(viewer)
        for sig, handler in old_handlers.items():
            signal.signal(sig, handler)
        print(f'Run artifacts retained at: {run_dir}', flush=True)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog='observatory')
    parser.add_argument('--client', choices=('desktop', 'cli'))
    parser.add_argument('--codex-home', default=str(Path.home() / '.observatory/profiles/main'))
    parser.add_argument('--runs-dir', default=str(Path.home() / '.observatory/runs'))
    parser.add_argument('command', nargs='?', choices=('replay',))
    parser.add_argument('capture', nargs='?')
    args = parser.parse_args(argv)
    if args.command == 'replay':
        if args.client or not args.capture:
            parser.error('replay requires a capture path and no --client')
        from observatory.capture_archive import open_capture
        from observatory import trace_viewer
        try:
            with open_capture(_absolute_path(args.capture)) as capture:
                return trace_viewer.main([str(capture), '--serve', '--recorded', '--show-content', '--host', '127.0.0.1', '--port', '0'])
        except (OSError, trace_viewer.TraceInputError) as exc:
            print(f'observatory: {exc}', file=sys.stderr)
            return 1
    if args.capture or not args.client:
        parser.error('--client is required for a live run')
    try:
        return _run(args.client, _absolute_path(args.codex_home), _absolute_path(args.runs_dir))
    except (ObservatoryError, OSError) as exc:
        print(f'observatory: {exc}', file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print('observatory: interrupted', file=sys.stderr)
        return 130


if __name__ == '__main__':
    raise SystemExit(main())
