# Instrumentation Tranches

All tranches write `HarnessTraceEvent` records into the existing rollout trace. They must not create another log file, emit app-server or desktop events, or persist model reasoning deltas. Event details should contain compact facts that explain a state transition. Existing payload references remain the source for full model requests, responses, tool arguments, and results.

Every event should carry the current `trace_step_id` when a `StepContext` is available. Use `call_id`, approval/review ID, child thread ID, and similar values as correlations. Prefer categorical outcomes and reasons over human-readable summaries that are hard to aggregate.

## Tranche 0: Shared trace foundation

Status: complete.

Owns the raw and reduced event envelope, step ID allocation, category and phase vocabulary, source pin, and baseline build record. Later tranches should consume this API without changing the envelope unless an actual missing field blocks their work.

## Tranche 1: Agent loop and supervision

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

## Verification budget

Each tranche should run one focused check for its event path and one compile check for the directly affected crate. Do not run the full workspace test suite. Do not commit `codex-rs/Cargo.lock` changes caused only by the release-tag workspace version mismatch.
