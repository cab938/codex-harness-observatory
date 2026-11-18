# DSH-style Context and Trajectory for the Observatory

Assessment date: 2026-11-16. The original source-grounded spike and baseline evidence are preserved here. The user subsequently authorized implementation; current delivered behavior, metric choices, acceptance results and remaining limits are recorded in [DEVELOPMENT.md](DEVELOPMENT.md#implementation-record-2026-11-16). The full feature inventory remains the wider target.

## Purpose and scope

Build an interface close to the DSH Context dashboard and Trajectory view supplied by the instructor, adapted to explain how Codex works. The audience is learners, including instructors sharing what they know. Throughput tuning, billing optimization, fleet administration, and production monitoring are secondary.

The target includes the visible panels and their supporting interactions: request selection, context composition and change, item inspection, tool nesting, timelines, filters, schemas, images, commands, and links between views. It does not automatically include DSH's surrounding chat application, plugin manager, advertising, global Context Insights, standalone Fleet tab, or context-changing commands.

The existing wire-event capture and Events view remain first-class alongside the two new semantic views. See the settled event-view and capture requirement in [DEVELOPMENT.md](DEVELOPMENT.md).

Preserved screenshot references:

- [Context overview](references/context-overview.png)
- [Context activity](references/context-activity.png)
- [Trajectory](references/trajectory.png)

## Read this spike

| Document | Owns |
|---|---|
| [FEATURE_MAP.md](FEATURE_MAP.md) | Feature-by-feature inventory, teaching purpose, DSH source, available data, remaining work, and capture-gap references. |
| [DATA_MAP.md](DATA_MAP.md) | Exact existing evidence routes, identities, joins, calculation semantics, and source limitations. |
| [CAPTURE_PLAN.md](CAPTURE_PLAN.md) | Concrete collection gaps, proposed smallest changes, alternatives, and patch boundaries. |
| [DEVELOPMENT.md](DEVELOPMENT.md) | Suggested implementation sequence, acceptance scenarios, and bounded discussion decisions. |
| [SOURCES.md](SOURCES.md) | Source revisions, code navigation keys used by the tables, investigation method, and limits. |
| [evidence.json](evidence.json) | Machine-readable audit of retained recordings, source state, and screenshot hashes. |

Detailed definitions live in those owning documents. This README is a route through them.

## Findings at the assessment baseline

1. **Most of the interface is a viewer/projection feature.** The recording already contains prepared model requests, parsed outputs, usage, tools and results, terminal observations, code-cell relationships, compaction checkpoints, agent relationships, and App Server/MCP messages. The present web UI exposes an event list and artifacts; it does not yet assemble the teaching displays.

2. **The best additional collection is existing information that we currently lose.** Codex already carries positional content kinds and source attribution, including user input, AGENTS.md, skills, developer instructions, harness context, and tool context. Provider request preparation removes some or all of these annotations. Neither audited local-provider request set retains them. Preserve this information in trace-local evidence before removal rather than inventing a classifier based on text or role. See G1 in the capture plan.

3. **Internal context budgets are more useful for teaching than performance metrics.** Codex already computes the usage estimate and thresholds that drive compaction. Our compaction decision event keeps categorical reasons but discards these quantities. Recording them would let the interface explain why Codex chose to compact. See G2.

4. **The DSH displays contain estimates and application-specific definitions.** Category token sizes are estimated and sometimes scaled to reported totals. "Skill Loads" counts distinct skill names in the inspected code. "Answers" includes assistant messages with text. Turn aggregation keeps the last context snapshot, rather than summing context sizes. These are useful references, not Codex semantics to copy silently.

5. **The target includes a DSH-style live context preview.** As recorded in D1 of DEVELOPMENT.md, the interface should support both historical requests and current history between requests. A last observed request is available now; the minimum extra collection needed for a faithful live preview remains open under G3. Accepted-item receipts are not full history snapshots, and a preview does not guarantee the eventual next request.

6. **Detailed timing is optional and should remain clearly defined.** Model/tool lifecycles and client-facing streaming observations already support useful timing. The six-way timing donut requires more precise inference-correlated observations. It should not block the core teaching views. See G5.

## Evidence checked

The main checkout was at 719236f944ddba6f6faeb5b5af7880dac087d218, with instrumented Codex at 008448a4e778564b7505d5e35095efaf1f8a6896. The release descriptor identifies Observatory 0.4.0, Core 0.169.0, Desktop 26.1111.21308, and raw schema 6.

The DSH context checkout is version 0.82.2, matching the plugin version in the screenshot. Trajectory is a DSH client package, not a separate context-plugin module. Its exact inspected revision and the surrounding reviewed checkout's dirty state are recorded in SOURCES and evidence.json.

A read-only audit used the Observatory reader to validate saved recording references:

| Recording | Records | Model attempts | Outcomes | Tool calls | Referenced payloads |
|---|---:|---:|---|---:|---:|
| CLI task | 3,233 | 16 | 16 completed | 13 | 995 |
| Desktop task | 2,174 | 10 | 4 completed, 6 failed | 3 | 732 |

Every model attempt and tool call in these two recordings had a matching terminal event. Usage was available for the 20 completed attempts. Trace hashes were unchanged. The assembled-package startup captures contain no model attempts and therefore supply startup evidence only.

These are short local-provider recordings. They do not exercise images, child agents, compaction, or incremental WebSocket requests. Source and existing regression-test inspection support those routes; new live acceptance was not performed.

At the assessment baseline, the checked-in collection inventory named Observatory 0.3.0/Core 0.166.0-alpha.6 and was stale relative to release.json. Implementation regenerated the declaration inventory for the pinned 0.169.0 source. Declaration availability remains separate from actual runtime exercise.

## Recommended discussion outcome

Settled discussion decisions are recorded in DEVELOPMENT.md. Agree on the remaining learner-facing meanings and minimum capture additions, then build linked Context and Trajectory projections with original evidence always reachable. The likely high-value capture additions are G1 source attribution and G2 context-budget observations. Exact next-request simulation, detailed decode timing, arbitrary filesystem auditing, and cost services should require an affirmative teaching reason.
