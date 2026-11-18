# Development and testing

This is the local build and test workflow for the refactored Observatory. Use `release.json` for the canonical Core, Desktop, V8, and artifact pins. The execution record below distinguishes verified behavior from remaining limits.

## Standard route

Edit and coordinate on the desktop host. Build and exercise candidate native clients in fresh disposable Linux VMs on Nellodee, selected through the current [agent-vm skill](/home/brooksch/.codex/skills/agent-vm/SKILL.md). The skill owns inventory, host/template selection, limits, pinned SSH access, guest console setup and teardown. Re-read it for each task instead of reusing an old VM address or display command. The maintained source VM and templates are not test guests.

For authenticated model acceptance, copy only the user's file-backed Codex auth cache into separate guest test homes using the helper below. Use the actual OpenAI provider and record the selected model. The historical local-model route below remains a reproduction record; it is not the default and is unnecessary for this route. Retained-recording and deterministic mock-provider checks do not need account credentials.

Keep source, caches, build outputs and evidence in task-owned guest directories. Transfer the candidate checkout including intended untracked files, record its base revision and dirty source digest, and use the exact Core, Desktop and V8 pins from release.json. Run build_v8_binding.py before build_native.sh when a matching binding is unavailable; published bindings and archives are separate inputs. Preserve the generated binding provenance. Reuse the unchanged pinned Desktop archive when only Core or the viewer changes.

The November 16 Ubuntu 26.04 guest used the source-pinned Rust 1.95.0 toolchain with rustfmt, clippy and rust-src, plus cargo-nextest 0.9.152 for `just test`. Its added packages were just, clang, cmake, pkg-config, libssl-dev, libsqlite3-dev, protobuf-compiler, libdbus-1-dev, libudev-dev and libcap-dev. The last is required by the bundled bwrap build. Follow the source toolchain and release pins on later runs rather than treating these observed versions as new pins. The final formatting command also needs the upstream formatting tools, including uv. Build bwrap first and embed that exact helper's digest through build_native.sh; a direct Cargo build that omits the digest is not an acceptance candidate.

Use narrow tests for the changed behavior, followed by one hand-checkable live file edit through the CLI and Desktop when native capture changes. Use the skill's guest console for GUI testing. Keep each client profile separate from source, test workspaces and recordings. Test the exact candidate executables rather than whichever Codex is on PATH. The temporary exact-executable AppArmor profile described below is appropriate only if the guest blocks Chromium sandbox startup.

Before deleting a guest, retrieve the candidate artifacts, source identity, focused test results, recordings and screenshots. Keep credentials and test homes out of those transfers. Delete task-owned disposable VMs through agent-vm and verify removal. A retained guest requires a stated reason and credential cleanup when its test homes are no longer needed.

The current checkout is a local 0.5.0.dev0 development candidate for the DSH-inspired teaching views. The existing 0.4.0 archive and its evidence remain intact. Development artifacts are built into a fresh output directory; no release is published by these checks.

## Authentication for a disposable Nellodee test VM

When a task needs the user's Codex authentication, copy only `auth.json` to a dedicated, short test home in an active disposable Nellodee instance. Use separate homes for CLI and Desktop, for example:

```bash
python3 src/scripts/vm_auth.py INSTANCE /home/codex/.obs-dsh-cli
python3 src/scripts/vm_auth.py INSTANCE /home/codex/.obs-dsh-desktop
```

The source defaults to `$CODEX_HOME/auth.json` when `CODEX_HOME` is set, otherwise `~/.codex/auth.json`; use `--source /path/to/auth.json` to override it. A missing file or keyring-only login requires a file-backed auth cache. The helper checks the managed instance and uses its pinned SSH configuration, sends credentials over SSH stdin, and installs the file with mode 0600 in an owned 0700 home. It does not copy other profile data.

Keep credentials out of templates, source transfers, logs, recordings, and exported artifacts. Delete the task's disposable VM after testing using the agent-vm workflow, which removes its test homes along with the VM. If the VM is explicitly retained, remove the task's credential-bearing homes when they are no longer needed.

## Historical local-model route (November 14)

The following numbered procedure records the earlier vm02/Qwen/vLLM acceptance environment. Its VM addresses, storage paths and capacity observations are historical. For current work, follow the disposable-VM route above and the live skill; do not start or reuse these old domains from this document.

## 1. Prepare the guest source and build storage

Create a fresh task directory below `/srv/observatory-0166/work/`. Put source, build output, caches, temporary files, packages, and test evidence on that disk. Preserve the earlier `source/`, `acceptance/`, `artifacts/`, and retained recordings.

Transfer the exact candidate source, including the instrumented Codex submodule and any intended uncommitted or untracked source changes. Exclude real profiles, recordings, model weights, and unrelated experiments. Record the main revision, submodule revision, dirty changes or source-archive digest, and build commands. A Git revision alone does not identify a dirty checkout.

Use the toolchain and native package recipe belonging to that candidate's release descriptor. vm02's existing `/srv/observatory-0166/build-env.sh` identifies its Cargo/Rustup caches, target directory, linker flags, and pinned V8 inputs. Inspect it as a reference before reuse; its V8 inputs belong to the earlier 0.166 build and must match the selected source.

Keep Cargo targets, compiler caches, and temporary files on the build disk. The executable recipes live in `src/scripts/`; run them from the candidate checkout. The native script builds `bwrap`, supplies its digest, builds Core and both companion executables, and packages the result.

For the selected release, generate the matching V8 binding before building. The published V8 static archive and the generated binding are separate inputs: an earlier release's binding is not interchangeable. `build_v8_binding.py` checks the pinned upstream source and Bazel inputs; retain its provenance report. Set `RUSTY_V8_ARCHIVE` and `RUSTY_V8_SRC_BINDING_PATH` to these exact files. When establishing a new release, a null binding pin permits the initial generation and reports the measured hash; pin that hash before the native build.

```bash
python3 src/scripts/build_v8_binding.py --help
src/scripts/build_native.sh

src/scripts/build_desktop.sh \
  --upstream-deb /absolute/path/to/official-package.deb \
  --archive /absolute/path/to/desktop-archive.tar.gz \
  --work-parent /srv/observatory-0166/work/dev-001/tmp

python3 src/scripts/finalize_release.py --help
python3 src/scripts/assemble_release.py \
  --core /absolute/path/to/core-archive.tar.gz \
  --desktop /absolute/path/to/desktop-archive.tar.gz \
  --output-dir /srv/observatory-0166/work/dev-001/assembled
```

The Desktop recipe validates the official package, applies the two pinned transformations, and creates a separate relocatable application. Its bundled Core version is recorded independently; our launcher routes its app-server connection through the instrumented Core. Do not assume the two version strings are identical.

Finalize the actual archive hashes with `finalize_release.py` before assembly. The assembler requires those pinned hashes and creates one learner archive containing the launcher, Observatory sources and documentation, and both native runtimes. It does not include profiles, recordings, models, or a native build checkout. Extract it in task-owned storage to test the same entrypoint learners will use.

Follow the native submodule's `AGENTS.md` for scoped tests and formatting. Use `just test`, not direct `cargo test`. Obtain the required user approval before the complete Rust workspace suite; a failed focused test permits debugging that path, not an automatic full run.

The full `just fmt` command also needs `uv` and `dotslash` on PATH for upstream Python and Bazel formatting. The VM's Cargo build environment alone does not provide them. In this run, copies of the host tools were placed in the task's `tools/` directory and prepended to PATH; UV and XDG caches stayed on the build disk.

## 2. Start the host model backend

Use one declared small-model baseline for plumbing tests. The baseline is [Qwen/Qwen3.5-4B](https://huggingface.co/Qwen/Qwen3.5-4B), with its documented reasoning and tool-call parsers. This choice is a lightweight test dependency, not a claim about teaching-model quality or compatibility with every Codex feature.

Test backend pins:

| Input | Value |
| --- | --- |
| Model | Qwen/Qwen3.5-4B |
| Model/tokenizer revision | 851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a |
| vLLM image | vllm/vllm-openai@sha256:902b49de0568ba5a5c951b0243bc06ef8541f46bc3eb80832961fefb22a19034 |
| Served model name | observatory-test |
| Server context limit | 32768 tokens |
| Concurrent sequences | 2 |
| Host endpoint | http://127.0.0.1:18000/v1 |

The image and selected model were cached during the November 14 run. The model cache is `/opt1/cache/observatory/huggingface`. Check availability again on another machine or after cache maintenance. Do not substitute a different model silently.

After checking free GPU memory and the port, start a task-owned container. Use a unique container name and record it:

```bash
obs_task_id=dev-001
obs_vllm_container="observatory-vllm-$obs_task_id"
obs_model_cache=/opt1/cache/observatory/huggingface
obs_model_revision=851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a
obs_vllm_image=vllm/vllm-openai@sha256:902b49de0568ba5a5c951b0243bc06ef8541f46bc3eb80832961fefb22a19034

mkdir -p "$obs_model_cache"

docker run -d --name "$obs_vllm_container" --init \
  --gpus all --ipc=host \
  -p 127.0.0.1:18000:8000 \
  --mount "type=bind,src=$obs_model_cache,dst=/root/.cache/huggingface" \
  --entrypoint vllm \
  "$obs_vllm_image" serve Qwen/Qwen3.5-4B \
  --revision "$obs_model_revision" \
  --tokenizer-revision "$obs_model_revision" \
  --served-model-name observatory-test \
  --host 0.0.0.0 --port 8000 \
  --dtype bfloat16 \
  --max-model-len 32768 --max-num-seqs 2 \
  --gpu-memory-utilization 0.25 \
  --reasoning-parser qwen3 \
  --enable-auto-tool-choice --tool-call-parser qwen3_coder
```

The container listens internally on all interfaces, while Docker publishes only host loopback. Check startup logs and readiness with bounded waits. A name or port collision is a reason to inspect ownership, not remove another container.

The 32K window is deliberately bounded for short tests. It is not a long-context evaluation. Record the actual server limit and keep client metadata consistent with it. A larger client-side number cannot increase the server's limit.

## 3. Verify the API, then connect the VM

Codex needs a compatible Responses API and tool calling. vLLM documents this integration, but exact candidate compatibility must be demonstrated with the selected binary and request shapes. A successful `/v1/models` or Chat Completions request is insufficient. [vLLM Codex integration](https://docs.vllm.ai/en/latest/serving/integrations/codex/)

Check the host endpoint:

```bash
curl --fail --max-time 10 http://127.0.0.1:18000/health
curl --fail --max-time 10 http://127.0.0.1:18000/v1/models
curl --fail --max-time 120 http://127.0.0.1:18000/v1/responses \
  -H 'Content-Type: application/json' \
  --data '{"model":"observatory-test","input":"Reply with OBSERVATORY_READY.","max_output_tokens":2048}'
```

Inspect the returned status and output. Also exercise one Responses function-call/output/final-answer round trip, then a streamed response. Require structured tool calls with usable arguments, not tool tags embedded in ordinary text. The actual Codex smoke below must cover its native tool shapes, which can include more than simple function tools. [vLLM Responses tool example](https://docs.vllm.ai/en/latest/examples/tool_calling/openai_responses_client_with_tools/)

From the host, keep this reverse tunnel running during the test:

```bash
ssh -N -T \
  -o BatchMode=yes -o ExitOnForwardFailure=yes \
  -o ServerAliveInterval=30 \
  -R 127.0.0.1:18000:127.0.0.1:18000 \
  codex@141.213.182.177
```

Then verify from inside the guest:

```bash
curl --fail --max-time 10 http://127.0.0.1:18000/v1/models
```

The reverse tunnel makes the host server available on guest loopback. It avoids depending on guest-to-host bridge addressing or opening a host LAN listener. Save the tunnel process identity for cleanup. If the guest port is already owned by another service, preserve it and choose a free guest port; update the test configuration to match. The November 14 run used guest port 18001 forwarding to host port 18000.

If the selected vLLM build rejects Codex's request or tool format, stop live acceptance and report the incompatibility. Do not disable native behavior, fabricate events, or quietly insert a different API adapter to make the test pass. Revise and document the single test baseline if a different model/version is needed.

## 4. Create the guest Codex homes

Create fresh, short, task-specific homes under `/home/codex/.observatory/profiles/`. Use separate homes for the CLI and Desktop smoke so each starts with known state. Copy the same minimal `config.toml` into each:

```toml
model = "observatory-test"
model_provider = "observatory_vllm"
model_context_window = 32768

[model_providers.observatory_vllm]
name = "Observatory local vLLM"
base_url = "http://127.0.0.1:18000/v1"
wire_api = "responses"
requires_openai_auth = false
supports_websockets = false
```

Inference through this loopback provider requires no OpenAI credentials. Desktop may still have a separate first-run sign-in or setup requirement; verify that through its normal UI and report any prerequisite that prevents autonomous acceptance. The model name matches the server alias. Use the candidate's native provider configuration; do not patch model routing for testing. [Codex custom providers](https://learn.chatgpt.com/docs/config-file/config-advanced#custom-model-providers)

Copy this configuration into the guest before launching. Keep permissions, feature settings, and MCP configuration at native defaults unless the changed behavior requires a specific setting; record any such setting explicitly. A fresh custom-provider CLI profile can start read-only. For the file-edit scenario, select the native `/permissions` option "Ask for approval" and wait for it to take effect before the edit turn. Do not bypass the native permission system. Add only the synthetic local MCP fixture when testing MCP behavior.

Keep test inputs in a disposable guest workspace, separate from the source checkout and Codex home. Keep Desktop application data, services, and IPC scoped to the selected test home. Do not import the daily host profile or host browser connection.

## 5. Build and check the changed path

Run the focused checks required by the changed code. For changes shared by capture or launch, exercise the same bounded scenario once through the CLI and once through Desktop. For a reader-only or UI-only change, an existing recording or synthetic fixture can be sufficient; starting a model is unnecessary.

Use one hand-checkable task: prepare a small text file, ask Codex to read it and change one known word, and verify the result on disk. Inspect the recording for the prompt, actual model request/response, tool arguments/results, relevant execution events, and correct identities. Keep failure outcomes visible.

Run the launcher inside the guest from the disposable workspace. From an extracted learner archive, use its absolute `observatory` path:

```bash
observatory --client cli \
  --codex-home /home/codex/.observatory/profiles/dev-cli \
  --runs-dir /srv/observatory-0166/work/dev-001/runs

observatory --client desktop \
  --codex-home /home/codex/.observatory/profiles/dev-desktop \
  --runs-dir /srv/observatory-0166/work/dev-001/runs
```

Replace example names with fresh task-specific names. The launcher must execute the candidate artifacts built for this task; check resolved executable paths and versions instead of relying on `PATH`.

For the Desktop route, first run the guest `cua-display doctor` and discover the required CUA tool schemas using the agent-vm skill. Source `/home/codex/bin/agent-display-env` in the guest before starting GUI commands. Use guest-local CUA and screenshots to verify the real Desktop and Observatory windows. A raw SSH shell does not inherit that display's Xauthority or session bus.

Ubuntu's AppArmor user-namespace policy can block an unpacked Electron executable before it opens. In the disposable VM, load a temporary profile attached to the exact candidate `ChatGPT` executable, using the same `flags=(unconfined) { userns, }` form as the installed Chromium/VS Code policies. Keep the policy in the task directory, load it with `sudo apparmor_parser -r FILE`, and remove it with `sudo apparmor_parser -R FILE` after the client stops. This permits Chromium to create its sandbox; do not pass `--no-sandbox` or disable the VM's global policy.

Do not use host GUI automation or SSH X11 forwarding. This standard GUI test uses the guest's software-rendered private display; it does not establish physical-GPU rendering behavior.

Check the material property affected by the change:

- Invocation changes: selected home, retained state, new run directory, and shutdown ownership.
- Capture changes: complete referenced payloads, event correlations, ordering, and reported collection health.
- Instrumentation changes: native prompts, decisions, and execution behavior remain unchanged, using a focused fixture or mocked comparison where practical.
- UI changes: the relevant evidence is readable and accessible in the actual browser view.
- Recorded viewing: stop the model/client, reopen the retained evidence, and confirm viewing does not modify it.

Extend the scenario with a child agent, MCP call, compaction, or overlapping roots only when that is the changed behavior. A small-model failure does not by itself prove a telemetry defect, and a successful simple task does not establish broad model or Desktop feature parity.

## 6. Retain evidence and clean up

Keep the source identity, build commands and artifact hashes, model/image pins, actual server options, effective test configuration, VM identity, scenario and outcome, full run bundle, and any relevant screenshot or failure log in the task's evidence directory. Report what was checked and what remains unverified.

Stop the processes created for this task using their recorded identities. Save vLLM logs before removing its container. Close the reverse tunnel, verify the candidate's owned descendants and sockets have stopped, and preserve the recording and test configuration. Stop the task-owned model container when it is no longer needed; preserve any endpoint that was already running before the task. Unload any temporary exact-executable AppArmor profile after its client stops. Restore a VM's original power state when this task booted it.

Do not use broad process-name kills, purge shared caches, or delete earlier acceptance artifacts. Do not replace the daily Desktop or publish a release as a side effect of testing.

## November 14 execution record

The refactor candidate used the stable Core and Desktop pins in `release.json`. Source and build work stayed under `/srv/observatory-0166/work/refactor-20261114` on vm02. The host ran the pinned Qwen/vLLM backend through a task-owned container and an SSH tunnel on guest port 18001. No daily Codex profile or host Desktop installation was used.

Verified:

- The pinned backend served Responses, a structured function-call/output/final-answer round trip, and streaming. Actual Codex tool requests also worked.
- The matching V8 binding was generated from pinned upstream source, then Core, code-mode host, exec server, and bwrap built successfully. Native archive packaging and the patched Desktop archive build succeeded.
- CLI and Desktop each read `lesson.txt`, changed BLUE to GREEN, and read the actual file back. The file on disk matched `The observatory marker is GREEN.\n` in both workspaces.
- Both recordings ended cleanly with all referenced payloads present: CLI had 3,233 log records and 995 payloads; Desktop had 2,174 records and 732 payloads. The final recording-completed record is outside the manifest's events-written count. Prompt content, tool arguments, and the returned file content were checked in the retained payloads.
- The live Desktop trace rendered in the guest browser. Desktop state persisted across relaunches, each invocation received its own run, and the native client and launcher exited normally.
- After both clients and the model stopped, the retained Desktop run replayed from a different working directory with no PYTHONPATH. The server returned its page, JavaScript, the actual GREEN tool-result payload, and a complete recorded stream. Every recording file had the same hash before and after replay.
- All 88 trace-crate tests and 557 MCP/App Server transport tests passed. A focused Core/App Server/CLI/MCP run passed 1,126 of 1,129 tests. The three failures were unchanged upstream assumptions: two doctor snapshots expect the development version string `v0.0.0`, and a daemon bootstrap fixture assumes omitted auto-update configuration defaults to false.
- The migrated viewer/archive/comparison checks, launcher checks, and installed-wheel portable replay check passed. Source launcher verification uses `PYTHONPATH=src python3 -m pytest tests/test_launcher.py -q`.
- Required scoped `just fix` runs completed for the changed crates, followed by the full `just fmt` command. The two Rust lint fixes were incorporated before the final native package build. Tests were not repeated solely after formatting.

The first Desktop attempt exposed Ubuntu's user-namespace restriction; an exact-executable temporary AppArmor profile permitted Chromium sandboxing. A later native folder-picker crash exposed missing glycin loader definitions in the isolated GTK tree; the launcher now copies those definitions for new and existing profiles, and the real folder picker succeeded after that correction.

This is a short plumbing test with one local model. Desktop also made six background requests for `gpt-6-luna`, which the single-alias test backend correctly rejected with HTTP 404. Those failures remain in the trace. The requested workspace edit used `observatory-test` and succeeded; this does not establish all Desktop background features or broad model compatibility. No complete Rust workspace suite or macOS/Windows native capture run was performed.

The task's build outputs, full recordings, logs, screenshots, and machine-readable check results are retained under the guest task directory and the host checkout's ignored `build/evidence/` directory. The resulting candidate is for local review; no Observatory release was published.
