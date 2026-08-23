# Codex Harness Observatory

This is a research and teaching fork of the open Codex agent harness. Its purpose is to expose the local machinery that turns a task into model sampling, decisions, tool execution, approvals, and coordinated agent work. It does not attempt to expose the model's private reasoning, and it does not instrument the desktop client or app-server protocol layer.

## Source pin

- Upstream tag: `rust-v0.149.0`
- Upstream commit: `758ef40f50c1a458425c7cfbf1eb12cbc07af0b0`
- Workspace version: `0.149.0`
- Rust toolchain: `1.95.0`
- Local baseline tag: `teaching-baseline-v0.149.0`

This repository intentionally has no Git remote. The upstream tag and commit above are the provenance record for the code taught in the course.

## Boundary

The observatory records events inside `codex-core` and at the Core-owned boundaries to model inference, approvals, tools, sandboxes, and child agents. Existing rollout-trace request and response payloads remain the packet-level evidence. New harness events explain why Core moved from one state to another.

Out of scope:

- desktop UI implementation
- app-server startup, transport, and connection mechanics
- private model reasoning performed by the hosted model
- production-grade telemetry retention or compatibility guarantees

## Baseline build

From `codex-rs`:

```bash
cargo build -j 1 -p codex-cli
./target/debug/codex --version
```

The unmodified source pin built successfully on the course machine and reported `codex-cli 0.149.0`. A parallel first build caused a Rust 1.95 LLVM `SIGSEGV`; the serial retry completed successfully. Use `-j 1` for reproducible teaching builds on this machine.

## Trace capture

Set `CODEX_ROLLOUT_TRACE_ROOT` to a writable directory before running the development binary. Each root task creates a trace bundle containing `manifest.json`, `trace.jsonl`, `payloads/`, and, after reduction, `state.json`.

The teaching fork adds a single `harness_event_observed` raw event family. Every event uses the same fields:

- raw sequence and timestamp
- thread and Codex turn IDs
- optional agent-step ID
- category, event name, and phase
- optional outcome and reason
- correlation IDs
- small structured details
- optional references to the existing payload store

This preserves one raw format: fine-grained events can be filtered directly and then reduced or aggregated for lecture views.
