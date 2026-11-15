# Codex Harness Observatory

A local teaching tool for exploring how Codex works. The CLI and Desktop feed one native recording pipeline, and the Observatory presents the captured events and full payloads for reflection and learning.

The assembled native candidate supports Linux x86_64 with glibc 2.39 or newer. Python 3.11 or newer is required. Recorded runs can be explored on any platform with that Python version.

## Run

An assembled distribution contains both instrumented Core and the patched Desktop. Extract it and run:

```bash
./observatory --client desktop \
  --codex-home ~/.observatory/profiles/umich \
  --runs-dir ./recordings
```

Use `--client cli` for the terminal client. Both clients print the URL of the live Observatory. Open that URL in a browser to explore the recording.

`--codex-home` defaults to `~/.observatory/profiles/main`. It is a complete, persistent Codex home, including configuration and MCP definitions. Missing homes are created; existing configuration is reused. Desktop application state is kept with the selected home. Complete any initial Codex setup using that home.

`--runs-dir` defaults to `~/.observatory/runs`. Every invocation creates a new run directory containing `manifest.json`, `trace.jsonl`, `payloads/`, and diagnostic logs. Relative paths resolve from the directory where you invoke the command. CLI tasks use that working directory; Desktop retains its usual project selection.

Stop the client when finished. The launcher stops its associated processes and retains the selected home and recordings.

Desktop needs working Chromium sandbox support. On Ubuntu systems that restrict user namespaces, an unpacked application may need an AppArmor profile for its exact executable path. The [development guide](docs/development.md) describes the VM setup used for testing.

## Explore a recorded run

```bash
./observatory replay ./recordings/RUN_ID
```

Replay also accepts an exported ZIP or a `trace.jsonl` path. It displays full content and reads the recording without changing it.

## Source layout

```text
src/
  launch.py           # Invocation, homes, runs, process lifecycle
  observatory/        # Trace readers, exploration server, browser assets
  scripts/            # Native packaging and assembled release scripts
lib/
  codex/              # Pinned instrumented Codex source
patches/
  desktop/            # Remaining Desktop transforms
tests/
  fixtures/           # Small synthetic recordings
docs/                 # Development process and historical design documents
release.json          # Source, package, patch, and artifact pins
build/                # Ignored runtime, packages, and development evidence
```

The native source keeps CLI, Core, App Server, and capture together in their upstream workspace. The main project owns visualization, rooted launch, and packaging. Recordings use the project's local event log with full payloads.

For a source checkout, initialize the pinned native source with `git submodule update --init --recursive`, then follow the development guide to build the matched runtimes.

See [development and testing](docs/development.md) for the VM build and local-model workflow, and [discussion notes](docs/discussion.md) for the requirements and design decisions. Most earlier documents in [docs](docs/README.md) are historical.
