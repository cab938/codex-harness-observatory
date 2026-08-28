#!/usr/bin/env bash

set -Eeuo pipefail

demonstration_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

usage() {
  cat <<'EOF'
Usage: ./build-desktop-observatory.sh [options]

Build a side-by-side Codex Desktop candidate that attaches to the Harness
Observatory's rebuilt CLI over the shared app-server Unix socket.

Options:
  --desktop-repo PATH  codex-desktop-linux checkout
  --app-dir PATH       candidate output directory
  --report-dir PATH    external installer report directory
  --upstream-deb PATH  use one already downloaded official chatgpt_*.deb
  -h, --help           show this help

Environment equivalents:
  OBSERVATORY_DESKTOP_REPO
  OBSERVATORY_DESKTOP_APP_DIR
  OBSERVATORY_DESKTOP_BUILD_REPORT_DIR

The helper does not inspect or copy CODEX_HOME credentials. Any explicit
CODEX_HOME remains inherited by the completed candidate at launch time.
EOF
}

fail() {
  echo "build-desktop-observatory.sh: $*" >&2
  exit 1
}

absolute_existing_directory() {
  local path="$1"
  if [[ "$path" != /* ]]; then
    path="$PWD/$path"
  fi
  [[ -d "$path" ]] || fail "directory does not exist: $path"
  cd -- "$path" && pwd -P
}

absolute_output_path() {
  local path="$1"
  local parent
  local base
  if [[ "$path" != /* ]]; then
    path="$PWD/$path"
  fi
  parent="$(dirname -- "$path")"
  base="$(basename -- "$path")"
  [[ -d "$parent" ]] || fail "parent directory does not exist: $parent"
  printf '%s/%s\n' "$(cd -- "$parent" && pwd -P)" "$base"
}

absolute_existing_file() {
  local path="$1"
  local parent
  local base
  if [[ "$path" != /* ]]; then
    path="$PWD/$path"
  fi
  [[ -f "$path" ]] || fail "file does not exist: $path"
  parent="$(dirname -- "$path")"
  base="$(basename -- "$path")"
  printf '%s/%s\n' "$(cd -- "$parent" && pwd -P)" "$base"
}

desktop_repo="${OBSERVATORY_DESKTOP_REPO:-/home/brooksch/sandboxes/codex-desktop-linux}"
app_dir="${OBSERVATORY_DESKTOP_APP_DIR:-}"
report_dir="${OBSERVATORY_DESKTOP_BUILD_REPORT_DIR:-}"
upstream_deb=""

while (($#)); do
  case "$1" in
    --desktop-repo)
      (($# >= 2)) || fail "--desktop-repo requires a path"
      desktop_repo="$2"
      shift 2
      ;;
    --app-dir)
      (($# >= 2)) || fail "--app-dir requires a path"
      app_dir="$2"
      shift 2
      ;;
    --report-dir)
      (($# >= 2)) || fail "--report-dir requires a path"
      report_dir="$2"
      shift 2
      ;;
    --upstream-deb)
      (($# >= 2)) || fail "--upstream-deb requires a path"
      upstream_deb="$2"
      shift 2
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      fail "unknown option: $1 (see --help)"
      ;;
  esac
done

desktop_repo="$(absolute_existing_directory "$desktop_repo")"
installer="$desktop_repo/install.sh"
feature_manifest="$desktop_repo/linux-features/shared-app-server-socket/feature.json"
[[ -x "$installer" ]] || fail "external Desktop install flow is not executable: $installer"
[[ -f "$feature_manifest" ]] || fail "shared-app-server-socket feature is missing: $feature_manifest"

if [[ -z "$app_dir" ]]; then
  app_dir="$desktop_repo/codex-observatory-app"
fi
if [[ -z "$report_dir" ]]; then
  report_dir="$desktop_repo/dist-next/observatory"
fi
app_dir="$(absolute_output_path "$app_dir")"
report_dir="$(absolute_output_path "$report_dir")"

if [[ "$app_dir" == "$desktop_repo" || "$app_dir" == "$desktop_repo/codex-app" ]]; then
  fail "candidate output must remain side-by-side, not $app_dir"
fi
if [[ -n "$upstream_deb" ]]; then
  upstream_deb="$(absolute_existing_file "$upstream_deb")"
  [[ "$(basename -- "$upstream_deb")" == *.deb ]] || fail "--upstream-deb must name an official chatgpt_*.deb package"
fi

umask 077
feature_config="$(mktemp "${TMPDIR:-/tmp}/codex-observatory-features.XXXXXX.json")"
cleanup() {
  rm -f -- "$feature_config"
}
trap cleanup EXIT
printf '%s\n' '{"enabled":["shared-app-server-socket"]}' >"$feature_config"

installer_args=()
if [[ -n "$upstream_deb" ]]; then
  installer_args+=("$upstream_deb")
fi

echo "Building Codex Observatory Desktop candidate at: $app_dir"
echo "Using Desktop source checkout: $desktop_repo"
echo "Enabling only: shared-app-server-socket"
(
  cd -- "$desktop_repo"
  exec env \
    CODEX_LINUX_FEATURES_CONFIG="$feature_config" \
    CODEX_APP_ID="codex-observatory" \
    CODEX_APP_DISPLAY_NAME="Codex Observatory" \
    CODEX_INSTALL_DIR="$app_dir" \
    REBUILD_REPORT_DIR="$report_dir" \
    "$installer" "${installer_args[@]}"
)

candidate_start="$app_dir/start.sh"
candidate_hook="$app_dir/.codex-linux/launcher.d/shared-app-server-socket-socket-env.sh"
[[ -x "$candidate_start" ]] || fail "installer completed without a candidate launcher: $candidate_start"
[[ -x "$candidate_hook" ]] || fail "installer completed without shared socket support: $candidate_hook"

echo "Desktop candidate is ready: $candidate_start"
echo "Launch the retained teaching run with:"
printf '  OBSERVATORY_DESKTOP_START=%q %q --desktop\n' "$candidate_start" "$demonstration_dir/run.sh"
