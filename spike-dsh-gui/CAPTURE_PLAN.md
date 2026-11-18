# Collection gaps and minimum-patch options

These are concrete proposals for discussion, not approved wire formats. Feature IDs are in [FEATURE_MAP.md](FEATURE_MAP.md); existing evidence and identity rules are in [DATA_MAP.md](DATA_MAP.md). Code keys resolve in [SOURCES.md](SOURCES.md).

This is the assessment inventory, not a claim of implemented parity. See [the implementation record](DEVELOPMENT.md#implementation-record-2026-11-16) for the delivered first version, G1-G3 capture additions, verification and deferred work.

## What can be built without new native patches

Historical request browser; model input/output inspection; actual reported usage and cache share; model/tool counts; coarse context trend/deltas; semantic tool/terminal ledger; code-cell/subtool hierarchy; compaction checkpoint comparison; root/agent navigation; rich/raw details; search, filtering, brushing, folding and linked selection.

These require substantial reader/projection/UI work, but not a new collector. Missing data in an older recording remains missing. New native patches should correspond to a specific teaching claim we cannot otherwise support.

| Gap | Primary benefit | Smallest plausible change | Recommendation |
|---|---|---|---|
| G1 | Explain where context comes from, independent of role. | Preserve existing annotated logical prompt in trace-local evidence before request shaping removes annotations. | Highest-value collection candidate. |
| G2 | Explain context pressure and why compaction occurred. | Add already-computed budget/model quantities to existing context observations. | Highest-value small capture candidate. |
| G3 | Inspect current history between requests in a DSH-style live preview. | Observe the needed post-mutation history facts at native owners. | Live preview is in the D1 target; fidelity and minimum capture boundary remain open. |
| G4 | Named explicit/implicit skill use, distinct from catalog/read. | Mirror native invocation observations into the project trace. | Small, targeted candidate after G1. |
| G5 | Faithful first-output and decode-phase timing. | Inference-correlated compact stream observations at the shared mapping boundary. | Optional teaching enhancement; lower priority than G1/G2. |
| G6 | Explain file operations and non-compaction removals. | Reuse typed existing evidence; add source-local observations only for selected missing operations. | Scope narrowly; no general OS audit. |
| G7 | Portable historical image/attachment previews. | Viewer extraction where bytes exist; copy only otherwise-missing observed media at its owner. | Add collection only after demonstrating a pointer-only gap. |
| G8 | Exact historical schema for otherwise-unresolved nested tools. | Prefer recorded exposure/discovery; otherwise snapshot selected resolved definition. | Missing-schema state is acceptable until needed. |
| G9 | Reproducible estimates, pricing and optimization labels. | A display-method decision, generally no native collection. | Settle estimator; defer external price services. |

## G1. Preserve context source annotations

### Why this is a real collection gap

C.ann defines ContentItemKind and ContentItemMetadata.provenance. Sources distinguish ordinary user input, skills, AGENTS.md, developer instructions, harness/command-hook content and tool namespaces. C.fragments keeps classification and metadata aligned with content through merging and text truncation. C.skills-fragments further distinguishes skills.catalog from skills.selected_skill_instructions.

C.client build_responses_request() formats input, creates the tools/base-instruction prefix and then clears per-content metadata for standard Responses. Third-party providers lose the entire internal passthrough. prepare_response_items_for_request() can also clear content kinds. Our record_prepared_request() observes the later body. Existing logical_request_payload is a continuity snapshot of that provider-shaped request, not a guaranteed pre-stripping annotated history.

Both audited request sets have no internal_chat_message_metadata_passthrough keys. Coarse context_contribution events cannot restore the discarded annotations. Role or text-tag matching cannot replace reliable source evidence.

### Recommended capture boundary

Extend the existing record_prompt_assembly() observation in C.turn to reference an annotated logical-prompt payload. It already receives the assembled Prompt immediately before sampling and records stage and attempt. Include the logical input's content kinds/provenance plus base instructions and catalog context needed to explain it. This does not change any prompt delivered to the model.

For exact per-attempt correlation, give that logical snapshot a trace-only identity and carry its reference through InferenceTraceContext to each concrete inference attempt. A retry may reference the same logical snapshot; a newly assembled prompt gets a new one. If an auxiliary request does not traverse this path, its provenance is unavailable unless captured at its actual owner. Do not fabricate a snapshot for it.

A lower-duplication implementation could retain only positional metadata and content digests at the final annotated-input boundary in build_responses_request(), before the clear calls, and associate that sidecar with the later request. That requires more plumbing through preparation and retries. The full logical snapshot at the existing harness hook is the simpler first candidate for this teaching tool. Choose after discussion, not by silently adding both.

### Proposed trace content

- Snapshot identity, source stage, owning thread/turn/step, sampling attempt.
- Ordered logical items with native IDs when available.
- For each message content entry: its index, native content kind, provenance and original content, or a precise reference to already recorded identical content.
- Base instructions and logical tool/capability representation, with stage labels.
- Explicit link from inference attempts to the logical snapshot if exact joins are implemented.

Request-only synthetic prefix items and transformed/omitted items must remain distinguishable from the earlier logical stage. The current request body remains the authority for the prepared body. A sidecar must not imply that every logical fragment survived request preparation or that the provider received it.

### Patch boundaries and limits

Reuse O.req/O.hist's writer and payload references. Likely touch the trace crate, the existing C.turn harness hook, and the trace context in C.client. Do not change ContentItemMetadata, internal provider passthrough schemas, public App Server APIs, or the model-visible serialization to deliver observability data. Do not introduce a new ontology, classifier service or second log.

This captures native classifications, not every imaginable source path or semantic intent. Several sources are only generically "harness"; older history may be Unknown. A named skill's resource identity needs G4. Hidden provider context and opaque reasoning remain unknowable.

Acceptance: mixed user/injected user-role content stays distinct; annotations align after truncation/merging; a provider that strips annotations still receives the same request bytes/structure with tracing enabled or disabled; retries and incremental requests point to the correct logical source; Unknown stays Unknown. See Q1/Q2 in DEVELOPMENT.

## G2. Record context-budget facts already computed by Core

C.budget ContextWindowTokenStatus computes active_context_tokens, auto_compact_scope_tokens, auto_compact_scope_limit, full_context_window_limit, base_window_tokens_remaining, auto_compact_window_prefill_tokens and threshold booleans. C.turn compaction_decision currently persists booleans/reasons while omitting those values. step_context_capture currently records lifecycle only.

Small proposal: enrich the existing decision event with the numeric status used for that decision, the scope, the configured fallback buffer where relevant, and whether the trigger was a background candidate/explicit request/token threshold. At completed step-context capture, optionally record the resolved model/provider/effort/mode and model limits that the selected step actually uses. Reuse already-loaded settings, not fresh model-catalog reads.

Record these as distinct quantities rather than a single ambiguous "context window":

- Last provider-reported request input and its request identity, where known.
- Current harness active-context estimate and observation time.
- Resolved effective full limit; nominal window and effective percentage only when separately available.
- Auto-compaction scope, limit and prefill baseline.
- Remaining budget and fallback buffer.
- Any actual output-token reservation/cap if the current model/config exposes it; otherwise unknown.

DSH reserveGeometry() uses a fixed 0.8 window ratio and 65536-token headroom plus maxOutputTokens. Those constants are not Codex policy and must not be copied. Codex supports total versus body-after-prefix compaction scope and model-dependent effective limits.

Likely patches: C.turn and, if needed, C.session's existing step-context event; trace-owned serialization only if payload size warrants it. No new estimator or provider round trip is necessary. Post-turn and alternate compaction paths should be checked for the same event coverage rather than assumed identical.

Acceptance: a hand-checkable threshold scenario displays exactly the status used by Core, including body-after-prefix scope; unknown limits remain unknown; the display distinguishes reported input from harness estimate; compaction counts increase only on installation. A request made before any usage is reported still has meaningful limit metadata without an invented usage total.

## G3. Live context preview and current history

The current data supports observed historical requests well. It does not expose a complete state machine of current live history between requests. history_item_accepted generally supplies only an ID. Its admission callback is called with the original envelope; live history may separately truncate that content. Requests also format/filter history, add prefix items and vary by selected model.

Discussion target: D1 in DEVELOPMENT.md includes a DSH-style live preview alongside historical request inspection. "Latest observed request" remains a useful initial implementation, with the live preview added as part of the agreed target.

DSH's live browser assembles the current surface nodes rather than selecting the last request snapshot (D.assemble). Its current estimate can therefore include later assistant messages or tool results. In live mode, the displayed Actual figure comes from the latest request record (D.browser); it is not a measured size for a future request. These observations were checked in the pinned local source during the design discussion.

If complete live-history fidelity is needed to support the preview, add an observation of the actual resulting history at append, replacement, rollback/resume and other relevant mutation boundaries. Reuse the owning ContextManager rather than reimplementing its mutation rules in the viewer. A snapshot/revision should establish:

- Actual ordered admitted items and post-mutation content, including truncation/filter outcome.
- Revision identity, predecessor and the operation/reason that changed it.
- Thread/turn/step and source-local stage/time.
- Boundary for replacement/compaction/rollback, retaining source recording evidence.

A whole post-mutation snapshot is easier to audit than a second viewer-maintained delta protocol, but duplicates payloads. A revision/delta design is more compact and more complex. This is the one collection area that could justify a larger revamp if exact live history is central; it should not be smuggled in as a small UI task.

Even complete history cannot guarantee future request contents: pending input, hooks, tools, selected model, modality filtering, compaction and request preparation may still change them. Label current history and predicted request separately.

Acceptance must cover mutation before any next request, output truncation, cancellation, compaction replacement with a retained suffix, and resumed/rolled-back history. Inherited content must not be relabelled as locally generated/admitted.

## G4. Skill invocation observations

C.skills already distinguishes explicit injection and native detection of implicit skill reads, tracks skill/resource identity and deduplicates implicit invocations per turn. These go to analytics/telemetry/contributors, not to a dedicated Observatory skill event.

Mirror those native observations to a small harness event with kind explicit/implicit, resource identity, display name, plugin/scope when known, status, thread/turn and step/call correlation when actually available. An explicit selected-content injection and an implicit detected read are different events. Native detection itself is a named mechanism, not proof that the model followed a skill correctly.

Prefer these existing owners over a new independent shell-text parser. G1 handles source classification of skill content and catalogs. Avoid fetching today's skill registry during replay to make old rows appear complete.

Acceptance: catalog presence alone produces no invocation count; multiple repeated reads retain the native deduplication semantics; failed explicit loading is not a successful load; two resources with the same name do not become one identity accidentally.

## G5. First-output and phase timing

Coarse request/tool durations can be drawn now. App Server item deltas provide observed client-boundary streaming, but may be filtered and lack an exact inference attempt key. Native inference output currently records completed items, not every provider delta.

C.client map_response_events() is a shared post-interceptor boundary with InferenceTraceAttempt in scope. It already computes a telemetry ttft_ms, but starts its Instant after stream setup and stops at OutputItemAdded. That is neither full request latency nor necessarily the first generated token.

If fine timing is selected, record compact phase observations keyed by inference_call_id:

- Prepared-request observation as an explicit time origin.
- First response/first output-item observation, separately named.
- First meaningful content observation when exposed, with kind text, reasoning text/summary, or tool arguments.
- Changes of observed output kind and their local monotonic offsets.
- Terminal status, including cancellation/failure and incomplete phase coverage.

Keep a compact span/transition record, not another copy of every text delta. Do not make the observation change stream scheduling or response interception. HTTP setup time and post-interceptor processing must have declared boundaries. Provider metadata can be preserved separately when available, never substituted for local observations without labelling.

Some endpoints expose opaque reasoning and no meaningful content deltas. Their generation split stays unknown. Observed time between deltas is not precise model compute time. Concurrent tools and model output can overlap, so a mutually exclusive donut needs a stated allocation or a coarser display.

Likely patch: C.client's shared mapper plus trace-owned event/payload helper; no Desktop or App Server API patch. Acceptance: deterministic mocked event timestamps/order, retry/cancel paths, opaque-only response, interleaved tools, and no negative/double-counted elapsed time. Do not benchmark a live model to validate this logic.

## G6. File operations, removals and truncation reasons

Start with existing typed tool calls, exec commandActions/runtime data where present, apply_patch parse/commit evidence, model output and snapshots. Derive file operations only when the structure warrants it. A request to read/edit and a confirmed result/commit should remain separate facts.

Arbitrary shell commands, JavaScript, subprocesses and remote MCP tools can touch files without yielding complete path/range metadata. No bounded local patch will make their full filesystem activity known. DSH also derives many file operations from recognized arguments and output metadata; its list is not an OS audit.

If exact teaching examples need more:

- Add source-local structured observations to the selected built-in read/search/edit owners that already know path/range/result.
- Preserve existing truncation counts/limits and the distinction between raw tool result and model-facing result.
- For a claimed "prune", observe the actual history mutation/removal owner with reason and affected native item IDs, or use G3's resulting snapshots.
- A snapshot membership difference alone is labelled "removed from this request", not a prune or deliberate forgetting action.

Do not add syscall tracing, intercept every filesystem API or alter tool behavior. Missing metadata for an opaque external tool remains unknown. Acceptance: failed patch/read is not counted as a committed write/read result; relative paths use recorded cwd; polling does not inflate file counts; model-visible truncation is not reported as evidence deletion.

## G7. Durable media and attachments

First implement viewer extraction of existing embedded input_image blocks, data URLs and MCP/tool result media. The native request/result payload may already contain all bytes needed. A new collector is unnecessary for those cases.

If a demonstrated route stores only a local path or expiring resource URL, copy the exact observed bytes once into the same bundle at the existing image preparation/tool-result owner, and reference them from the observation. Retain media type, dimensions when known, content identity, original source locator, and whether it was resized/transformed for the model. Do not assume the original disk image and model-facing image are identical.

Use the existing payload writer; no asset service or global media cache. Rendering from a recording must work after the original file is changed or deleted. Do not resolve a historical path against the replay machine or silently fetch the network.

No media was present in the two audited task captures. A single bounded image/attachment scenario is necessary before claiming route coverage. Audio/video support is a separate extension unless needed to render a specific recorded block.

## G8. Historical schema and tool ownership

Lookup order for a selected call:

1. Model-facing top-level or in-band additional_tools catalog in its request.
2. Recorded deferred-tool/search exposure that applies to that request.
3. Recorded backend MCP discovery/definition with explicit stage.
4. Unavailable.

Existing O.req tool_catalog points to the prepared request. It does not guarantee schemas for every tool callable inside a code cell. DSH's plugin attribution includes inferred ownership; Codex should preserve known namespaces/server/plugin facts and label unknown ownership.

If exact nested-call-time schema is a chosen requirement, record the selected resolved definition/digest at the existing tool dispatch/registry boundary, linked to tool_call_id or mcp_call_id. Preserve public wrapper schema separately from backend schema. For MCP catalog mutation, follow the existing connection-manager ownership rather than plumbing schema state through the agent loop.

No need to dump the entire registry on every call or modify remote servers. Acceptance: catalog changes between requests retain both historical versions; a discovery-only tool is not shown as advertised to the model; a missing definition is not replaced with today's schema.

## G9. Estimation, costs and threshold conventions

This is primarily an interpretation decision, not missing telemetry.

Choose one visible category-sizing method with a method/version identifier. Cheap options are content byte/character measures, a declared text-token estimate, or a suitable local tokenizer for supported models. Native reported usage remains separate. Preserve opaque/media/unallocated portions and avoid false precision. Do not turn method choice into a new provider dependency.

DSH uses four characters per token plus fixed overheads, applies model-specific image estimation, and anchors category proportions to provider totals. It also uses a 10-second "slow command" threshold and a two-minute inactivity threshold. Copying these defaults would make durable interpretive decisions without a Codex teaching rationale.

Pricing requires additional external, dated data plus provider/account/discount assumptions. A subscription, custom model or local model may not have a meaningful comparable per-token price. Recommend keeping cost unavailable unless explicitly configured for a lesson; do not start a price service to fill a cosmetic dashboard slot.

## Schema and recording compatibility

Keep all new evidence in the existing append-only log and payload directory, with the same rooted client launch. Preserve actual model behavior, request contents, provider stripping rules, interception and tool semantics.

Trace-owned additions should define their observation stage and identity explicitly. Adding an unknown harness name alone is easy for the Python reader, but readers/reducers that need new semantics must expose feature availability and missing values honestly. A new raw payload shape or variant needs an explicit raw-schema/reader/reducer update; the current Python reader caps raw schema at 6.

Do not change public App Server request/response types or provider passthrough structs for this spike's telemetry. Do not require a second exporter, storage backend, plugin runtime, or daemon. Old recordings should still open through the existing reader with unavailable new features; no migration should rewrite their original evidence.

The minimal native candidate for discussion is G1 + G2, with G4 if named skill use belongs in the first teaching release. Everything else can be evaluated against the first linked prototype before adding patches.
