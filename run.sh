#!/usr/bin/env bash

set -Eeuo pipefail

demonstration_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
environment_file="$demonstration_dir/.env"

usage() {
  cat <<'EOF'
Usage: ./run.sh [--tui | --desktop]

Starts the Harness Observatory with its existing TUI client by default.
Use --desktop to launch the separately built Codex Observatory Desktop candidate
against one retained, full-evidence rollout-trace run.
EOF
}

client_mode="tui"
case "$#" in
  0) ;;
  1)
    case "$1" in
      --tui) client_mode="tui" ;;
      --desktop) client_mode="desktop" ;;
      -h | --help) usage; exit 0 ;;
      *)
        echo "run.sh: unknown option: $1" >&2
        usage >&2
        exit 2
        ;;
    esac
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac

if [[ ! -f "$environment_file" ]]; then
  echo "run.sh: missing $environment_file" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "$environment_file"
set +a

resolve_path() {
  local value="$1"
  if [[ "$value" == /* ]]; then
    printf '%s\n' "$value"
  else
    printf '%s/%s\n' "$demonstration_dir" "$value"
  fi
}

resolve_command() {
  local value="$1"
  if [[ "$value" == */* ]]; then
    resolve_path "$value"
  else
    command -v -- "$value" 2>/dev/null || true
  fi
}

require_port() {
  local label="$1"
  local value="$2"
  if [[ ! "$value" =~ ^[0-9]+$ ]] || ((value < 1 || value > 65535)); then
    echo "run.sh: $label must be an integer from 1 through 65535 (got '$value')" >&2
    exit 1
  fi
}

: "${OBSERVATORY_CODEX_BIN:?missing OBSERVATORY_CODEX_BIN in .env}"
: "${OBSERVATORY_CORE_UPSTREAM_TAG:?missing OBSERVATORY_CORE_UPSTREAM_TAG in .env}"
: "${OBSERVATORY_CORE_UPSTREAM_COMMIT:?missing OBSERVATORY_CORE_UPSTREAM_COMMIT in .env}"
: "${OBSERVATORY_CORE_VERSION:?missing OBSERVATORY_CORE_VERSION in .env}"
: "${OBSERVATORY_DESKTOP_PACKAGE_VERSION:?missing OBSERVATORY_DESKTOP_PACKAGE_VERSION in .env}"
: "${OBSERVATORY_DESKTOP_PACKAGE_SHA256:?missing OBSERVATORY_DESKTOP_PACKAGE_SHA256 in .env}"
: "${OBSERVATORY_VIEWER_SCRIPT:?missing OBSERVATORY_VIEWER_SCRIPT in .env}"
: "${OBSERVATORY_PYTHON:?missing OBSERVATORY_PYTHON in .env}"
: "${OBSERVATORY_VIEWER_HOST:?missing OBSERVATORY_VIEWER_HOST in .env}"
: "${OBSERVATORY_VIEWER_PORT:?missing OBSERVATORY_VIEWER_PORT in .env}"
: "${OBSERVATORY_SHOW_CONTENT:?missing OBSERVATORY_SHOW_CONTENT in .env}"
: "${OBSERVATORY_WORKSPACE:?missing OBSERVATORY_WORKSPACE in .env}"
: "${OBSERVATORY_RUNS_DIR:?missing OBSERVATORY_RUNS_DIR in .env}"
: "${OBSERVATORY_STARTUP_TIMEOUT_SECONDS:?missing OBSERVATORY_STARTUP_TIMEOUT_SECONDS in .env}"

if [[ "$client_mode" == "tui" ]]; then
  : "${OBSERVATORY_APP_SERVER_HOST:?missing OBSERVATORY_APP_SERVER_HOST in .env}"
  : "${OBSERVATORY_APP_SERVER_PORT:?missing OBSERVATORY_APP_SERVER_PORT in .env}"
  : "${OBSERVATORY_DISABLE_REMOTE_CONTROL:?missing OBSERVATORY_DISABLE_REMOTE_CONTROL in .env}"
else
  : "${OBSERVATORY_DESKTOP_START:?missing OBSERVATORY_DESKTOP_START in .env}"
fi

require_port "OBSERVATORY_VIEWER_PORT" "$OBSERVATORY_VIEWER_PORT"
if [[ "$client_mode" == "tui" ]]; then
  require_port "OBSERVATORY_APP_SERVER_PORT" "$OBSERVATORY_APP_SERVER_PORT"
fi
if [[ ! "$OBSERVATORY_STARTUP_TIMEOUT_SECONDS" =~ ^[1-9][0-9]*$ ]]; then
  echo "run.sh: OBSERVATORY_STARTUP_TIMEOUT_SECONDS must be a positive integer" >&2
  exit 1
fi
if [[ "$OBSERVATORY_SHOW_CONTENT" != "0" && "$OBSERVATORY_SHOW_CONTENT" != "1" ]]; then
  echo "run.sh: OBSERVATORY_SHOW_CONTENT must be 0 or 1" >&2
  exit 1
fi

codex_bin="$(resolve_command "$OBSERVATORY_CODEX_BIN")"
python_bin="$(resolve_command "$OBSERVATORY_PYTHON")"
viewer_script="$(resolve_path "$OBSERVATORY_VIEWER_SCRIPT")"
workspace="$(resolve_path "$OBSERVATORY_WORKSPACE")"
runs_dir="$(resolve_path "$OBSERVATORY_RUNS_DIR")"
desktop_start=""
desktop_feature_hook=""
desktop_home_description=""

if [[ -z "$codex_bin" || ! -x "$codex_bin" ]]; then
  echo "run.sh: patched Codex binary is not executable: ${codex_bin:-$OBSERVATORY_CODEX_BIN}" >&2
  echo "Build it first with: (cd codex-rs && cargo build -p codex-cli --bin codex)" >&2
  exit 1
fi
actual_core_version="$("$codex_bin" --version 2>/dev/null)"
expected_core_version="codex-cli $OBSERVATORY_CORE_VERSION"
if [[ "$actual_core_version" != "$expected_core_version" ]]; then
  echo "run.sh: patched Core is '$actual_core_version'; expected '$expected_core_version'" >&2
  exit 1
fi
if ! command -v git >/dev/null 2>&1; then
  echo "run.sh: git is required to verify the Core source pin" >&2
  exit 1
fi
tagged_core_commit="$(git -C "$demonstration_dir" rev-parse "${OBSERVATORY_CORE_UPSTREAM_TAG}^{commit}" 2>/dev/null || true)"
if [[ "$tagged_core_commit" != "$OBSERVATORY_CORE_UPSTREAM_COMMIT" ]]; then
  echo "run.sh: $OBSERVATORY_CORE_UPSTREAM_TAG resolves to '${tagged_core_commit:-missing}'; expected $OBSERVATORY_CORE_UPSTREAM_COMMIT" >&2
  exit 1
fi
if ! git -C "$demonstration_dir" merge-base --is-ancestor "$OBSERVATORY_CORE_UPSTREAM_COMMIT" HEAD; then
  echo "run.sh: current source does not contain pinned Core commit $OBSERVATORY_CORE_UPSTREAM_COMMIT" >&2
  exit 1
fi
if [[ -z "$python_bin" || ! -x "$python_bin" ]]; then
  echo "run.sh: Python executable was not found: $OBSERVATORY_PYTHON" >&2
  exit 1
fi
if [[ ! -f "$viewer_script" ]]; then
  echo "run.sh: trace viewer was not found: $viewer_script" >&2
  exit 1
fi
if [[ ! -d "$workspace" ]]; then
  echo "run.sh: Codex workspace is not a directory: $workspace" >&2
  exit 1
fi
if ! command -v curl >/dev/null 2>&1; then
  echo "run.sh: curl is required for service readiness checks" >&2
  exit 1
fi

if [[ "$client_mode" == "desktop" ]]; then
  desktop_start="$(resolve_path "$OBSERVATORY_DESKTOP_START")"
  if [[ ! -x "$desktop_start" ]]; then
    echo "run.sh: Desktop candidate launcher is not executable: $desktop_start" >&2
    echo "Build it first with: $demonstration_dir/build-desktop-observatory.sh" >&2
    exit 1
  fi
  desktop_feature_hook="$(dirname -- "$desktop_start")/.codex-linux/launcher.d/shared-app-server-socket-socket-env.sh"
  if [[ ! -x "$desktop_feature_hook" ]]; then
    echo "run.sh: Desktop candidate does not include the shared-app-server-socket feature: $desktop_feature_hook" >&2
    echo "Rebuild it with: $demonstration_dir/build-desktop-observatory.sh" >&2
    exit 1
  fi
  desktop_app_dir="$(dirname -- "$desktop_start")"
  desktop_bundled_codex="$desktop_app_dir/resources/codex"
  desktop_package_control="$desktop_app_dir/.codex-linux/upstream-package/control"
  desktop_build_info="$desktop_app_dir/.codex-linux/build-info.json"
  if [[ ! -x "$desktop_bundled_codex" || ! -f "$desktop_package_control" || ! -f "$desktop_build_info" ]]; then
    echo "run.sh: Desktop candidate is missing bundled Core or provenance metadata" >&2
    echo "Rebuild it with: $demonstration_dir/build-desktop-observatory.sh" >&2
    exit 1
  fi
  desktop_bundled_version="$("$desktop_bundled_codex" --version 2>/dev/null)"
  desktop_package_version="$(sed -n 's/^Version: //p' "$desktop_package_control")"
  desktop_package_sha256="$(sed -n 's/.*"sha256": "\([^"]*\)".*/\1/p' "$desktop_build_info")"
  if [[ "$desktop_bundled_version" != "$expected_core_version" \
    || "$desktop_package_version" != "$OBSERVATORY_DESKTOP_PACKAGE_VERSION" \
    || "$desktop_package_sha256" != "$OBSERVATORY_DESKTOP_PACKAGE_SHA256" ]]; then
    echo "run.sh: Desktop candidate does not match the pinned teaching artifact" >&2
    echo "Rebuild it with: $demonstration_dir/build-desktop-observatory.sh" >&2
    exit 1
  fi
  if ! command -v setsid >/dev/null 2>&1; then
    echo "run.sh: setsid is required to manage only the Desktop process group started by this launcher" >&2
    exit 1
  fi
  if [[ -n "${OBSERVATORY_CODEX_HOME:-}" ]]; then
    export CODEX_HOME="$OBSERVATORY_CODEX_HOME"
    desktop_home_description="selected CODEX_HOME: $CODEX_HOME"
  elif [[ -v CODEX_HOME && -n "$CODEX_HOME" ]]; then
    export CODEX_HOME
    desktop_home_description="inherited CODEX_HOME: $CODEX_HOME"
  else
    desktop_home_description="normal Codex login/default profile (CODEX_HOME unset)"
  fi
fi

mkdir -p -- "$runs_dir"
run_dir="$(mktemp -d "$runs_dir/run-$(date +%Y%m%d-%H%M%S).XXXXXX")"
trace_root="$run_dir/traces"
app_server_log="$run_dir/app-server.log"
viewer_log="$run_dir/trace-viewer.log"
desktop_log="$run_dir/desktop.log"
mkdir -p -- "$trace_root"

app_server_url=""
app_server_ready_url=""
if [[ "$client_mode" == "tui" ]]; then
  app_server_url="ws://${OBSERVATORY_APP_SERVER_HOST}:${OBSERVATORY_APP_SERVER_PORT}"
  app_server_ready_url="http://${OBSERVATORY_APP_SERVER_HOST}:${OBSERVATORY_APP_SERVER_PORT}/readyz"
fi
viewer_url="http://${OBSERVATORY_VIEWER_HOST}:${OBSERVATORY_VIEWER_PORT}"
app_server_pid=""
viewer_pid=""
desktop_pid=""
desktop_socket=""
cleanup_started=0

stop_process() {
  local label="$1"
  local process_id="$2"
  if [[ -z "$process_id" ]] || ! kill -0 "$process_id" >/dev/null 2>&1; then
    return
  fi

  kill "$process_id" >/dev/null 2>&1 || true
  for _ in {1..50}; do
    if ! kill -0 "$process_id" >/dev/null 2>&1; then
      wait "$process_id" >/dev/null 2>&1 || true
      echo "$label stopped."
      return
    fi
    sleep 0.1
  done

  echo "$label did not stop after 5 seconds; terminating it forcefully." >&2
  kill -KILL "$process_id" >/dev/null 2>&1 || true
  wait "$process_id" >/dev/null 2>&1 || true
  echo "$label stopped."
}

stop_process_group() {
  local label="$1"
  local process_group_id="$2"
  if [[ -z "$process_group_id" ]] || ! kill -0 -- "-$process_group_id" >/dev/null 2>&1; then
    return
  fi

  kill -TERM -- "-$process_group_id" >/dev/null 2>&1 || true
  for _ in {1..50}; do
    if ! kill -0 -- "-$process_group_id" >/dev/null 2>&1; then
      wait "$process_group_id" >/dev/null 2>&1 || true
      echo "$label stopped."
      return
    fi
    sleep 0.1
  done

  echo "$label did not stop after 5 seconds; terminating its process group forcefully." >&2
  kill -KILL -- "-$process_group_id" >/dev/null 2>&1 || true
  wait "$process_group_id" >/dev/null 2>&1 || true
  echo "$label stopped."
}

cleanup() {
  local original_status=$?
  if ((cleanup_started)); then
    return "$original_status"
  fi
  cleanup_started=1
  trap - EXIT INT TERM HUP
  set +e
  echo
  echo "Shutting down the Codex harness observatory..."
  stop_process_group "Codex Desktop candidate" "$desktop_pid"
  stop_process "Codex app server" "$app_server_pid"
  stop_process "Log web server" "$viewer_pid"
  echo "Run artifacts retained at: $run_dir"
  return "$original_status"
}

handle_signal() {
  local status="$1"
  exit "$status"
}

trap cleanup EXIT
trap 'handle_signal 130' INT
trap 'handle_signal 143' TERM
trap 'handle_signal 129' HUP

show_startup_failure() {
  local label="$1"
  local log_file="$2"
  echo "run.sh: $label failed to start; recent log output follows:" >&2
  tail -n 30 -- "$log_file" >&2 || true
}

wait_for_service() {
  local label="$1"
  local ready_url="$2"
  local process_id="$3"
  local log_file="$4"
  local attempts=$((OBSERVATORY_STARTUP_TIMEOUT_SECONDS * 10))

  for ((attempt = 0; attempt < attempts; attempt++)); do
    if ! kill -0 "$process_id" >/dev/null 2>&1; then
      show_startup_failure "$label" "$log_file"
      return 1
    fi
    if curl --fail --silent --show-error --max-time 1 "$ready_url" >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.1
  done

  echo "run.sh: timed out waiting for $label at $ready_url" >&2
  show_startup_failure "$label" "$log_file"
  return 1
}

wait_for_socket() {
  local label="$1"
  local socket_path="$2"
  local process_id="$3"
  local log_file="$4"
  local attempts=$((OBSERVATORY_STARTUP_TIMEOUT_SECONDS * 10))

  for ((attempt = 0; attempt < attempts; attempt++)); do
    if ! kill -0 "$process_id" >/dev/null 2>&1; then
      show_startup_failure "$label" "$log_file"
      return 1
    fi
    if [[ -S "$socket_path" ]]; then
      if [[ ! -O "$socket_path" ]]; then
        echo "run.sh: $label was created by a different user: $socket_path" >&2
        return 1
      fi
      return 0
    fi
    sleep 0.1
  done

  echo "run.sh: timed out waiting for $label at $socket_path" >&2
  show_startup_failure "$label" "$log_file"
  return 1
}

start_viewer() {
  local -a viewer_content_args=()
  if [[ "$client_mode" == "desktop" || "$OBSERVATORY_SHOW_CONTENT" == "1" ]]; then
    viewer_content_args+=(--show-content)
  else
    viewer_content_args+=(--redact-content)
  fi

  "$python_bin" "$viewer_script" "$trace_root" \
    --serve \
    --wait-for-bundle \
    "${viewer_content_args[@]}" \
    --host "$OBSERVATORY_VIEWER_HOST" \
    --port "$OBSERVATORY_VIEWER_PORT" \
    >"$viewer_log" 2>&1 &
  viewer_pid=$!

  wait_for_service "log web server" "$viewer_url/" "$viewer_pid" "$viewer_log"
  echo "Log web server started."
  echo "  Viewer:   $viewer_url"
  echo "  PID:      $viewer_pid"
  echo "  Traces:   $trace_root"
  echo "  Log:      $viewer_log"
  if [[ "$client_mode" == "desktop" || "$OBSERVATORY_SHOW_CONTENT" == "1" ]]; then
    echo "  Content:  full teaching evidence (prompts, responses, and tool payloads)"
  else
    echo "  Content:  redacted metadata only"
  fi
  echo
}

prepare_desktop_socket() {
  local socket_parent
  local socket_name
  local runtime_root="${XDG_RUNTIME_DIR:-}"
  if [[ -z "$runtime_root" || ! -d "$runtime_root" || ! -O "$runtime_root" ]]; then
    echo "run.sh: Desktop mode requires an existing user-owned XDG_RUNTIME_DIR" >&2
    exit 1
  fi
  if ! command -v realpath >/dev/null 2>&1; then
    echo "run.sh: Desktop mode requires realpath to validate the private socket path" >&2
    exit 1
  fi
  runtime_root="$(realpath -e -- "$runtime_root")"

  desktop_socket="${OBSERVATORY_DESKTOP_SOCKET:-$runtime_root/codex-observatory/app.sock}"
  desktop_socket="$(realpath -m -- "$desktop_socket")"
  case "$desktop_socket" in
    "$runtime_root"/*) ;;
    *)
      echo "run.sh: OBSERVATORY_DESKTOP_SOCKET must be under XDG_RUNTIME_DIR: $runtime_root" >&2
      exit 1
      ;;
  esac
  if ((${#desktop_socket} > 96)); then
    echo "run.sh: Desktop bridge socket path is too long for Unix sockets: $desktop_socket" >&2
    exit 1
  fi

  socket_parent="$(dirname -- "$desktop_socket")"
  socket_name="$(basename -- "$desktop_socket")"
  umask 077
  mkdir -p -- "$socket_parent"
  socket_parent="$(realpath -e -- "$socket_parent")"
  case "$socket_parent" in
    "$runtime_root" | "$runtime_root"/*) ;;
    *)
      echo "run.sh: Desktop bridge socket directory escaped XDG_RUNTIME_DIR: $socket_parent" >&2
      exit 1
      ;;
  esac
  desktop_socket="$socket_parent/$socket_name"
  chmod 0700 -- "$socket_parent"
  if [[ ! -d "$socket_parent" || ! -O "$socket_parent" ]]; then
    echo "run.sh: Desktop bridge socket directory is not private to this user: $socket_parent" >&2
    exit 1
  fi
  if [[ -S "$desktop_socket" || -e "$desktop_socket" || -L "$desktop_socket" ]]; then
    echo "run.sh: Desktop bridge socket path already exists: $desktop_socket" >&2
    echo "Close the previous Codex Observatory Desktop candidate or set a new short OBSERVATORY_DESKTOP_SOCKET." >&2
    exit 1
  fi
}

start_desktop() {
  prepare_desktop_socket
  (
    cd -- "$workspace"
    exec setsid env \
      CODEX_CLI_PATH="$codex_bin" \
      CODEX_ROLLOUT_TRACE_ROOT="$trace_root" \
      CODEX_ROLLOUT_TRACE_SHARED_RUN=1 \
      CODEX_INTERNAL_APP_SERVER_REMOTE_CONTROL_DISABLED=1 \
      CODEX_REMOTE_CONTROL_DAEMON_AUTOSTART_DISABLED=1 \
      CODEX_LINUX_APP_SERVER_BRIDGE_SOCKET="$desktop_socket" \
      "$desktop_start" --new-instance
  ) >"$desktop_log" 2>&1 &
  desktop_pid=$!

  wait_for_socket "Codex Desktop bridge socket" "$desktop_socket" "$desktop_pid" "$desktop_log"
  echo "Codex Desktop candidate started."
  echo "  PID:      $desktop_pid"
  echo "  Socket:   $desktop_socket"
  echo "  Log:      $desktop_log"
  echo "  Profile:  $desktop_home_description"
  echo
}

if [[ "$client_mode" == "desktop" ]]; then
  # The Desktop-owned app server does not create a bundle until Desktop connects,
  # so make the full-evidence viewer ready before launching the candidate.
  start_viewer
  start_desktop
  echo "Use the Codex Observatory Desktop window for the demonstration."
  echo "Closing that window stops this retained run's viewer and leaves its evidence on disk."
  set +e
  wait "$desktop_pid"
  desktop_status=$?
  set -e
  echo "Codex Desktop candidate exited; beginning shutdown."
  exit "$desktop_status"
fi

(
  cd -- "$workspace"
  exec env \
    CODEX_ROLLOUT_TRACE_ROOT="$trace_root" \
    CODEX_INTERNAL_APP_SERVER_REMOTE_CONTROL_DISABLED="$OBSERVATORY_DISABLE_REMOTE_CONTROL" \
    "$codex_bin" app-server --listen "$app_server_url"
) >"$app_server_log" 2>&1 &
app_server_pid=$!

wait_for_service "Codex app server" "$app_server_ready_url" "$app_server_pid" "$app_server_log"
echo "Codex app server started."
echo "  Endpoint: $app_server_url"
echo "  PID:      $app_server_pid"
echo "  Log:      $app_server_log"

start_viewer

while true; do
  if IFS= read -r -p "Start the Codex TUI and connect it to this app server? [Y/n] " answer; then
    case "${answer,,}" in
      "" | y | yes)
        echo "Starting the Codex TUI. Use /exit to return and shut down both servers."
        set +e
        "$codex_bin" --remote "$app_server_url" -C "$workspace"
        tui_status=$?
        set -e
        echo "Codex TUI exited; beginning shutdown."
        exit "$tui_status"
        ;;
      n | no)
        echo "Codex TUI was not started; beginning shutdown."
        exit 0
        ;;
      *)
        echo "Please answer Y or n. Press Enter for Y."
        ;;
    esac
  else
    echo
    echo "No answer was received. The servers remain available for another client."
    echo "Connect to $app_server_url, or press Ctrl-C to shut everything down."
    set +e
    wait -n "$app_server_pid" "$viewer_pid"
    service_status=$?
    set -e
    echo "A background server exited; beginning shutdown."
    exit "$service_status"
  fi
done
