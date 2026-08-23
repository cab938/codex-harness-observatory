#!/usr/bin/env bash

set -Eeuo pipefail

demonstration_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
environment_file="$demonstration_dir/.env"

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
: "${OBSERVATORY_VIEWER_SCRIPT:?missing OBSERVATORY_VIEWER_SCRIPT in .env}"
: "${OBSERVATORY_PYTHON:?missing OBSERVATORY_PYTHON in .env}"
: "${OBSERVATORY_APP_SERVER_HOST:?missing OBSERVATORY_APP_SERVER_HOST in .env}"
: "${OBSERVATORY_APP_SERVER_PORT:?missing OBSERVATORY_APP_SERVER_PORT in .env}"
: "${OBSERVATORY_VIEWER_HOST:?missing OBSERVATORY_VIEWER_HOST in .env}"
: "${OBSERVATORY_VIEWER_PORT:?missing OBSERVATORY_VIEWER_PORT in .env}"
: "${OBSERVATORY_SHOW_CONTENT:?missing OBSERVATORY_SHOW_CONTENT in .env}"
: "${OBSERVATORY_WORKSPACE:?missing OBSERVATORY_WORKSPACE in .env}"
: "${OBSERVATORY_RUNS_DIR:?missing OBSERVATORY_RUNS_DIR in .env}"
: "${OBSERVATORY_STARTUP_TIMEOUT_SECONDS:?missing OBSERVATORY_STARTUP_TIMEOUT_SECONDS in .env}"
: "${OBSERVATORY_DISABLE_REMOTE_CONTROL:?missing OBSERVATORY_DISABLE_REMOTE_CONTROL in .env}"

require_port "OBSERVATORY_APP_SERVER_PORT" "$OBSERVATORY_APP_SERVER_PORT"
require_port "OBSERVATORY_VIEWER_PORT" "$OBSERVATORY_VIEWER_PORT"
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

if [[ -z "$codex_bin" || ! -x "$codex_bin" ]]; then
  echo "run.sh: patched Codex binary is not executable: ${codex_bin:-$OBSERVATORY_CODEX_BIN}" >&2
  echo "Build it first with: (cd codex-rs && cargo build -p codex-cli --bin codex)" >&2
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

mkdir -p -- "$runs_dir"
run_dir="$(mktemp -d "$runs_dir/run-$(date +%Y%m%d-%H%M%S).XXXXXX")"
trace_root="$run_dir/traces"
app_server_log="$run_dir/app-server.log"
viewer_log="$run_dir/trace-viewer.log"
mkdir -p -- "$trace_root"

app_server_url="ws://${OBSERVATORY_APP_SERVER_HOST}:${OBSERVATORY_APP_SERVER_PORT}"
app_server_ready_url="http://${OBSERVATORY_APP_SERVER_HOST}:${OBSERVATORY_APP_SERVER_PORT}/readyz"
viewer_url="http://${OBSERVATORY_VIEWER_HOST}:${OBSERVATORY_VIEWER_PORT}"
app_server_pid=""
viewer_pid=""
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

viewer_content_args=()
if [[ "$OBSERVATORY_SHOW_CONTENT" == "1" ]]; then
  viewer_content_args+=(--show-content)
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
if [[ "$OBSERVATORY_SHOW_CONTENT" == "1" ]]; then
  echo "  Content:  full teaching evidence (prompts, responses, and tool payloads)"
else
  echo "  Content:  redacted metadata only"
fi
echo

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
