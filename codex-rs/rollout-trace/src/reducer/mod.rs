//! Deterministic replay from raw trace events to `RolloutTrace`.

use std::collections::BTreeMap;
use std::fs::File;
use std::io::BufRead;
use std::io::BufReader;
use std::path::Path;
use std::path::PathBuf;

use anyhow::Context;
use anyhow::Result;
use anyhow::bail;
use serde_json::Value;

use crate::bundle::MANIFEST_FILE_NAME;
use crate::bundle::RAW_EVENT_LOG_FILE_NAME;
use crate::bundle::REDUCED_TRACE_SCHEMA_VERSION;
use crate::bundle::TraceBundleManifest;
use crate::model::ExecutionStatus;
use crate::model::RolloutTrace;
use crate::payload::RawPayloadRef;
use crate::raw_event::RAW_TRACE_EVENT_SCHEMA_VERSION;
use crate::raw_event::RawTraceEvent;
use crate::raw_event::RawTraceEventPayload;

mod code_cell;
mod compaction;
mod conversation;
mod inference;
#[cfg(test)]
pub(crate) mod test_support;
mod thread;
mod tool;

use self::code_cell::PendingCodeCellLifecycleEvent;
use self::code_cell::PendingCodeCellStart;
use self::code_cell::StartedCodeCell;
use self::compaction::StartedCompactionRequest;
use self::inference::StartedInferenceCall;
use self::tool::ObservedAgentResultEdge;
use self::tool::PendingAgentInteractionEdge;
use self::tool::ToolCallStarted;

/// Replays a local trace bundle into a reduced rollout graph.
pub fn replay_bundle(bundle_dir: impl AsRef<Path>) -> Result<RolloutTrace> {
    let bundle_dir = bundle_dir.as_ref();
    let manifest: TraceBundleManifest =
        serde_json::from_reader(File::open(bundle_dir.join(MANIFEST_FILE_NAME))?)
            .with_context(|| format!("read {}", bundle_dir.join(MANIFEST_FILE_NAME).display()))?;
    let mut reducer = TraceReducer {
        rollout: RolloutTrace::new(
            REDUCED_TRACE_SCHEMA_VERSION,
            manifest.trace_id,
            manifest.rollout_id,
            manifest.root_thread_id,
            manifest.started_at_unix_ms,
            manifest.shared_run,
        ),
        bundle_dir: bundle_dir.to_path_buf(),
        next_conversation_item_ordinal: 1,
        next_terminal_operation_ordinal: 1,
        thread_conversation_snapshots: BTreeMap::new(),
        pending_compaction_replacement_item_ids: BTreeMap::new(),
        code_cell_ids_by_runtime: BTreeMap::new(),
        pending_code_cell_starts: BTreeMap::new(),
        pending_code_cell_lifecycle_events: BTreeMap::new(),
        pending_agent_interaction_edges: Vec::new(),
        next_raw_event_seq: 1,
        run_started_seen: false,
        run_ended_seen: false,
        task_roots_by_thread_id: BTreeMap::new(),
    };

    let event_log_path = bundle_dir.join(RAW_EVENT_LOG_FILE_NAME);
    let event_log = File::open(&event_log_path)
        .with_context(|| format!("open trace event log {}", event_log_path.display()))?;
    for (line_index, line) in BufReader::new(event_log).lines().enumerate() {
        let line = line.with_context(|| format!("read trace event line {}", line_index + 1))?;
        if line.trim().is_empty() {
            continue;
        }
        let event: RawTraceEvent = serde_json::from_str(&line)
            .with_context(|| format!("parse trace event line {}", line_index + 1))?;
        reducer.apply_event(event)?;
    }
    // Spawn edges prefer the child task message as their target, but a child can
    // fail before that message is ever reduced. Only after replaying the whole
    // bundle do we know which spawn deliveries need the child-thread fallback.
    reducer.resolve_pending_spawn_edge_fallbacks()?;

    Ok(reducer.rollout)
}

struct TraceReducer {
    rollout: RolloutTrace,
    bundle_dir: PathBuf,
    next_conversation_item_ordinal: u64,
    next_terminal_operation_ordinal: u64,
    /// Last model-visible conversation snapshot per thread.
    ///
    /// Requests and responses both advance this sequence because both are
    /// model-facing payloads. Repeated request snapshots reuse item IDs only
    /// when the same normalized item appears at the same position; identical
    /// content at a new position must remain a distinct conversation item.
    thread_conversation_snapshots: BTreeMap<String, Vec<String>>,
    /// Replacement snapshot installed by compaction but not yet seen in a sampling request.
    ///
    /// The first full request after compaction should compare against the installed replacement
    /// history, not against the pre-compaction request. That keeps repeated prefix/context messages
    /// as fresh post-compaction conversation items while still reusing the summary/replacement
    /// items that actually became live history.
    pending_compaction_replacement_item_ids: BTreeMap<String, Vec<String>>,
    /// Runtime cell ids indexed by thread-local code-mode handle.
    ///
    /// Reduced `CodeCellId`s are based on the model-visible `exec` call id
    /// because that is the durable source identity. Runtime lifecycle, nested
    /// tools, and `wait` calls arrive with the runtime-local `cell_id`, so this
    /// index is the one intentional bridge between those namespaces.
    code_cell_ids_by_runtime: BTreeMap<(String, String), String>,
    /// Code-cell starts whose model-visible `custom_tool_call` item has not
    /// been reduced yet.
    ///
    /// Core begins executing tools before the stream-completion hook records
    /// the response payload that requested them. Queueing keeps replay strict
    /// about eventual source-item ownership without requiring trace producers
    /// to reorder runtime events behind inference completion.
    pending_code_cell_starts: BTreeMap<String, PendingCodeCellStart>,
    /// Initial/end events that arrived while the matching start was queued.
    ///
    /// Fast cells can return before the inference response payload that proves
    /// the model-visible `exec` source item has been reduced. The start remains
    /// queued for ownership validation; these lifecycle events wait with it and
    /// are replayed in raw sequence order once the cell materializes.
    pending_code_cell_lifecycle_events: BTreeMap<String, Vec<PendingCodeCellLifecycleEvent>>,
    /// Multi-agent deliveries whose recipient-side transcript item has not been observed yet.
    ///
    /// V2 agent tools enqueue mailbox messages in the target thread. The trace event for the
    /// sending tool arrives before the recipient inference request materializes that mailbox item
    /// as a `ConversationItem`, so the reducer keeps the delivery edge pending until it can point
    /// at the exact model-visible item instead of a coarse thread.
    pending_agent_interaction_edges: Vec<PendingAgentInteractionEdge>,
    /// Next contiguous raw sequence number expected from the one writer.
    next_raw_event_seq: u64,
    /// Shared and standalone lifecycle starts are optional only for legacy
    /// hand-assembled fixtures, but never repeat within a real bundle.
    run_started_seen: bool,
    /// A trace may be replayed while running, so no terminal event is required.
    /// When one exists, the run authority may emit it only once.
    run_ended_seen: bool,
    /// Task root inherited by every started thread in a shared run.
    task_roots_by_thread_id: BTreeMap<String, String>,
}

impl TraceReducer {
    fn read_payload_json(&self, payload: &RawPayloadRef) -> Result<Value> {
        // Reducers keep raw bodies out of the graph, but typed replay sometimes
        // needs a small subset of fields to build semantic objects.
        let payload_path = self.bundle_dir.join(&payload.path);
        let file = File::open(&payload_path)
            .with_context(|| format!("open payload {}", payload.raw_payload_id))?;
        serde_json::from_reader(file)
            .with_context(|| format!("parse payload {}", payload.raw_payload_id))
    }

    fn apply_event(&mut self, event: RawTraceEvent) -> Result<()> {
        self.validate_event_envelope(&event)?;
        let task_root_thread_id = event.task_root_thread_id.clone();
        // Raw payload refs are reducer-wide evidence, not owned by a single
        // semantic arm. Keep this bookkeeping separate so typed reduction can
        // stay strict without duplicating payload insertion in every case.
        for payload in event.payload.raw_payload_refs() {
            self.insert_raw_payload(payload);
        }

        match event.payload {
            RawTraceEventPayload::RunStarted { trace_id } => {
                self.rollout.trace_id = trace_id;
                self.rollout.shared_run = true;
            }
            RawTraceEventPayload::RunEnded { status } => {
                self.rollout.status = status;
                self.rollout.ended_at_unix_ms = Some(event.wall_time_unix_ms);
            }
            RawTraceEventPayload::RolloutStarted {
                trace_id,
                root_thread_id,
            } => {
                self.rollout.trace_id = trace_id;
                self.rollout.root_thread_id = root_thread_id;
                self.rollout.shared_run = false;
                if !self
                    .rollout
                    .task_root_thread_ids
                    .contains(&self.rollout.root_thread_id)
                {
                    self.rollout
                        .task_root_thread_ids
                        .push(self.rollout.root_thread_id.clone());
                }
            }
            RawTraceEventPayload::RolloutEnded { status } => {
                self.rollout.status = status;
                self.rollout.ended_at_unix_ms = Some(event.wall_time_unix_ms);
            }
            RawTraceEventPayload::ThreadStarted {
                thread_id,
                agent_path,
                metadata_payload,
            } => {
                let started_thread_id = thread_id.clone();
                let event_thread_id = event.thread_id.clone();
                self.start_thread(
                    event.seq,
                    event.wall_time_unix_ms,
                    thread_id,
                    agent_path,
                    metadata_payload,
                )?;
                self.register_task_root_for_thread(
                    task_root_thread_id,
                    event_thread_id,
                    started_thread_id,
                )?;
            }
            RawTraceEventPayload::ThreadEnded { thread_id, status } => {
                self.end_thread(event.seq, event.wall_time_unix_ms, thread_id, status)?;
            }
            RawTraceEventPayload::CodexTurnStarted {
                codex_turn_id,
                thread_id,
            } => {
                self.start_codex_turn(
                    event.seq,
                    event.wall_time_unix_ms,
                    codex_turn_id,
                    thread_id,
                )?;
            }
            RawTraceEventPayload::CodexTurnEnded {
                codex_turn_id,
                status,
            } => {
                self.end_codex_turn(
                    event.seq,
                    event.wall_time_unix_ms,
                    event.thread_id,
                    codex_turn_id,
                    status,
                )?;
            }
            RawTraceEventPayload::InferenceStarted {
                inference_call_id,
                thread_id,
                codex_turn_id,
                model,
                provider_name,
                request_payload,
            } => {
                self.start_inference_call(
                    event.seq,
                    event.wall_time_unix_ms,
                    StartedInferenceCall {
                        inference_call_id,
                        thread_id,
                        codex_turn_id,
                        model,
                        provider_name,
                        request_payload,
                    },
                )?;
            }
            payload @ (RawTraceEventPayload::InferenceCompleted { .. }
            | RawTraceEventPayload::InferenceFailed { .. }
            | RawTraceEventPayload::InferenceCancelled { .. }) => {
                self.complete_inference_call(event.seq, event.wall_time_unix_ms, payload)?;
            }
            RawTraceEventPayload::ProtocolEventObserved { .. }
            | RawTraceEventPayload::AppServerFrameObserved { .. }
            | RawTraceEventPayload::McpFrameObserved { .. } => {
                // Protocol wrappers are raw debug breadcrumbs. Typed hooks own
                // the reduced graph, so these payload refs are retained without
                // creating semantic objects.
            }
            RawTraceEventPayload::HarnessEventObserved {
                event: harness_event,
            } => {
                self.rollout
                    .harness_events
                    .push(crate::HarnessEvent::from_raw(
                        event.seq,
                        event.wall_time_unix_ms,
                        event.task_root_thread_id,
                        event.thread_id,
                        event.codex_turn_id,
                        harness_event,
                    ));
            }
            RawTraceEventPayload::ToolCallStarted {
                tool_call_id,
                model_visible_call_id,
                code_mode_runtime_tool_id,
                requester,
                kind,
                summary,
                invocation_payload,
            } => {
                self.start_tool_call(
                    event.seq,
                    event.wall_time_unix_ms,
                    event.thread_id,
                    event.codex_turn_id,
                    ToolCallStarted {
                        tool_call_id,
                        model_visible_call_id,
                        code_mode_runtime_tool_id,
                        requester,
                        kind,
                        summary,
                        invocation_payload,
                    },
                )?;
            }
            RawTraceEventPayload::McpToolCallCorrelationAssigned {
                tool_call_id,
                mcp_call_id,
            } => {
                self.assign_mcp_tool_call_correlation(tool_call_id, mcp_call_id)?;
            }
            RawTraceEventPayload::ToolCallRuntimeStarted {
                tool_call_id,
                runtime_payload,
            } => {
                self.start_tool_runtime_observation(
                    event.seq,
                    event.wall_time_unix_ms,
                    tool_call_id,
                    runtime_payload,
                )?;
            }
            RawTraceEventPayload::ToolCallRuntimeEnded {
                tool_call_id,
                status,
                runtime_payload,
            } => {
                self.end_tool_runtime_observation(
                    event.seq,
                    event.wall_time_unix_ms,
                    tool_call_id,
                    status,
                    runtime_payload,
                )?;
            }
            RawTraceEventPayload::ToolCallEnded {
                tool_call_id,
                status,
                result_payload,
            } => {
                self.end_tool_call(
                    event.seq,
                    event.wall_time_unix_ms,
                    tool_call_id,
                    status,
                    result_payload,
                )?;
            }
            RawTraceEventPayload::CodeCellStarted {
                runtime_cell_id,
                model_visible_call_id,
                source_js,
            } => {
                let thread_id = self.code_cell_event_thread_id(
                    event.thread_id,
                    event.codex_turn_id.as_deref(),
                    &runtime_cell_id,
                    "code cell start",
                )?;
                let reduced_code_cell_id =
                    self.reduced_code_cell_id_for_model_visible_call(&model_visible_call_id);
                self.record_runtime_code_cell_id(
                    &thread_id,
                    &runtime_cell_id,
                    &reduced_code_cell_id,
                )?;
                self.start_or_queue_code_cell(PendingCodeCellStart {
                    seq: event.seq,
                    wall_time_unix_ms: event.wall_time_unix_ms,
                    thread_id,
                    codex_turn_id: event.codex_turn_id,
                    started: StartedCodeCell {
                        code_cell_id: reduced_code_cell_id,
                        runtime_cell_id,
                        model_visible_call_id,
                        source_js,
                    },
                })?;
            }
            RawTraceEventPayload::CodeCellInitialResponse {
                runtime_cell_id,
                status,
                ..
            } => {
                let thread_id = self.code_cell_event_thread_id(
                    event.thread_id,
                    event.codex_turn_id.as_deref(),
                    &runtime_cell_id,
                    "code cell initial response",
                )?;
                let code_cell_id = self.code_cell_id_for_runtime_cell_id(
                    &thread_id,
                    &runtime_cell_id,
                    "code cell initial response",
                )?;
                self.record_or_queue_code_cell_initial_response(
                    event.seq,
                    event.wall_time_unix_ms,
                    code_cell_id,
                    runtime_cell_id,
                    status,
                )?;
            }
            RawTraceEventPayload::CodeCellEnded {
                runtime_cell_id,
                status,
                ..
            } => {
                let thread_id = self.code_cell_event_thread_id(
                    event.thread_id,
                    event.codex_turn_id.as_deref(),
                    &runtime_cell_id,
                    "code cell end",
                )?;
                let code_cell_id = self.code_cell_id_for_runtime_cell_id(
                    &thread_id,
                    &runtime_cell_id,
                    "code cell end",
                )?;
                self.end_or_queue_code_cell(
                    event.seq,
                    event.wall_time_unix_ms,
                    code_cell_id,
                    status,
                )?;
            }
            RawTraceEventPayload::CompactionRequestStarted {
                compaction_id,
                compaction_request_id,
                thread_id,
                codex_turn_id,
                model,
                provider_name,
                request_payload,
            } => {
                self.start_compaction_request(
                    event.seq,
                    event.wall_time_unix_ms,
                    StartedCompactionRequest {
                        compaction_id,
                        compaction_request_id,
                        thread_id,
                        codex_turn_id,
                        model,
                        provider_name,
                        request_payload,
                    },
                )?;
            }
            RawTraceEventPayload::CompactionRequestCompleted {
                compaction_id,
                compaction_request_id,
                response_payload,
            } => {
                self.complete_compaction_request(
                    event.seq,
                    event.wall_time_unix_ms,
                    compaction_id,
                    compaction_request_id,
                    ExecutionStatus::Completed,
                    Some(response_payload),
                )?;
            }
            RawTraceEventPayload::CompactionRequestFailed {
                compaction_id,
                compaction_request_id,
                ..
            } => {
                self.complete_compaction_request(
                    event.seq,
                    event.wall_time_unix_ms,
                    compaction_id,
                    compaction_request_id,
                    ExecutionStatus::Failed,
                    /*response_payload*/ None,
                )?;
            }
            RawTraceEventPayload::CompactionInstalled {
                compaction_id,
                checkpoint_payload,
            } => {
                let Some(thread_id) = event.thread_id else {
                    bail!("compaction installed event {compaction_id} did not include a thread id");
                };
                let Some(codex_turn_id) = event.codex_turn_id else {
                    bail!(
                        "compaction installed event {compaction_id} did not include a codex turn id"
                    );
                };
                self.reduce_compaction_installed_event(
                    event.wall_time_unix_ms,
                    thread_id,
                    codex_turn_id,
                    compaction_id,
                    checkpoint_payload,
                )?;
            }
            RawTraceEventPayload::AgentResultObserved {
                edge_id,
                child_thread_id,
                child_codex_turn_id,
                parent_thread_id,
                message,
                carried_payload,
            } => {
                self.queue_agent_result_interaction_edge(ObservedAgentResultEdge {
                    wall_time_unix_ms: event.wall_time_unix_ms,
                    edge_id,
                    child_thread_id,
                    child_codex_turn_id,
                    parent_thread_id,
                    message,
                    carried_payload,
                })?;
            }
            RawTraceEventPayload::Other { .. } => {
                bail!("raw trace event has no reducer implementation");
            }
        }

        Ok(())
    }

    fn insert_raw_payload(&mut self, payload: &RawPayloadRef) {
        self.rollout
            .raw_payloads
            .insert(payload.raw_payload_id.clone(), payload.clone());
    }

    fn validate_event_envelope(&mut self, event: &RawTraceEvent) -> Result<()> {
        if event.schema_version == 0 || event.schema_version > RAW_TRACE_EVENT_SCHEMA_VERSION {
            bail!(
                "unsupported raw trace event schema version {} at seq {}",
                event.schema_version,
                event.seq
            );
        }
        if event.rollout_id != self.rollout.rollout_id {
            bail!(
                "raw trace event seq {} belongs to rollout {}, expected {}",
                event.seq,
                event.rollout_id,
                self.rollout.rollout_id
            );
        }
        if event.seq != self.next_raw_event_seq {
            bail!(
                "raw trace event sequence is not contiguous: expected {}, found {}",
                self.next_raw_event_seq,
                event.seq
            );
        }
        self.next_raw_event_seq += 1;

        match &event.payload {
            RawTraceEventPayload::RunStarted { .. }
            | RawTraceEventPayload::RolloutStarted { .. } => {
                if self.run_started_seen {
                    bail!("duplicate trace run start event at seq {}", event.seq);
                }
                self.run_started_seen = true;
            }
            RawTraceEventPayload::RunEnded { .. } | RawTraceEventPayload::RolloutEnded { .. } => {
                if self.run_ended_seen {
                    bail!("duplicate trace run end event at seq {}", event.seq);
                }
                self.run_ended_seen = true;
            }
            _ => {}
        }

        let Some(thread_id) = event.thread_id.as_deref() else {
            return Ok(());
        };
        let Some(expected_task_root_thread_id) = self.task_roots_by_thread_id.get(thread_id) else {
            return Ok(());
        };
        match event.task_root_thread_id.as_deref() {
            Some(task_root_thread_id) if task_root_thread_id == expected_task_root_thread_id => {
                Ok(())
            }
            Some(task_root_thread_id) => bail!(
                "raw trace event seq {} used task root {} for thread {}, expected {}",
                event.seq,
                task_root_thread_id,
                thread_id,
                expected_task_root_thread_id
            ),
            None if matches!(
                &event.payload,
                RawTraceEventPayload::AppServerFrameObserved { .. }
                    | RawTraceEventPayload::McpFrameObserved { .. }
            ) =>
            {
                Ok(())
            }
            // Schema versions before task-root attribution and hand-built
            // fixtures remain replayable. New production contexts populate it.
            None => Ok(()),
        }
    }

    fn register_task_root_for_thread(
        &mut self,
        task_root_thread_id: Option<String>,
        event_thread_id: Option<String>,
        started_thread_id: String,
    ) -> Result<()> {
        if let Some(event_thread_id) = event_thread_id
            && event_thread_id != started_thread_id
        {
            bail!(
                "thread start payload used {started_thread_id}, but its event envelope used {event_thread_id}"
            );
        }
        let Some(task_root_thread_id) = task_root_thread_id else {
            return Ok(());
        };
        let thread = self
            .rollout
            .threads
            .get(&started_thread_id)
            .with_context(|| format!("missing started thread {started_thread_id}"))?;
        match &thread.origin {
            crate::model::AgentOrigin::Root => {
                if task_root_thread_id != started_thread_id {
                    bail!("root thread {started_thread_id} used task root {task_root_thread_id}");
                }
            }
            crate::model::AgentOrigin::Spawned {
                parent_thread_id, ..
            } => {
                let parent_task_root_thread_id = self
                    .task_roots_by_thread_id
                    .get(parent_thread_id)
                    .with_context(|| {
                        format!(
                            "spawned thread {started_thread_id} started before parent {parent_thread_id} had task-root attribution"
                        )
                    })?;
                if task_root_thread_id != *parent_task_root_thread_id {
                    bail!(
                        "spawned thread {started_thread_id} used task root {task_root_thread_id}, but parent {parent_thread_id} uses {parent_task_root_thread_id}"
                    );
                }
            }
        }
        if !self
            .rollout
            .task_root_thread_ids
            .contains(&task_root_thread_id)
        {
            self.rollout
                .task_root_thread_ids
                .push(task_root_thread_id.clone());
        }
        self.task_roots_by_thread_id
            .insert(started_thread_id, task_root_thread_id);
        Ok(())
    }
}
