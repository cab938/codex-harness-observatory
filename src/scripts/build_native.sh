#!/usr/bin/env bash
# Build and package the native runtime using the descriptor's V8 inputs.
set -Eeuo pipefail

root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)"
export CARGO_TARGET_DIR="${CARGO_TARGET_DIR:-$root/build/cargo}"
export CARGO_INCREMENTAL=0
export CARGO_PROFILE_DEV_DEBUG=0
: "${RUSTY_V8_ARCHIVE:?Set RUSTY_V8_ARCHIVE to the pinned V8 archive}"
: "${RUSTY_V8_SRC_BINDING_PATH:?Set RUSTY_V8_SRC_BINDING_PATH to the generated binding}"

python3 - "$root/release.json" <<'PY'
import hashlib
import json
import os
import sys

v8 = json.load(open(sys.argv[1], encoding="utf-8"))["core"]["v8"]
for variable, pin in (
    ("RUSTY_V8_ARCHIVE", "archive_sha256"),
    ("RUSTY_V8_SRC_BINDING_PATH", "binding_sha256"),
):
    with open(os.environ[variable], "rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    if digest != v8[pin]:
        raise SystemExit(f"{variable} does not match release.json")
PY

cd "$root/lib/codex/codex-rs"
cargo build --locked --bin bwrap
export CODEX_BWRAP_SHA256="$(sha256sum "$CARGO_TARGET_DIR/debug/bwrap" | cut -d' ' -f1)"
cargo build --locked --bin codex --bin codex-code-mode-host --bin codex-exec-server
mkdir -p "$root/build/artifacts"
python3 "$root/src/scripts/build_core.py" \
  --bin-dir "$CARGO_TARGET_DIR/debug" --profile dev \
  --optimization unoptimized \
  --output-dir "$root/build/artifacts"
