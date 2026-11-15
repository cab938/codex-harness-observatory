# Observatory refactoring discussion

Date: 2026-11-13

These are working discussion notes. Record user requirements separately from assistant proposals. The user authorized the refactor and an upgrade of both Codex core and Desktop on 2026-11-14. These notes retain the design discussion and distinguish settled requirements from implementation evidence.

## User requirements

- Support both Codex Desktop and the CLI. Learners must be able to see traces directly for either interface.
- The purpose is learning. Add telemetry that helps explain Codex behavior; do not add functionality to Codex tools.
- Capture full messages and substantial payload data so learners can understand events in context. For the intended personal learning use, sensitivity is not a reason to omit or redact that content.
- The ideal system has an expansive read-only log that can be rendered for exploration.
- Keep notes throughout this discussion for the later refactor.

## Design heuristic: one great solution

Prefer one coherent solution over optional alternatives or parallel implementation paths. This is a heuristic, not an absolute rule; exceptions need a concrete justification.

The user's limited maintenance time makes avoiding drift, unnecessary choices, and accumulated complexity a design priority. Supporting both Desktop and CLI remains a requirement; both should feed the same capture and exploration design.

## Readability and UI principles

- Prefer an implementation that is easy to read over efficiency or security-driven complexity for this self-reflection and learning project.
- Extensibility is welcome only when it does not come at the expense of readability.
- Keep all UI elements minimal.
- Defer styling to later work.

## Settled decision: project-owned capture

Use the project's own capture with one local event log and full payloads. Do not add an Observatory OTel capture path, exporter, or alternative backend.

The user explicitly accepts additional Codex patching when needed to provide the required learning telemetry. The rationale is a single focused solution with less maintenance and drift, rather than optional interoperability.

This supersedes the assistant's earlier proposal for an optional OTel export. Implementation began on 2026-11-14.

## Requested component boundaries

The user wants to clean up the exploratory repository and system into a coherent arrangement with:

- CLI and Desktop clients, patched where needed for telemetry.
- App Server, patched where needed.
- An Observatory GUI for visualization and exploration of traces throughout the system. The user renamed this component from Explorer to Observatory.
- An isolation sandbox that roots CODEX_HOME so learners can download and use the system without clobbering an existing Codex space.

## Repository layout

The user proposes src for our source, lib for source dependencies, src/scripts for build scripts, and src/observatory for the visualization/exploration application. Keep tests at the root. Patch placement was left open between src/patches and root-level patches.

The assistant supports this naming and recommends root-level patches to make upstream modifications visible beside lib. A candidate layout is:

```text
README.md             # Current install and launch entry point
pyproject.toml        # Python package and observatory command
release.json          # Proposed single matched-release descriptor
src/
  observatory/        # Visualization, trace reading, browser interface
  launch.py           # Rooted startup and process lifecycle
  scripts/            # Build and packaging scripts
lib/
  codex/              # Pinned submodule: instrumented Codex fork
patches/
  desktop/            # Our Desktop patch inputs
docs/
  README.md           # Notes that much of the documentation is historical
  development.md      # Proposed autonomous development/testing workflow
  ...                 # Existing Observatory and visual-design documents
tests/
  fixtures/           # Small synthetic recordings
build/                # Generated output, ignored by Git
```

The refactor uses this layout. Root release.json is the single source descriptor for the matched build. Native source changes are commits in lib/codex.

The user explicitly requests a main-project docs directory for Observatory and visual-design documentation. docs/README.md has now been added with a brief historical-status note. This is not a request to rewrite all old documentation. Upstream Codex's documentation will remain with its source under lib/codex.

The user reviewed this overview before authorizing implementation.

The earlier recommendation remains one small main repository plus one instrumented Codex fork. Keep CLI, TUI, App Server, Core, and the native capture crate together in that fork, following upstream's workspace layout. The existing Linux Desktop companion remains a pinned build dependency fetched into build storage, with our transforms in patches/desktop. No additional maintained Desktop, Observatory UI, or sandbox repository is proposed.

Use one recording contract across producers and the Observatory. Build products and real recordings stay outside tracked source; small synthetic fixtures remain in tests. Learners download the assembled release without needing a source checkout or local build.

Source inspection found the newer implementation in the observatory-0166 worktree, while the main checkout contains older source and additional launcher work. The implementation preserves the original tracked and untracked work from all three checkouts under build/preserved/20261114 before replacing the old root layout.

## Settled invocation design

The user accepted:
- Each selected home contains complete persistent Codex state, including configuration and the relevant MCP configuration.
- Desktop application state and runtime paths are rooted consistently with that home.
- Either client can use the same home.
- A missing home is initialized; an existing home is reused without reinitialization.
- The recording destination is a parent directory, with a fresh uniquely named run directory per invocation.
- Each run directory contains its manifest, ordered event log, and full payloads.
- Codex state persists independently of recordings.

The user explicitly delegated choosing clearer Observatory flag names to avoid confusion with native Codex flags and then accepted --codex-home and --runs-dir. The settled interface for the later refactor is:

```bash
observatory --client desktop \
  --codex-home ~/.observatory/profiles/umich \
  --runs-dir ./recordings
```

- --client selects desktop or cli. The launcher requires an explicit client.
- --codex-home PATH selects the complete Codex home directory. Default: ~/.observatory/profiles/main.
- --runs-dir PATH selects the parent directory for recordings. Default: ~/.observatory/runs.
- Both directory arguments are paths. Relative paths resolve from the invocation's current working directory. A bare name is a relative path, not a special lookup under profiles.
- The launcher creates/selects the home and sets CODEX_HOME to its resolved path.
- Each invocation writes below RUNS_DIR/RUN_ID, with a unique run ID. Run IDs use a UTC timestamp followed by a UUID.
- The default locations are Observatory-owned; there is no implicit fallback to the daily Codex home.
- The old proposed --profile and --logs spellings are superseded. They were discussion proposals and have not been implemented.
- The profiles directory is a storage convention for reusable homes; this interface does not require a separate profile registry.

Naming rationale: --codex-home states the actual storage boundary and accepts a literal directory path. --runs-dir describes a parent containing full run bundles, including payloads, and distinguishes these recordings from ordinary diagnostic logs. Codex's native --profile remains distinct. Native argument forwarding is not part of the current agreed scope.

The assistant's earlier term "sandbox" meant rooted launch/environment-management code and the application state it manages. A simple launch module creates/selects the home, starts the required native processes and the Observatory, and manages shutdown while retaining state and recordings. This is separate from Codex's tool-execution sandbox and does not imply a separate framework or repository.

The work/project directory remains separate from both the Codex home and the recording destination. The CLI can use the invocation's current working directory; Desktop retains its normal project selection. No extra working-directory flag has been proposed.

The launcher implementation follows these decisions; actual native acceptance is recorded in development.md.

Current official configuration semantics were checked against:

- [Codex configuration profiles](https://learn.chatgpt.com/docs/config-file/config-advanced#profiles)
- [Codex config and state locations](https://learn.chatgpt.com/docs/config-file/config-advanced#config-and-state-locations)

## Development and testing workflow

The user described the host desktop, its RTX PRO 6000 Blackwell development GPU, and libvirt domains brooksch-agent-vm00 through vm03. They want agents to autonomously build and test candidates in the VMs against a small host vLLM backend, using a guest-local Codex configuration.

The proposed process is owned by [development.md](development.md). It uses the host for editing/GPU inference and vm02's existing build disk/private display for candidate execution, connected through loopback SSH reverse forwarding. The document contains the single initial model/image recipe, provider configuration, build routing, focused checks, evidence retention, and cleanup. Do not duplicate its commands or pins in these notes.

The initial November 13 discovery was read-only. The authorized November 14 implementation subsequently exercised the host model, VM builds, both clients, live capture, and replay. The execution record and remaining limits are maintained in development.md.

## Evidence informing the capture decision

OTel can represent structured full-content logs and operation relationships, but it would still require instrumentation for observations Codex does not emit. Its SDK/export/storage behavior would need explicit handling for complete, live learning records. OTel support is therefore technically possible but is not the selected project direction.

Sources:

- [Codex observability and telemetry](https://learn.chatgpt.com/docs/config-file/config-advanced#observability-and-telemetry)
- [OTel logs data model](https://opentelemetry.io/docs/specs/otel/logs/data-model/)
- [OTel tracing SDK: limits, sampling, processors, and export](https://opentelemetry.io/docs/specs/otel/trace/sdk/)
- [What is OpenTelemetry?](https://opentelemetry.io/docs/what-is-opentelemetry/)

## Refactor authorization and version selection

On 2026-11-14, the user explicitly requested upgrading both Codex core and Desktop to their latest versions and authorized Terra or Luna agents at any appropriate reasoning level. The orchestrator selected the latest stable release of each, rather than prereleases: core 0.169.0 and Desktop 26.1111.21308. Exact source commits, package and patch hashes belong to release.json.

Desktop bundles core 0.169.0-alpha.11.1, independently of the instrumented stable core. Build provenance records these separately; release compatibility must be demonstrated through the shared App Server protocol, rather than asserting the version strings are identical.

The main repository now owns the launcher, viewer, build scripts, and Desktop patch inputs. The pinned native fork owns the CLI, Core, App Server, and capture schema/writer. The assembled download contains both native runtimes and the Python interface, so learners do not build upstream source. Capture is Linux x86_64 at this stage; replay remains portable. The existing visualization capabilities are preserved while styling remains deferred.
