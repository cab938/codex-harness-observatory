# Codex Harness Observatory

Codex Harness Observatory is a research and teaching fork of the Codex
agent harness. It makes the local path from a task through App Server frames,
model sampling, decisions, approvals, tools, MCP, and child-agent coordination
visible in a filterable trace. It does not expose a model's private reasoning
or instrument the Desktop renderer.

## Quickstart: installed TUI

The installed route is for Linux x86_64. Until this project publishes to PyPI,
install the wheel asset from the latest GitHub release:

```bash
wheel_dir="$(mktemp -d)"
gh release download --repo cab938/codex-harness-observatory \
  --pattern 'codex_harness_observatory-*.whl' --dir "$wheel_dir"
pipx install "$wheel_dir"/codex_harness_observatory-*.whl
mkdir my-observatory-run
cd my-observatory-run
codex-harness-observatory
```

The intended PyPI installation, once published, is:

```bash
pipx install codex-harness-observatory
```

On its first run in a directory, the launcher interactively invokes
`codex-configure init` for that exact current directory. Choose the
Stock/OpenAI configuration during initialization. The observatory does not
use `codex-configure`'s provider-patching capability. After initialization it
re-enters through `codex-configure launch -- ...`, which supplies the rooted
environment and executes the selected command directly. Later runs reuse the
same root; use `codex-harness-observatory --help` for the available launcher
options.

The verified observatory Core is installed below
`ROOT/.codex-configure/observatory`. Run directories, traces, service logs,
and related state stay below that root. The launcher starts the patched TUI
and local trace viewer, then retains the run artifacts when the session ends.

## Quickstart: source checkout

The source route is useful when teaching from or modifying this repository:

```bash
git clone https://github.com/cab938/codex-harness-observatory.git
cd codex-harness-observatory
(cd codex-rs && cargo build -j 1 -p codex-cli)
./run.sh                 # patched TUI plus local viewer
./run.sh --desktop       # optional Desktop teaching route
```

The `--desktop` route additionally requires the separately checked-out and
built `codex-desktop-linux` candidate. See
[`HARNESS_OBSERVATORY.md`](HARNESS_OBSERVATORY.md) and
[`DESKTOP_OBSERVATORY_PLAN.md`](DESKTOP_OBSERVATORY_PLAN.md) for the exact
Desktop prerequisite and bridge details.

## What the viewer shows

Each run stores a trace bundle containing `manifest.json`, `trace.jsonl`,
`payloads/`, and, after reduction, `state.json`. The viewer can filter raw
transport packets and harness events by thread, turn, step, category, method,
phase, and correlation. It can also check trace-integrity invariants and serve
a live local browser view. The detailed event families and examples are in
[`HARNESS_OBSERVATORY.md`](HARNESS_OBSERVATORY.md).

The default teaching viewer is private full-content evidence: prompts,
responses, tool arguments and results, paths, and raw App Server/MCP frames
may be shown. Review a bundle before sharing it. Set
`OBSERVATORY_SHOW_CONTENT=0` for metadata-only TUI viewing, or use the
viewer's `--redact-content` option.

## Provenance and boundaries

This repository is pinned to upstream Codex tag
`rust-v0.150.0-alpha.12.2` at commit
`a9802304f60ab14c0b07e3ee0db9a9c105ab0cb3`, with the observatory patches
applied on top. The source launcher and installed launcher use that same
teaching Core version when verifying artifacts.

This is light isolation, not a security sandbox. It separates Codex state,
configuration, Desktop/Chrome-related state, and observatory traces for a
teaching directory, but it does not protect against a process with access to
the same user account or host. Do not use the full-content route for ordinary
private work without reviewing its retention and sharing implications.

## Development and builds

The source checkout is the canonical development surface. Build the patched
Core with `cargo build -j 1 -p codex-cli`; the GitHub workflow builds the
Linux x86_64 release Core and the installable Python wheel. The package
depends on `codex-configure>=0.5.1,<0.6` for rooted launch behavior and does
not apply its provider patch. Keep the source and signed Desktop provenance
pins in `.env` aligned when changing the teaching set.

The full trace schema, launch contracts, focused verification history, and
Desktop bridge notes live in [`HARNESS_OBSERVATORY.md`](HARNESS_OBSERVATORY.md).
