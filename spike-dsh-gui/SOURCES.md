# Sources, evidence and investigation limits

Assessment date: 2026-11-16. The analysis uses the actual local source checkouts, supplied screenshots and retained recordings. It is scoped to the two requested views and their data-producing pathways, not a repository-wide correctness/security review.

## Source identity

| Source | Identity at investigation | State and authority |
|---|---|---|
| Observatory | 719236f944ddba6f6faeb5b5af7880dac087d218 | Implementation tree initially clean. New spike files account for the later untracked spike entry. release.json owns matched release identity. |
| Instrumented Codex | 008448a4e778564b7505d5e35095efaf1f8a6896 | Clean pinned submodule; based on stable Core 0.169.0. Native capture is project-owned. |
| dsh-context | 432c5cbb9911778de070f34b297ca4d982106048 | Clean candidate checkout; package.json version 0.82.2, matching the plugin label in the reference. Apache-2.0 in package/LICENSE. No source was copied into the implementation. |
| DSH harness / Trajectory | 66491b05e3f05ad35bcdd4f6cd7ed26041d9e3db | Reviewed checkout contains local desktop/runtime/connection changes. The inspected packages/client/ui-trajectory source itself is unmodified relative to that commit. Do not treat the whole checkout as a pristine upstream release or claim an exact screenshot-build match. |

Local roots are recorded in [source-index.json](source-index.json) and [evidence.json](evidence.json). DSH clone origins point to earlier local reviewed candidates, so this spike does not invent upstream commit permalinks. The named source paths and file hashes are the reproducible local pointers.

The Observatory release descriptor reports 0.4.0 / Core 0.169.0 / Desktop 26.1111.21308, raw schema 6, manifest 4 and reduced schema 5. The checked-in src/observatory/collection_inventory.json still names 0.3.0 / Core 0.166.0-alpha.6. Its declaration is useful as a route list but is not current coverage evidence. This discrepancy was documented, not repaired.

The project authorities consulted were [README](../README.md), [discussion](../docs/discussion.md), [development](../docs/development.md) and [visual design guide](../docs/visual-design-guide.md). Older instrumentation documents are historical and do not override these sources or the current implementation.

## Code navigation keys

These keys are used in FEATURE_MAP, DATA_MAP and CAPTURE_PLAN. File/line links refer to the inspected local files; line numbers can move after development. source-index.json carries the root, path, line and SHA-256 for each navigation reference. Fingerprinting a reference does not claim every line in that file was reviewed.

## Observatory reader and UI

| Key | Source location | Relevant responsibility |
|---|---|---|
| O.release | [release.json:1](/home/brooksch/sandboxes/brooksch/projects/teaching/codex-harness-observatory/release.json:1) | Matched release and capability pins. |
| O.view | [src/observatory/trace_viewer.py:1524](/home/brooksch/sandboxes/brooksch/projects/teaching/codex-harness-observatory/src/observatory/trace_viewer.py:1524)<br>[src/observatory/web/app.js:1](/home/brooksch/sandboxes/brooksch/projects/teaching/codex-harness-observatory/src/observatory/web/app.js:1)<br>[src/observatory/web/index.html:108](/home/brooksch/sandboxes/brooksch/projects/teaching/codex-harness-observatory/src/observatory/web/index.html:108) | viewer_event, TaskLedger, SSE/artifact routes and existing web UI. |

## Instrumented native capture and Core

| Key | Source location | Relevant responsibility |
|---|---|---|
| O.raw | [codex-rs/rollout-trace/src/raw_event.rs:33](/home/brooksch/sandboxes/brooksch/projects/teaching/codex-harness-observatory/lib/codex/codex-rs/rollout-trace/src/raw_event.rs:33) | Raw event envelope and payload variants. |
| O.req | [codex-rs/rollout-trace/src/inference.rs:231](/home/brooksch/sandboxes/brooksch/projects/teaching/codex-harness-observatory/lib/codex/codex-rs/rollout-trace/src/inference.rs:231)<br>[codex-rs/rollout-trace/src/reducer/inference.rs:1](/home/brooksch/sandboxes/brooksch/projects/teaching/codex-harness-observatory/lib/codex/codex-rs/rollout-trace/src/reducer/inference.rs:1) | Prepared body/logical continuity, tool catalog, category counts, output serializer and inference reduction. |
| O.hist | [codex-rs/rollout-trace/src/thread.rs:631](/home/brooksch/sandboxes/brooksch/projects/teaching/codex-harness-observatory/lib/codex/codex-rs/rollout-trace/src/thread.rs:631)<br>[codex-rs/rollout-trace/src/reducer/conversation.rs:64](/home/brooksch/sandboxes/brooksch/projects/teaching/codex-harness-observatory/lib/codex/codex-rs/rollout-trace/src/reducer/conversation.rs:64) | History admission receipts, snapshot reconciliation and incremental context. |
| O.tools | [codex-rs/rollout-trace/src/tool_dispatch.rs:1](/home/brooksch/sandboxes/brooksch/projects/teaching/codex-harness-observatory/lib/codex/codex-rs/rollout-trace/src/tool_dispatch.rs:1)<br>[codex-rs/rollout-trace/src/reducer/tool.rs:1](/home/brooksch/sandboxes/brooksch/projects/teaching/codex-harness-observatory/lib/codex/codex-rs/rollout-trace/src/reducer/tool.rs:1) | Canonical invocation/result and runtime tool identities. |
| O.cell | [codex-rs/rollout-trace/src/code_cell.rs:1](/home/brooksch/sandboxes/brooksch/projects/teaching/codex-harness-observatory/lib/codex/codex-rs/rollout-trace/src/code_cell.rs:1)<br>[codex-rs/rollout-trace/src/reducer/code_cell.rs:1](/home/brooksch/sandboxes/brooksch/projects/teaching/codex-harness-observatory/lib/codex/codex-rs/rollout-trace/src/reducer/code_cell.rs:1) | Cell lifecycle, nested tools and wait/result links. |
| O.term | [codex-rs/rollout-trace/src/reducer/tool/terminal.rs:1](/home/brooksch/sandboxes/brooksch/projects/teaching/codex-harness-observatory/lib/codex/codex-rs/rollout-trace/src/reducer/tool/terminal.rs:1)<br>[codex-rs/rollout-trace/src/model/runtime.rs:222](/home/brooksch/sandboxes/brooksch/projects/teaching/codex-harness-observatory/lib/codex/codex-rs/rollout-trace/src/model/runtime.rs:222) | Terminal process/operation/result and recyclable process resolution. |
| O.comp | [codex-rs/rollout-trace/src/compaction.rs:85](/home/brooksch/sandboxes/brooksch/projects/teaching/codex-harness-observatory/lib/codex/codex-rs/rollout-trace/src/compaction.rs:85)<br>[codex-rs/rollout-trace/src/reducer/compaction.rs:1](/home/brooksch/sandboxes/brooksch/projects/teaching/codex-harness-observatory/lib/codex/codex-rs/rollout-trace/src/reducer/compaction.rs:1) | Input/installation/suffix/replacement checkpoint and installation lifecycle. |
| O.protocol | [codex-rs/rollout-trace/src/protocol_event.rs:1](/home/brooksch/sandboxes/brooksch/projects/teaching/codex-harness-observatory/lib/codex/codex-rs/rollout-trace/src/protocol_event.rs:1) | Typed runtime observations and protocol wrappers. |
| O.bundle | [codex-rs/rollout-trace/src/bundle.rs:1](/home/brooksch/sandboxes/brooksch/projects/teaching/codex-harness-observatory/lib/codex/codex-rs/rollout-trace/src/bundle.rs:1)<br>[codex-rs/rollout-trace/src/reducer/mod.rs:53](/home/brooksch/sandboxes/brooksch/projects/teaching/codex-harness-observatory/lib/codex/codex-rs/rollout-trace/src/reducer/mod.rs:53)<br>[codex-rs/cli/src/main.rs:2114](/home/brooksch/sandboxes/brooksch/projects/teaching/codex-harness-observatory/lib/codex/codex-rs/cli/src/main.rs:2114) | Manifest/health/schema and debug trace-reduce -> state.json. |
| O.wire | [codex-rs/rollout-trace/src/wire.rs:1](/home/brooksch/sandboxes/brooksch/projects/teaching/codex-harness-observatory/lib/codex/codex-rs/rollout-trace/src/wire.rs:1)<br>[codex-rs/rollout-trace/src/mcp.rs:1](/home/brooksch/sandboxes/brooksch/projects/teaching/codex-harness-observatory/lib/codex/codex-rs/rollout-trace/src/mcp.rs:1) | App Server/MCP observation and exchange identity. |
| O.model | [codex-rs/rollout-trace/src/model/session.rs:1](/home/brooksch/sandboxes/brooksch/projects/teaching/codex-harness-observatory/lib/codex/codex-rs/rollout-trace/src/model/session.rs:1)<br>[codex-rs/rollout-trace/src/model/conversation.rs:1](/home/brooksch/sandboxes/brooksch/projects/teaching/codex-harness-observatory/lib/codex/codex-rs/rollout-trace/src/model/conversation.rs:1)<br>[codex-rs/rollout-trace/src/model/runtime.rs:1](/home/brooksch/sandboxes/brooksch/projects/teaching/codex-harness-observatory/lib/codex/codex-rs/rollout-trace/src/model/runtime.rs:1) | Reduced identities, execution windows, conversation parts and usage. |
| O.agents | [codex-rs/core/src/agent/control.rs:1](/home/brooksch/sandboxes/brooksch/projects/teaching/codex-harness-observatory/lib/codex/codex-rs/core/src/agent/control.rs:1)<br>[codex-rs/core/src/agent/control/spawn.rs:1](/home/brooksch/sandboxes/brooksch/projects/teaching/codex-harness-observatory/lib/codex/codex-rs/core/src/agent/control/spawn.rs:1)<br>[codex-rs/core/src/tools/handlers/multi_agents/spawn.rs:1](/home/brooksch/sandboxes/brooksch/projects/teaching/codex-harness-observatory/lib/codex/codex-rs/core/src/tools/handlers/multi_agents/spawn.rs:1)<br>[codex-rs/core/src/tools/handlers/multi_agents_v2/message_tool.rs:1](/home/brooksch/sandboxes/brooksch/projects/teaching/codex-harness-observatory/lib/codex/codex-rs/core/src/tools/handlers/multi_agents_v2/message_tool.rs:1) | Agent identity, spawn and message source observations. |
| O.tests | [codex-rs/rollout-trace/src/reducer/acceptance_tests.rs:1](/home/brooksch/sandboxes/brooksch/projects/teaching/codex-harness-observatory/lib/codex/codex-rs/rollout-trace/src/reducer/acceptance_tests.rs:1)<br>[codex-rs/rollout-trace/src/reducer/inference_tests.rs:1](/home/brooksch/sandboxes/brooksch/projects/teaching/codex-harness-observatory/lib/codex/codex-rs/rollout-trace/src/reducer/inference_tests.rs:1)<br>[codex-rs/rollout-trace/src/reducer/code_cell_tests.rs:1](/home/brooksch/sandboxes/brooksch/projects/teaching/codex-harness-observatory/lib/codex/codex-rs/rollout-trace/src/reducer/code_cell_tests.rs:1)<br>[codex-rs/rollout-trace/src/reducer/conversation_tests.rs:1](/home/brooksch/sandboxes/brooksch/projects/teaching/codex-harness-observatory/lib/codex/codex-rs/rollout-trace/src/reducer/conversation_tests.rs:1)<br>[codex-rs/core/src/tools/tool_dispatch_trace_tests.rs:1](/home/brooksch/sandboxes/brooksch/projects/teaching/codex-harness-observatory/lib/codex/codex-rs/core/src/tools/tool_dispatch_trace_tests.rs:1) | Existing identity, cancellation, continuity, compaction and nested-call regression references; not rerun by this spike. |
| C.client | [codex-rs/core/src/client.rs:1161](/home/brooksch/sandboxes/brooksch/projects/teaching/codex-harness-observatory/lib/codex/codex-rs/core/src/client.rs:1161)<br>[codex-rs/core/src/client_common.rs:61](/home/brooksch/sandboxes/brooksch/projects/teaching/codex-harness-observatory/lib/codex/codex-rs/core/src/client_common.rs:61) | Request preparation/stripping, HTTP/WebSocket recording, map_response_events. |
| C.turn | [codex-rs/core/src/session/turn.rs:809](/home/brooksch/sandboxes/brooksch/projects/teaching/codex-harness-observatory/lib/codex/codex-rs/core/src/session/turn.rs:809)<br>[codex-rs/core/src/session/turn.rs:2191](/home/brooksch/sandboxes/brooksch/projects/teaching/codex-harness-observatory/lib/codex/codex-rs/core/src/session/turn.rs:2191) | Compaction decision, record_prompt_assembly and response usage. |
| C.session | [codex-rs/core/src/session/mod.rs:4052](/home/brooksch/sandboxes/brooksch/projects/teaching/codex-harness-observatory/lib/codex/codex-rs/core/src/session/mod.rs:4052)<br>[codex-rs/core/src/session/mod.rs:4329](/home/brooksch/sandboxes/brooksch/projects/teaching/codex-harness-observatory/lib/codex/codex-rs/core/src/session/mod.rs:4329)<br>[codex-rs/core/src/session/mod.rs:4888](/home/brooksch/sandboxes/brooksch/projects/teaching/codex-harness-observatory/lib/codex/codex-rs/core/src/session/mod.rs:4888)<br>[codex-rs/core/src/session/mod.rs:5195](/home/brooksch/sandboxes/brooksch/projects/teaching/codex-harness-observatory/lib/codex/codex-rs/core/src/session/mod.rs:5195) | History admission, step capture, compaction replacement, source counts and usage. |
| C.budget | [codex-rs/core/src/session/context_window.rs:1](/home/brooksch/sandboxes/brooksch/projects/teaching/codex-harness-observatory/lib/codex/codex-rs/core/src/session/context_window.rs:1)<br>[codex-rs/core/src/context_manager/history.rs:1163](/home/brooksch/sandboxes/brooksch/projects/teaching/codex-harness-observatory/lib/codex/codex-rs/core/src/context_manager/history.rs:1163) | ContextWindowTokenStatus and harness active-token estimate. |
| C.ann | [codex-rs/protocol/src/models/item_metadata.rs:55](/home/brooksch/sandboxes/brooksch/projects/teaching/codex-harness-observatory/lib/codex/codex-rs/protocol/src/models/item_metadata.rs:55)<br>[codex-rs/protocol/src/models.rs:1024](/home/brooksch/sandboxes/brooksch/projects/teaching/codex-harness-observatory/lib/codex/codex-rs/protocol/src/models.rs:1024) | Per-part provenance and internal passthrough/skip-serialization. |
| C.fragments | [codex-rs/context-fragments/src/fragment.rs:56](/home/brooksch/sandboxes/brooksch/projects/teaching/codex-harness-observatory/lib/codex/codex-rs/context-fragments/src/fragment.rs:56)<br>[codex-rs/context-fragments/src/annotated_content.rs:1](/home/brooksch/sandboxes/brooksch/projects/teaching/codex-harness-observatory/lib/codex/codex-rs/context-fragments/src/annotated_content.rs:1)<br>[codex-rs/core/src/context_manager/updates.rs:1](/home/brooksch/sandboxes/brooksch/projects/teaching/codex-harness-observatory/lib/codex/codex-rs/core/src/context_manager/updates.rs:1) | Producer annotations survive grouping and truncation. |
| C.skills | [codex-rs/core/src/skills.rs:145](/home/brooksch/sandboxes/brooksch/projects/teaching/codex-harness-observatory/lib/codex/codex-rs/core/src/skills.rs:145)<br>[codex-rs/core/src/skills.rs:240](/home/brooksch/sandboxes/brooksch/projects/teaching/codex-harness-observatory/lib/codex/codex-rs/core/src/skills.rs:240) | Native explicit and detected implicit skill invocations. |
| C.skills-fragments | [codex-rs/ext/skills/src/fragments.rs:1](/home/brooksch/sandboxes/brooksch/projects/teaching/codex-harness-observatory/lib/codex/codex-rs/ext/skills/src/fragments.rs:1) | Catalog versus selected skill instructions, metadata and content kinds. |

## DSH context plugin

| Key | Source location | Relevant responsibility |
|---|---|---|
| D.view | [src/client/components/contextView.tsx:1](/home/brooksch/sandboxes/brooksch/projects/research/dsh-reviewed/candidates/0.8/dsh-context/src/client/components/contextView.tsx:1) | Panel composition, cross-card focus, scope and hover/pin linkage. |
| D.stats | [src/client/components/statsContext.tsx:1](/home/brooksch/sandboxes/brooksch/projects/research/dsh-reviewed/candidates/0.8/dsh-context/src/client/components/statsContext.tsx:1) | Counts, I/O, tool/command chips, current/family usage and click navigation. |
| D.browser | [src/client/components/browser.tsx:1](/home/brooksch/sandboxes/brooksch/projects/research/dsh-reviewed/candidates/0.8/dsh-context/src/client/components/browser.tsx:1) | Request/baseline selection, category/item inspection, filtering, sorting and treemap/DNA controls. |
| D.categories | [src/client/categories.ts:1](/home/brooksch/sandboxes/brooksch/projects/research/dsh-reviewed/candidates/0.8/dsh-context/src/client/categories.ts:1) | Category palette, officialParts, anchoredParts and billedParts. |
| D.tokens | [src/client/components/statsTokens.tsx:1](/home/brooksch/sandboxes/brooksch/projects/research/dsh-reviewed/candidates/0.8/dsh-context/src/client/components/statsTokens.tsx:1) | Token donut, cumulative totals and cache share. |
| D.format | [src/client/format.ts:1](/home/brooksch/sandboxes/brooksch/projects/research/dsh-reviewed/candidates/0.8/dsh-context/src/client/format.ts:1) | Cache-share and display formatting. |
| D.current | [src/client/components/currentComposition.tsx:1](/home/brooksch/sandboxes/brooksch/projects/research/dsh-reviewed/candidates/0.8/dsh-context/src/client/components/currentComposition.tsx:1) | Current gauge, composition, legend and reserve rendering. |
| D.headline | [src/client/headline.ts:1](/home/brooksch/sandboxes/brooksch/projects/research/dsh-reviewed/candidates/0.8/dsh-context/src/client/headline.ts:1) | Projected/sampled/derived occupancy precedence and anchored category areas. |
| D.reserve | [src/client/reserve.ts:1](/home/brooksch/sandboxes/brooksch/projects/research/dsh-reviewed/candidates/0.8/dsh-context/src/client/reserve.ts:1) | Fixed DSH reserve geometry; not Codex policy. |
| D.timing | [src/client/components/statsTiming.tsx:1](/home/brooksch/sandboxes/brooksch/projects/research/dsh-reviewed/candidates/0.8/dsh-context/src/client/components/statsTiming.tsx:1) | Active-time donut, phase totals, tool busy time and TPS. |
| D.metering | [src/host/foldMetering.ts:1](/home/brooksch/sandboxes/brooksch/projects/research/dsh-reviewed/candidates/0.8/dsh-context/src/host/foldMetering.ts:1) | Time accumulation, interval merge/carving, idle threshold. |
| D.strip | [src/client/components/timingStrip.tsx:1](/home/brooksch/sandboxes/brooksch/projects/research/dsh-reviewed/candidates/0.8/dsh-context/src/client/components/timingStrip.tsx:1) | Phase strip and shared hover labels. |
| D.fold | [src/host/fold.ts:1](/home/brooksch/sandboxes/brooksch/projects/research/dsh-reviewed/candidates/0.8/dsh-context/src/host/fold.ts:1) | DSH event taxonomy, source categories, request/answer counts and compaction/prune events. |
| D.skills | [src/host/skills.ts:1](/home/brooksch/sandboxes/brooksch/projects/research/dsh-reviewed/candidates/0.8/dsh-context/src/host/skills.ts:1) | Session-scoped catalog lookup for live plugin features. |
| D.trend | [src/client/components/trendChart.tsx:1](/home/brooksch/sandboxes/brooksch/projects/research/dsh-reviewed/candidates/0.8/dsh-context/src/client/components/trendChart.tsx:1)<br>[src/client/components/trendWindow.ts:1](/home/brooksch/sandboxes/brooksch/projects/research/dsh-reviewed/candidates/0.8/dsh-context/src/client/components/trendWindow.ts:1) | Stacked/DNA bars, scrolling, adaptive axes and viewport windowing. |
| D.trendModel | [src/client/components/trendModel.ts:1](/home/brooksch/sandboxes/brooksch/projects/research/dsh-reviewed/candidates/0.8/dsh-context/src/client/components/trendModel.ts:1) | Turn's final snapshot, signed delta/churn, markers and tooltips. |
| D.duration | [src/client/components/trendDurationCurve.tsx:1](/home/brooksch/sandboxes/brooksch/projects/research/dsh-reviewed/candidates/0.8/dsh-context/src/client/components/trendDurationCurve.tsx:1) | Duration overlay drawing. |
| D.dna | [src/client/dna.ts:1](/home/brooksch/sandboxes/brooksch/projects/research/dsh-reviewed/candidates/0.8/dsh-context/src/client/dna.ts:1) | Item-level bands, identity and added/removed areas. |
| D.overview | [src/client/components/trendOverview.tsx:1](/home/brooksch/sandboxes/brooksch/projects/research/dsh-reviewed/candidates/0.8/dsh-context/src/client/components/trendOverview.tsx:1) | Fit-to-width ribbon and turn/category navigation. |
| D.request | [src/client/components/requestDetail.tsx:1](/home/brooksch/sandboxes/brooksch/projects/research/dsh-reviewed/candidates/0.8/dsh-context/src/client/components/requestDetail.tsx:1) | Selected request brief and reported/estimated metrics. |
| D.events | [src/client/components/events.tsx:1](/home/brooksch/sandboxes/brooksch/projects/research/dsh-reviewed/candidates/0.8/dsh-context/src/client/components/events.tsx:1) | Context-event labels, source location, size and reveal links. |
| D.files | [src/client/components/fileCard.tsx:1](/home/brooksch/sandboxes/brooksch/projects/research/dsh-reviewed/candidates/0.8/dsh-context/src/client/components/fileCard.tsx:1) | Path table, filters, sorts and operation expansion. |
| D.activity | [src/client/fileActivity.ts:1](/home/brooksch/sandboxes/brooksch/projects/research/dsh-reviewed/candidates/0.8/dsh-context/src/client/fileActivity.ts:1) | File aggregation, path display and operation/source linking. |
| D.fileOps | [src/shared/fileOps.ts:1](/home/brooksch/sandboxes/brooksch/projects/research/dsh-reviewed/candidates/0.8/dsh-context/src/shared/fileOps.ts:1) | Recognized call arguments and inferred read/write/search/range metadata. |
| D.commands | [src/client/commands.ts:1](/home/brooksch/sandboxes/brooksch/projects/research/dsh-reviewed/candidates/0.8/dsh-context/src/client/commands.ts:1)<br>[src/shared/commands.ts:1](/home/brooksch/sandboxes/brooksch/projects/research/dsh-reviewed/candidates/0.8/dsh-context/src/shared/commands.ts:1) | Command tools, outcome parsing, units, grouping and slow threshold. |
| D.commandPanel | [src/client/components/commandPanel.tsx:1](/home/brooksch/sandboxes/brooksch/projects/research/dsh-reviewed/candidates/0.8/dsh-context/src/client/components/commandPanel.tsx:1) | Command rows/results, summary, filters, pagination and locate behavior. |
| D.attachments | [src/client/components/attachments.tsx:1](/home/brooksch/sandboxes/brooksch/projects/research/dsh-reviewed/candidates/0.8/dsh-context/src/client/components/attachments.tsx:1) | Recorded image/file references, thumbnail loading and metadata. |
| D.nodes | [src/client/components/browserNodes.tsx:1](/home/brooksch/sandboxes/brooksch/projects/research/dsh-reviewed/candidates/0.8/dsh-context/src/client/components/browserNodes.tsx:1)<br>[src/client/components/nodes.tsx:1](/home/brooksch/sandboxes/brooksch/projects/research/dsh-reviewed/candidates/0.8/dsh-context/src/client/components/nodes.tsx:1) | Mixed message parts and kind filters. |
| D.schema | [src/client/components/browserToolCard.tsx:1](/home/brooksch/sandboxes/brooksch/projects/research/dsh-reviewed/candidates/0.8/dsh-context/src/client/components/browserToolCard.tsx:1)<br>[src/client/components/browserSchema.ts:1](/home/brooksch/sandboxes/brooksch/projects/research/dsh-reviewed/candidates/0.8/dsh-context/src/client/components/browserSchema.ts:1)<br>[src/host/headers.ts:1](/home/brooksch/sandboxes/brooksch/projects/research/dsh-reviewed/candidates/0.8/dsh-context/src/host/headers.ts:1)<br>[src/host/attribution.ts:1](/home/brooksch/sandboxes/brooksch/projects/research/dsh-reviewed/candidates/0.8/dsh-context/src/host/attribution.ts:1) | Schema rendering, historical headers and inferred plugin ownership. |
| D.content | [src/client/components/richText.tsx:1](/home/brooksch/sandboxes/brooksch/projects/research/dsh-reviewed/candidates/0.8/dsh-context/src/client/components/richText.tsx:1) | Rich/raw content handling. |
| D.treemap | [src/client/components/browserTreemap.tsx:1](/home/brooksch/sandboxes/brooksch/projects/research/dsh-reviewed/candidates/0.8/dsh-context/src/client/components/browserTreemap.tsx:1)<br>[src/client/treemap.ts:1](/home/brooksch/sandboxes/brooksch/projects/research/dsh-reviewed/candidates/0.8/dsh-context/src/client/treemap.ts:1) | Category/item area maps. |
| D.assemble | [src/client/assemble.ts:1](/home/brooksch/sandboxes/brooksch/projects/research/dsh-reviewed/candidates/0.8/dsh-context/src/client/assemble.ts:1) | Historical surface/header reconstruction and missing/approximate flags. |
| D.plugin | [src/client/components/pluginInfo.tsx:1](/home/brooksch/sandboxes/brooksch/projects/research/dsh-reviewed/candidates/0.8/dsh-context/src/client/components/pluginInfo.tsx:1)<br>[src/client/components/recomCard.tsx:1](/home/brooksch/sandboxes/brooksch/projects/research/dsh-reviewed/candidates/0.8/dsh-context/src/client/components/recomCard.tsx:1) | Host metadata and recommendation/promotional panels. |
| D.cost | [src/client/cost.ts:1](/home/brooksch/sandboxes/brooksch/projects/research/dsh-reviewed/candidates/0.8/dsh-context/src/client/cost.ts:1) | Price lookup, cost estimation and billed-token totals. |
| D.types | [src/shared/types.ts:1](/home/brooksch/sandboxes/brooksch/projects/research/dsh-reviewed/candidates/0.8/dsh-context/src/shared/types.ts:1)<br>[src/shared/estimate.ts:1](/home/brooksch/sandboxes/brooksch/projects/research/dsh-reviewed/candidates/0.8/dsh-context/src/shared/estimate.ts:1)<br>[src/host/pricing.ts:1](/home/brooksch/sandboxes/brooksch/projects/research/dsh-reviewed/candidates/0.8/dsh-context/src/host/pricing.ts:1) | Shared data contracts and text/schema estimation. |

## DSH Trajectory client package

| Key | Source location | Relevant responsibility |
|---|---|---|
| T.view | [packages/client/ui-trajectory/src/client/TrajectoryView.tsx:1](/home/brooksch/sandboxes/brooksch/projects/research/dsh-reviewed/candidates/0.8/deepseek-harness/packages/client/ui-trajectory/src/client/TrajectoryView.tsx:1) | Projection consumer, request numbering, partial/live rows, history and selection. |
| T.table | [packages/client/ui-trajectory/src/client/TrajectoryTable.tsx:1](/home/brooksch/sandboxes/brooksch/projects/research/dsh-reviewed/candidates/0.8/deepseek-harness/packages/client/ui-trajectory/src/client/TrajectoryTable.tsx:1) | Detail tabs, hierarchy, rich/raw/JSON/code output, resizable pane and virtual ledger. |
| T.toolbar | [packages/client/ui-trajectory/src/client/TrajectoryToolbar.tsx:1](/home/brooksch/sandboxes/brooksch/projects/research/dsh-reviewed/candidates/0.8/deepseek-harness/packages/client/ui-trajectory/src/client/TrajectoryToolbar.tsx:1) | Duration toggle, fold controls, search and hidden actual-time control. |
| T.timeline | [packages/client/ui-trajectory/src/client/timeline.ts:1](/home/brooksch/sandboxes/brooksch/projects/research/dsh-reviewed/candidates/0.8/deepseek-harness/packages/client/ui-trajectory/src/client/timeline.ts:1) | Sequence/duration/complete/compressed time projections and three lane mapping. |
| T.overview | [packages/client/ui-trajectory/src/client/TrajectoryTimeline.tsx:1](/home/brooksch/sandboxes/brooksch/projects/research/dsh-reviewed/candidates/0.8/deepseek-harness/packages/client/ui-trajectory/src/client/TrajectoryTimeline.tsx:1) | Overview click/brush, wheel zoom, pan, focus and tooltip interactions. |
| T.record | [packages/client/ui-trajectory/src/client/trajectory-record.ts:1](/home/brooksch/sandboxes/brooksch/projects/research/dsh-reviewed/candidates/0.8/deepseek-harness/packages/client/ui-trajectory/src/client/trajectory-record.ts:1) | Record/source-block contracts, stable record IDs and metrics. |
| T.contract | [packages/client/ui-trajectory/src/client/trajectory-contract.ts:1](/home/brooksch/sandboxes/brooksch/projects/research/dsh-reviewed/candidates/0.8/deepseek-harness/packages/client/ui-trajectory/src/client/trajectory-contract.ts:1) | Request headers, partial assistant, tool schemas and image renderer slot. |
| T.layout | [packages/client/ui-trajectory/src/client/layout.ts:1](/home/brooksch/sandboxes/brooksch/projects/research/dsh-reviewed/candidates/0.8/deepseek-harness/packages/client/ui-trajectory/src/client/layout.ts:1) | Turn/step groups, assistant/tool/subcall nesting. |
| T.tool | [packages/client/ui-trajectory/src/client/trajectory-tool-definition.ts:1](/home/brooksch/sandboxes/brooksch/projects/research/dsh-reviewed/candidates/0.8/deepseek-harness/packages/client/ui-trajectory/src/client/trajectory-tool-definition.ts:1) | Call/result/dispatch lifecycle, nested/error/interruption handling. |
| T.assistant | [packages/client/ui-trajectory/src/client/trajectory-assistant-definition.ts:1](/home/brooksch/sandboxes/brooksch/projects/research/dsh-reviewed/candidates/0.8/deepseek-harness/packages/client/ui-trajectory/src/client/trajectory-assistant-definition.ts:1) | Request and assistant lifecycle, partial output, retries and failed requests. |
| T.header | [packages/client/ui-trajectory/src/client/trajectory-request-header-definition.ts:1](/home/brooksch/sandboxes/brooksch/projects/research/dsh-reviewed/candidates/0.8/deepseek-harness/packages/client/ui-trajectory/src/client/trajectory-request-header-definition.ts:1) | Prompt/catalog introductions and updates. |
| T.comp | [packages/client/ui-trajectory/src/client/trajectory-compaction-definition.ts:1](/home/brooksch/sandboxes/brooksch/projects/research/dsh-reviewed/candidates/0.8/deepseek-harness/packages/client/ui-trajectory/src/client/trajectory-compaction-definition.ts:1) | Compaction request/result/checkpoint projection. |
| T.code | [packages/client/ui-trajectory/src/client/code-program.ts:1](/home/brooksch/sandboxes/brooksch/projects/research/dsh-reviewed/candidates/0.8/deepseek-harness/packages/client/ui-trajectory/src/client/code-program.ts:1) | JavaScript program source/summary and tool presentation. |
| T.search | [packages/client/ui-trajectory/src/client/trajectory-search-index.ts:1](/home/brooksch/sandboxes/brooksch/projects/research/dsh-reviewed/candidates/0.8/deepseek-harness/packages/client/ui-trajectory/src/client/trajectory-search-index.ts:1) | Searchable raw/rich content, source metadata and schemas. |

## Supporting source inspection

The feature walk started at D.view's panel composition and T.view/T.table's view/detail composition, then followed component data contracts, host event folds, category/estimate calculations, timing intervals, schema attribution, file/command extraction, history assembly and selection/navigation. It did not infer interactions solely from screenshots.

On the Observatory side, inspection followed the browser's event/artifact consumption back through the Python reader, native raw variants and reducers, then to Core's request preparation, prompt assembly, history admission, context budgets, source annotations and skill invocation owners. Existing regression tests were read for identity/continuity/cancellation/compaction/code-cell invariants; they were not rerun as part of this documentation task.

The official [Codex App Server event documentation](https://learn.chatgpt.com/docs/app-server#events) was fetched in this conversation and corroborates public item lifecycle/delta/usage concepts. The pinned patched implementation is the authority for this spike's exact capture boundaries. No claim of current hosted-model behavior or full platform/provider coverage is based on public documentation alone.

## Recording audit

The audit imported the current Python reader with PYTHONPATH=src and used validated_events() to expand/validate the saved events and their discoverable payload references. It paired native attempt/tool lifecycle IDs, inspected request/response structures and usage, counted protocol delta methods, checked context window metadata, compared sequence continuity and hashed trace.jsonl before/after reading. It did not invoke collectors, agents, models, VMs or browsers.

The first audit invocation omitted PYTHONPATH and failed to import observatory. Rerunning with the repository's source path completed the same bounded read-only audit; no implementation change was needed.

Audited task recordings, relative to the repository:

- build/evidence/runs-cli/20261115T042924Z-b864be53ea8f4291854e416622daa785
- build/evidence/runs-desktop/20261115T044146Z-d31d9a29418f46a7889fa4ceb1ad91d9

The initial Desktop startup-only attempt was not used as task evidence. The assembled-runs-cli and assembled-runs-desktop captures were inspected and retained in evidence.json specifically to show that they contain no inference attempts. They cannot establish task, token, tool or model acceptance.

The task recordings validate 995 and 732 unique referenced payloads respectively. All 26 attempts have a terminal: CLI 16 completed; Desktop 4 completed and 6 failed. All 16 tool calls have terminal records. Usage exists for the 20 completed attempts; no report was invented for the six failures.

Request media was text only, all model transports were HTTP, there were no native compaction installations or child results, and no request-message attribution metadata survived preparation. Consequently:

- Composition, request/tool identity and reported-usage observations have direct saved-run evidence.
- WebSocket continuity, code-mode hierarchy, compaction, media and child-agent support are grounded in source/test inspection, not newly demonstrated live.
- No end-to-end visual acceptance of the proposed interface has occurred.
- No Python/Rust test suite, benchmark, native build or model run was needed for the research deliverable.

A minimal reproduction of the core pairing check, run from the Observatory repository, is:

~~~bash
PYTHONPATH=src python - <<'PY'
from pathlib import Path
from observatory.trace_viewer import validated_events

for group in ("runs-cli", "runs-desktop"):
    for path in sorted((Path("build/evidence") / group).glob("*/trace.jsonl")):
        events = list(validated_events(path))
        starts = {
            event["payload"]["inference_call_id"]
            for event in events
            if event["payload"]["type"] == "inference_started"
        }
        if not starts:
            continue
        ends = [
            event["payload"]
            for event in events
            if event["payload"]["type"] in {
                "inference_completed", "inference_failed", "inference_cancelled"
            }
        ]
        print(path, len(events), len(starts), len(ends))
        assert len(ends) == len(starts)
        assert all(item["inference_call_id"] in starts for item in ends)
PY
~~~

The saved evidence.json contains the more detailed field/method/count summaries and hashes. It contains no full prompt, response, credential, or copied recording payload. The three reference PNGs are unchanged copies of the instructor's attachments.

## What remains uncertain

The exact desired teaching vocabulary, chart estimator and next-request promise await discussion. The spike recommends bounded choices in DEVELOPMENT; it does not settle them by implementing a schema.

No claim is made that the current instrumentation observes every Core transition, every provider stream event, every external-tool filesystem operation, every schema available to a running code cell, or hidden provider context. A clean writer and valid references do not establish those claims. Unknowns are part of the display requirements, not defects to conceal with inferred data.
