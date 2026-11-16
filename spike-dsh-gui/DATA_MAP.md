# Existing data and interpretation contract

This document owns the evidence routes and proposed display semantics. Source keys resolve in [SOURCES.md](SOURCES.md). Feature IDs resolve in [FEATURE_MAP.md](FEATURE_MAP.md); G-numbers resolve in [CAPTURE_PLAN.md](CAPTURE_PLAN.md).

"Available" below means an owning source exists. The recorded-evidence column distinguishes exercised data from source-only support. None of these definitions changes the recording contract in this spike.

## Current pipeline and reuse boundary

Both clients feed the project's native capture:

Client -> instrumented Core/App Server -> one run's manifest.json + trace.jsonl + payloads -> Python reader/server -> browser event stream and lazy artifact reads.

The Python server currently exposes /api/header, /api/stream, and /api/artifact. Its viewer_event() includes the full payload and original event in full-content mode; the supplied browser receives references, not automatically parsed request/response bodies. The current app.js renders task lanes, a filterable event list, selected-event facts, protocol pairing, and raw/formatted artifacts. It has no request-indexed context projection, semantic transcript, token dashboard, or trajectory overview.

A rich Rust reducer already exists: replay_bundle() builds inference, conversation, tool, code-cell, terminal, compaction, and interaction objects. The native CLI's debug trace-reduce command can write state.json. That file is not automatically produced by these recordings or consumed by the web UI. Its presence must not be assumed.

Recommendation for discussion: keep the portable Python replay path and derive the necessary teaching projection from the existing raw recording. Use the Rust reducer's identities and invariants as reference rather than building an unrelated interpretation. Requiring a native reducer for every replay would change the documented Python-only replay requirement. Also, the reducer intentionally normalizes a subset of item types; raw payloads must remain reachable for newer/unsupported types. This is a development-path proposal, not a new canonical schema.

## Evidence routes

| Key | Data present now and concrete route | Useful displays | Limit and recorded evidence |
|---|---|---|---|
| E1 | RawTraceEvent: seq, wall_time_unix_ms, rollout_id, task_root_thread_id, thread_id, codex_turn_id; harness events add step_id and correlations. O.raw, O.view. | Ordering, grouping, scopes, selection, cross-links. | seq is local writer append order, not a universal causal clock. Both task recordings exercise IDs and lifecycle pairing. |
| E2 | inference_started: inference_call_id, model, provider_name, step_id, request_kind, compaction_id, transport, request_payload, optional logical_request_payload. O.req; C.client HTTP and WebSocket preparation. | Every request's input items, instructions, options, schemas, model, failed attempts, incremental continuity. | Prepared body is observed before the transport call; it does not prove receipt. Both live-evidence recordings use HTTP; WebSocket continuity is source/test evidence only. |
| E3 | inference_completed/failed/cancelled reference response_payload or partial_response_payload. TracedResponseStreamOutput contains response_id, upstream_request_id, token_usage, observation_stage, output_items, partial_output_text. O.req. | Assistant output, tool-call arguments, usage, failure and cancellation details, opaque content. | Stage is after_interceptors. This is parsed output, not every provider stream event or original wire bytes. Usage is optional. Twenty completed attempts report usage; six failed Desktop attempts do not. |
| E4 | history_item_accepted records item_id and local time/sequence; agent messages additionally retain an agent_message_payload. O.hist. | Distinguish locally admitted output from discarded attempts, and local admission from inherited prefill. | Other receipts do not carry the accepted item body. No ID means no receipt. Callback observes admission of the original envelope, not a complete post-truncation history snapshot. |
| E5 | harness prompt_assembly: logical stage, attempt, history/tool counts, role/family/modality counts. prepared_request_context: categories and instructions/previous-response presence. context_contribution: source in correlations, outcome, bounded counts. C.turn, C.session, O.req. | Explain assembly stages, coarse context events, sanity checks. | Counts, not per-part source links or token lengths. step_context_capture only records lifecycle success/failure; its completed event does not serialize the captured StepContext, environment, model budget, or tool registry. |
| E6 | compaction_request_* capture request attempts/results; compaction_installed references checkpoint with input_history, installation_history, installation_suffix, replacement_history. compaction_application/decision add lifecycle/reasons. O.comp; C.session. | Before/after context, actual installation marker, retained suffix, failed/background candidate distinctions. | A decision or finished candidate is not an installation. Current task samples have no compaction installation; source and reducer tests support this route. |
| E7 | tool_call_started/ended, tool_call_runtime_started/ended, summary, invocation_payload, result_payload, runtime_payload; model_visible_call_id, code_mode_runtime_tool_id, requester. MCP correlation assignment is separate. O.tools, O.raw. | One semantic tool row with original call, runtime execution, result, status and duration. | These are distinct observations of one call, not separate call counts. Samples exercise direct exec_command and apply_patch; not all tool kinds. |
| E8 | code_cell_started/initial_response/ended: runtime_cell_id, model_visible_call_id, source_js, response_payload, runtime status; nested tools name a code-cell requester. O.cell; O.model. | Outer JavaScript program, subtools, yield/wait/resume, call hierarchy. | A yielded initial response is not the cell's final end. Result returned to JavaScript is not automatically included in model input. Source/tests support this; the two task samples do not exercise code cells. |
| E9 | Exec runtime payloads and stdin_target_resolved; reduced TerminalSession/TerminalOperation/TerminalResult document process/operation joins, cwd, stdin, exit, stdout/stderr, formatted output, original_token_count and chunk_id. O.term, O.protocol, O.model. | Commands, process lifetimes, polling, failure and truncation, command panel. | Runtime process/session IDs can be reused. A write_stdin poll is not another command launch. Caller-visible output may differ from full runtime output. |
| E10 | app_server_frame_observed retains frame_payload with connection_instance_id, exchange_id, direction, frame_kind, method, typed request ID, thread/turn/item IDs when known. Includes turn/start/steer, item events/deltas, tokenUsage updates, approvals and settings. O.raw, O.wire. | Submitted user inputs, streaming display, request settings, schema/item details, protocol evidence. | Negotiation/subscriptions/filters govern observation. Prepared outgoing does not prove client delivery. Deltas exist in both task recordings but are not uniformly linked to inference_call_id. |
| E11 | mcp_frame_observed and wire transport events retain typed discovery/call frames and mcp_call_id; Core captures backend results separately. O.wire, O.tools. | MCP input/output and discovery schemas, exact tool identity, transport detail. | Typed JSON is not original bytes. tools/list inventory is not proof the model received those schemas. Model-facing wrappers and backend schemas may differ. |
| E12 | task-root envelope, thread starts/metadata, agent paths, agent_spawn/identity/message/delivery/admission/residency events, agent_result_observed and tool links. O.agents, O.hist, O.view TaskLedger. | Parent/child scope, messages, descendant usage, agent navigation. | Queue admission, delivery, history admission and later request inclusion are separate facts. Independent Desktop background roots are not subagents. No child-result evidence in the audited task samples. |
| E13 | Manifest: schemas, build_descriptor, shared_run, root anchor, capture_health. Recording completion and run/thread terminal events. O.bundle, O.release. | Recording identity, compatibility, incomplete/missing evidence display, replay status. | Clean writer health means no recorded writer failures, not complete instrumentation coverage. Per-event roots own shared-run tasks; manifest's first-root anchor does not own the whole run. |
| E14 | Internal annotations: ContentItemKind and ContentItemMetadata.provenance, positional to each message content entry. C.ann, C.fragments, C.client. | Reliable source-aware grouping, instructions vs human input, skills catalog vs selected skill content. | Present in Core before provider shaping, but removed selectively for standard Responses and third-party providers. Neither task recording preserves them in requests. Reduced conversation bodies also do not expose these annotations. G1 preserves existing information. |
| E15 | thread/tokenUsage/updated carries total, last and modelContextWindow. Core ContextWindowTokenStatus computes active_context_tokens, compaction-scope values, effective full limit, remaining budget and threshold booleans. C.budget, C.session. | Current-context gauge, why-compaction explanation, window/threshold markers. | App Server carries a useful coarse window; it is not a complete resolved budget snapshot. Numeric decision inputs are currently omitted from the harness compaction event. G2. |

## Identity and joining rules

1. Scope all identities by recording/run. Use task root and owning thread for the selected conversation; include descendants only through explicit relationships.
2. One agent step can have several sampling attempts and transport retries. Keep step, sampling attempt and inference_call_id separate. Do not use a displayed "Step 7" as a global join key.
3. Pair inference terminals by inference_call_id. response_id supports previous_response_id continuity; upstream_request_id is a provider transport identifier, not an interchangeable key.
4. Link model-visible tool call/output items by call_id in the owning thread and their source request/response. Join runtime tool_call_id to model_visible_call_id or the code-mode bridge metadata. Do not merge them merely because their strings happen to match.
5. Link nested calls through requester.code_cell/runtime_cell_id; the outer exec call and subsequent wait calls can observe the same cell. A tree may contain outliving work.
6. Use stdin_target_resolved to disambiguate recycled process handles. Separate a terminal process lifetime from each command/write/poll operation.
7. Pair protocol exchanges by protocol + connection_instance_id + exchange_id. Retain frame direction and role. A numeric JSON-RPC ID alone is insufficient.
8. An accepted receipt establishes local admission of that ID only. Seeing identical text in another attempt does not establish acceptance; inherited child prefill does not become locally generated output.
9. Prefer explicit item IDs. For a visual item without an ID, use snapshot-local position plus content identity and occurrence information. Such matching may support a visual diff but must not create a new causal, acceptance, or cross-thread identity claim.
10. Preserve references to the original seq, payload path, and JSON location in every derived row. A semantic row may cite several events. The raw log remains accessible without duplicating every transport notification as a learner-facing row.

## Proposed learner-facing definitions

These are recommended meanings to settle in discussion.

### Requests and context snapshots

- "Observed request" means the prepared transport body at E2.
- "Logical context" means the separate continuity snapshot when supplied, or a reconstruction supported by prior request/response evidence. Mark its stage and any unavailable prefix.
- A WebSocket delta can be much smaller than the context it continues. Show both sent delta and logical context; never graph the delta alone as total context occupancy.
- If a prior response is absent but the native logical snapshot is present, use that evidence. If neither supplies the omitted prefix, show incomplete context instead of inventing it.
- "Latest request" is the most recent observed request for the selected thread. The last known request is not the guaranteed next request.
- Context comparison operates on a named snapshot and baseline. Compaction resets, retained background suffixes, and model/provider changes must remain visible.
- Inputs from turn/start and turn/steer establish submission. They do not establish that all content was accepted or included in a model request.

### Counts and scope

- Label native activations "Turns"; show human submissions separately if useful. A native turn can start without a new human prompt.
- Label distinct agent-step IDs "Steps", and inference attempts "Model requests" or expose the distinction on selection. DSH's countsOfRecords() uses request records for steps; direct copying would obscure retries.
- Count a semantic tool_call_id once. Present direct model calls and nested calls separately; do not sum raw start/runtime/end frames.
- Show "Assistant messages" unless terminal-answer phase is known. If offering "Answers", use observed final-answer phases and retain an unknown-phase category. DSH counts assistant text more broadly.
- A skills catalog is available guidance, not a skill invocation. Explicit native invocation, native detection of an implicit invocation, a SKILL.md read, and the model claiming to use a skill are distinct observations.
- File counts distinguish unique paths, operation count, image blocks and image reads. The same image can participate in several categories; do not present a sum as unique files.
- Parent+descendant usage includes requests actually made by those threads. Replayed inherited context is not a second output-generation event, although resubmission consumes input tokens. Exclude unrelated Desktop background roots from a selected teaching chat.

### Tokens and estimation

Use per-inference reported usage as the accounting source. Do not also sum cumulative App Server total updates. Keep failed/cancelled requests with missing usage in the request count and label coverage, for example "usage reported for 4 of 10 requests".

For the captured Codex TokenUsage representation:

- Input tokens already include cached input. Cache read/write counts are components/annotations, not additional input to add again.
- Output tokens include reasoning_output_tokens; do not add reasoning again.
- Cumulative processed tokens = sum(input_tokens + output_tokens) over attempts with reported usage. This repeatedly counts context sent on later requests; it is not the size of a conversation.
- Cache read share = sum(cached_input_tokens) / sum(input_tokens) for the same reported subset. Do not average per-request percentages.
- A single request's context composition is different from cumulative processed tokens. DSH's billedParts() mixes accumulated usage with estimated content shares; label any analogous allocation as estimated.
- Keep per-category estimates separate from reported totals. A chart scaled to match a total still has estimated category attribution. It must not be labelled an exact breakdown.
- Text/schema estimates need one declared, reproducible method and version. DSH uses four characters per token plus fixed overheads; that is not a Codex tokenizer. Do not apply DSH image formulas to all Codex models.
- Image/audio and opaque reasoning/compaction items can account for a gap between visible estimates and reported input. Keep an explicit unallocated/opaque portion rather than normalizing every discrepancy away.
- content_token_count exists internally on some output messages but is skip_serializing and not preserved by the current response trace serializer. Even retaining it would not provide an exact input-source token breakdown.

The audit found input+output=total for every reported usage object in the two task recordings. CLI reported input=169230, output=1342, total=170572; Desktop reported input=106807, output=363, total=107170. These are observations of this provider, not a new cross-provider billing contract.

### Context occupancy and compaction

Last provider input, current live-history estimate, cumulative usage, usable context limit, and auto-compaction threshold are different quantities. The Core's get_total_token_usage() combines last reported usage with estimated later additions and reasoning-accounting rules. Capture that value as a harness estimate, not an exact provider count.

Do not infer a reserved-output band from the difference between an advertised model window and effective limit. The two audited clients report modelContextWindow=31129; the configured test provider's nominal window was 32768. G2 should record the actual resolved quantities and their roles.

A compaction marker means a replacement history was installed. Show candidate creation, request completion, installation and failure separately. A removed item between snapshots is a change, not proof of a prune operation. Codex normalization, media filtering, history truncation and request preparation can also change membership.

Turn-level trend bars represent the last snapshot in each turn. Totals across steps describe processing; summing context sizes does not produce a context snapshot. Delta bars show signed category/item changes relative to the named baseline; distinguish net change from the sum of absolute changes ("churn"). A first displayed snapshot with an unavailable baseline has unknown delta.

### Timing

Use observed wall timestamps for display and writer sequence for order/ties. Clock regressions or absent terminals yield unknown durations, not negative values silently converted into plausible measurements.

A model request's observed duration and a tool's runtime duration are useful now. A tool dispatch, terminal operation, entire process, code cell and model wait are different intervals. Concurrent intervals overlap; their sum is not elapsed wall time.

For teaching, a useful aggregate is the union of known active operation intervals within the selected scope, with waiting/unknown intervals distinguishable. Do not silently inherit DSH's two-minute inactivity heuristic or imply that uncovered time is CPU/network "overhead".

Client-facing first delta latency is observable in E10 when attributable. It is not guaranteed first generated token time. Core's existing ttft_ms starts its clock after stream setup and uses OutputItemAdded; simply exporting it as full request-to-first-token latency would be misleading. G5 defines a better trace observation if that display is wanted.

## Media, schema and replay boundaries

Embedded data URLs and recorded blocks can be rendered from the bundle with viewer work. A file path or remote resource URL alone does not guarantee durable bytes. The artifact server serves bundle-local content; it should not silently read today's workspace file or fetch a remote image to fill a historical gap. Show the recorded path/metadata with "content not recorded" when necessary. A narrow collection change for durable media is G7.

Look up the model-facing schema in the selected request's top-level tools and in-band additional_tools, including namespaces/deferred tool definitions where represented. Tool discovery packets provide backend schemas with a different stage. If only a backend schema is known, say so; do not present today's tools/list as the historical model-facing schema. G8 is optional for missing nested-call-time schemas.

Readable reasoning content, provider summaries and encrypted content are different renderable forms. Preserve any authentic readable content already returned to Codex. Mark encrypted blocks as opaque; neither an interface nor more local collection can reconstruct hosted private reasoning.

Replay and export must stay read-only with respect to source recordings. Missing payloads, unsupported schemas, interrupted runs, redacted-content mode, and partial history are display states. None should become a zero value or a false "complete" claim.
