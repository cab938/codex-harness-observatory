# Desktop Observatory: Shared-Run Teaching Plan

## Purpose and settled contract

The desktop teaching experience must show the same patched Core and App Server
that the command-line observatory uses. It must make simultaneous independent
tasks legible, including agent nesting and interleaved App Server and MCP
traffic. The objective is explanation through direct evidence, not a
production telemetry service.

One App Server lifetime is one **shared trace run**:

- a single retained bundle contains one `trace.jsonl`, one payload store, and
  one writer-assigned, strictly increasing `seq` order;
- every independent task started by Desktop is a root task and carries its own
  `task_root_thread_id` on its trace evidence;
- a task spawned by another task remains nested under that root rather than
  becoming a second root;
- frames not yet attributable to a task, such as initialization traffic, stay
  in the session lane rather than being silently assigned; and
- the shared writer remains open until the App Server lifecycle ends. A root
  task finishing must not close the run while other Desktop tasks remain
  active.

`task_root_thread_id` is the cross-layer join key. The ordinary `thread_id`,
`turn_id`, and `trace_step_id` retain their existing meanings. MCP calls also
retain their root, thread, and turn identity; response attribution must never
depend only on a JSON-RPC request ID, because IDs may be reused by overlapping
connections.

The teaching launcher is deliberately full evidence. It passes complete event
fields and payload artifacts to the loopback viewer, so prompts, replies, tool
arguments/results, paths, and exact App Server/MCP JSON can be examined during
a private demonstration. This does not expose private model reasoning and is
not a safe default for ordinary work or for a bundle that will leave the
teaching machine.

## Architecture

```text
Desktop task A -----\
Desktop task B ------+-- private Unix socket -- patched App Server -- patched Core
Desktop task C -----/                                   |                 |
                                                       shared run writer   harness/MCP events
                                                              |
                                            trace.jsonl + payloads (one exact seq order)
                                                              |
                                            loopback viewer: session lane + task lanes
```

The Desktop shell is a transport client, not a new trace producer. It launches
the patched Core selected by `CODEX_CLI_PATH`; the existing private Unix-socket
feature supplies `CODEX_LINUX_APP_SERVER_BRIDGE_SOCKET` and owns the child App
Server lifecycle. The observatory launcher supplies
`CODEX_ROLLOUT_TRACE_ROOT`, `CODEX_ROLLOUT_TRACE_SHARED_RUN=1`, and the
full-content viewer option. This keeps the Desktop/CLI boundary narrow: no
Desktop protocol changes and no public listener are introduced.

The signed Desktop supplies a base `codex_app` MCP transport in its bundled
plugin, then sends per-thread policy such as `enabled_tools` when starting a
task. Public Core does not know that bundled base transport and rejects the
policy-only table. `run.sh --desktop` therefore gives Desktop a retained
per-run `CODEX_CLI_PATH` bridge. For `app-server` only, the bridge prepends the
base stdio transport and approval defaults from the pinned signed bundle before
starting the development Core; Desktop's request still owns the per-thread
tool selection. Other CLI commands pass through unchanged. No normal-profile
configuration is rewritten.

The existing TUI flow stays compatible. Without
`CODEX_ROLLOUT_TRACE_SHARED_RUN=1`, a standalone root task keeps its current
single-bundle behavior. With it, the App Server scope creates one shared bundle
for all root tasks in that server lifetime.

## Implementation work

| Workstream | Owned change | Completion evidence |
| --- | --- | --- |
| Shared run | Make the trace writer App Server-scoped in opt-in shared mode; attach `task_root_thread_id`; keep exact sequence allocation global; delay closure to server shutdown. | Focused rollout-trace/App Server tests demonstrate two roots append to one bundle with increasing sequence values, and closing root A does not stop root B. |
| App Server attribution | Establish root identity on `thread/start`; route pre-root frames to a session lane; carry the root identity into sent/received wire envelopes. | An interleaved `thread/start` capture has identifiable roots and initialization is visible, not dropped. |
| MCP attribution | Preserve root/thread/turn/call context around every send/receive transport shape; scope pending correlation by connection as well as request ID. | A focused overlapping-call test proves that responses retain their original task attribution. |
| Viewer data model | Treat `trace.jsonl` as the only persisted input; derive roots, child edges, activity and task status from live rows. | Deterministic fixture and Python tests show separate task roots, child nesting, session traffic, and raw writer order. |
| Viewer interaction | Add an all-tasks view, task focus, status badges, lanes and concurrency overlap without reordering evidence. | Browser interaction shows two roots in flight, an agent child below its root, focus changes, and a full payload opened from the correct lane. |
| Desktop teaching launcher | Build/use a separately identified Desktop candidate that enables the existing socket feature; select the patched Core through the retained compatibility bridge at `CODEX_CLI_PATH`; launch the viewer before Desktop; retain the run directory on shutdown. | Existing socket-feature test passes with the patched binary, bundled `codex_app` reaches ready state, Desktop connects through the private socket, and a trace bundle is retained. |
| Documentation | Explain boundaries, launch flow, full-evidence consequence, and the distinction between implemented paths and live acceptance. | This plan, the main observatory guide, and tranche record agree on the contract. |

## Teaching sequence

1. Build the side-by-side candidate with
   `./build-desktop-observatory.sh`, then start it with `./run.sh --desktop`.
   The build helper accepts `--desktop-repo`, `--app-dir`, and `--report-dir`
   (or their `OBSERVATORY_DESKTOP_*` equivalents); the launcher uses
   `OBSERVATORY_DESKTOP_START` and, when an explicit socket path is required,
   `OBSERVATORY_DESKTOP_SOCKET`.
2. The teaching launcher creates a fresh retained run directory,
   starts the loopback full-evidence viewer, and starts a side-by-side Desktop
   candidate whose App Server bridge uses the patched Core.
3. In Desktop, begin task A and task B before either completes. The viewer
   shows two roots in separate task lanes with interleaved, globally ordered
   evidence.
4. Ask task A to delegate a bounded subtask. Its child remains visually nested
   below task A, and the viewer makes the parent/child correlations selectable.
5. Trigger a tool or MCP interaction in either root. The focused lane shows the
   Core decision/tool lifecycle alongside the exact request and response
   artifacts.
6. Switch to the all-tasks view to explain concurrency: order is the writer's
   exact `seq`, not a timestamp-sorted reconstruction. Finish one task while
   another continues to demonstrate that the run remains live.
7. Exit Desktop or stop the launcher. The App Server and viewer stop, while the
   bundle, payloads, and service logs remain available for replay.

## Implementation status and acceptance

The shared-run writer, App Server and MCP attribution, task-aware viewer, and
side-by-side Desktop launcher are implemented.

Measured acceptance on 2026-08-28:

- `codex-rollout-trace` passed 70 focused tests, including overlapping roots,
  child attachment, exact sequence ordering, and one terminal shared-run event;
- the combined viewer and Lecture 2 backend suite passed 28 tests, and browser
  interaction confirmed task focus, child nesting, full artifact access, and
  no console errors;
- the original Desktop socket acceptance passed all 41 focused tests against
  the patched Core, and the current development binary now reports
  `codex-cli 0.150.0-alpha.12.2`;
- the Core source is pinned to `rust-v0.150.0-alpha.12.2` at
  `a9802304f60ab14c0b07e3ee0db9a9c105ab0cb3`; the bundled Core in signed
  Desktop package `26.825.32147` reports the same version (package SHA-256
  `986d38b690dd0310933ce61175b09c27434001f4e114332bb0f7b6ffdc3ca406`);
- the signed candidate opened on isolated X11 display `:93` with a disposable
  unauthenticated profile, connected through the private socket, reported App
  Server `0.150.0-alpha.12.2`, and completed the initialization handshake;
- retained run `personal/observatory-runs/run-20260828-202045.eGufqk`
  contains the matching Desktop and viewer logs. No trace bundle was expected,
  because the disposable profile stopped at the sign-in screen before a root
  task was created;
- two independent protocol-level Desktop roots were loaded concurrently. The
  live viewer reported two active task lanes in one full-evidence bundle;
- the retained native run at
  `personal/observatory-runs/run-20260828-185713.dGrQg4` contains 165 contiguous
  events, exactly one `run_started`, two root lifecycles, and exactly one final
  `run_ended`; and
- the ordinary TUI launcher started its App Server and full-evidence viewer and
  shut both down cleanly with a disposable `CODEX_HOME`.

The public source is pinned to the tag and commit above, while the signed
Desktop artifact is separately pinned by package version and digest. Both Core
binaries report `0.150.0-alpha.12.2`; this is a compatible teaching set, not a
claim that the signed private binary is bit-identical to the public-source
build.

Measured authenticated acceptance on 2026-08-30, after explicit operator
authorization:

- diagnostic run `personal/observatory-runs/run-20260830-104808.robXnh`
  reached the signed-in Desktop but failed before a model turn with `invalid
  transport in mcp_servers.codex_app`. Its request showed the policy-only
  Desktop overlay, which established the need for the base-transport bridge;
- accepted run `personal/observatory-runs/run-20260830-105825.2pCAKV` retained
  shared bundle
  `traces/trace-02210732-8de9-46a1-ab4a-8be773667a18-shared`. It contains 2,515
  events, including 1,228 App Server frames, 549 MCP frames, 18 thread
  lifecycles, nine turn lifecycles, one child result, and one terminal shared
  run event. `tools/trace_viewer.py --check` reports `trace integrity: clean`;
- root turn `01a05331-e7ae-7e83-8af8-eeaa8d79b26a` ran from
  `1788102175228` through `1788102259629`. Independent root turn
  `01a05332-4b59-7f01-85f6-f1ef97063683` began at `1788102200668` and ended at
  `1788102210149`, entirely inside the first interval. This is the accepted
  concurrency evidence. The earlier task A/task B pair was sequential and is
  not counted as proof of overlap;
- child `01a0532e-5fd4-7433-af8e-e016406fb492` was visibly spawned under root
  `01a0532e-3ccc-7f70-a7f4-6225975cd5b5`, retained that
  `task_root_thread_id`, and returned its result through the shared ledger;
- the checked-in bridge then passed a separate authenticated smoke in
  `personal/observatory-runs/run-20260830-110931.WNdenH`. Desktop returned
  `PERSISTENT BRIDGE OK`, its log reported `codex_app` ready without the
  transport error, and bundle
  `traces/trace-75aa7b3e-c14f-401f-a350-0699457a5d03-shared` retained 751 clean
  events; and
- both accepted sessions shut down cleanly. Their shared traces contain one
  final `run_ended`, the private viewer port closed, and isolated X11 display
  `:93` was removed. The launcher did not edit the normal profile; ordinary
  signed-in Desktop/account runtime activity occurred within the disclosed
  authorization.

The normal-profile live-model, overlapping-root, and Desktop-spawned-child gate
is complete. The retained bundles contain unredacted private teaching evidence
and must remain local unless reviewed deliberately.

The Desktop route is intentionally Linux-specific because it uses the existing
Linux socket feature. The Core and trace changes remain platform-neutral; no
claim of macOS or Windows Desktop support follows from this plan.

## Explicit non-goals

- Instrumenting or modifying the Desktop renderer itself.
- Capturing hosted-model private reasoning.
- Publishing full-evidence bundles or weakening normal-product privacy
  defaults.
- Supporting multiple App Server lifetimes in one bundle. A new server lifetime
  is a new teaching run.
