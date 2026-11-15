"""Install and launch the isolated Codex Observatory Desktop candidate."""

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
from typing import Mapping
from urllib.parse import quote
from xml.sax.saxutils import escape

from ._process_cleanup import stop_owned_descendants
from .release import RELEASE


class DesktopError(RuntimeError):
    """A user-facing Desktop candidate or launch error."""


class DesktopCandidate:
    """Validated files needed to attach Desktop to the Observatory Core."""

    def __init__(self, start: Path, codex_app_tools_root: Path):
        self.start = start
        self.codex_app_tools_root = codex_app_tools_root


def _executable(path: Path, label: str) -> Path:
    if not path.is_file() or not os.access(path, os.X_OK):
        raise DesktopError(f"{label} is not executable: {path}")
    return path


def _json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("expected an object")
        return value
    except (OSError, ValueError) as exc:
        raise DesktopError(f"Desktop metadata is unreadable: {path}") from exc


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def resolve_desktop_candidate(
    start_value: str | None, core_version: str
) -> DesktopCandidate:
    """Validate the version, patch evidence, and identity of the candidate."""
    if not start_value:
        raise DesktopError("A verified Observatory Desktop candidate is required.")
    start = Path(start_value).expanduser().resolve()
    _executable(start, "Desktop candidate launcher")
    app = start.parent
    hook = app / ".codex-linux/launcher.d/shared-app-server-socket-socket-env.sh"
    bundled_codex = app / "resources/codex"
    tools = app / "resources/plugins/openai-bundled/plugins/codex-app-tools"
    _executable(hook, "Desktop shared socket hook")
    _executable(bundled_codex, "Desktop bundled Core")
    _executable(tools / "scripts/launch_codex_app_tools_mcp", "Desktop tools launcher")
    for path in (tools / ".mcp.json", tools / "server.mjs"):
        if not path.is_file():
            raise DesktopError(f"Desktop candidate is missing a required file: {path}")

    provenance = _json(app / ".codex-linux/observatory-build.json")
    info = _json(app / ".codex-linux/build-info.json")
    report = _json(app / ".codex-linux/patch-report.json")
    pin = RELEASE["desktop"]
    if (
        pin.get("core_socket_policy")
        != "profile-rendezvous-upstream-protected-physical-socket"
    ):
        raise DesktopError(
            "The release descriptor does not identify the protected Core socket policy."
        )
    expected = {
        "schemaVersion": 1,
        "desktopVersion": pin["version"],
        "packageSha256": pin["package_sha256"],
        "coreVersion": core_version,
        "bundledCoreVersion": pin["bundled_core_version"],
        "companionCommit": pin["companion_commit"],
        "featurePatchSha256": pin["feature_patch_sha256"],
        "isolationPatchSha256": pin["isolation_patch_sha256"],
        "asarVersion": pin["asar_version"],
        "appId": "codex-observatory-0-3",
        "updaterIncluded": False,
        "chromeNativeBridgeEnabled": False,
    }
    try:
        valid = all(provenance.get(key) == value for key, value in expected.items())
        valid = (
            valid and info["upstreamLinuxPackage"]["sha256"] == pin["package_sha256"]
        )
        valid = valid and info["source"]["commit"] == pin["companion_commit"]
        valid = valid and info["appIdentity"]["id"] == expected["appId"]
        valid = valid and info["linuxFeatures"]["enabled"] == [
            "shared-app-server-socket"
        ]
        required = {
            "feature:shared-app-server-socket:main-process-shared-app-server-socket",
            "feature:shared-app-server-socket:observatory-private-ipc-paths",
        }
        applied = {
            item["name"] for item in report["patches"] if item["status"] == "applied"
        }
        valid = valid and required <= applied
        valid = (
            valid
            and _sha256(app / "resources/app.asar") == provenance["outputAsarSha256"]
        )
        valid = valid and _sha256(start) == provenance["launcherSha256"]
        valid = valid and "OBSERVATORY_LAUNCH_GUARD" in start.read_text(
            encoding="utf-8"
        )
        plugins = app / "resources/plugins/openai-bundled/plugins"
        for plugin in ("browser", "chrome"):
            service = plugins / plugin / "scripts/browser-service.mjs"
            valid = (
                valid and _sha256(service) == provenance["browserServiceSha256"][plugin]
            )
        for name, relative in (
            (
                "cua",
                "resources/cua_node/lib/node_modules/@oai/browser-desktop/scripts/browser-service.mjs",
            ),
            (
                "cua_skill",
                "resources/cua_node/lib/node_modules/@oai/cua/dist/lib/js/oai_js_browser/dist/skill/scripts/browser-service.mjs",
            ),
        ):
            valid = (
                valid
                and _sha256(app / relative) == provenance["browserServiceSha256"][name]
            )
        native_host = plugins / "chrome/extension-host/linux/x64/extension-host"
        valid = (
            valid and native_host.is_file() and not (native_host.stat().st_mode & 0o111)
        )
        control = (app / ".codex-linux/upstream-package/control").read_text(
            encoding="utf-8"
        )
        valid = valid and f"Version: {pin['version']}\n" in control
    except (KeyError, TypeError, OSError) as exc:
        raise DesktopError("Desktop candidate provenance is incomplete.") from exc
    if not valid:
        raise DesktopError(
            "Desktop candidate does not match the pinned release and patch evidence."
        )
    try:
        with tempfile.TemporaryDirectory(prefix="observatory-desktop-version-") as temp:
            environment = {
                "PATH": os.defpath, "HOME": temp, "CODEX_HOME": str(Path(temp) / "codex"),
                "XDG_CONFIG_HOME": str(Path(temp) / "config"),
                "XDG_DATA_HOME": str(Path(temp) / "data"),
                "XDG_CACHE_HOME": str(Path(temp) / "cache"),
                "XDG_STATE_HOME": str(Path(temp) / "state"), "TMPDIR": temp,
            }
            result = subprocess.run([str(bundled_codex), "--version"], check=True,
                                    capture_output=True, text=True, timeout=15, env=environment)
    except (OSError, subprocess.SubprocessError) as exc:
        raise DesktopError(f"Could not execute Desktop bundled Core: {bundled_codex}") from exc
    if result.stdout.strip() != f"codex-cli {pin['bundled_core_version']}":
        raise DesktopError("Desktop bundled Core version does not match the release descriptor.")
    return DesktopCandidate(start, tools)


def _private_directory(path: Path) -> Path:
    if path.is_symlink() or not path.is_dir():
        raise DesktopError(f"Desktop profile path must be a real directory: {path}")
    st = path.stat()
    if st.st_uid != os.getuid():
        raise DesktopError(
            f"Desktop profile directory must be user-owned: {path}"
        )
    return path


def _prepare_system_desktop_data(state: Path) -> Path:
    """Copy the host's read-only GTK resources into the private XDG tree."""
    target = state / "system-data"
    marker = target / ".complete"
    if target.exists():
        _private_directory(target)
        if marker.is_symlink() or not marker.is_file():
            raise DesktopError(f"Incomplete private GTK data directory: {target}")
        schemas = target / "glib-2.0/schemas"
        if not schemas.exists():
            parent = target / "glib-2.0"
            parent.mkdir(mode=0o700, exist_ok=True)
            with tempfile.TemporaryDirectory(
                prefix=".schemas-", dir=parent
            ) as temporary:
                staging = Path(temporary) / "schemas"
                shutil.copytree("/usr/share/glib-2.0/schemas", staging)
                os.rename(staging, schemas)
        if not (schemas / "gschemas.compiled").is_file():
            raise DesktopError(f"Private GSettings schemas are unavailable: {schemas}")
        # Newer GTK uses glycin's system loader configuration for image formats.
        # Add it to existing profiles as well as newly prepared profiles.
        loaders = Path("/usr/share/glycin-loaders")
        if loaders.is_dir() and not (target / "glycin-loaders").exists():
            with tempfile.TemporaryDirectory(prefix=".glycin-", dir=target) as temporary:
                staging = Path(temporary) / "glycin-loaders"
                shutil.copytree(loaders, staging)
                try:
                    os.rename(staging, target / "glycin-loaders")
                except FileExistsError:
                    pass
        return target
    with tempfile.TemporaryDirectory(prefix=".gtk-data-", dir=state) as temporary:
        staging = Path(temporary) / "system-data"
        staging.mkdir(mode=0o700)
        for source, relative in (
            (Path("/usr/share/mime"), "mime"),
            (Path("/usr/share/glycin-loaders"), "glycin-loaders"),
            (Path("/usr/share/icons/hicolor"), "icons/hicolor"),
            (Path("/usr/share/icons/Adwaita"), "icons/Adwaita"),
            (Path("/usr/share/glib-2.0/schemas"), "glib-2.0/schemas"),
        ):
            if source.is_dir():
                shutil.copytree(source, staging / relative)
        if (
            not (staging / "mime/mime.cache").is_file()
            or not (staging / "icons/hicolor/index.theme").is_file()
            or not (staging / "glib-2.0/schemas/gschemas.compiled").is_file()
        ):
            raise DesktopError(
                "GUI mode requires system GTK MIME and hicolor icon data."
            )
        (staging / ".complete").write_text(
            "system GTK resources copied for candidate isolation\n", encoding="ascii"
        )
        try:
            os.rename(staging, target)
        except FileExistsError:
            _private_directory(target)
            if marker.is_symlink() or not marker.is_file():
                raise DesktopError(f"Incomplete private GTK data directory: {target}")
    return target


def prepare_desktop_environment(environment: Mapping[str, str]) -> dict[str, str]:
    """Root all candidate state and IPC under an explicitly selected profile."""
    value = environment.get("OBSERVATORY_CODEX_HOME", "")
    if not value:
        raise DesktopError(
            "GUI mode requires an explicit dedicated OBSERVATORY_CODEX_HOME."
        )
    home = Path(value)
    if not home.is_absolute():
        raise DesktopError("The selected CODEX_HOME must be an absolute path.")
    _private_directory(home)
    state = home / ".obs"
    state.mkdir(mode=0o700, exist_ok=True)
    _private_directory(state)
    dirs = {
        name: state / short
        for name, short in {
            "HOME": "r",
            "XDG_CONFIG_HOME": "config",
            "XDG_DATA_HOME": "data",
            "XDG_CACHE_HOME": "cache",
            "XDG_STATE_HOME": "state",
            "XDG_RUNTIME_DIR": "r",
            "TMPDIR": "tmp",
            "CODEX_ELECTRON_USER_DATA_PATH": "electron",
        }.items()
    }
    for path in dirs.values():
        path.mkdir(mode=0o700, exist_ok=True)
        _private_directory(path)
    runtime = dirs["XDG_RUNTIME_DIR"]
    longest = runtime / "a" / ("x" * 36 + ".sock")
    if len(os.fsencode(longest)) > 103:
        raise DesktopError(
            f"OBSERVATORY_CODEX_HOME is too long for Desktop IPC: {home}"
        )
    system_data = _prepare_system_desktop_data(state)
    child = dict(environment)
    for key in list(child):
        if (
            key.startswith("XDG_")
            and (key.endswith("_DIR") or key.endswith("_DIRS") or key.endswith("_HOME"))
        ) or key in {
            "CODEX_ELECTRON_USER_DATA_DIR",
            "CODEX_APP_TOOLS_PIPE_PATH",
            "BROWSER_USE_ACCESS_PIPE_PATH",
            "CODEX_LINUX_APP_STATE_DIR",
            "CODEX_LINUX_APP_CACHE_DIR",
            "CODEX_LINUX_SETTINGS_FILE",
            "CODEX_LINUX_FEATURE_HOOK_PHASE",
            "DBUS_SESSION_BUS_ADDRESS",
            "SSH_AUTH_SOCK",
            "GPG_AGENT_INFO",
        }:
            child.pop(key, None)
    child.update({key: str(path) for key, path in dirs.items()})
    child.update(
        {
            "CODEX_HOME": str(home),
            "XDG_CONFIG_DIRS": str(dirs["XDG_CONFIG_HOME"]),
            "XDG_DATA_DIRS": str(system_data),
            "GSETTINGS_SCHEMA_DIR": str(system_data / "glib-2.0/schemas"),
            "TMP": str(dirs["TMPDIR"]),
            "TEMP": str(dirs["TMPDIR"]),
            "OBSERVATORY_DESKTOP_IPC_ROOT": str(runtime),
            "CODEX_LINUX_APP_ID": "codex-observatory-0-3",
            "CODEX_LINUX_APP_DISPLAY_NAME": "Codex Observatory 0.3",
            "OBSERVATORY_DESKTOP_LAUNCH": "1",
        }
    )
    return child


def _refresh_cached_browser_services(candidate: DesktopCandidate, home: Path) -> None:
    """Keep this dedicated profile's managed plugin cache on the verified bundle."""
    plugins = candidate.start.parent / "resources/plugins/openai-bundled/plugins"
    for plugin in ("browser", "chrome"):
        cached = (
            home
            / "plugins/cache/openai-bundled"
            / plugin
            / RELEASE["desktop"]["version"]
            / "scripts/browser-service.mjs"
        )
        if not cached.exists() and not cached.is_symlink():
            continue
        if (
            cached.is_symlink()
            or cached.resolve() != cached
            or not cached.is_file()
            or cached.stat().st_uid != os.getuid()
        ):
            raise DesktopError(
                f"Desktop browser plugin cache is not an owned real file: {cached}"
            )
        source = plugins / plugin / "scripts/browser-service.mjs"
        if _sha256(cached) == _sha256(source):
            continue
        descriptor, temporary = tempfile.mkstemp(
            prefix=".observatory-browser-", dir=cached.parent
        )
        try:
            with os.fdopen(descriptor, "wb") as target, source.open("rb") as original:
                shutil.copyfileobj(original, target)
                target.flush()
                os.fsync(target.fileno())
            os.chmod(temporary, cached.stat().st_mode & 0o777)
            os.replace(temporary, cached)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


def _prepare_bridge(
    run_dir: Path, bridge_template: Path, codex_bin: Path, tools: Path
) -> Path:
    _executable(bridge_template, "Packaged Desktop Core bridge")
    bridge_dir = run_dir / "desktop-cli"
    bridge_dir.mkdir(mode=0o700)
    bridge = bridge_dir / "codex"
    shutil.copyfile(bridge_template, bridge)
    bridge.chmod(0o700)
    (bridge_dir / "real-codex").symlink_to(codex_bin)
    (bridge_dir / "codex-app-tools").symlink_to(tools, target_is_directory=True)
    return bridge


def _prepare_socket(environment: Mapping[str, str]) -> Path:
    runtime = _private_directory(Path(environment["XDG_RUNTIME_DIR"]))
    socket = runtime / "app.sock"
    for path in (socket, runtime / "bus"):
        if path.exists() or path.is_symlink():
            raise DesktopError(f"Desktop IPC path already exists: {path}")
    return socket


def _dbus_config(runtime: Path) -> Path:
    address = escape("unix:path=" + quote(str(runtime / "bus"), safe="/._-"))
    config = f"""<!DOCTYPE busconfig PUBLIC "-//freedesktop//DTD D-Bus Bus Configuration 1.0//EN" "http://www.freedesktop.org/standards/dbus/1.0/busconfig.dtd">
<busconfig><type>session</type><listen>{address}</listen><auth>EXTERNAL</auth><policy context="default"><allow send_destination="*" eavesdrop="true"/><allow eavesdrop="true"/><allow own="*"/></policy></busconfig>\n"""
    path = runtime / "dbus.conf"
    if path.is_symlink():
        raise DesktopError(f"Desktop D-Bus configuration is a symlink: {path}")
    if path.exists() and path.read_text(encoding="utf-8") != config:
        raise DesktopError(
            f"Desktop D-Bus configuration differs from the expected private bus: {path}"
        )
    if not path.exists():
        path.write_text(config, encoding="utf-8")
        path.chmod(0o600)
    return path


@dataclass(frozen=True)
class _OwnedSocket:
    rendezvous: Path
    alias_identity: tuple[int, int]
    physical: Path
    physical_identity: tuple[int, int]
    lock: Path
    lock_identity: tuple[int, int]
    lock_contents: bytes
    processes: tuple[tuple[int, str], ...]


def _identity(info: os.stat_result) -> tuple[int, int]:
    return info.st_dev, info.st_ino


def _process_state(pid: int) -> tuple[str, str] | None:
    try:
        text = Path(f"/proc/{pid}/stat").read_text(encoding="ascii")
    except FileNotFoundError:
        return None
    fields = text[text.rfind(")") + 2 :].split()
    return fields[0], fields[19]


def _remember_owned_socket(
    process: subprocess.Popen,
    rendezvous: Path,
    physical: Path,
    alias: os.stat_result,
    endpoint: os.stat_result,
) -> None:
    lock = rendezvous.with_name(rendezvous.name + ".lock")
    descriptor = os.open(lock, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        info = os.fstat(descriptor)
        contents = os.read(descriptor, 256)
    finally:
        os.close(descriptor)
    parts = contents.split()
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.getuid()
        or info.st_mode & 0o077
        or _identity(info) != _identity(lock.lstat())
        or len(parts) != 4
        or not all(part.isdigit() for part in parts)
    ):
        raise DesktopError(f"Desktop socket ownership lock is invalid: {lock}")
    identities = (
        (int(parts[0]), parts[1].decode("ascii")),
        (int(parts[2]), parts[3].decode("ascii")),
    )
    for pid, start in identities:
        state = _process_state(pid)
        if (
            state is None
            or state[0] == "Z"
            or state[1] != start
            or os.getpgid(pid) != process.pid
        ):
            raise DesktopError(
                f"Desktop socket owner is outside the launched process group: {pid}"
            )
    process._observatory_socket = _OwnedSocket(
        rendezvous,
        _identity(alias),
        physical,
        _identity(endpoint),
        lock,
        _identity(info),
        contents,
        identities,
    )


def _cleanup_owned_socket(snapshot: _OwnedSocket | None) -> None:
    if snapshot is None:
        return
    deadline = time.monotonic() + 0.5
    while time.monotonic() < deadline:
        if all(
            (state := _process_state(pid)) is None
            or state[0] == "Z"
            or state[1] != start
            for pid, start in snapshot.processes
        ):
            break
        time.sleep(0.025)
    else:
        print(
            f"Desktop: socket owners are still running; retained {snapshot.rendezvous}",
            file=sys.stderr,
        )
        return
    try:
        for path, expected in (
            (snapshot.rendezvous, snapshot.alias_identity),
            (snapshot.physical, snapshot.physical_identity),
            (snapshot.lock, snapshot.lock_identity),
        ):
            try:
                current = path.lstat()
            except FileNotFoundError:
                continue
            if current.st_uid != os.getuid() or _identity(current) != expected:
                raise DesktopError(f"Desktop IPC identity changed: {path}")
        if (
            snapshot.rendezvous.is_symlink()
            and snapshot.rendezvous.readlink() != snapshot.physical
        ):
            raise DesktopError(
                f"Desktop rendezvous target changed: {snapshot.rendezvous}"
            )
        if (
            snapshot.lock.exists()
            and snapshot.lock.read_bytes() != snapshot.lock_contents
        ):
            raise DesktopError(f"Desktop socket lock changed: {snapshot.lock}")
        if any(
            line.split()[-1:] == [str(snapshot.physical)]
            for line in Path("/proc/net/unix").read_text(encoding="ascii").splitlines()
        ):
            raise DesktopError(
                f"Desktop physical socket is still in use: {snapshot.physical}"
            )
        for path, expected in (
            (snapshot.physical, snapshot.physical_identity),
            (snapshot.rendezvous, snapshot.alias_identity),
            (snapshot.lock, snapshot.lock_identity),
        ):
            try:
                if _identity(path.lstat()) != expected:
                    raise DesktopError(f"Desktop IPC identity changed: {path}")
                path.unlink()
            except FileNotFoundError:
                pass
    except (OSError, DesktopError) as exc:
        print(
            f"Desktop: retained IPC paths because safe cleanup could not be verified: {exc}",
            file=sys.stderr,
        )


def _wait_for_socket(
    socket_path: Path, process: subprocess.Popen, log_path: Path, timeout: float
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            recent = log_path.read_text(encoding="utf-8", errors="replace")[-4000:]
            raise DesktopError(f"Codex GUI exited before connecting:\n{recent}")
        try:
            alias = socket_path.lstat()
            if not stat.S_ISLNK(alias.st_mode) or alias.st_uid != os.getuid():
                raise DesktopError(
                    f"Desktop socket rendezvous is not an owned symlink: {socket_path}"
                )
            physical = socket_path.resolve(strict=True)
            daemon_dir = Path("/tmp").resolve() / f"codex-daemon-{os.getuid()}"
            expected = daemon_dir / hashlib.sha256(os.fsencode(socket_path)).hexdigest()
            directory = daemon_dir.lstat()
            endpoint = physical.stat()
            if (
                physical != expected
                or not stat.S_ISDIR(directory.st_mode)
                or directory.st_uid != os.getuid()
                or directory.st_mode & 0o777 != 0o700
                or not stat.S_ISSOCK(endpoint.st_mode)
                or endpoint.st_uid != os.getuid()
            ):
                raise DesktopError(
                    f"Desktop socket has an unexpected physical endpoint: {physical}"
                )
            _remember_owned_socket(process, socket_path, physical, alias, endpoint)
            return
        except FileNotFoundError:
            pass
        time.sleep(0.1)
    recent = log_path.read_text(encoding="utf-8", errors="replace")[-4000:]
    raise DesktopError(
        f"Timed out waiting for the Codex GUI connection at {socket_path}.\n{recent}"
    )


def stop_desktop(process: subprocess.Popen | None) -> None:
    """Stop the candidate group and remove only its recorded stale socket paths."""
    if process is None:
        return
    previous = {}
    try:
        # A second signal while unwinding must not interrupt cleanup.
        for signum in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
            previous[signum] = signal.signal(signum, signal.SIG_IGN)
        with stop_owned_descendants(process):
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            deadline = time.monotonic() + 1
            while time.monotonic() < deadline:
                process.poll()
                try:
                    os.killpg(process.pid, 0)
                except ProcessLookupError:
                    break
                time.sleep(0.05)
            else:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            process.wait()
        _cleanup_owned_socket(getattr(process, "_observatory_socket", None))
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


def start_desktop(
    candidate: DesktopCandidate,
    *,
    bridge_template: Path,
    codex_bin: Path,
    run_dir: Path,
    trace_root: Path,
    workspace: Path,
    environment: Mapping[str, str],
    log_path: Path,
    timeout: float,
) -> tuple[subprocess.Popen, Path]:
    """Start Desktop in its own process group and private D-Bus session."""
    child = prepare_desktop_environment(environment)
    dbus = shutil.which("dbus-run-session", path=child.get("PATH"))
    if not dbus:
        raise DesktopError(
            "GUI mode requires dbus-run-session for its private session bus."
        )
    socket = _prepare_socket(child)
    _refresh_cached_browser_services(candidate, Path(child["CODEX_HOME"]))
    config = _dbus_config(Path(child["XDG_RUNTIME_DIR"]))
    bridge = _prepare_bridge(
        run_dir, bridge_template, codex_bin, candidate.codex_app_tools_root
    )
    child.update(
        {
            "CODEX_CLI_PATH": str(bridge),
            "CODEX_ROLLOUT_TRACE_RUN_DIR": str(trace_root),
            "CODEX_INTERNAL_APP_SERVER_REMOTE_CONTROL_DISABLED": "1",
            "CODEX_REMOTE_CONTROL_DAEMON_AUTOSTART_DISABLED": "1",
            "CODEX_LINUX_APP_SERVER_BRIDGE_SOCKET": str(socket),
        }
    )
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            [
                dbus,
                "--config-file",
                str(config),
                "--",
                str(candidate.start),
                "--new-instance",
                f"--user-data-dir={child['CODEX_ELECTRON_USER_DATA_PATH']}",
            ],
            cwd=workspace,
            env=child,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    print(
        "Chrome extension integration is disabled in the isolated Desktop candidate; in-app browser remains available.",
        flush=True,
    )
    try:
        _wait_for_socket(socket, process, log_path, timeout)
        print(
            f"Core socket: profile rendezvous {socket} -> protected endpoint {socket.resolve()}",
            flush=True,
        )
    except BaseException:
        stop_desktop(process)
        raise
    return process, socket


