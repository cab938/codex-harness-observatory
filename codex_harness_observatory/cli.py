"""Run the telemetry-enabled Codex harness from an installed package."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path, PurePosixPath
from typing import Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from . import __version__

PACKAGE_VERSION = __version__
CORE_VERSION = "0.150.0-alpha.12.2"
CORE_TARGET = "x86_64-unknown-linux-gnu"
RELEASE_TAG = f"v{PACKAGE_VERSION}"
RELEASE_BASE_URL = (
    "https://github.com/cab938/codex-harness-observatory/releases/download/"
    f"{RELEASE_TAG}"
)
CORE_ARCHIVE_NAME = f"codex-harness-observatory-core-{PACKAGE_VERSION}-{CORE_TARGET}.tar.gz"
CORE_CHECKSUM_NAME = f"{CORE_ARCHIVE_NAME}.sha256"
CORE_INSTALL_DIR_NAME = f"core-{PACKAGE_VERSION}-{CORE_TARGET}"
EXPECTED_PACKAGE = {
    "layoutVersion": 1,
    "version": CORE_VERSION,
    "target": CORE_TARGET,
    "variant": "codex",
    "entrypoint": "bin/codex",
    "resourcesDir": "codex-resources",
    "pathDir": "codex-path",
}
REQUIRED_PACKAGE_FILES = (
    "codex-package.json",
    "bin/codex",
    "bin/codex-code-mode-host",
    "codex-resources/bwrap",
    "codex-path/rg",
)


class ObservatoryError(RuntimeError):
    """A user-facing launcher or installation error."""


def _python_executable() -> Path:
    """Return the active interpreter path without leaving its virtual environment."""

    return Path(os.path.abspath(sys.executable))


def _same_venv_codex_configure() -> Path:
    """Resolve the dependency executable in the pipx environment."""

    executable = _python_executable().parent / "codex-configure"
    if executable.is_file() and os.access(executable, os.X_OK):
        return executable
    raise ObservatoryError(
        "codex-configure was not found in this installation's environment. "
        "Reinstall with pipx so its dependencies are available."
    )


def _launch_root_is_valid(cwd: Path) -> bool:
    state = cwd / ".codex-configure"
    return all(
        (
            (state / "root.toml").is_file(),
            (state / "launch.toml").is_file(),
            (state / "launch.sh").is_file(),
            os.access(state / "launch.sh", os.X_OK),
        )
    )


def _ensure_launch_root(cwd: Path, configure: Path) -> None:
    if _launch_root_is_valid(cwd):
        return
    print(
        "This directory is not configured for Codex yet; starting codex-configure init.",
        flush=True,
    )
    print(
        "Choose Stock Core and OpenAI: the observatory uses codex-configure "
        "for rooting, not its provider patch.",
        flush=True,
    )
    result = subprocess.run([str(configure), "init"], cwd=cwd)
    if result.returncode:
        raise ObservatoryError(f"codex-configure init failed with status {result.returncode}.")
    if not _launch_root_is_valid(cwd):
        raise ObservatoryError(
            "codex-configure init completed without creating a valid .codex-configure launch root."
        )


def _prepend_venv_to_path(environment: dict[str, str]) -> None:
    bin_dir = str(_python_executable().parent)
    old_path = environment.get("PATH", "")
    environment["PATH"] = bin_dir if not old_path else f"{bin_dir}{os.pathsep}{old_path}"


def _dispatch_installed(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="codex-harness-observatory",
        description="Launch the isolated Codex Harness Observatory.",
    )
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--tui", action="store_true", help="run the TUI client (default)")
    modes.add_argument("--desktop", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.desktop:
        print(
            "Desktop mode is available from the observatory source checkout only; "
            "the pipx package supports the TUI path.",
            file=sys.stderr,
        )
        return 2

    cwd = Path.cwd().resolve()
    configure = _same_venv_codex_configure()
    _ensure_launch_root(cwd, configure)
    environment = os.environ.copy()
    _prepend_venv_to_path(environment)
    command = [
        str(configure),
        "launch",
        "--",
        str(_python_executable()),
        "-m",
        "codex_harness_observatory",
        "_run",
        "--tui",
    ]
    os.execvpe(str(configure), command, environment)
    return 0  # pragma: no cover - execvpe does not return on success


def _safe_archive_member(name: str) -> PurePosixPath:
    if "\\" in name:
        raise ObservatoryError(f"Core archive contains an unsafe member path: {name!r}")
    path = PurePosixPath(name)
    if path.is_absolute() or not path.parts or ".." in path.parts or "." in path.parts:
        raise ObservatoryError(f"Core archive contains an unsafe member path: {name!r}")
    return path


def _validate_archive(archive: tarfile.TarFile) -> None:
    names: set[str] = set()
    for member in archive.getmembers():
        path = _safe_archive_member(member.name)
        if str(path) in names:
            raise ObservatoryError(f"Core archive contains duplicate member: {member.name!r}")
        names.add(str(path))
        if not (member.isdir() or member.isreg()):
            raise ObservatoryError(
                f"Core archive contains unsupported member type: {member.name!r}"
            )
        if member.isreg() and member.size < 0:
            raise ObservatoryError(f"Core archive contains an invalid member size: {member.name!r}")
    required = set(REQUIRED_PACKAGE_FILES)
    if not required.issubset(names):
        missing = ", ".join(sorted(required - names))
        raise ObservatoryError(f"Core archive is missing required package files: {missing}")


def _validate_package_dir(package_dir: Path) -> Path:
    metadata_path = package_dir / "codex-package.json"
    if not metadata_path.is_file() or metadata_path.is_symlink():
        raise ObservatoryError(f"Installed Core is missing canonical metadata: {metadata_path}")
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ObservatoryError(f"Installed Core metadata is unreadable: {metadata_path}") from exc
    if metadata != EXPECTED_PACKAGE:
        raise ObservatoryError(
            "Installed Core metadata does not match the pinned observatory package."
        )
    for relative in REQUIRED_PACKAGE_FILES:
        path = package_dir / relative
        if not path.is_file() or path.is_symlink():
            raise ObservatoryError(f"Installed Core package file is missing or unsafe: {path}")
        if relative != "codex-package.json" and not os.access(path, os.X_OK):
            raise ObservatoryError(f"Installed Core package file is not executable: {path}")
    binary = package_dir / "bin" / "codex"
    return binary


def _download(url: str, destination: Path) -> None:
    try:
        request = Request(url, headers={"User-Agent": "codex-harness-observatory"})
        with urlopen(request, timeout=60) as response, destination.open("wb") as output:
            shutil.copyfileobj(response, output)
    except (HTTPError, URLError, OSError) as exc:
        raise ObservatoryError(f"Could not download {url}: {exc}") from exc


def _verify_checksum(archive_path: Path, checksum_path: Path) -> None:
    try:
        checksum_text = checksum_path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise ObservatoryError(f"Could not read Core checksum: {checksum_path}") from exc
    expected = checksum_text.split()[0] if checksum_text else ""
    if len(expected) != 64 or any(character not in "0123456789abcdefABCDEF" for character in expected):
        raise ObservatoryError(f"Core checksum has invalid SHA-256 text: {checksum_path}")
    digest = hashlib.sha256()
    with archive_path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    if digest.hexdigest().lower() != expected.lower():
        raise ObservatoryError("Core archive SHA-256 does not match its release checksum.")


def _verify_binary(binary: Path) -> None:
    try:
        result = subprocess.run(
            [str(binary), "--version"],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ObservatoryError(f"Could not execute the patched Core: {binary}") from exc
    expected = f"codex-cli {CORE_VERSION}"
    if result.stdout.strip() != expected:
        raise ObservatoryError(
            f"Patched Core reported {result.stdout.strip()!r}; expected {expected!r}."
        )


def install_core(codex_home: Path) -> Path:
    """Install and validate the pinned GNU Core package under CODEX_HOME."""

    if sys.platform != "linux" or platform.machine().lower() not in {"amd64", "x86_64"}:
        raise ObservatoryError(
            "The prebuilt observatory Core currently supports Linux x86_64 only."
        )
    install_root = codex_home.parent / "observatory"
    package_dir = install_root / CORE_INSTALL_DIR_NAME
    if package_dir.is_dir():
        binary = _validate_package_dir(package_dir)
        _verify_binary(binary)
        return binary
    if package_dir.exists() or package_dir.is_symlink():
        raise ObservatoryError(f"Refusing to replace an unsafe Core install path: {package_dir}")

    install_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="core-", dir=install_root) as temporary:
        temporary_dir = Path(temporary)
        archive_path = temporary_dir / CORE_ARCHIVE_NAME
        checksum_path = temporary_dir / CORE_CHECKSUM_NAME
        print(f"Downloading and verifying Observatory Core {CORE_VERSION}...")
        _download(f"{RELEASE_BASE_URL}/{CORE_ARCHIVE_NAME}", archive_path)
        _download(f"{RELEASE_BASE_URL}/{CORE_CHECKSUM_NAME}", checksum_path)
        _verify_checksum(archive_path, checksum_path)
        extracted = temporary_dir / "package"
        extracted.mkdir()
        try:
            with tarfile.open(archive_path, "r:gz") as archive:
                _validate_archive(archive)
                archive.extractall(extracted, filter="data")
        except (OSError, tarfile.TarError) as exc:
            raise ObservatoryError(f"Could not unpack the Core release archive: {exc}") from exc
        binary = _validate_package_dir(extracted)
        _verify_binary(binary)
        os.replace(extracted, package_dir)
    return _validate_package_dir(package_dir)


def _setting(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _port(name: str, default: str) -> int:
    value = _setting(name, default)
    try:
        port = int(value)
    except ValueError as exc:
        raise ObservatoryError(f"{name} must be an integer from 1 through 65535 (got {value!r})") from exc
    if not 1 <= port <= 65535:
        raise ObservatoryError(f"{name} must be an integer from 1 through 65535 (got {value!r})")
    return port


def _positive_seconds(name: str, default: str) -> float:
    value = _setting(name, default)
    try:
        seconds = float(value)
    except ValueError as exc:
        raise ObservatoryError(f"{name} must be positive (got {value!r})") from exc
    if seconds <= 0:
        raise ObservatoryError(f"{name} must be positive (got {value!r})")
    return seconds


def _show_content() -> bool:
    value = _setting("OBSERVATORY_SHOW_CONTENT", "1")
    if value not in {"0", "1"}:
        raise ObservatoryError("OBSERVATORY_SHOW_CONTENT must be 0 or 1")
    return value == "1"


def _workspace(cwd: Path) -> Path:
    value = Path(_setting("OBSERVATORY_WORKSPACE", "."))
    workspace = value if value.is_absolute() else cwd / value
    workspace = workspace.resolve()
    if not workspace.is_dir():
        raise ObservatoryError(f"Codex workspace is not a directory: {workspace}")
    return workspace


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


def _run() -> int:
    codex_home_value = os.environ.get("CODEX_HOME", "")
    if not codex_home_value:
        raise ObservatoryError("codex-configure did not provide a rooted CODEX_HOME")
    cwd = Path.cwd().resolve()
    codex_home = Path(codex_home_value).expanduser().resolve()
    if not codex_home.is_dir() or codex_home != cwd / ".codex-configure" / "codex-home":
        raise ObservatoryError(f"CODEX_HOME is not a codex-configure launch root: {codex_home}")
    override = os.environ.get("OBSERVATORY_CODEX_BIN")
    if override:
        codex_bin = Path(override)
        if not codex_bin.is_absolute():
            codex_bin = cwd / codex_bin
        codex_bin = codex_bin.resolve()
        if not codex_bin.is_file() or not os.access(codex_bin, os.X_OK):
            raise ObservatoryError(f"OBSERVATORY_CODEX_BIN is not executable: {codex_bin}")
        _verify_binary(codex_bin)
    else:
        codex_bin = install_core(codex_home)

    app_host = _setting("OBSERVATORY_APP_SERVER_HOST", "127.0.0.1")
    app_port = _port("OBSERVATORY_APP_SERVER_PORT", "4500")
    viewer_host = _setting("OBSERVATORY_VIEWER_HOST", "127.0.0.1")
    viewer_port = _port("OBSERVATORY_VIEWER_PORT", "8765")
    timeout = _positive_seconds("OBSERVATORY_STARTUP_TIMEOUT_SECONDS", "15")
    show_content = _show_content()
    workspace = _workspace(cwd)
    runs_value = Path(_setting("OBSERVATORY_RUNS_DIR", ".codex-configure/observatory/runs"))
    runs_dir = (runs_value if runs_value.is_absolute() else cwd / runs_value).resolve()
    runs_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    run_dir = Path(tempfile.mkdtemp(prefix="run-", dir=runs_dir))
    trace_root = run_dir / "traces"
    trace_root.mkdir(mode=0o700)
    app_log = run_dir / "app-server.log"
    viewer_log = run_dir / "trace-viewer.log"
    environment = os.environ.copy()
    environment.update(
        {
            "CODEX_ROLLOUT_TRACE_ROOT": str(trace_root),
            "CODEX_INTERNAL_APP_SERVER_REMOTE_CONTROL_DISABLED": _setting(
                "OBSERVATORY_DISABLE_REMOTE_CONTROL", "1"
            ),
        }
    )
    app_url = f"ws://{app_host}:{app_port}"
    app_ready_url = f"http://{app_host}:{app_port}/readyz"
    viewer_url = f"http://{viewer_host}:{viewer_port}"
    app_process: subprocess.Popen[object] | None = None
    viewer_process: subprocess.Popen[object] | None = None
    tui_status = 0
    try:
        with app_log.open("w", encoding="utf-8") as log:
            app_process = subprocess.Popen(
                [str(codex_bin), "app-server", "--listen", app_url],
                cwd=workspace,
                env=environment,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        _wait_for_service("Codex app server", app_ready_url, app_process, app_log, timeout)
        viewer_arguments = [
            str(Path(__file__).resolve().parent.parent / "tools" / "trace_viewer.py"),
            str(trace_root),
            "--serve",
            "--wait-for-bundle",
            "--show-content" if show_content else "--redact-content",
            "--host",
            viewer_host,
            "--port",
            str(viewer_port),
        ]
        with viewer_log.open("w", encoding="utf-8") as log:
            viewer_process = subprocess.Popen(
                [sys.executable, *viewer_arguments],
                cwd=workspace,
                env=environment,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        _wait_for_service("log web server", f"{viewer_url}/", viewer_process, viewer_log, timeout)
        print(f"Codex app server started at {app_url}.")
        print(f"Log web server started at {viewer_url}.")
        print(f"Run artifacts retained at: {run_dir}")
        print("Content: full teaching evidence" if show_content else "Content: redacted metadata only")
        try:
            answer = input("Start the Codex TUI and connect it to this app server? [Y/n] ")
        except EOFError:
            answer = "n"
        if answer.lower() not in {"", "y", "yes"}:
            print("Codex TUI was not started; beginning shutdown.")
            return 0
        print("Starting the Codex TUI. Use /exit to return and shut down both servers.")
        tui_status = subprocess.run(
            [str(codex_bin), "--remote", app_url, "-C", str(workspace)],
            cwd=workspace,
            env=environment,
        ).returncode
        return tui_status
    finally:
        _terminate(app_process)
        _terminate(viewer_process)
        print(f"Run artifacts retained at: {run_dir}")


def main(argv: Sequence[str] | None = None) -> int:
    try:
        arguments = list(sys.argv[1:] if argv is None else argv)
        if arguments and arguments[0] == "_run":
            arguments = arguments[1:]
            if arguments not in ([], ["--tui"]):
                print("codex-harness-observatory: internal arguments are invalid", file=sys.stderr)
                return 2
            return _run()
        return _dispatch_installed(arguments)
    except ObservatoryError as exc:
        print(f"codex-harness-observatory: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("codex-harness-observatory: interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
