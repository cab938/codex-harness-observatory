# Development handoff and discussion decisions

This document records settled discussion decisions, the original implementation sequence and the implementation record below. The user authorized implementation on 2026-11-16. The feature inventory remains a map of the full target; authorization does not imply that every DSH feature or proposed collection gap has been delivered.

## Settled learning-experience principle

User decision, 2026-11-16: Instructors and other learners receive equal design weight. An instructor is a learner who is willing to share what they know. Independent exploration and sharing an explanation are both central uses of the learning interface.

## Settled event-view and capture requirement

User decision, 2026-11-16: Preserve the expansive "events on the wire" capture and provide it as a first-class view for learning and debugging understanding. Keep an Events view alongside Context and Trajectory. Events exposes recorded protocol messages and harness/runtime observations in their original sequence, with timestamps, direction where known, correlation identities and original payload inspection. Capture-stage meanings and limits remain those documented in DATA_MAP.md.

Context and Trajectory group and explain the same recorded evidence. Their summaries link to the contributing events and payloads; an event can link back to related requests/items where the recording establishes that relationship. Events also exposes records that have no semantic grouping. View selection and filtering do not change collection or discard original evidence.

## Recommended implementation shape

Keep one recording and one derived teaching projection shared by Context and Trajectory, alongside the preserved Events view. Extend the existing Python reader/server and browser application; do not add a DSH host, another collector, a database, an OTel route or a second persisted event format.

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

## Original implementation sequence

### Stage 1. Linked semantic trajectory over an existing recording

Build U01-U04/U08, T01/T04-T13/T16/T19-T20/T24, with coarse known timing and raw evidence. Start with the two saved task recordings and a compact hand-checkable fixture for nested calls. Preserve all current task/agent and protocol inspection capabilities, keeping Events separately navigable with links from the semantic views.

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

Add the DSH-style live context preview selected in D1, using the smallest G3 collection change that supports the agreed behavior. Detailed phase timing (G5) remains a separate choice. Production cost/rate/slow-command features remain mapped but can stay lower priority.

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
| Q14 | Hover/pin/select/filter/fold/range operations agree across overview, ledger and Context; live arrival does not move a pinned historical selection. Jump from a grouped item to its contributing Events rows and original payloads, and return through recorded relationships. Unmapped raw events remain inspectable. | Shared projection/selection, preserved Events view and usability. |
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

Discussion outcome, 2026-11-16: Include **historical request inspection and a DSH-style live context preview** in the target interface. The live view represents observed current history between model requests. The latest actual request remains separately inspectable, and reported usage stays attached to the request that produced it. A live preview cannot guarantee the eventual next request.

The initial G3 implementation and its observation boundaries are recorded below. Historical request payloads, logical prompts and observed retained history remain distinct stages; the preview does not simulate a future request.

### D2. What should composition charts mean?

User decision, 2026-11-16: Approximate category sizes are sufficient when the actual content and available provider-reported request totals remain inspectable. Use the proposed source-oriented groups: base instructions, tool definitions, human messages, injected context (including project instructions), skill instructions, assistant messages and tool results. Preserve original role and source information in item details.

Use recorded source attribution where available, explicit unknowns, and one declared reproducible text/schema sizing estimate. Show media/opaque/unallocated portions instead of scaling away uncertainty. The initial estimator and category-bar normalization are specified in the implementation record below. The Events view and underlying capture are preserved as specified above.

G1 + G2 are the recommended first capture additions, with G4 if the skill statistic should denote native invocation rather than merely selected skill content. Raw source kinds remain available even if the instructor-facing grouping changes later.

### D3. How much timing detail helps the lesson?

User decision, 2026-11-16: Start with **coarse model-request durations, tool durations and observable waiting periods**, retaining the DSH strip/overview interaction. Use recorded evidence and preserve unknown intervals; the calculation semantics remain in DATA_MAP.md.

Detailed reasoning/text/tool-argument phase timing (G5) is deferred until a teaching use justifies it. Cache share can use existing reported totals; cost services and throughput optimization are outside the initial timing scope.

## Original spike completion boundaries

Done here: source and recording investigation; display-feature inventory; evidence/identity/metric mapping; concrete gap proposals; implementation stages; acceptance catalogue; durable screenshots and evidence audit; discussion decisions on equal learner/instructor weight, the preserved Events view, live context, approximate category sizes and initial timing scope.

Not done here: adopting a new trace schema, editing collectors/viewer behavior, running new live capture, porting DSH components, choosing an estimator or frontend framework, or claiming full provider/platform/media/compaction acceptance. Those choices and changes belong to the subsequent discussed implementation.

## Implementation record: 2026-11-16

The checkout is a local 0.5.0.dev0 development candidate. It reuses Core 0.169.0 and the unchanged pinned Desktop archive. Earlier 0.4.0 artifacts and evidence are preserved. No release publication or daily-host installation is part of this work.

The implementation spans more than the repository's preferred single-change size. Review it in dependency order: native capture and its focused tests; Python projection/API and evidence checks; the three browser views; then the VM auth helper and usage documentation. The trace-owned native capture is the smallest coherent stage to land first. The projection can then be reviewed against real captured artifacts before landing the browser views.

### Delivered behavior

| Area | Implemented behavior | Source owner |
|---|---|---|
| Shared evidence | One raw recording, one read-only teaching projection, a shared task/agent/descendant scope and frozen prefix when paused. | [teaching.py](../src/observatory/teaching.py), [teaching_http.py](../src/observatory/teaching_http.py) |
| Events | Original event list, filters, payload/byte inspection and protocol relationships remain directly accessible. Semantic rows link back to contributing events; Events links to related requests and trajectory rows where identities establish the relationship. | [trace_viewer.py](../src/observatory/trace_viewer.py), existing browser app |
| Trajectory | User submissions, separate model attempts, assistant outputs, tools and native code-cell nesting. Request parents, fold/search/overview selection and Summary/Payload/Result/Schema/Timing details. Bare history-admission bookkeeping stays in Events. | [teaching.py](../src/observatory/teaching.py), [teaching.js](../src/observatory/web/teaching.js) |
| Context | Historical request selector, Live observed-history preview, expandable source groups and lazy item content, original role/source/stage and JSON pointer, original artifact links, estimated composition/trend, previous-request/turn category deltas, reported usage/cache share, linked coarse timing strips and aggregates, context events and supported file/command observations. | [teaching_snapshot.py](../src/observatory/teaching_snapshot.py), [teaching.js](../src/observatory/web/teaching.js) |
| G1 | Annotated logical prompt captured before provider preparation, including input, base instructions and tools. Each concrete inference attempt links to its logical prompt, including retries. Public model/App Server payloads are unchanged. | Native session/turn and rollout-trace inference/thread owners |
| G2 | Core's resolved limits and actual pre-turn, mid-turn and post-turn compaction-budget facts. A pre-turn decision legitimately has no step yet. | Native context-window/session owners; phase-specific reader validation |
| G3 | Full observed retained history after admission/truncation, agent messages, retained instruction append, compaction installation and completed restore/reconstruction. Snapshot IDs and raw sequence order preserve observation identity. | [history_trace.rs](../lib/codex/codex-rs/core/src/session/history_trace.rs) and its existing mutation owners |
| VM auth | Host helper validates a ready managed Nellodee instance, copies only auth.json over pinned SSH stdin, and atomically installs an owned 0600 file in a dedicated 0700 guest home. CLI and Desktop use separate homes. | [vm_auth.py](../src/scripts/vm_auth.py), [development guide](../docs/development.md#authentication-for-a-disposable-nellodee-test-vm) |

### Implemented metric and evidence meanings

Category sizing uses one reproducible estimate: ceil(declared text Unicode code points / 4), plus four tokens per nonempty recorded part. Tool definitions use compact, sorted JSON characters under the same rule. Category bars describe that estimated visible composition; they are not normalized to provider totals. Media/opaque portions are excluded and counted separately. Source-unknown items remain explicit. The estimator is intentionally rough and can overestimate or underestimate a provider's tokenizer.

Tool definitions can also be native typed additional_tools items inside input/history. These are displayed as schemas at their original JSON pointers, preserving their role and source without counting the same definitions again in injected text. In the real Terra runs, top-level base_instructions.text was empty and the top-level tools list was empty; the visible catalog came from these inline definitions. Empty recorded content remains empty. Missing payloads or an unavailable historical snapshot produce unknown counts/sizes and explicit coverage gaps.

Provider usage is summed only for attempts that report it, with the reporting-attempt denominator shown. Cached input remains a subset of input; reasoning remains a subset of output. A failed/retried attempt is retained rather than merged into the successful request. Repeated request context is counted repeatedly in processed totals.

Timing uses observed model/tool intervals. The active aggregate is their union, so concurrent intervals do not double-count elapsed time. Only explicit recorded wait-like calls are labeled waiting; uncovered gaps retain unknown cause. These are lifecycle/runtime intervals, not decode phases. Strip widths remain proportional to observed duration. A normal interval list provides exact pointer/keyboard selection when a mark is too narrow to select on a long recording.

File rows describe patch invocations and the owning tool's status. They do not establish that a file changed. Command tool lifecycle and a directly observed process exit code are separate. Unknown exits stay unknown, and shell text is not treated as a filesystem audit.

Live combines the latest observed retained history with the last separately observed base instructions/tool definitions when available. Each prefix component keeps its original event, stage and artifact reference. Current history is not request-normalized input, pending input, provider state or a promise of the next request. History version is Core's reset/generation counter, not an append counter. Restore emits one final observation; pre-root restore can still precede writer enablement.

### Deliberate first-version limits

The complete FEATURE_MAP remains the wider target. This version does not implement a DNA treemap, adaptive axes, selection ranges/bookmarks, a full item-membership diff or side-by-side A/B GUI, native skill-invocation statistics, decode-phase timing, pricing, or a complete filesystem audit. It does not add G4-G8 collection merely to fill a panel. Recorded inline image data can be previewed; missing historical bytes/definitions remain unavailable. Large-session/media/projector acceptance remains separate from the small retained-recording check.

Raw schema 6, manifest 4 and reduced 5 remain unchanged: the additions use the existing extensible harness-event/payload envelope. The release descriptor and regenerated inventory identify the new teaching capture capabilities. Earlier recordings remain read-only and show missing attribution/current-history coverage explicitly.

### Verification record

The local development candidate passed the focused implementation checks, a controlled baseline comparison, and real OpenAI CLI and Desktop acceptance. The full Rust workspace suite has not been run: AGENTS.md requires approval, which was requested and has not been received. Large-session, missing-media and projector acceptance remain outside this completed small-scenario check.

| Check | Result and evidence |
|---|---|
| Native capture | Eight focused native tests passed: concrete inference-to-prompt linkage; annotated prompt capture; effective full-window/body budget facts; unchanged history-admission broadcast behavior; post-truncation tool output; two compaction-adoption cases; and restore after rollback. Scoped fixes and final formatting completed. [Native logs](../build/evidence/dsh-gui/native-build/) preserve the commands/results. |
| Projection and API | Four focused projection tests passed, covering recorded call/frame identities, exact user input, failed patch/process-exit evidence, and linked prompts/history with unavailable content. The HTTP prefix/artifact route check, phase-specific pre-turn validator and two auth-helper tests passed. The missing-content check was rerun for unavailable counts and actual native inline schemas. |
| Existing recording | The retained CLI recording gives 3,233 raw events, 69 semantic rows (19 folded), 16 requests and 17 Context choices including Live. Overview/evidence navigation, lazy schemas, Pause at sequence 3233, timing markers, the exact interval list, failed patch-attempt labels and unknown exits passed with no browser errors. All 999 files retained their hashes. Reported usage reproduced 169,230 input, 146,304 cached input, 1,342 output and 170,572 total tokens. [Recording check](../build/evidence/dsh-gui/retained-recording-check.json), [browser check](../build/evidence/dsh-gui/browser-check.json), [timing check](../build/evidence/dsh-gui/timing-check.json). |
| Controlled equivalence | Baseline untraced, candidate untraced and candidate traced each completed the same deterministic dynamic-tool scenario with two provider requests. Normalized provider inputs/results matched. Recorded prepared requests matched received bodies; a 192,024-character tool result, typed/reused exchanges, unknown members and a large integer were preserved. Notification filtering was honored; traced capture closed cleanly with 193 events and 60 payloads. This establishes the tested scenario, not universal equivalence. [Comparison](../build/evidence/dsh-gui/equivalence/equivalence.json). |
| Public API | Candidate stable and experimental generated schemas were byte-identical to the baseline: 329 stable files and 479 experimental files. No public App Server API was added. [Schema check](../build/evidence/dsh-gui/api/candidate-schema-check.json). |
| Auth transfer | Actual copies into separate CLI/Desktop test homes were recognized by the native clients. Guest UID 1001, directory 0700 and auth.json 0600 were verified. Credentials traveled over pinned SSH stdin and were excluded from retrieved artifacts. |
| Real CLI and Desktop | Both packaged clients used OpenAI gpt-6.1-terra with high reasoning to read only lesson.txt, change BLUE to GREEN, read it back and report its exact contents. Both exited normally with clean, closed captures and no missing artifact references. The client-specific counts are below. |
| Final rendered interface | Final packaged replay passed Live-history, historical logical-prompt, inline-schema/human-content inspection, budget facts, Trajectory and links back to Events. CLI showed six request choices and 25 trajectory rows; Desktop showed five choices and 19 rows. No browser page errors occurred. The Desktop check caught ambiguous shortened scope IDs; task/agent selectors now display full IDs, and unique-label checks passed. [CLI check](../build/evidence/dsh-gui/cli-live-browser-check.json), [Desktop check](../build/evidence/dsh-gui/desktop-live-browser-check.json). |

| Real-client measure | CLI | Desktop |
|---|---|---|
| Recording | 20261116T230838Z-16c9092b1ed84752b54e84f58fbbbd96 | 20261116T231512Z-9f18cd0c838340768675903e3d4a8277 |
| Lesson thread | 01a1e6a0-749b-7b82-bafd-cc1e68c0cf9b | 01a1e6b8-3c2c-7082-9fb7-058fce68ce07 |
| Complete raw recording | 818 events; 267 payloads | 4,672 events; 1,615 payloads |
| Lesson requests/tools | 5 completed requests; 7 tool calls | 4 completed requests; 6 tool calls |
| Prompt snapshots/attempt links/history snapshots | 5 / 5 / 15 | 4 / 4 / 11 |
| Provider usage: input / cached / output / total | 88,629 / 82,176 / 260 / 88,889 | 85,139 / 76,416 / 184 / 85,323 |
| Budget evidence | Pre-turn and mid-turn; effective window 475,000 | Pre-turn and mid-turn; effective window 475,000 |
| Read-only replay | All 271 original files unchanged | All 1,621 original files unchanged |
| Source report | [CLI capture check](../build/evidence/dsh-gui/cli-live-check.json) | [Desktop capture check](../build/evidence/dsh-gui/desktop-live-check.json) |

Both checks establish that Live contains an admitted assistant message absent from the last completed request's logical prompt. Historical request inspection and current observed history therefore remain observably distinct. These short lessons did not force a live compaction; native focused tests cover the changed compaction/restore observation paths.

Desktop also generated background suggestion/account-related requests, including other models and one cancelled request at shutdown. The lesson assertions use the exact completed lesson thread; the complete Events recording retains the other threads. Dedicated copied-auth homes isolate local files while using the same account and connected services. Recordings and screenshots remain private ignored build evidence. The host transfer materialized a linked Desktop runtime directory into five extra regular files; the 1,621-file invariant above refers to the original guest recording before that transfer.

### Candidate identity, reproduction and cleanup

The source-matched Core archive is pinned in release.json. Native HEAD is 008448a4e778564b7505d5e35095efaf1f8a6896 and the full upstream-to-worktree patch SHA-256 is 478abe629c3f51ceabe6d6f8ab2b8b8f03aeff850cd3781b27de9a8d8e50c138. The build generated the V8 binding from pinned sources, built Bubblewrap before embedding its digest, and retained final binaries and build provenance. These are unoptimized development binaries. [Source identity](../build/evidence/dsh-gui/native-source-identity.json) and [runtime hashes](../build/evidence/dsh-gui/native-build/final-runtime.json) identify the exact candidate.

The final learner archive is [codex-observatory-0.5.0.dev0-linux-x86_64.tar.gz](../build/evidence/dsh-gui/releases-verified/codex-observatory-0.5.0.dev0-linux-x86_64.tar.gz), with its adjacent SHA-256 sidecar. Its SHA-256 is 4d109bace0768d84932e3677d199cfc6482e858d1065ec8c2a75ccf33dbff8c3. Every packaged file matches the guest package that passed the final Desktop replay. Relative to the package used to execute native acceptance, only the two projection files and the scope-label JavaScript changed; native clients and launcher are identical. [Package check](../build/evidence/dsh-gui/final-package-check.json) records that comparison. Earlier candidate artifacts are retained as intermediate evidence.

To reproduce replay, extract this archive and run ./observatory replay RECORDING_DIRECTORY. For a fresh native test, follow [the development guide](../docs/development.md) to create a disposable VM, transfer auth with src/scripts/vm_auth.py, and launch either client with its own dedicated home. The bounded prompt used above was: "Read lesson.txt, replace BLUE with GREEN using a tool, then read it back and report its exact contents. Do not inspect or change any other file." Start with exactly "The observatory marker is BLUE." followed by a newline.

Both disposable Nellodee guests used ubuntu-26-04-desktop@2026-11-16 with four CPUs and 20 GiB RAM. Native build guest avm-nellodee-0e10bd6ead70 and integration guest avm-nellodee-b26711e5c433 were deleted after evidence retrieval, and agent-vm list confirmed no remaining task guests. The temporary exact-executable Desktop AppArmor profile was unloaded after normal client exit. Its initial sandbox-start failure and successful follow-up capture are both retained. No credential home or template was exported. No publication, push or daily-host runtime replacement was performed.
