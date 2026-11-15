# Desktop Observatory implementation

## Approved 0.3 target

The integration uses signed Linux Desktop 26.1029.61003 with its matching Core 0.166.0-alpha.6 at `4f093f2748667f3b0e6a07e3d4055121cbd3ce64`. The package digest and build inputs are owned by `codex_harness_observatory/release.json`; that descriptor is the single source of release pins. Stable terminal Core 0.166.0 is a separate build.

The daily Desktop installation and its profile must remain untouched. Live capture is Linux x86_64. Recorded viewing is portable Python 3.11+ plus a browser. The operator curates authentic full recordings before sharing; no sanitizer or HTML exporter is part of this release.

## Implementation ledger

- [x] Preserve the original eight changed paths and the staged alpha.5.1 implementation.
- [x] Create the alpha.6 integration branch and retain the previous captures.
- [x] Build a separately identified, relocatable Desktop and matching Core package.
- [x] Establish rootless shared-run startup, raw schema 6, manifest schema 4, reduced schema 5, and capture-health disclosure.
- [x] Correct typed connection/exchange correlations and logical transport boundaries.
- [x] Align context, compaction, agent, approval, Guardian, and hook observations with native owners.
- [x] Correct activity, provenance, payload presentation, and root selection in the viewer.
- [x] Provide byte-preserving ZIP export and replay without capture dependencies.
- [x] Verify the exact packages, isolated native Desktop behavior, and legacy replay.
- [x] Finalize package checksums, collection inventory, and acceptance evidence.

Only checked entries have completion evidence. Earlier acceptance does not establish alpha.6 behavior.

## Collection contract

One App Server lifetime is one shared bundle. It starts before clients connect and may contain only session traffic. Root, child, ephemeral, and unattributed events remain distinct. The writer sequence is append order; explicit correlations establish relationships.

Reuse native inference, history, tool, terminal, Code Mode, compaction, and MCP-result collectors. Add source-local explanations only where native evidence is insufficient. Observers must not change prompts, decisions, native synchronization order, or execution policy.

Record complete semantic App Server and MCP JSON at declared logical boundaries. Outgoing prepared messages are not proof of delivery. Preserve typed request IDs, connection instances, directions, exchanges, failures, and reconnects. Capture actual negotiated capabilities, filters, subscriptions, and raw-event settings.

Model request payloads distinguish constructed transport bodies, incremental bodies, logical warmup snapshots, and reconstructed context. Queue acceptance, mailbox drain, history admission, and model consumption are separate facts. Proposed hook changes are separate from applied changes. Report collection losses and unknown final state rather than certifying completeness from valid JSONL.

The versioned inventory distinguishes source/API availability, implemented collection, observed traffic, and exercised acceptance. Provider-exposed reasoning-associated text may be recorded; inaccessible hosted private reasoning is not exposed.

## Isolation and sharing

The candidate has its own app identity, real short Core home, Electron user-data path, HOME, XDG directories, temporary directory, IPC services, and sockets. `CODEX_ELECTRON_USER_DATA_PATH` must be set before Desktop starts. Namespace isolation includes the app's otherwise hardcoded temporary service paths. Cleanup stops owned processes only. Credentials are authenticated separately and are never copied from the daily profile.

Export copies only the selected bundle, preserving all regular file bytes and optional reduced state. The recipient opens a directory or ZIP using the installed viewer without Core, Desktop, authentication, or a checkout. Display formatting is separate from original artifact text.

## Acceptance

The final acceptance record belongs here and in the retained evidence directory. It must cover native/traced behavioral equivalence; typed/reused protocol IDs and errors; full payloads; context and compaction; agents; Guardian and hooks; recording failures; overlapping roots and children in actual Desktop; and ZIP/legacy replay.

Builds and remaining native GUI acceptance run in Ubuntu vm02 at the operator's request. The guest has a separate 200 GiB Observatory build disk mounted at `/srv/observatory-0166`, with source at `/srv/observatory-0166/source`. The original VM system disk is retained without replacement or resizing; required build packages are installed in the guest. Its original libvirt configuration is retained for restoration. Only source and public signed build inputs are transferred; profiles, authentication, browser state, and recordings are not copied from the host.

Native GUI acceptance uses the guest's maintained Xvfb/Openbox display through guest-local CUA over SSH, without X11 forwarding or a host browser connection. It must verify visible behavior, actual executable/profile/IPC ownership, and normal/interrupted teardown. Authentication uses a fresh guest-only profile.

Run focused tests through `just test`, use isolated test homes, and follow the repository's full-suite approval rule. Do not change expected snapshots solely for host-installed skills. Package preparation does not publish, install, or promote the release.

## Current validation record

The coordinated changed-crate Rust run executed 8,587 tests: 8,586 passed, one failed, and 20 were skipped. The failure identified premature standalone trace finalization when a root shuts down before a resumed child. The writer-only lifecycle fix passed the original App Server case and all 86 rollout-trace tests. The operator approved the complete workspace suite. Its host attempt was blocked by GStreamer 1.28 development dependencies; the subsequent run excluding voice-host executed 23,307 tests, with 23,242 passed, 64 failed, one timed out, and 51 skipped. Snapshot/IPC and two V8 failures remain recorded rather than accepted as expected output. The Ubuntu VM provides the required GStreamer version. Its first changed-crate run executed 8,597 tests: 8,586 passed, 11 failed, and 22 were skipped. A guest im-config logging defect explained six failures; its reversible guest-only correction removed the unexpected stderr. The focused rerun passed 114 of 118 tests, including all 87 rollout-trace tests and the overlapping request-ID regression. Four process-cleanup failures remain. Untouched alpha.6 Core independently reproduces the network-rejection cleanup failure; syscall controls identify an AppArmor exec transition clearing the parent-death signal. The VM's profiles and native sandbox semantics remain unchanged.

The published V8 archive and binding both match their committed checksums but disagree on the Unix sandbox ABI. Untouched upstream reproduces the regression. The Observatory helper now regenerates a matching binding from the exact pinned producer and verifies both input and output digests. A fresh source snapshot reproduced the same binding bytes. Four focused runtime canaries and archive inspection checked typed-array access and limits, CppGC storage and collection, and sandbox identity. The original published assets remain unchanged; all build pins are in `core.v8`. The final full VM workspace run used the corrected pair and executed 23,371 tests: 23,315 passed, 56 failed, and 53 were skipped. Its log and source identity are retained in `workspace-final-tests.json`. Failures include version snapshots, platform-dependent shell/TLS/sandbox cases, and the four process-cleanup failures; they were not changed into expected output. A short private temporary directory and standard file permissions resolved earlier fixture-path and IPC-directory failures without changing Core policy. The scoped fix and final format pass completed successfully after that run. Rust tests were not rerun after fix/format, following the repository rule; the automatic semantic fix removed a redundant clone of a Copy status value. The final native archives were built from the formatted source, whose Rust patch digest is pinned in the release descriptor.

The late trace scenarios passed for prepared WebSocket warmup, local and background compaction, history admission, proposed versus applied hook effects, Guardian denial and pre-session cancellation, and linked versus unlinked elicitation. The child eviction/mail/reload test found a real observation gap: a reload request could lose its writer after eviction. The corrected observer records requested or failed reload through the live caller while preserving the child identity; it adds no native scheduling decision. All four repaired Guardian/agent cases passed, and the complete workspace run includes those changes.

The offline validation client observed equivalent model inputs and tool results across stock Core, candidate with tracing disabled, and candidate with tracing enabled. It normalizes generated identities and timestamps explicitly. The recorded prepared bodies match actual mock-provider requests; the complete 192,024-character tool result, typed/reused IDs, unknown semantic JSON members, experimental raw events, and notification filter were verified. This bounded scenario does not establish universal equivalence.

The descriptor-pinned installed Core and Desktop passed native acceptance on Ubuntu vm02. The rich normal capture contains 7,225 events and 2,490 payload files, including two root turns overlapping for 112.7 seconds, a child, an actual Desktop file-open tool exchange, a synthetic localhost IAB page, and continuation in the same shared bundle. Normal teardown removed all 48 recorded candidate processes and owned IPC paths. A separate rootless session closed cleanly with 1,609 session events and 668 payloads.

An initial active-interruption check found that a sandboxed sleep process could outlive Desktop's process group. The launcher now snapshots only verified descendants, pins their PID identities, and terminates surviving owned descendants after group teardown. A regression check preserves an unrelated process. Final active interruption removed all 33 recorded owned processes, including the actual sandbox and sleep, and their IPC paths. Its 2,697-event capture correctly remains partial with unknown writer health and no invented closing event. Manifest counters can lag the last appended events in this case.

ZIP exports preserve all 2,492 normal and 1,031 interrupted bundle files byte-for-byte. The final wheel's capture components are byte-identical to those used in the accepted final teardown runs; its later viewer change clears stale active/open/loaded counters on directly observed thread/run closure. Final installed ZIP replay renders the normal capture as clean and closed with zero current active/open/loaded counts, and the interrupted capture as partial with unknown writer health.

The final native package's 321 stable and 467 experimental schema files match the signed Desktop's stock Core byte-for-byte. Archive file hashes and dynamic dependencies were checked. These are development-profile native binaries requiring glibc 2.39, rather than optimized builds. A VM-only Electron flag disables Electron's own sandbox for the isolated Xvfb test because Ubuntu rejected its user-namespace startup; native Core sandbox policy and host configuration were unchanged. The guide documents the flag and its scope.

A provisional browser test discovered that hidden Node runtime copies of the browser service still used a shared socket and exposed daily Chrome tab metadata, including a sign-in callback URL, to the test model/tool transcript. The affected local recording and dedicated test conversation were removed. Model/tool conversation records cannot be erased here. The superseded archive is quarantined. The corrected transform covers all four browser-service copies, rejects an ordinary HOME fallback, and refreshes only verified dedicated-profile caches. The corrected archive successfully opened a synthetic localhost page through private IAB IPC. No daily Chrome tab was opened or changed.

Three baseline daily helper processes exited during testing; their cause is unknown. The daily ChatGPT processes remained present. Do not convert this evidence into a claim that every daily subprocess was unaffected.

The final Python 3.11 wheel passed clean installed directory, JSONL, and ZIP replay on Linux and native Windows without Core, Desktop, authentication, source checkout, or capture dependencies. Windows additionally exercised all six archive regressions, including junction rejection. The Windows stat/fstat identity discrepancy was fixed using fresh lstat identities, with reparse-point rejection. Temporary ZIP extraction was removed at shutdown and recipient homes remained empty. Native macOS execution remains unverified; its CI route is prepared but has not run.

The accepted artifacts are prepared locally only. No release was published, no branch was pushed, and the daily Desktop installation was not replaced. vm02 remains available with the dedicated authenticated demo profile and `/srv/observatory-0166/acceptance/launch-demo-gui.sh`; vm01 was shut down normally after its replay check. Temporary build swap and guarded orphan test fixtures were cleaned up. The prepared `personal/observatory-0166-20261104/release-0.3.0/` folder retains SHA-256 checksums, the portable wheel and source distribution, both native archives, a full source patch against exact alpha.6, the canonical Rust patch, build/provenance reports, the source and observed collection inventories, and acceptance results. `just bazel-lock-update` also passed with an unchanged lock digest. Final VM source was synchronized into the separate `codex/observatory-0.166` integration worktree and its Rust patch digest matches the packaged descriptor. Private recordings and service logs are retained separately for operator curation.

## Historical evidence

The preserved alpha.5.1 worktree and ignored `personal/observatory-demo-20261031/` retain four accepted 0.150/0.166-alpha.5.1 captures, their checksums, and installed-viewer reports from 2026-11-01. They are legacy replay fixtures and historical comparison evidence, not current alpha.6 acceptance. Keep them unchanged.
