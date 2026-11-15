#!/usr/bin/env bash
set -Eeuo pipefail

root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)"
descriptor="$root/release.json"
feature_patch="$root/patches/desktop/shared-app-server-socket.patch"
isolation_patch="$root/patches/desktop/isolate-ipc.js"

usage() {
  cat <<'HELP'
Usage: ./build-desktop-observatory.sh --upstream-deb FILE --archive FILE
       [--companion-source URL-OR-REPOSITORY] [--work-parent DIRECTORY]

Build a relocatable, separately identified Desktop candidate in a new temporary
workspace. The official package must match the packaged release descriptor.
The archive must not already exist. No existing installation is replaced.
The companion source is cloned and checked out at the descriptor's pinned commit.
HELP
}
fail() { echo "build-desktop-observatory.sh: $*" >&2; exit 1; }

upstream_deb=""
archive=""
companion_source=""
work_parent="${TMPDIR:-/tmp}"
while (($#)); do
  case "$1" in
    --upstream-deb) (($# >= 2)) || fail "$1 requires a path"; upstream_deb="$2"; shift 2 ;;
    --archive) (($# >= 2)) || fail "$1 requires a path"; archive="$2"; shift 2 ;;
    --companion-source) (($# >= 2)) || fail "$1 requires a URL or path"; companion_source="$2"; shift 2 ;;
    --work-parent) (($# >= 2)) || fail "$1 requires a path"; work_parent="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) fail "unknown option: $1" ;;
  esac
done
[[ -f "$upstream_deb" ]] || fail "--upstream-deb must name the official .deb"
[[ -n "$archive" ]] || fail "--archive is required"
[[ ! -e "$archive" && ! -L "$archive" ]] || fail "archive already exists: $archive"
[[ -d "$(dirname -- "$archive")" ]] || fail "archive parent does not exist"
[[ -d "$work_parent" ]] || fail "work parent does not exist: $work_parent"
for command in python3 git node npx npm dpkg-deb gpgv sha256sum tar; do
  command -v "$command" >/dev/null || fail "required command is missing: $command"
done

# The packaged descriptor is the single authority for these pins.
eval "$(python3 - "$descriptor" <<'PY'
import json, shlex, sys
r = json.load(open(sys.argv[1], encoding='utf-8'))
d = r['desktop']
for name, value in {
    'core_tag': r['core']['upstream_tag'], 'core_commit': r['core']['upstream_commit'],
    'core_version': r['core']['version'], 'bundled_core_version': d['bundled_core_version'],
    'package_version': d['version'],
    'package_sha': d['package_sha256'], 'companion_url': d['companion_repository'],
    'companion_commit': d['companion_commit'], 'asar_version': d['asar_version'],
    'feature_sha': d['feature_patch_sha256'], 'isolation_sha': d['isolation_patch_sha256'],
}.items():
    print(f'{name}={shlex.quote(value)}')
PY
)"
[[ "$(sha256sum "$upstream_deb" | cut -d' ' -f1)" == "$package_sha" ]] || fail "official .deb SHA-256 does not match the release descriptor"
[[ "$(dpkg-deb -f "$upstream_deb" Package)" == chatgpt ]] || fail "unexpected package name"
[[ "$(dpkg-deb -f "$upstream_deb" Version)" == "$package_version" ]] || fail "unexpected package version"
[[ "$(dpkg-deb -f "$upstream_deb" Architecture)" == amd64 ]] || fail "expected an amd64 package"
[[ "$(sha256sum "$feature_patch" | cut -d' ' -f1)" == "$feature_sha" ]] || fail "feature patch digest does not match the descriptor"
[[ "$(sha256sum "$isolation_patch" | cut -d' ' -f1)" == "$isolation_sha" ]] || fail "IPC transform digest does not match the descriptor"
tagged="$(git -C "$root/lib/codex" rev-parse "${core_tag}^{commit}" 2>/dev/null || true)"
[[ "$tagged" == "$core_commit" ]] || fail "Core tag does not resolve to the descriptor commit"
git -C "$root/lib/codex" merge-base --is-ancestor "$core_commit" HEAD || fail "source does not contain the pinned Core"

upstream_deb="$(realpath -e -- "$upstream_deb")"
archive_parent="$(cd -- "$(dirname -- "$archive")" && pwd -P)"
archive="$archive_parent/$(basename -- "$archive")"
[[ -n "$companion_source" ]] || companion_source="$companion_url"
if [[ -d "$companion_source" ]]; then companion_source="$(realpath -e -- "$companion_source")"; fi
umask 077
work="$(mktemp -d "$work_parent/codex-observatory-desktop-build.XXXXXX")"
archive_tmp="$(mktemp "$archive_parent/.observatory-desktop-archive.XXXXXX")"
cleanup() { rm -rf -- "$work"; rm -f -- "$archive_tmp"; }
trap cleanup EXIT

mkdir -p "$work/home" "$work/tmp" "$work/reports"
git clone --quiet --no-checkout --no-hardlinks -- "$companion_source" "$work/companion"
git -C "$work/companion" checkout --quiet --detach "$companion_commit"
[[ "$(git -C "$work/companion" rev-parse HEAD)" == "$companion_commit" ]] || fail "companion checkout did not reach the pinned commit"
git -C "$work/companion" apply --check "$feature_patch"
git -C "$work/companion" apply "$feature_patch"
cp "$isolation_patch" "$work/companion/linux-features/shared-app-server-socket/observatory-isolation.js"
printf '\nmodule.exports.descriptors.push(...require("./observatory-isolation.js").descriptors);\n' >> "$work/companion/linux-features/shared-app-server-socket/patch.js"
HOME="$work/home" npm_config_cache="$work/npm-cache" npm install --silent --no-save --prefix "$work/asar" "@electron/asar@$asar_version"
asar_bin="$work/asar/node_modules/.bin/asar"
printf '%s\n' '{"enabled":["shared-app-server-socket"]}' > "$work/features.json"
app="$work/codex-observatory-desktop"
echo "Building isolated Desktop candidate from companion $companion_commit"
env -i \
  PATH="$PATH" HOME="$work/home" TMPDIR="$work/tmp" \
  npm_config_cache="$work/npm-cache" CODEX_ASAR_BIN="$asar_bin" \
  CODEX_LINUX_FEATURES_CONFIG="$work/features.json" \
  CODEX_APP_ID=codex-observatory-0-3 \
  CODEX_APP_DISPLAY_NAME="Codex Observatory 0.3" \
  CODEX_INSTALL_DIR="$app" CODEX_INSTALL_TRANSACTION_ACTIVE=1 \
  CODEX_PATCH_REPORT_JSON="$work/reports/patch-report.json" \
  CODEX_UPSTREAM_LINUX_METADATA_JSON="$work/reports/upstream-package.json" \
  PACKAGE_WITH_UPDATER=0 \
  "$work/companion/install.sh" "$upstream_deb"

node - "$isolation_patch" "$app" <<'NODE'
const patch = require(process.argv[2]);
patch.isolateBundledServices(process.argv[3]);
patch.guardLauncher(process.argv[3]);
NODE
[[ -x "$app/start.sh" && -x "$app/resources/codex" ]] || fail "candidate launcher or bundled Core is missing"
mkdir -m 0700 "$work/version-home" "$work/version-home/.codex"
version="$(env -i PATH="$PATH" HOME="$work/version-home" CODEX_HOME="$work/version-home/.codex" \
  XDG_CONFIG_HOME="$work/version-home/config" XDG_DATA_HOME="$work/version-home/data" \
  XDG_CACHE_HOME="$work/version-home/cache" XDG_STATE_HOME="$work/version-home/state" \
  TMPDIR="$work/tmp" "$app/resources/codex" --version)"
[[ "$version" == "codex-cli $bundled_core_version" ]] || fail "Desktop bundles a different Core version than its descriptor"
python3 - "$app" "$descriptor" "$version" <<'PY'
import hashlib, json, sys
from pathlib import Path
app = Path(sys.argv[1])
release = json.loads(Path(sys.argv[2]).read_text())
desktop = release['desktop']
# The disabled native Chrome host contains the upstream shared path but cannot run.
# No other bundled resource may retain it, including hidden Node module copies.
needle = b'/tmp/codex-browser-use'
disabled_host = app / 'resources/plugins/openai-bundled/plugins/chrome/extension-host/linux/x64/extension-host'
for resource in (app / 'resources').rglob('*'):
    if resource == disabled_host or not resource.is_file():
        continue
    with resource.open('rb') as source:
        tail = b''
        while block := source.read(1024 * 1024):
            data = tail + block
            if needle in data:
                raise SystemExit(f'Unexpected shared browser IPC path in {resource.relative_to(app)}')
            tail = data[-len(needle):]
report = json.loads((app / '.codex-linux/patch-report.json').read_text())
required = {
    'feature:shared-app-server-socket:main-process-shared-app-server-socket',
    'feature:shared-app-server-socket:observatory-private-ipc-paths',
}
applied = {entry['name'] for entry in report['patches'] if entry['status'] == 'applied'}
if not required <= applied:
    raise SystemExit(f'Required Desktop patches not applied: {sorted(required - applied)}')
info = json.loads((app / '.codex-linux/build-info.json').read_text())
if info['upstreamLinuxPackage']['sha256'] != desktop['package_sha256'] or info['source']['commit'] != desktop['companion_commit']:
    raise SystemExit('Candidate provenance differs from the descriptor')
provenance = {
    'schemaVersion': 1,
    'desktopVersion': desktop['version'],
    'packageSha256': desktop['package_sha256'],
    'coreVersion': release['core']['version'],
    'bundledCoreVersion': sys.argv[3].removeprefix('codex-cli '),
    'companionCommit': desktop['companion_commit'],
    'featurePatchSha256': desktop['feature_patch_sha256'],
    'isolationPatchSha256': desktop['isolation_patch_sha256'],
    'asarVersion': desktop['asar_version'],
    'appId': 'codex-observatory-0-3',
    'updaterIncluded': False,
    'chromeNativeBridgeEnabled': False,
    'launcherSha256': hashlib.sha256((app / 'start.sh').read_bytes()).hexdigest(),
    'browserServiceSha256': {
        **{plugin: hashlib.sha256((app / 'resources/plugins/openai-bundled/plugins' / plugin / 'scripts/browser-service.mjs').read_bytes()).hexdigest()
           for plugin in ('browser', 'chrome')},
        'cua': hashlib.sha256((app / 'resources/cua_node/lib/node_modules/@oai/browser-desktop/scripts/browser-service.mjs').read_bytes()).hexdigest(),
        'cua_skill': hashlib.sha256((app / 'resources/cua_node/lib/node_modules/@oai/cua/dist/lib/js/oai_js_browser/dist/skill/scripts/browser-service.mjs').read_bytes()).hexdigest(),
    },
    'outputAsarSha256': hashlib.sha256((app / 'resources/app.asar').read_bytes()).hexdigest(),
}
(app / '.codex-linux/observatory-build.json').write_text(json.dumps(provenance, indent=2) + '\n')
PY
# A direct candidate build has no updater package or promotion operation.
tar -C "$work" -czf "$archive_tmp" codex-observatory-desktop
if ! ln -- "$archive_tmp" "$archive"; then fail "could not create archive without replacing an existing file: $archive"; fi
sha256sum "$archive"
echo "Desktop archive ready: $archive"
