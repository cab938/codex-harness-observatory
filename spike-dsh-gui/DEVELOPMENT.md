# Development handoff and discussion decisions

This is a proposed sequence following instructor discussion. It is not an instruction to implement now. The feature inventory, data semantics and collection proposals have separate owners; this document identifies the work boundaries and evidence that would establish a working teaching interface.

## Recommended implementation shape

Keep one recording and one derived teaching projection shared by both views. Extend the existing Python reader/server and browser application; do not add a DSH host, another collector, a database, an OTel route or a second persisted event format.

Put new projection logic in a focused module rather than growing the 2400-line trace_viewer.py. Similarly, keep new browser views separate from the existing large app.js. The server currently serves three explicit asset paths, so loading additional local modules/assets needs a small server/package-data change. This does not require a frontend framework or native patch.

The projection should retain:

- Scope: recording, task root, thread and optional explicit descendant set.
- Native turns and steps, distinct logical sampling attempts and concrete inference attempts.
- Snapshot references for prepared body, logical context and optional source-annotated prompt.
- Semantic records linked to all contributing raw seqs/payload locations.
- Tools, code cells, terminal operations and agent relationships with the identities in DATA_MAP.
- Reported usage with coverage; estimated sizes with a declared method; unknown portions.
- Actual compaction installations and associated before/after snapshots.
- View-only selection, filters, fold state and time/sequence ranges.

These are responsibilities, not a proposed new public schema. Keep large content behind existing artifact references. A view should be replayable from a recorded prefix; the arrival of a final event can update provisional rows without changing their identity or erasing the failed attempts that preceded them.

Do not require state.json or a native Codex executable for portable replay. If a matching reduced graph is present, it can be useful evidence, but making it a required backend would be a separate architectural change.

## Coherent implementation stages

### Stage 1. Linked semantic trajectory over an existing recording

Build U01-U04/U08, T01/T04-T13/T16/T19-T20/T24, with coarse known timing and raw evidence. Start with the two saved task recordings and a compact hand-checkable fixture for nested calls. Preserve all current task/agent and protocol inspection capabilities.

Deliver a dense ledger with recognizable user/assistant/tool rows, explicit unknown context sources, request selection, a three-lane overview, and a useful selected-record pane. Reuse the current pause/follow and detail pane. Schema/media/timing tabs should report unavailable content when the recording cannot support them.

The purpose is to assess whether the hierarchy and navigation make the agent loop teachable. No native patch is required for this stage. Do not implement pricing or fine timing to fill visual slots.

### Stage 2. Context browser, composition and change

Build B01/B03/B05/B08, R01-R03/R05-R06/R09-R10, C01-C07/C10-C12, X02/X04-X05, and the linked file/command inspection supported by existing evidence.

Make prepared input, logical continuity and latest observed request explicit. Add previous-step/turn baselines, estimated composition with unknown source/media portions, actual reported usage, tool catalogs and source evidence links. Include compaction before/after inspection from a small controlled fixture. Add treemap, adaptive scale and full overview after the basic teaching interaction is reviewable.

Stage 1 and 2 should use the same item/request identities and projection. This avoids two viewers drifting into different explanations.

### Stage 3. Minimum teaching capture additions

If approved in discussion, add G1 source annotations and G2 budget facts, then G4 native skill-invocation observations if named skill use is part of the initial release. Feed the same views; do not add a separate dashboard.

Keep changes at existing owners and in trace-owned types. The schema/reader/reducer/release/inventory changes must be treated as one coherent recording-contract update, with small reviewable patches if needed. Do not alter public provider or App Server payloads to transport the new observations.

This stage should make it possible to answer "Where did this instruction come from?" and "Why did Codex compact here?" without relying on guessed text patterns.

### Stage 4. Remaining resemblance and demonstrated gaps

Finish file/command presentation, media previews, schema details and long-session interactions. Add G7/G8 collection only where a concrete missing recorded asset/definition blocks a chosen lesson.

G3 exact live history and G5 detailed phase timing are separate scoped changes. Their need should be judged against the linked prototype. Production cost/rate/slow-command features remain mapped but can stay lower priority.

## Acceptance catalogue

These are behaviorally meaningful scenarios for the future implementation. Select checks by the changed path; do not run every scenario or a repository-wide suite for every patch. Existing repository and crate instructions still govern mandatory native tests.

| Check | Scenario and expected evidence | Guards |
|---|---|---|
| Q1 | A user-role skill/injected fragment and a normal human prompt appear in one request; role is preserved while source labels differ. Unknown legacy source remains unknown. | G1, A02/A04, C03, T06/T16. |
| Q2 | Same agent step retries after a failure; failed and completed attempts remain separate, each links to the correct prompt stage, and usage is counted once per reporting attempt. | E2/E3 identity; B01/B08; trajectory request numbers. |
| Q3 | A full request is followed by an incremental WebSocket request; prepared delta and logical context remain distinct. Repeat with a missing previous response, both with and without an available logical snapshot. | Context browser/trend correctness; no invented prefix. |
| Q4 | Two identical output strings come from different attempts; only the native accepted ID gains admission. A child inherits content without gaining its parent's generation/acceptance history. | Acceptance and source identity; existing O.tests acceptance cases. |
| Q5 | One outer JS cell calls tools, yields, is polled/waited and later completes. The nested value reaches JS before any later model request includes it. | T08/K05 hierarchy; no premature "model saw this". |
| Q6 | Two terminal launches reuse a process handle; write_stdin is explicitly resolved to the right exec. Nonzero exit, still-running result and model-facing truncation stay distinct. | Terminal correlation, command counts, raw/result distinction. |
| Q7 | Background compaction candidate completes without installation; a later installed checkpoint retains a suffix added after the candidate input. | X02/R05; install count, before/after/retained content. |
| Q8 | Snapshot membership changes through normalization/media filtering or truncation without a compaction install. Show the change and any recorded reason; do not create a prune event. | G6 and faithful history explanations. |
| Q9 | Effective context limit and body-after-prefix threshold differ. The displayed estimate/limits match the Core values recorded at its decision. | G2; no copied DSH 0.8/65536 constants. |
| Q10 | One parent, its child and an unrelated Desktop background root overlap. Selected-chat totals include only the named scope; all-thread forensic mode remains available. | Agent/root isolation, fleet summary, timelines. |
| Q11 | An image appears in a tool result/request. Replay after the original image is changed/deleted uses the recorded bytes, or explicitly reports that bytes were not recorded. | G7; historical reproducibility. |
| Q12 | Catalog changes between requests; a tool can be advertised, backend-discovered or runtime-only. Schema pane uses the correct historical stage/version. | G8; no substitution of current schema. |
| Q13 | Missing payload, partial final line, interrupted recording, unsupported event/item, opaque reasoning and redact-content mode each produce a meaningful state without fabricated zeros. | Read-only/error states, forward visibility. |
| Q14 | Hover/pin/select/filter/fold/range operations agree across overview, ledger and Context; live arrival does not move a pinned historical selection. | Shared projection/selection and usability. |
| Q15 | Two concurrent tools overlap a model interval. Sum of durations can exceed elapsed time; a timing strip/aggregate does not double-count wall time. | M01/M05; G5 if fine timing selected. |
| Q16 | A long representative session includes many images, code blocks and nested calls at an instructor laptop/projector viewport. Rows remain readable and selection is retained while older records load. | Density/scroll/detail behavior; no gratuitous cards or tiny text. |

A small synthetic recording may cover several cases. Prefer known identities and quantities over model wording. Tests of native capture should assert the actual trace/payload contract and unchanged model/tool behavior, not merely that a new event name exists.

## Narrow validation plan

For a reader/UI-only stage:

1. One targeted projection execution against a tiny fixture or one retained recording, checking IDs/counts and a hand-verifiable input/output relationship.
2. One rendered interaction check of the changed view, including selection linkage and an unavailable-data state. Use existing synthetic/retained data; no model server is needed.

Use the relevant existing tests in tests/test_trace_viewer.py, test_capture_archive.py and test_trace_compare.py as references, not as a reason to broaden validation. The current trace_compare tool compares evidence coverage; it is not an existing side-by-side GUI context comparison.

For a capture stage, add the required focused native integration coverage for the changed semantics. Reuse current trace-crate acceptance/code-cell/conversation tests and Core tool-dispatch/context tests. The project development guide requires a bounded scenario through both CLI and Desktop when capture/launch behavior is shared. Keep exact model/build/config identity and replay the resulting bundle after shutdown. Full Rust-suite execution requires the project's normal approval; this spike does not authorize it.

Visual verification should use the existing browser route and the project's light, dense, square-corner conventions. No mockup or GUI implementation was produced by this research task.

## Three discussion decisions

### D1. What should "live context" promise?

Recommend **historical snapshots plus a live-following latest observed request** initially. This supports the central lessons with existing data and G1/G2. If the instructor needs complete current history between requests, choose G3 explicitly and account for mutation coverage and a larger capture change. A guaranteed next request cannot be promised even then.

### D2. What should composition charts mean?

Recommend **recorded source attribution where available, explicit unknowns, and one declared text/schema sizing estimate alongside provider-reported totals**. Preserve both role and source. Show media/opaque/unallocated portions instead of scaling away uncertainty. A tokenizer choice and any area normalization must be settled before accepting quantitative charts; no need to buy precision from a new service.

G1 + G2 are the recommended first capture additions, with G4 if the skill statistic should denote native invocation rather than merely selected skill content. Raw source kinds remain available even if the instructor-facing grouping changes later.

### D3. How much timing detail helps the lesson?

Recommend **coarse request/tool/wait timing first**, retaining the DSH strip/overview interaction. Add G5 only if separating observed reasoning/text/tool-argument intervals advances the intended teaching. Cache share can be displayed cheaply from existing totals; cost services and throughput optimization should not determine collection architecture.

## Completion boundaries for this spike

Done here: source and recording investigation; display-feature inventory; evidence/identity/metric mapping; concrete gap proposals; implementation stages; acceptance catalogue; durable screenshots and evidence audit.

Not done here: adopting a new trace schema, editing collectors/viewer behavior, running new live capture, porting DSH components, choosing an estimator or frontend framework, or claiming full provider/platform/media/compaction acceptance. Those choices and changes belong to the subsequent discussed implementation.
