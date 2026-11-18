# Feature inventory and data mapping

The goal is close functional resemblance to the supplied Context and Trajectory views, with differences made deliberately for teaching. This inventory includes interactions revealed by source inspection that a still screenshot cannot show. It does not mean every listed feature should be implemented in the first tranche.

This is the assessment inventory, not a claim of implemented parity. See [the implementation record](DEVELOPMENT.md#implementation-record-2026-11-16) for the delivered first version, G1-G3 capture additions, verification and deferred work.

Source keys (D.*, T.*, O.*, C.*) are navigation keys in [SOURCES.md](SOURCES.md). Evidence routes E1-E15 and metric definitions are owned by [DATA_MAP.md](DATA_MAP.md). G1-G9 are collection/design gaps owned by [CAPTURE_PLAN.md](CAPTURE_PLAN.md).

## Reading the map

- **P1:** central teaching value. **P2:** useful supporting inspection/navigation. **P3:** lower priority, often production optimization or host application behavior.
- **V:** relevant data exercised in the inspected task recordings. **S:** supported by owning source/tests, not exercised in those samples. **D:** requires a derived or estimated interpretation.
- These flags describe data readiness, not a completed Observatory widget. All new displays still need viewer work.
- A G-reference identifies what additional collection would improve fidelity. "No capture change" means existing records can support the stated behavior, subject to missing data in a particular recording.

## Shared experience

| ID / priority | Display and teaching purpose | DSH reference | Existing data / support | Work or additional collection |
|---|---|---|---|---|
| U01 P1 | Select chat/task and agent; understand whose work and context are shown. | D.view, T.view; session-bound views | E1/E12, V+S; existing TaskLedger and task tree | Reuse root/thread identities. Add explicit self/descendants scope; independent background roots stay separate. |
| U02 P1 | Context, Trajectory and Events have linked request/item/event selections. | D.view focus handlers, T.view; existing Observatory event inspection | E1-E3/E7, V | Shared stable selection; graph/trend click selects matching ledger/detail. Derived rows link to all contributing raw events; unmatched raw selections remain valid. No capture change. |
| U03 P1 | Observe live work, pause inspection, follow the tail, replay after shutdown. | D.view, T.view | E13 and existing SSE/replay, V | Reuse pause/follow and recorded mode. Freeze inspection position without stopping capture. |
| U04 P1 | Preserve a first-class Events view for wire traffic and raw harness/runtime observations, alongside Context and Trajectory. | Existing Observatory raw-event/artifact view; T.table source detail | E1-E13, V+S | Preserve expansive capture, original event order and payload inspection. Derived rows cite every contributing event and JSON location. Working view/navigation requirement is recorded in DEVELOPMENT.md. |
| U05 P2 | Stable selection, keyboard focus, aligned rows, linked color highlighting. | D.browser/D.trend, T.table/T.timeline | UI state only | Preserve semantic colors and non-color labels; honor the project's visual guide. No capture change. |
| U06 P1 | Inspect text, code, JSON, available media and opaque content without conflating them. | D.content, T.table | E2/E3/E7/E10, V+S | Rich renderers plus raw form. Render authentic reasoning only when present; encrypted content stays opaque. |
| U07 P1 | Distinguish a historical recording from today's tools/files/configuration. | D.assemble, T.header | E2/E11/E13, V+S | Resolve everything against the recording; show unavailable historical state. G7/G8 only where bytes/schema are absent. |
| U08 P1 | Recognize missing, unsupported, loading, redacted or interrupted evidence. | D.view/D.browser/D.activity, T.view | E13; reader error handling, V+S | Explicit states and retry for failed reads. Unknown is not zero; writer health is not coverage. |
| U09 P2 | Use a long teaching session with many screenshots and tool calls. | D.view lazy mounting, T.table virtual rows | Ordered log/payload refs, V | Window rows, lazy-load large content, maintain scroll/selection. Viewer work; no new retention caps on original evidence. |

## Context: overview and navigation

These panels appear in the first two screenshots. DSH's stats are often clickable entry points, not just decorations.

| ID / priority | Display and teaching purpose | DSH reference | Existing data / support | Work or additional collection |
|---|---|---|---|---|
| A01 P1 | Turns, steps and model-request counts: see how one interaction expands into work. | D.stats countsOfRecords | E1/E2/E5, V | Count native turns, distinct steps and attempts separately. DSH uses request records as steps; make the difference visible. |
| A02 P1 | Skill loads/use: distinguish catalog availability, selected content and actual invocation. | D.stats, D.fold, D.skills | E2/E5/E14, D+S | G1 preserves catalog/selected-content kinds; G4 records native explicit/implicit invocation identity. A file read alone is weaker evidence. |
| A03 P1 | Assistant messages/answers: separate progress narration from final answers. | D.fold assistant/message, D.stats | E3/E10, V | Group output by item and phase. DSH counts messages with text as answers; do not silently adopt that label. |
| A04 P1 | Input/output breakdown: human input, reads, writes, searches and images. | D.stats, D.activity | E2/E7/E9/E10, V+D | Declare units: submissions, operations, unique paths or image blocks. G1 for human/injected distinction; G6 for richer file facts. |
| A05 P1 | Tool-call totals and per-tool chips, with drilldown. | D.stats toolTallyOf | E7/E8, V+S | Count canonical calls once; expose model vs nested scope. Chip selection filters the relevant rows/browser group. |
| A06 P2 | Command totals and program chips, including JavaScript execution. | D.stats, D.commands | E8/E9, V+S | Separate shell launches from JS cells; DSH run_code is not Codex's exact tool name or lifecycle. No capture change. |
| A07 P1 | Inject/compact/prune totals, linked to context events. | D.stats, D.events | E5/E6, V+S+D | Coarse contribution and installation counts now. G1/G6 for exact contribution/removal attribution. Do not count compaction candidates as installations. |
| A08 P1 | Current agent and descendant counts/tokens: understand delegation's scale. | D.stats subagent fold | E1/E3/E12, V+S | Aggregate explicitly scoped reported usage; retain coverage and failed attempts. No new fleet backend. |
| A09 P2 | Click fleet summary to inspect agent relationships and messages. | D.view AgentGraph/agentInspector | E12, S; current task tree already exists | Reuse root/child relationships and delivery stages. Full standalone Fleet is outside these two views. |
| A10 P3 | Plugin version/build information. | D.plugin | E13/O.release, V | Replace DSH plugin metadata with recording/build provenance where useful; do not add a plugin manager. |
| A11 P1 | Click count/chip to reveal related items or apply a filter. | D.stats StatsJump, D.view onJump | E1-E12, V+S | Map shortcuts to stable selections and filters, including offscreen panels. No new telemetry. |
| A12 P3 | Cost and price details beside current/fleet token totals. | D.stats, D.cost | E3, V; prices not part of recording | Optional estimate needs a dated price source and account/provider assumptions. G9; not a prerequisite for teaching. |

## Context: tokens and current composition

| ID / priority | Display and teaching purpose | DSH reference | Existing data / support | Work or additional collection |
|---|---|---|---|---|
| B01 P1 | Cumulative token total: distinguish repeated processing from context size. | D.tokens, D.categories | E3, V | Sum reported per-attempt input+output once. Show missing-usage coverage; no capture change. |
| B02 P2 | Token donut for instructions, tools, user, injected context, skills, tool calls, reasoning and answers. | D.tokens, D.categories billedParts | E2/E3/E14, V+D | Estimated source allocation, not an exact provider breakdown. G1 for source labels; G9 for a declared estimator and opaque/unallocated share. |
| B03 P2 | Cache-hit percentage: explain reused prefixes without centering optimization. | D.tokens, D.format | E3, V | Weighted cached_input/input over the same usage subset; no new collection. Cache writes remain separately labelled. |
| B04 P1 | Current context used/limit/percentage. | D.current, D.headline | E2/E15, V+D | Last reported input gauge is possible. G2 supplies the harness's later estimate and actual decision thresholds. G3 if current live history is promised. |
| B05 P1 | Model, provider and reasoning effort for the selected request. | D.current/D.view | E2 plus request reasoning/options, V | Use request-time identity; distinguish configured/default from actual attempt. No capture change for observed requests. |
| B06 P1 | Composition bar and category legend with sizes and shares. | D.current, D.categories | E2/E14, V+D | Preserve system/developer roles and source as separate dimensions. G1/G9; unknown categories remain visible. |
| B07 P2 | Free-space/hatched reserved region and thresholds. | D.reserve, D.headline | E15, partial V | G2 records resolved effective/nominal limits and any explicit reservation. Never infer a reservation from unexplained unused space. |
| B08 P1 | Estimated versus actual totals, uncertainty, denominator and scope. | D.browser/D.headline | E2/E3/E13/E15, V+D | Label stage, units and estimate method. Missing usage leaves actual unknown. No new collection just to label uncertainty. |

## Context: timing

| ID / priority | Display and teaching purpose | DSH reference | Existing data / support | Work or additional collection |
|---|---|---|---|---|
| M01 P2 | Active-time total versus elapsed session time. | D.timing, D.metering | E1/E2/E7-E9, V+D | Derive operation interval union with explicit unknown gaps. DSH excludes idle using heuristics; no silent adoption. |
| M02 P3 | TTFT/reasoning/answers/tool arguments/tool runs/overhead donut. | D.timing/D.metering/D.fold | E1/E10 provide partial timing, V+D | G5 for inference-correlated phase observations. Until then show model/tool/wait/unknown, not fabricated six-way proportions. |
| M03 P2 | Colored timing strip and linked hover details. | D.strip, D.timing | E1 and known intervals, V+D | Can show coarse intervals now. Fine phase colors depend on G5; overlap and uncovered time must remain legible. |
| M04 P3 | Tokens per second. | D.timing | E3 usage, E10 partial timing, V+D | Optional observed-output rate needs an explicit timing denominator. G5 for consistent boundaries; never infer provider compute throughput. |
| M05 P2 | Tool time/call counts, including parallel execution. | D.metering, D.timing | E7-E9, V+S | Show sum of call durations separately from elapsed busy time. Reuse call identities; no capture change. |

## Context: trend and selected-request brief

| ID / priority | Display and teaching purpose | DSH reference | Existing data / support | Work or additional collection |
|---|---|---|---|---|
| R01 P1 | Stacked context bars over model requests: see growth and replacement. | D.trend | E2/E3, V+D | Build request snapshots, preserve reported/estimated distinction, reconstruct WebSocket continuity. G1/G9 improve composition. |
| R02 P1 | Step/turn granularity and turn bands. | D.trendModel aggregateByTurn | E1/E2/E5, V | Turn bar uses last snapshot; processing counts and durations aggregate separately. Retries stay identifiable. |
| R03 P1 | Total/delta modes with signed additions/removals. | D.trendModel deltaOf, D.dna | E2/E6, V+D | Named baseline, unknown initial delta, distinguish net from absolute churn. G1 helps explain sources of change. |
| R04 P2 | Duration curve on a second axis. | D.trend/D.duration | E1/E2/E7, V+D | Define whether duration is model wait, request span or step span. Missing terminal breaks the curve rather than becoming zero. |
| R05 P1 | Compaction/prune markers and boundary range. | D.events/D.trendModel | E5/E6, S+D | Installation marker now; G6 for explicit non-compaction removal cause. Link to before/after snapshots. |
| R06 P1 | DNA mode: individual context item bands across requests. | D.dna/D.trend | E2/E6/E14, V+S+D | Stable item/occurrence identities, unknown matching disclosed. G1 preserves source kinds; same text does not prove same origin. |
| R07 P2 | Adaptive vertical scale for the visible range. | D.trend visible maxima | Snapshot arrays only | UI calculation, no telemetry. Axis must clearly change; this is not token-budget adaptation. |
| R08 P2 | Overview that fits the entire trend as a ribbon. | D.overview | Same data as R01 | Fit-to-width view, turn/category selection and duration overlay. Not a separate dataset or heatmap service. |
| R09 P1 | Hover previews, pinned selection, category focus and linked browser. | D.view/D.trend | E1/E2, V | Keep hover distinct from pin; preserve pin during streaming and scrolling. No capture change. |
| R10 P1 | Selected request's turn/step/time, user/input/response brief, actual input/output/cache and transition marker. | D.request | E1-E3/E10, V | Build from request and its source items; include failed attempts. G1 improves user/injected distinction, G5 only for fine timings. |

## Context: request browser

| ID / priority | Display and teaching purpose | DSH reference | Existing data / support | Work or additional collection |
|---|---|---|---|---|
| C01 P1 | Select a historical request or latest/live context. | D.browser selector | E2/E3, V | Historical/latest observed request now. G3 only for a complete live-history/next-request preview. Label the distinction explicitly. |
| C02 P1 | Compare with previous step or previous turn. | D.browser deltaBase | E1/E2/E6, V | Baseline respects thread, model request and compaction. No capture change; estimates must use the same method. |
| C03 P1 | Expandable category rows with item count, token estimate/share and deltas. | D.browser CATS rows | E2/E14, V+D | G1/G9. Role does not identify source; an instruction can have user role. |
| C04 P1 | Expand complete base/system/developer instructions. | D.browser systemRow | E2, V | Retain wire roles and original ordering; base instructions can be synthesized developer messages rather than a top-level instructions field. |
| C05 P1 | Browse tool catalog, descriptions, parameter schemas, owner/namespace, use counts; search/sort by size/count/name. | D.browser toolsGroup, D.schema | E2/E7/E11, V+S | Include additional_tools and deferred wrappers. Show advertised, discovered and executed tools separately. G8 only for absent historical nested schemas. |
| C06 P2 | Search category contents and filter assistant rows by text/reasoning/tool-call kind. | D.browser/D.nodes | E2/E3, V | Parse source blocks without dropping mixed-content messages; lazy search has explicit coverage. No capture change. |
| C07 P1 | Expand item body, code and original structure; copy/wrap/render as appropriate. | D.nodes/D.schema/D.content | E2/E3/E7, V+S | Evidence renderer and immutable original representation. No capture change. |
| C08 P1 | Image thumbnails and attachment metadata/preview. | D.attachments | E2/E3/E7, S | Embedded bytes need viewer extraction only. G7 when only a file path/resource URL was recorded; file metadata is not image bytes. |
| C09 P2 | Treemap view of category/item size. | D.treemap | Same estimates and identities as C03/R06 | UI-only area layout; expose estimate/missing media. No separate collection. |
| C10 P2 | DNA/flat ordered item browser linked to bands. | D.browser/D.dna | E2/E14, V+D | Use actual model input order for Codex; source grouping stays a separate view. G1 for trustworthy labels. |
| C11 P1 | Select an item/band to reveal its content and originating trajectory observation. | D.view locateNode/revealBand | E1-E4/E7/E12, V+S | Explicit source links only; distinguish first sighting, acceptance and request inclusion. G1 can strengthen origin links. |
| C12 P1 | Show incomplete historical prefix, retention gap, unavailable header or read failure. | D.assemble/D.browser | E2/E13; reader checks, V+S | Preserve unavailable portions. Observatory need not copy DSH's bounded in-memory archives into durable recording. |

## Context: context events

| ID / priority | Display and teaching purpose | DSH reference | Existing data / support | Work or additional collection |
|---|---|---|---|---|
| X01 P1 | Injection rows: source/form, time, location and estimated added size. | D.events/D.fold | E5/E14, V+D | Coarse context contributions now; G1 for specific parts/source and first inclusion; G4 for named skills. Replayed inclusion is not a fresh injection. |
| X02 P1 | Compaction rows: request vs installation, replaced items, retained suffix and replacement content. | D.events, T.comp | E6, S | Project checkpoint arrays and lifecycle. Show estimated change separately from reported usage; no new collection for existing checkpoint contents. |
| X03 P2 | Prune/removal rows and size/count. | D.fold compaction/prune | Snapshot diff E2, D | Codex has no universal DSH prune event. G6 if a removal reason is needed; otherwise show observed membership change with unknown cause. |
| X04 P1 | Model/provider and plan/collaboration-mode changes. | D.events/D.fold | E2/E10/E14, V+S+D | Diff actual request identity; request-time settings where recorded. Distinguish settings requested from applied; G2 can carry resolved mode/config. |
| X05 P1 | Kind filters, counts, reverse chronological list and jumps to request/content. | D.events/D.view | E1/E5/E6, V+S | UI projection and cross-selection. Do not present unavailable event classes as a known zero. |

## Context: file activity

| ID / priority | Display and teaching purpose | DSH reference | Existing data / support | Work or additional collection |
|---|---|---|---|---|
| F01 P1 | File list with read/write/search/image counts per path. | D.files/D.activity | E7-E9, V+D | Typed calls/patches give strong evidence; shell/JS inference is incomplete. G6 for additional typed events, not full filesystem surveillance. |
| F02 P2 | Path filter; all/read/write/search/image tabs; most-active/lines/latest/path/name sorting. | D.files | F01 derived entries | Viewer-only. Sort uses declared operation units; retain pattern/directory entries instead of pretending every search is a file. |
| F03 P1 | Expand operation history: source tool, time, range, +added/-removed, result/error and location. | D.files/D.fileOps | E7/E9 plus patch parse/commit, V+D | Derive from recorded arguments/results. G6 if exact read ranges or truncation changes are missing. Attempted edits differ from committed changes. |
| F04 P1 | Preview a file/image as it appeared in the interaction. | D.files/D.attachments | E2/E7, V+S | Prefer recorded tool result or media. Never use today's file as historical content. G7 for missing media bytes; arbitrary file snapshots are optional. |
| F05 P1 | Jump from a file operation to its tool/trajectory/context item. | D.view locateFileOp | E1/E7-E9, V+S | Keep operation-to-call and result-to-request links. A file read is not proof the model used its contents. |

## Context: command executions

| ID / priority | Display and teaching purpose | DSH reference | Existing data / support | Work or additional collection |
|---|---|---|---|---|
| K01 P1 | Compact command/JS rows with summary, status, size, time and turn/step. | D.commandPanel | E7-E9, V+S | Map Codex exec_command/write_stdin and code cells directly. Preserve original source; summaries are display-only. |
| K02 P2 | Runs/time/failure/background summary and program grouping. | D.commandPanel/D.commands | E8/E9, V+S+D | Define launches, polls and JS cells separately. Multi-program shell strings can belong to several groups, not mutually exclusive totals. |
| K03 P3 | All/failed/slow/background filters; latest/slowest sorting and attention links. | D.commands SLOW_MS=10000 | E7-E9, V+D | Failure/background useful for teaching. DSH's 10s slow threshold is a convention, not a Codex quality criterion; optional G9 decision. |
| K04 P1 | Expand code/command, cwd, sandbox/timeout settings, exit/signal, stdout/stderr and truncation. | D.commandPanel/D.commands | E7-E9, V+S | Existing payload parsing. Prefer explicit runtime exit over DSH-style inference from output text. Keep runtime and model-visible output distinct. |
| K05 P1 | Distinguish command start, background process lifetime, yield, stdin/poll, and final exit. | D.commandPanel; Codex-specific extension | E8/E9, V+S | Reuse terminal/code-cell joins; a returned tool call can leave work running. No new capture where current events exist. |
| K06 P2 | Load older commands/results, preserve scroll and locate their source. | D.commandPanel command pager | E1/E7-E9, V | Local recording paging/lazy reads; no DSH remote service required. Show source coverage when history is partial. |

## Trajectory

The third screenshot shows the overview strip, compact ledger and selected subtool's detail pane. The inspected source adds request detail, rich content, system/catalog diffs and timeline interaction beyond what is visible.

| ID / priority | Display and teaching purpose | DSH reference | Existing data / support | Work or additional collection |
|---|---|---|---|---|
| T01 P1 | Three overview lanes: input/context, model, tools. | T.timeline laneFor, T.overview | E1-E3/E7-E8, V+S | Derive semantic intervals/points. Keep other harness/protocol evidence reachable rather than forcing every event into one of three kinds. |
| T02 P2 | Equal-width operation mode versus duration mode. | T.toolbar/T.timeline | E1/E7-E9, V+D | Recorded-time layout now. DSH source also has complete/compressed time modes, but its actual-time toolbar control is hidden. Do not assume screenshot exposes it. |
| T03 P1 | Click, brush/select a range, zoom and pan; timeline selects/focuses rows. | T.overview pointer/wheel handlers | E1 and projected row identities | Viewer-only interactions, keyboard alternative, stable range under filters. Raw sequence and wall-time domains are labelled separately. |
| T04 P1 | Full-text search across summaries, bodies, results, schemas, sources and attachments. | T.search | E2/E3/E7/E10, V+S | Payload-aware search, with loaded/full-recording coverage explicit. No new data collection. |
| T05 P1 | Fold/expand all turns, assistant tool calls and nested subcalls. | T.toolbar, T.table | E1/E7/E8, V+S | UI state over stable hierarchy. Folded rows remain represented in counts/selection. |
| T06 P1 | Type-labelled, color-coded compact ledger: system/user/context/assistant/tool/subtool/compacted. | T.record/T.table | E1-E8/E14, V+S+D | Separate type from outcome. G1 for reliable user/context distinction; keep unknown source/role visible. |
| T07 P1 | Turn/step groups, request separators, request numbering and token columns. | T.view/T.layout/T.table | E1-E3/E5, V | Differentiate native step and inference attempts. Request numbers are local display ordinals, not identities. |
| T08 P1 | Assistant -> outer code tool -> nested calls hierarchy. | T.tool, T.code, T.layout | E7/E8, S | Use requester and bridge IDs. Preserve late/yielded cell completion and distinguish JS return values from model input. |
| T09 P1 | A tool row pairs its invocation with final result/summary. | T.tool/T.table | E7/E9, V+S | Merge lifecycle facts by canonical ID, not adjacent rows. Keep invocation, runtime and caller result separately inspectable. |
| T10 P1 | Running/streaming/failed/interrupted records with partial output. | T.assistant/T.view/T.tool | E3/E7/E10, V+S | Client deltas provide some live text; authoritative final payload replaces the provisional display. G5 only for uniform native streaming phases. |
| T11 P1 | Summary tab with status and clickable hierarchy/source breadcrumbs. | T.table | E1-E4/E7/E8/E12, V+S | Join explicit relationships, retain unknown edges. Use "observed in request" when causal origin is unavailable. |
| T12 P1 | Payload/source tab: JSON tree, pretty/raw form, code, copy value/JSON/path and string wrapping. | T.table/T.code | E2/E7/E10/E11, V | Renderer work. Keep exact original text/bytes accessible; JavaScript formatting is not an exact serialization. |
| T13 P1 | Result tab: structured blocks, errors, text, images and raw output. | T.table/T.tool | E3/E7-E9, V+S | Preserve block order and full/partial distinction; G7 for media not recorded. |
| T14 P1 | Schema tab for the selected tool/subtool. | T.contract/T.table | E2/E11, V+S | Model-facing schema at that request, backend schema labelled separately. G8 when exact nested-call-time schema is absent. |
| T15 P2 | Timing/usage/options tabs: start/duration, latency, tokens, model configuration. | T.table REQUEST_TABS, T.record | E1-E3/E10/E15, V+D | Request span and usage now; G2 for resolved budget/options not in request, G5 for uniform first-output/decode timing. |
| T16 P1 | Message summary, rendered preview, raw text and source tab; preserve reasoning summaries/content. | T.table detailTabs | E2/E3/E10/E14, V+S | G1 for source attribution. Actual readable reasoning can be shown; opaque content is not decoded or synthesized. |
| T17 P1 | System/prompt and catalog introduction/update with diff, complete text and tool schemas. | T.header/T.table | E2, V+D | Diff request-time instruction/catalog states and expose placement. G1 strengthens provenance; do not call every developer message the system prompt. |
| T18 P1 | Compaction rows with summary/raw output and failed compaction request details. | T.comp/T.table | E6, S | Separate request result from installed replacement; include before/after context jump. No new collection for existing checkpoints. |
| T19 P2 | Auxiliary/background/failed request headers even when no assistant message exists. | T.view requestOnly, T.assistant | E1-E3/E10/E12, V+S | Preserve failed attempts and their scope. Background roots may be outside selected chat; never relabel them as user-request steps. |
| T20 P1 | Navigate assistant -> request -> tool -> subtool/result, and back to Context. | T.table/T.view | E1-E8/E12, V+S | One shared selection and reference index. No independent duplicate event ledger. |
| T21 P1 | Inline image gallery/thumbnail plus original block labels and metadata. | T.contract image slot, T.table | E2/E3/E7, S | Viewer extraction for embedded media; G7 for pointer-only images. Match images to their tool result/message, not just path. |
| T22 P2 | Adjustable, stable detail pane and retained fold/selection/scroll state. | T.table/T.view | UI state | Existing Observatory detail pane can be extended. No capture or Desktop patch. |
| T23 P2 | Load older history and window large ledgers without changing item identity. | T.view/T.table | E1/E13, V | Read local recording pages, preserve selection when prepending. Native reduced state is optional, not assumed. |
| T24 P1 | Unknown/unmapped records and full event evidence remain inspectable. | Observatory raw view; DSH limited kinds | E1-E13, V+S | Necessary deviation: pedagogical grouping must not hide approvals, supervision, transport failures or new event kinds. No new collection. |

## Source-visible host features outside the proposed two-view core

These remain inventoried so resemblance does not accidentally grow into rebuilding DSH.

| ID / priority | Reference feature | Existing information and proposed disposition |
|---|---|---|
| Z01 P3 | DSH sidebar/workspaces, new-session button, chat composer, model picker and writable controls | Observatory is read-only exploration beside either Codex client. Reuse its recording/task selection. No chat client or Codex behavior changes proposed. |
| Z02 P3 | Plugin Info update links, sponsor/recommendation cards, plugin settings opener | Recording/build provenance is useful (A10). Promotional and plugin-management UI has no teaching-data requirement; proposed omission. |
| Z03 P3 | Context command, prompt prefix/suffix, destructive compaction/prune actions, upgrades | These change the running agent. They are not needed to visualize the screenshots; no collection or control implementation proposed. |
| Z04 P3 | Global Context Insights, date-range usage/cost dashboards, model-price lookup and optimization recommendations | Different cross-session scope. No requirement to scan personal Codex homes or add external services; defer unless explicitly selected. |
| Z05 P2 | Plugin placement/default settings, sidebar agent graph and localization | Compact graph/drilldown is covered by A09. Standalone placement and language preferences are reversible UI work; not a reason to add capture patches. |

## Coverage and intentional deviations to discuss

All panels visible in the three references have mappings above. Source-only supporting functions are included where they materially affect implementation: DNA and treemap views, exact baseline selection, request header diffs, search, fold state, timeline brushing/panning, historical gaps, and lazy content retrieval.

Recommended deviations are semantic before stylistic: expose requests separately from steps; keep message role separate from content source; distinguish tool execution from model inclusion; distinguish compaction candidate from installation; and label estimates, missing evidence and opaque content. Cost/throughput panels can follow the DSH layout later without making their precision the dependency for the core teaching interface.
