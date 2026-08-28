# Instrumentation Tranches

Core instrumentation tranches 0-10 write `HarnessTraceEvent` records into the existing rollout trace. They must not create another log file, emit desktop events, or persist model reasoning deltas. Event details should contain compact facts that explain a state transition. Existing payload references remain the source for full model requests, responses, tool arguments, and results. Phase 3 extends that same ledger with explicitly scoped App Server and MCP transport frames for the lecture sequence.

Every event should carry the current `trace_step_id` when a `StepContext` is available. Use `call_id`, approval/review ID, child thread ID, and similar values as correlations. Prefer categorical outcomes and reasons over human-readable summaries that are hard to aggregate.

## Tranche 0: Shared trace foundation

Status: complete.

Owns the raw and reduced event envelope, step ID allocation, category and phase vocabulary, source pin, and baseline build record. Later tranches should consume this API without changing the envelope unless an actual missing field blocks their work.

## Tranche 1: Agent loop and supervision

Status: complete and merged.

Primary ownership:

- `codex-rs/core/src/session/turn.rs`
- `codex-rs/core/src/session/turn_input.rs`
- `codex-rs/core/src/session/input_queue.rs` when needed for user steering or turn admission
- directly related small session helpers

Required teaching events:

- `turn_input_disposition`: start, steer, queue, defer, or ignore
- `agent_step`: started, completed, failed, or cancelled
- `sampling_request`: requested, completed, failed, or cancelled
- `agent_step_next_action`: continue for model-requested tool output, pending user input, mailbox delivery, compaction, or stop-hook continuation; otherwise complete, abort, or fail
- `compaction_decision`: whether and why Core rolls to a new context window

Capture counts, booleans, policy choices, and categorical reasons. Do not duplicate full prompts or response streams already stored as inference payloads.

## Tranche 2: Approval, Guardian, and sandbox decisions

Status: complete and merged.

Primary ownership:

- `codex-rs/core/src/tools/approvals.rs`
- `codex-rs/core/src/tools/orchestrator.rs`
- `codex-rs/core/src/tools/sandboxing.rs`
- `codex-rs/core/src/tools/network_approval.rs` when useful
- `codex-rs/core/src/guardian/`
- approval and Guardian entries in `codex-rs/rollout-trace/src/protocol_event.rs`

Required teaching events:

- `approval_requirement`: skip, needs approval, or forbidden, including policy source
- `approval_cache`: hit, miss, or stored
- `approval_reviewer`: user or Guardian and why
- `guardian_review`: requested, completed, failed, timed out, or cancelled, correlated by review ID
- `approval_resolution`: decision and whether it came from configuration, user, cache, or automated reviewer
- `sandbox_selection`: effective permissions, sandbox type, and bypass decision
- `sandbox_attempt`: first or escalated attempt and outcome
- `sandbox_escalation`: eligible, suppressed, requested, approved, or denied, with reason

Do not record environment values, auth material, full prompts, or command output in harness-event details.

## Tranche 3: Tool routing and file patching

Status: complete and merged.

Primary ownership:

- `codex-rs/core/src/tools/router.rs`
- `codex-rs/core/src/tools/registry.rs`
- `codex-rs/core/src/tools/parallel.rs`
- `codex-rs/core/src/tools/tool_dispatch_trace.rs`
- `codex-rs/core/src/tools/handlers/apply_patch.rs`
- `codex-rs/core/src/tools/runtimes/apply_patch.rs`
- directly related tool handlers, excluding approval and sandbox orchestration owned by Tranche 2

Required teaching events:

- `tool_catalog`: model-visible tool counts by major family
- `tool_handler_resolution`: built-in, MCP, dynamic, extension, collaboration, hosted, or unknown
- `tool_parallelism`: parallel or serialized and why
- `tool_dispatch`: accepted, rejected, started, completed, failed, or cancelled
- `patch_parse`: file/action counts or validation failure
- `patch_safety`: accepted, rejected, or approval required
- `patch_commit`: per-file action and aggregate success, without copying full file contents

The existing typed tool lifecycle remains canonical for invocation and result payloads. New events explain dispatch, routing, and patch decisions around that lifecycle.

## Tranche 4: Multi-agent coordination

Status: complete and merged.

Primary ownership:

- `codex-rs/core/src/thread_manager.rs`
- `codex-rs/core/src/agent/`
- `codex-rs/core/src/tools/handlers/multi_agents*`
- mailbox-specific additions to `codex-rs/core/src/session/input_queue.rs`

Required teaching events:

- `agent_target_resolution`: requested target, resolved thread/path, or failure reason
- `agent_spawn_admission`: depth, slot, role, and authority checks
- `agent_spawn`: requested, created, failed, or cancelled, with parent/child correlation
- `agent_message`: enqueued, delivered, deferred, or rejected
- `agent_wait`: target set and wake reason
- `agent_interrupt` and `agent_close`: requested and resolved
- `agent_result_delivery`: child completion enqueued and materialized in the parent

Record role/model/reasoning overrides as categorical configuration, not prompt contents. Preserve parent, child, root, thread, turn, and tool-call correlations.

## Tranche 5: Teaching capture and viewer

Starts after the instrumentation tranches merge.

Provide a dependency-light command that reads one `trace.jsonl`, filters by thread, turn, step, category, name, phase, or correlation, and prints a compact ordered timeline. It should also summarize counts and durations by category/name without creating a second persisted format. Add one small deterministic fixture or self-test and a short capture recipe using the development binary.

Status: complete.

Coverage delivered in `tools/trace_viewer.py` and `tools/tests/test_trace_viewer.py`:

- accepts a bundle directory or `trace.jsonl`, streams checked raw `seq` order, and reports malformed lines with their line number;
- shows raw packet/lifecycle and harness rows together, with filters for raw type, thread, turn, step, category, name, phase, and repeatable correlations;
- prints count summaries and explicitly labelled matched lifecycle durations, without writing a derived trace format;
- includes a hand-checkable synthetic fixture covering agent loop, Guardian/decision, patch/tool, multi-agent, inference, and tool lifecycle evidence; and
- is standard-library-only, deterministic, and does not require cloud access or authentication.

## Phase 2 merge order

Phase 2 extends the same `harness_event_observed` envelope. Tranches 6, 7, and 8
start from this committed plan in separate worktrees and may proceed in parallel.
They merge in numeric order so any shared imports or formatting conflicts are
resolved before Tranche 9 validates the combined vocabulary. Tranche 10 starts
only after the instrumentation and integrity rules are integrated.

## Tranche 6: Context construction and prompt provenance

Status: complete and merged.

Primary ownership:

- `codex-rs/core/src/session/mod.rs`, limited to step-context capture and context contribution assembly
- `codex-rs/core/src/session/turn.rs`, limited to final prompt assembly
- the directly related compaction application path when needed
- focused Core tests for these paths

Required teaching events:

- `step_context_capture`: started, completed, failed, or cancelled around the snapshot used for one agent step
- `context_contribution`: included, unchanged, refreshed, or omitted, classified by source rather than content
- `prompt_assembly`: completed with bounded counts by role and item family, history size, tool count, and input modalities
- `compaction_application`: started, completed, failed, or cancelled, including window identity and before/after item counts when available

Record provenance categories and bounded counts, not instruction text, memory
contents, environment values, file contents, prompts, or model responses. The
existing inference payload remains the packet-level source for the exact request.

Focused verification:

- one Core test showing a step emits context capture and prompt assembly events with the current step ID
- one compact or context-update test showing provenance without persisted source contents
- `cargo check -p codex-core` or an equivalent serial package build; do not run the workspace suite in the worktree

Delivered coverage: `step_context_capture`, `context_contribution`, `prompt_assembly`, and `compaction_application`, with source categories and bounded counts but no source contents. Focused context/provenance tests passed.

## Tranche 7: Multi-agent V2 identity, persistence, and residency

Status: complete and merged.

Primary ownership:

- `codex-rs/core/src/agent/control/residency.rs`
- `codex-rs/core/src/agent/control/spawn.rs`, limited to V2 metadata restore and reload
- `codex-rs/core/src/agent/registry.rs` only when a registry transition cannot be observed at the control boundary
- directly related V2 residency and reload tests

Required teaching events:

- `agent_identity`: registered, restored, or forgotten for a named V2 task
- `agent_residency`: slot requested, reserved, touched, released, rejected, or selected for eviction
- `agent_eviction`: requested, completed, skipped, or failed, with categorical eligibility reason
- `agent_reload`: requested, completed, raced, or failed when a non-resident V2 task is materialized from stored history
- `agent_status_transition`: observed only where Core already owns a meaningful V2 lifecycle transition

Every event must identify the implementation as V2 and preserve available root,
parent, task-path, and thread correlations. Do not record task messages, rollout
contents, environment values, or model configuration secrets. Do not duplicate
the existing spawn, message, wait, interrupt, or result events from Tranche 4.

Focused verification:

- one existing residency test extended to prove an idle task is evicted with a traceable reason
- one reload test extended to prove the same task identity is restored after eviction
- `cargo check -p codex-core` or an equivalent serial package build; do not run the workspace suite in the worktree

Delivered coverage: V2 `agent_identity`, `agent_residency`, `agent_eviction`, and `agent_reload` events, including categorical failure and race outcomes. Focused eviction and reload tests passed, and an explicitly enabled private V2 capture recorded live reservation and registration events.

## Tranche 8: Hook supervision and continuation effects

Status: complete and merged.

Primary ownership:

- Core-owned hook invocation boundaries and adapters
- stop-hook continuation handling in `codex-rs/core/src/session/turn.rs` only when needed
- directly related hook-boundary tests

Required teaching events:

- `hook_selection`: none, selected, or skipped, with hook event name and bounded handler count
- `hook_invocation`: requested, completed, failed, timed out, or cancelled
- `hook_effect`: context added, arguments updated, permission allowed, permission denied, continued, stopped, or no effect
- `stop_supervision`: evaluated, continued, or completed, correlated to the current step

Instrument the Core boundary rather than command-runner internals. Existing hook
protocol events remain canonical for individual handler output. Do not record
hook commands, stdout, stderr, injected context, rewritten arguments, or denial
messages in harness-event details.

Focused verification:

- one hook-boundary test covering a no-effect or context-addition outcome
- one stop-hook test distinguishing continuation from actual completion
- focused package checks only; do not run the workspace suite in the worktree

Delivered coverage: `hook_selection`, `hook_invocation`, `hook_effect`, and `stop_supervision`. Focused tests passed for categorical hook effects and the distinction between continuation and actual completion.

## Tranche 9: Trace integrity and teaching captures

Status: complete and merged.

Extend `tools/trace_viewer.py` rather than creating a second validator. Add a
`--check` mode that verifies sequence order, opening-to-terminal lifecycle
pairing, required step IDs, and event-specific correlations. Findings must name
the raw sequence and violated invariant without opening payload contents.

Extend the deterministic teaching fixture to include context, supervision, and
V2 residency events, plus one intentionally broken fixture used only by tests.
Run small live synthetic captures in a private temporary directory for a patch
path, a decision path, and a V2 coordination path. Do not commit raw live
bundles or payload contents; commit only deliberately synthetic, hand-audited
fixtures and the capture recipe.

Focused verification:

- viewer tests for a clean trace and representative orphan, correlation, and ordering failures
- one private live capture successfully passes `--check`, or the exact external blocker is recorded

Delivered coverage: metadata-only `--check`, an expanded clean teaching fixture, and an intentionally broken fixture. Fifteen viewer tests pass. Private live patch and explicitly enabled V2 coordination captures both pass integrity; the live runs also supplied regression cases for valid pre-step, pre-approval-identity, pre-child-identity, and standalone mailbox events.

## Tranche 10: Unified live log viewer

Status: complete and merged.

Keep `tools/trace_viewer.py` as the single launcher and preserve its existing
timeline, summary, filtering, and check modes. Add a local browser mode that:

- accepts either a bundle directory or `trace.jsonl` and binds to loopback by default
- reads existing rows, then tails appended JSONL records in writer-assigned order
- displays manifest identity and safe stream metadata in a fixed header
- provides filters for raw type, thread, turn, step, category, name, phase, and correlations
- supports pause/resume and follow-live behavior without losing received rows
- opens a selected event in a detail pane with redacted envelope, harness details, correlations, and payload-reference metadata
- reports malformed appended lines without silently skipping or rewriting them
- never creates a derived trace file and never opens payload contents by default

The browser client and streaming endpoint are one local application launched by
the existing command. Favor standard-library server code and static assets over
a second service or persistent data store. Include keyboard-accessible event
selection and filter controls, and keep the layout usable at a laptop recording
resolution.

Focused verification:

- Python tests for initial load, incremental append delivery, manifest metadata, redaction, and malformed-line reporting
- one browser interaction pass proving filter changes, event selection, detail display, pause/resume, and receipt of an event appended after connection

Delivered coverage: `tools/trace_viewer.py --serve` launches one standard-library loopback server and static browser client. It streams initial and appended events, exposes safe header metadata, supports the complete filter set plus pause/resume and follow-live, and opens a redacted event detail pane without reading payload contents. Python stream/server tests and an isolated browser interaction pass completed successfully.

## Phase 3: Lecture protocol and execution logging

Phase 3 preserves the single append-only `trace.jsonl` ledger and payload store. Protocol envelopes contain bounded metadata; exact frames are payload artifacts and are exposed by the local viewer only when full-content mode is enabled.

## Tranche 11: App Server and MCP JSON-RPC frames

Status: complete.

Delivered coverage:

- `app_server_frame_observed` captures client-to-server frames before App Server dispatch and server-to-client frames after connection-specific filtering but before delivery;
- request/response correlation preserves the originating App Server method and
  source thread, turn, and task-root context in both directions, including
  initialization and `thread/start` traffic buffered before the root trace
  exists;
- App Server envelopes normalize source and new thread IDs, item IDs, fork
  lineage, and session IDs while retaining the exact frame as a payload;
- `mcp_frame_observed` wraps every rmcp client transport shape and captures typed frames immediately before send and after receive;
- MCP response envelopes inherit the request method and trace-only `mcp_call_id`, when present, so packet evidence joins to the canonical tool lifecycle; and
- exact JSON remains in `payloads/` under the new `app_server_frame` and `mcp_frame` payload kinds.

## Tranche 12: Lecture-focused observatory views

Status: complete.

The viewer exposes additive `app_server`, `mcp`, `tool`, and `decision`
categories. These map directly to Lecture 2 App Server traffic, Lecture 3
execution plus MCP traffic, and Lecture 4 execution plus approval/sandbox
decisions. Protocol methods participate in name filtering, frame kinds
participate in phase filtering, and wire request/call IDs participate in
correlation filtering. App Server request/response pairs are linked by
connection, direction, and request ID. A deterministic Lecture 2 checker
accepts the expected thread, turn, item, steer, completion, and fork lifecycle
and rejects an extra turn start after steering.

## Phase 4: Desktop shared-run teaching

Status: in implementation.

Phase 4 changes the run ownership model only when explicitly enabled through
`CODEX_ROLLOUT_TRACE_SHARED_RUN=1`. One App Server lifetime then owns one
append-only teaching bundle. It is the first phase that makes simultaneous
independent Desktop tasks visible in one exact event order. See
`DESKTOP_OBSERVATORY_PLAN.md` for the settled teaching contract and launch
boundary.

## Tranche 13: Shared App Server run and task identity

Primary ownership:

- `codex-rs/rollout-trace/`
- App Server trace lifecycle and transport attribution boundaries

Required behavior:

- one writer and global `seq` allocation for all root tasks in an opt-in App
  Server lifetime;
- `task_root_thread_id` on attributable raw/harness/wire evidence;
- root task completion does not end the shared run; App Server shutdown does;
- descendants retain their root identity and parent/child correlations; and
- pre-root or otherwise unattributable App Server frames remain in a session
  lane.

Focused verification:

- two roots interleave into one bundle with strictly increasing `seq`;
- ending one root leaves the second writer path live; and
- one child task is associated with its parent root.

## Tranche 14: Concurrent MCP attribution

Primary ownership:

- `codex-rs/rmcp-client/`
- `codex-rs/codex-mcp/src/rmcp_client.rs`

Required behavior:

- every MCP transport frame retains root, thread, turn, and bridge call
  context when available; and
- pending response correlation is connection-scoped so repeated JSON-RPC IDs
  from overlapping tasks cannot cross-attribute evidence.

Focused verification:

- overlapping calls using the same request ID retain their respective roots
  and methods on responses.

## Tranche 15: Concurrent task viewer and Desktop route

Primary ownership:

- `tools/trace_viewer.py`, `tools/trace_viewer_web/`
- the teaching launcher and Desktop candidate build route

Required behavior:

- all-task and task-focus modes show root lanes, child nesting, active/completed
  status, and session traffic while preserving raw `seq` order;
- full content remains the teaching-launcher default, including payload
  artifacts; and
- a side-by-side Linux Desktop candidate starts the patched Core via
  `CODEX_CLI_PATH` and the existing private
  `CODEX_LINUX_APP_SERVER_BRIDGE_SOCKET` feature.

Focused verification:

- deterministic viewer tests plus one browser interaction cover focus, live
  interleaving, child nesting, and full payload selection; and
- isolated Desktop acceptance starts two independent tasks plus one child and
  retains one shared bundle. Do not mark this tranche complete until that live
  capture succeeds.

## Verification budget

Each tranche should run one focused check for its event path and one compile check for the directly affected crate. Do not run the full workspace test suite. Do not commit `codex-rs/Cargo.lock` changes caused only by the release-tag workspace version mismatch.
