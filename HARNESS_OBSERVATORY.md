# Codex Harness Observatory

This is a research and teaching fork of the open Codex agent harness. Its purpose is to expose the local machinery that turns a task into model sampling, decisions, tool execution, approvals, and coordinated agent work. It does not attempt to expose the model's private reasoning, and it does not instrument the desktop client or app-server protocol layer.

## Source pin

- Upstream tag: `rust-v0.149.0`
- Upstream commit: `758ef40f50c1a458425c7cfbf1eb12cbc07af0b0`
- Workspace version: `0.149.0`
- Rust toolchain: `1.95.0`
- Local baseline tag: `teaching-baseline-v0.149.0`

This repository intentionally has no Git remote. The upstream tag and commit above are the provenance record for the code taught in the course.

## Boundary

The observatory records events inside `codex-core` and at the Core-owned boundaries to model inference, approvals, tools, sandboxes, and child agents. Existing rollout-trace request and response payloads remain the packet-level evidence. New harness events explain why Core moved from one state to another.

Out of scope:

- desktop UI implementation
- app-server startup, transport, and connection mechanics
- private model reasoning performed by the hosted model
- production-grade telemetry retention or compatibility guarantees

## Baseline build

From `codex-rs`:

```bash
cargo build -j 1 -p codex-cli
./target/debug/codex --version
```

The unmodified source pin built successfully on the course machine and reported `codex-cli 0.149.0`. A parallel first build caused a Rust 1.95 LLVM `SIGSEGV`; the serial retry completed successfully. Use `-j 1` for reproducible teaching builds on this machine.

Tool-bearing runs also need `codex-code-mode-host` beside the development CLI. Building that package from the release tag was blocked on this machine on 2026-08-23 because the pinned Rusty V8 binary URL returned HTTP 404. For live verification only, the development CLI used the companion host already packaged with the installed npm Codex, after confirming that both CLIs reported version `0.149.0`. Do not mix host and CLI versions silently.

## Trace capture

Set `CODEX_ROLLOUT_TRACE_ROOT` to a writable directory before running the development binary. Each root task creates a trace bundle containing `manifest.json`, `trace.jsonl`, `payloads/`, and, after reduction, `state.json`.

The teaching fork adds a single `harness_event_observed` raw event family. Every event uses the same fields:

- raw sequence and timestamp
- thread and Codex turn IDs
- optional agent-step ID
- category, event name, and phase
- optional outcome and reason
- correlation IDs
- small structured details
- optional references to the existing payload store

This preserves one raw format: fine-grained events can be filtered directly and then reduced or aggregated for lecture views.

The phase-two additions make four further teaching boundaries visible without copying their contents:

- context capture, contribution provenance, prompt assembly, and compaction application;
- hook selection, invocation, categorical effects, and stop-hook continuation;
- V2 agent identity, residency, eviction, and reload; and
- trace-integrity invariants for lifecycle pairing and required correlations.

## Teaching capture and raw trace viewer

The source pin is `rust-v0.149.0` at `758ef40f50c1a458425c7cfbf1eb12cbc07af0b0`; the baseline development build is the serial build documented above:

```bash
cd codex-rs
cargo build -j 1 -p codex-cli
```

From the repository root, capture a small synthetic task with the development binary. Choose a new, private directory for each recording:

```bash
capture_root="$(mktemp -d /tmp/codex-rollout-traces.XXXXXX)"
export CODEX_ROLLOUT_TRACE_ROOT="$capture_root"
./codex-rs/target/debug/codex exec "For this synthetic exercise, say hello and stop."
find "$capture_root" -mindepth 1 -maxdepth 1 -type d -print
```

The listed directory is the trace bundle. Check its metadata-level invariants before teaching from it, reduce its raw evidence with the hidden `debug trace-reduce` command when a graph view is useful, or inspect the raw timeline without opening payload files:

```bash
bundle="/path/printed/by/find"
python3 tools/trace_viewer.py "$bundle" --check
./codex-rs/target/debug/codex debug trace-reduce "$bundle"
python3 tools/trace_viewer.py "$bundle"
```

The viewer accepts either a bundle directory or its `trace.jsonl`. It streams writer-assigned `seq` order and never writes a derived file. It includes ordinary packet/lifecycle rows alongside `harness_event_observed` rows by default. Useful focused views include:

```bash
# One teaching step, only the harness transitions.
python3 tools/trace_viewer.py "$bundle" --harness-only --step "step:thread:turn:1"

# One tool relation or one parent/child relation.
python3 tools/trace_viewer.py "$bundle" --correlation tool_call_id=call-123
python3 tools/trace_viewer.py "$bundle" --category multi_agent --correlation child_thread_id=thread-child

# Aggregate upward. Durations are only matched opening-to-terminal pairs.
python3 tools/trace_viewer.py "$bundle" --summary
```

Use `--payload-type`, `--thread`, `--turn`, `--step`, `--category`, `--name`, and `--phase` as repeatable filters; `--correlation KEY=VALUE` is repeatable too. `--details` adds compact, redacted structured harness details. `--help` describes exit codes: `0` means one or more matched events, `1` means no match, and `2` means malformed or unreadable input.

`--check` is deliberately metadata-only. It verifies raw sequence order, known opening-to-terminal lifecycle pairs, step IDs where a `StepContext` exists, and event-specific correlations. It returns `0` for a clean trace, `1` for integrity findings, and `2` for malformed or unreadable input. It understands real boundary cases such as turn admission before step construction, approval skips before an approval identity exists, pre-identity V2 reservation, and standalone mailbox delivery facts.

## Unified live viewer

Launch the same tool in browser mode:

```bash
python3 tools/trace_viewer.py "$bundle" --serve
```

The server binds to `127.0.0.1:8765` by default; use `--port 0` to select a free port. It sends existing rows and then tails appended JSONL records over one server-sent event stream in writer-assigned order. The fixed header shows safe manifest and stream metadata. The interface can filter on raw type, thread, turn, step, harness category/name/phase, and correlation key/value; pause and resume without dropping received rows; toggle follow-live; and open any event for a redacted detail view. Malformed appended lines become visible stream errors.

The browser receives only a safe envelope, compact harness facts, permitted correlations, and payload-reference metadata. It never opens the payload files. Absolute manifest paths, prompt/message/file content, commands, and other sensitive detail keys are omitted or redacted before they reach the browser.

For a deterministic no-cloud demonstration, run the checked-in synthetic trace:

```bash
python3 tools/trace_viewer.py tools/tests/fixtures/teaching_trace.jsonl
python3 tools/trace_viewer.py tools/tests/fixtures/teaching_trace.jsonl --summary --harness-only
```

> **Sensitive raw evidence:** Raw bundles and payload files can contain prompts, responses, tool arguments/results, paths, and other sensitive data. Use synthetic tasks for teaching, do not publish captures casually, and dispose of captures deliberately. The viewer does not open payload files and deliberately avoids printing stored prompt/message/file contents, but the bundle itself remains sensitive.

## Focused verification

The integrated fork was checked with focused package tests and private synthetic captures, not a repository-wide suite:

- `cargo build -j 1 -p codex-cli` completed, and the development binary reports `codex-cli 0.149.0`;
- five focused Core tests passed for context provenance, V2 eviction/reload, hook effects, and stop supervision;
- `python3 -m unittest tools.tests.test_trace_viewer` passed 15 tests for timeline/filter/summary behavior, integrity rules, tailing, redaction, HTTP metadata, and malformed input;
- `node --check tools/trace_viewer_web/app.js` and `git diff --check` passed before the final formatter pass;
- a private live patch run produced 81 raw events, including 60 harness events, changed the synthetic file, and passed `--check`;
- a private live V2 spawn/wait run produced 140 raw events, including `agent_residency` and `agent_identity`, and passed `--check`; and
- an isolated headless browser received 34 initial fixture events, filtered two decision rows, opened a redacted Guardian detail, buffered one appended event while paused, displayed it after resume, and filtered six rows by `tool_call_id=tool-9`.

`just fix -p codex-core` completed; its two mechanical fixes in instrumented paths were retained, while an unrelated upstream test cleanup was discarded. The Rust formatting stage also applied its change. The overall `just fmt` wrapper returned nonzero because this host lacks `dotslash` and its unrelated Python formatter could not write the uv cache; those host-tooling failures did not affect the Rust formatting result. No full workspace test suite was run.
