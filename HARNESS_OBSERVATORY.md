# Codex Harness Observatory

This is a research and teaching fork of the open Codex agent harness. Its purpose is to expose the local machinery that turns a task into App Server protocol traffic, model sampling, decisions, tool execution, approvals, MCP calls, and coordinated agent work. It does not attempt to expose the model's private reasoning or instrument the desktop renderer. The Desktop teaching route connects that renderer to this patched Core through the App Server bridge.

## Source pin

- Upstream tag: `rust-v0.150.0-alpha.12.2`
- Upstream commit: `a9802304f60ab14c0b07e3ee0db9a9c105ab0cb3`
- Workspace version: `0.150.0-alpha.12.2`
- Rust toolchain: `1.95.0`
- Rollback tag: `teaching-baseline-v0.149.0`
- Rollback branch: `backup/pre-core-pin-v0.149.0`
- Signed Desktop package: `26.825.32147`
- Signed package SHA-256: `986d38b690dd0310933ce61175b09c27434001f4e114332bb0f7b6ffdc3ca406`

This repository intentionally has no Git remote. The exact Core and Desktop
pins above are also enforced by `.env`, `run.sh`, and
`build-desktop-observatory.sh`; the teaching launcher fails closed when the
source, development binary, bundled Core, package version, or package digest
does not match.

## Boundary

The observatory records events inside `codex-core`, at the Core-owned boundaries to model inference, approvals, tools, sandboxes, and child agents, and at the App Server and MCP JSON-RPC transport boundaries. Exact requests and responses live in the existing rollout payload store. Small raw envelopes and harness events make those packets filterable and explain why Core moved from one state to another.

Out of scope:

- desktop UI implementation
- app-server startup and connection-management internals beyond the observed JSON-RPC frames
- private model reasoning performed by the hosted model
- production-grade telemetry retention or compatibility guarantees

## Baseline build

From `codex-rs`:

```bash
cargo build -j 1 -p codex-cli
./target/debug/codex --version
```

The integrated source pin built successfully on the course machine and reports
`codex-cli 0.150.0-alpha.12.2`. Use `-j 1` for reproducible teaching builds on
this machine. The signed Desktop package carries the same Core version and its
matching companion binaries; the launcher verifies that pairing before use.

## Trace capture

Set `CODEX_ROLLOUT_TRACE_ROOT` to a writable directory before running the development binary. Each root task creates a trace bundle containing `manifest.json`, `trace.jsonl`, `payloads/`, and, after reduction, `state.json`.

The teaching fork adds three raw event families to the same `trace.jsonl` ledger:

- `harness_event_observed` records execution and decision semantics;
- `app_server_frame_observed` records App Server JSON-RPC requests, responses, errors, and notifications; and
- `mcp_frame_observed` records MCP JSON-RPC requests, responses, errors, and notifications.

Harness events use the following fields:

- raw sequence and timestamp
- thread and Codex turn IDs
- optional agent-step ID
- category, event name, and phase
- optional outcome and reason
- correlation IDs
- small structured details
- optional references to the existing payload store

This preserves one raw format: fine-grained events can be filtered directly and then reduced or aggregated for lecture views.

Wire-event envelopes contain only transport, direction, frame kind, method,
request ID, and available correlation IDs. App Server envelopes normalize
source and new thread IDs, turn and item context, fork lineage, and session ID
when the frame carries them. Per-connection request state lets responses inherit
the originating method, source thread, turn, and task root without confusing a
fork's source thread with its returned new thread. The exact JSON frame remains
a referenced payload artifact. App Server traffic received before
`thread/start` creates the root trace is buffered in memory and flushed into
that root bundle in its original observed order. MCP responses inherit the
originating request method and the bridge MCP call ID when available.

The phase-two additions make four further teaching boundaries visible:

- context capture, contribution provenance, prompt assembly, and compaction application;
- hook selection, invocation, categorical effects, and stop-hook continuation;
- V2 agent identity, residency, eviction, and reload; and
- trace-integrity invariants for lifecycle pairing and required correlations.

## Desktop shared-run teaching mode

The Desktop teaching route is an opt-in use of the same App Server and rollout
trace, not Desktop instrumentation. One App Server lifetime owns one shared
trace bundle. Independent Desktop tasks are roots in that bundle and each row
carries `task_root_thread_id`; spawned agents remain children of their root.
The writer allocates one exact `seq` order across roots, and initialization or
other not-yet-attributable App Server traffic is shown in a session lane.

The Linux launcher selects this development Core with `CODEX_CLI_PATH` and uses
the existing private Unix-socket bridge through
`CODEX_LINUX_APP_SERVER_BRIDGE_SOCKET`. It enables
`CODEX_ROLLOUT_TRACE_SHARED_RUN=1` and full viewer evidence for the private
teaching session. The normal standalone TUI flow remains available. The
detailed contract, execution work, and acceptance boundary are in
[`DESKTOP_OBSERVATORY_PLAN.md`](DESKTOP_OBSERVATORY_PLAN.md). The current Core
pin exactly matches the signed Desktop payload that will be used for teaching;
an isolated disposable-profile handshake is complete, and the remaining
normal-profile authorization boundary is recorded in that plan.

## Teaching capture and raw trace viewer

The source pin is `rust-v0.150.0-alpha.12.2` at
`a9802304f60ab14c0b07e3ee0db9a9c105ab0cb3`; the development build is the
serial build documented above:

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

The listed directory is the trace bundle. Check its metadata-level invariants before teaching from it, reduce its raw evidence with the hidden `debug trace-reduce` command when a graph view is useful, or inspect the raw timeline:

```bash
bundle="/path/printed/by/find"
python3 tools/trace_viewer.py "$bundle" --check
python3 tools/lecture_2_app_server_trace_check.py "$bundle"
./codex-rs/target/debug/codex debug trace-reduce "$bundle"
python3 tools/trace_viewer.py "$bundle"
```

The Lecture 2 checker is deliberately narrower than the general integrity
check. It accepts the prepared thread, turn, item, steer, completion, and
persistent-fork sequence; pairs bidirectional requests and responses per
connection; rejects a second `turn/started` after steering; and verifies the
fork's distinct thread identity and returned lineage.

The viewer accepts either a bundle directory or its `trace.jsonl`. It streams writer-assigned `seq` order and never writes a derived file. It includes ordinary packet/lifecycle rows alongside `harness_event_observed` rows by default. Useful focused views include:

```bash
# One teaching step, only the harness transitions.
python3 tools/trace_viewer.py "$bundle" --harness-only --step "step:thread:turn:1"

# One tool relation or one parent/child relation.
python3 tools/trace_viewer.py "$bundle" --correlation tool_call_id=call-123
python3 tools/trace_viewer.py "$bundle" --category multi_agent --correlation child_thread_id=thread-child

# Aggregate upward. Durations are only matched opening-to-terminal pairs.
python3 tools/trace_viewer.py "$bundle" --summary

# Lecture 2: App Server JSON-RPC packets.
python3 tools/trace_viewer.py "$bundle" --category app_server

# Lecture 3: Codex tool execution plus MCP request/response frames.
python3 tools/trace_viewer.py "$bundle" --category tool --category mcp

# Lecture 4: execution and decision events around approvals and sandboxing.
python3 tools/trace_viewer.py "$bundle" --category tool --category decision
```

Use `--payload-type`, `--thread`, `--turn`, `--step`, `--category`, `--name`, and `--phase` as repeatable filters; `--correlation KEY=VALUE` is repeatable too. `--details` adds compact, redacted structured harness details. `--help` describes exit codes: `0` means one or more matched events, `1` means no match, and `2` means malformed or unreadable input.

`--check` is deliberately metadata-only. It verifies raw sequence order, known opening-to-terminal lifecycle pairs, step IDs where a `StepContext` exists, and event-specific correlations. It returns `0` for a clean trace, `1` for integrity findings, and `2` for malformed or unreadable input. It understands real boundary cases such as turn admission before step construction, approval skips before an approval identity exists, pre-identity V2 reservation, and standalone mailbox delivery facts.

## Unified live viewer

Launch the same tool in browser mode:

```bash
python3 tools/trace_viewer.py "$bundle" --serve
```

The server binds to `127.0.0.1:8765` by default; use `--port 0` to select a free port. It sends existing rows and then tails appended JSONL records over one server-sent event stream in writer-assigned order. The fixed header shows manifest and stream metadata. The interface can filter on raw type, thread, turn, step, additive teaching categories, harness event, protocol method, human-readable tool name, phase or frame kind, and correlation key/value; pause and resume without dropping received rows; toggle follow-live; and open any event for detail. App Server rows label their paired request or response and highlight the counterpart when either row is selected, including server-initiated requests. Select `App Server` for Lecture 2, `Tool + MCP` for Lecture 3, and `Tool + Decision` for Lecture 4. Malformed appended lines become visible stream errors.

Browser mode exposes full evidence by default. Use `--redact-content` only when a metadata-only view is explicitly wanted. In full-content mode the browser receives complete raw event fields, and each payload reference is a button that opens the stored artifact below the event. This includes exact App Server and MCP frames, which can contain prompts, tool arguments, paths, and server-returned content. Tool-call IDs are correlated across related decisions and lifecycle rows so that the timeline says `apply_patch`, `exec_command`, or the relevant MCP/code-mode tool when Core recorded that identity. An `apply_patch` invocation also gets a dedicated view of the affected files and patch text, labeled explicitly as Codex's internal patch machinery rather than a shell or MCP call.

The checked-in `run.sh` enables full-content mode by default through `OBSERVATORY_SHOW_CONTENT=1` in `.env`. This is intentional for the private teaching environment. Set it to `0` to make the TUI route metadata-only; Desktop teaching mode remains full evidence. Invoke the viewer directly for either mode:

```bash
python3 tools/trace_viewer.py "$bundle" --serve
python3 tools/trace_viewer.py "$bundle" --serve --redact-content
```

For a deterministic no-cloud demonstration, run the checked-in synthetic trace:

```bash
python3 tools/trace_viewer.py tools/tests/fixtures/teaching_trace.jsonl
python3 tools/trace_viewer.py tools/tests/fixtures/teaching_trace.jsonl --summary --harness-only
python3 tools/lecture_2_app_server_trace_check.py tools/tests/fixtures/lecture_2_app_server_trace
```

> **Private teaching mode:** `run.sh` deliberately exposes prompts, responses, tool arguments/results, paths, and other stored payload content in the local viewer. This makes the agent loop legible for demonstration, but a captured bundle still contains everything shown. Do not reuse this full-content setting for ordinary work or publish a bundle without reviewing it.

## Focused verification

The integrated fork was checked with focused package tests and private synthetic captures, not a repository-wide suite:

- `cargo build -j 1 -p codex-cli --bin codex` completed, and the development
  binary reports `codex-cli 0.150.0-alpha.12.2`;
- six focused Core tests passed for context provenance, V2 eviction and both
  reload routes, hook effects, and hook-source attribution;
- focused rollout-trace, RMCP, and App Server tests passed for exact frame persistence, request/response correlation, typed MCP `_meta` propagation, and unchanged filtered routing;
- `just test -p codex-rollout-trace` passed all 70 focused crate tests,
  including normalized App Server identities, bidirectional response context,
  persistent fork lineage, and shared-run ordering;
- `python3 -m unittest tools.tests.test_trace_viewer tools.tests.test_lecture_2_app_server_trace_check`
  passed all 28 tests for viewer behavior and the deterministic Lecture 2
  lifecycle checker;
- `node --check tools/trace_viewer_web/app.js` and `git diff --check` passed before the final formatter pass;
- a private live patch run produced 81 raw events, including 60 harness events, changed the synthetic file, and passed `--check`;
- a private live V2 spawn/wait run produced 140 raw events, including `agent_residency` and `agent_identity`, and passed `--check`; and
- an isolated headless browser received 34 initial fixture events, showed Guardian rows as decisions while naming their `apply_patch` relation, opened `payloads/tool-input.json` into a dedicated internal-patch view, and opened `payloads/request.json` to show the exact synthetic user prompt.
- the signed Desktop candidate opened on isolated X11 display `:93`, reported
  App Server `0.150.0-alpha.12.2`, completed its initialization handshake, and
  served the full-evidence Observatory viewer on a separately verified port;
  the disposable profile correctly stopped at sign-in; and
- an occupied-port check proved that `run.sh` now reports the viewer's bind
  failure instead of accepting an unrelated local HTTP service as ready.

`just fix -p codex-core`, `just fix -p codex-app-server`, and `just fmt`
completed. The formatter used a temporary writable uv cache because the host's
default cache is read-only in the managed workspace. No full workspace test
suite was run.
