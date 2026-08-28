//! Thread-scoped rollout trace helpers.
//!
//! A rollout bundle can contain a root thread plus spawned child threads. This
//! context owns the stable identity for one thread inside that bundle. Keeping
//! thread-local event methods here avoids repeatedly plumbing `thread_id`
//! through session code.

use codex_protocol::protocol::AgentStatus;
use codex_protocol::protocol::EventMsg;
use codex_protocol::protocol::SessionSource;
use serde::Serialize;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use tracing::debug;
use tracing::warn;
use uuid::Uuid;

use crate::AgentThreadId;
use crate::CodeCellTraceContext;
use crate::CodexTurnId;
use crate::CompactionId;
use crate::CompactionTraceContext;
use crate::HarnessStepId;
use crate::HarnessTraceEvent;
use crate::InferenceTraceContext;
use crate::McpCallTraceContext;
use crate::McpWireTaskContext;
use crate::RawPayloadKind;
use crate::RawPayloadRef;
use crate::RawTraceEventContext;
use crate::RawTraceEventPayload;
use crate::RolloutStatus;
use crate::ToolCallId;
use crate::ToolDispatchInvocation;
use crate::ToolDispatchTraceContext;
use crate::TraceWriter;
use crate::protocol_event::codex_turn_trace_event;
use crate::protocol_event::tool_runtime_trace_event;
use crate::protocol_event::wrapped_protocol_event_type;
use crate::shared_run::attach_shared_root_if_active;
use crate::wire::activate_wire_trace;
use crate::wire::deactivate_wire_trace;
use crate::wire::register_task_root_thread;

/// Environment variable that enables local trace-bundle recording.
///
/// The value is a root directory. Each independent root session gets one child
/// bundle directory. Spawned child threads share their root session's bundle so
/// one reduced `state.json` describes the whole multi-agent rollout tree.
pub const CODEX_ROLLOUT_TRACE_ROOT_ENV: &str = "CODEX_ROLLOUT_TRACE_ROOT";

/// Metadata captured once at thread/session start.
///
/// This payload is intentionally operational rather than reduced: it is a raw
/// payload that later reducers can mine as the reduced thread model evolves.
#[derive(Serialize)]
pub struct ThreadStartedTraceMetadata {
    pub thread_id: String,
    pub agent_path: String,
    pub task_name: Option<String>,
    pub nickname: Option<String>,
    pub agent_role: Option<String>,
    pub session_source: SessionSource,
    pub cwd: std::path::PathBuf,
    pub rollout_path: Option<std::path::PathBuf>,
    pub model: String,
    pub provider_name: String,
    pub approval_policy: String,
    pub sandbox_policy: String,
}

/// Trace-only payload for a child completion notification delivered to its parent.
#[derive(Serialize)]
pub struct AgentResultTracePayload<'a> {
    pub child_agent_path: &'a str,
    pub message: &'a str,
    pub status: &'a AgentStatus,
}

/// No-op capable trace handle for one thread in a rollout bundle.
#[derive(Clone, Debug)]
pub struct ThreadTraceContext {
    state: ThreadTraceContextState,
}

#[derive(Clone, Debug)]
enum ThreadTraceContextState {
    Disabled,
    Enabled(EnabledThreadTraceContext),
}

#[derive(Clone, Debug)]
struct EnabledThreadTraceContext {
    writer: Arc<TraceWriter>,
    task_root_thread_id: AgentThreadId,
    thread_id: AgentThreadId,
    run_scope: TraceRunScope,
    next_step_ordinal: Arc<AtomicU64>,
}

/// Scope that owns the terminal lifecycle event for this thread's writer.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum TraceRunScope {
    StandaloneRoot,
    SharedAppServer,
}

impl ThreadTraceContext {
    /// Builds a context that accepts trace calls and records nothing.
    pub fn disabled() -> Self {
        Self {
            state: ThreadTraceContextState::Disabled,
        }
    }

    /// Starts a root thread trace from `CODEX_ROLLOUT_TRACE_ROOT`, or disables tracing.
    ///
    /// Trace startup is best-effort. A tracing failure must not make the Codex
    /// session unusable, because traces are diagnostic and can be enabled while
    /// debugging unrelated production failures.
    pub fn start_root_or_disabled(metadata: ThreadStartedTraceMetadata) -> Self {
        let Some(root) = std::env::var_os(CODEX_ROLLOUT_TRACE_ROOT_ENV) else {
            return Self::disabled();
        };
        let task_root_thread_id = metadata.thread_id.clone();
        if let Some(writer) = attach_shared_root_if_active(&task_root_thread_id) {
            return match writer {
                Ok(writer) => Self::start_shared_root(writer, task_root_thread_id, metadata),
                Err(err) => {
                    warn!("failed to attach root task to shared rollout trace: {err:#}");
                    Self::disabled()
                }
            };
        }
        let root = PathBuf::from(root);
        match start_root_in_root(root.as_path(), metadata, true) {
            Ok(context) => context,
            Err(err) => {
                warn!("failed to initialize rollout trace bundle: {err:#}");
                Self::disabled()
            }
        }
    }

    /// Starts a root trace in a known directory.
    ///
    /// This is public for tests that need replayable trace bundles without
    /// mutating process environment.
    pub fn start_root_in_root_for_test(
        root: &Path,
        metadata: ThreadStartedTraceMetadata,
    ) -> anyhow::Result<Self> {
        start_root_in_root(root, metadata, false)
    }

    /// Starts one thread lifecycle inside an existing rollout bundle.
    fn start(
        writer: Arc<TraceWriter>,
        task_root_thread_id: AgentThreadId,
        run_scope: TraceRunScope,
        metadata: ThreadStartedTraceMetadata,
    ) -> Self {
        let context = EnabledThreadTraceContext {
            writer,
            task_root_thread_id,
            thread_id: metadata.thread_id.clone(),
            run_scope,
            next_step_ordinal: Arc::new(AtomicU64::new(1)),
        };
        register_task_root_thread(
            context.thread_id.clone(),
            context.task_root_thread_id.clone(),
        );
        record_thread_started(&context, metadata);
        Self {
            state: ThreadTraceContextState::Enabled(context),
        }
    }

    pub(crate) fn start_shared_root(
        writer: Arc<TraceWriter>,
        task_root_thread_id: AgentThreadId,
        metadata: ThreadStartedTraceMetadata,
    ) -> Self {
        Self::start(
            writer,
            task_root_thread_id,
            TraceRunScope::SharedAppServer,
            metadata,
        )
    }

    /// Returns whether this handle will write trace events.
    ///
    /// Most methods have their own disabled fast path. Callers should branch on
    /// this only when preparing trace payloads would otherwise clone data the
    /// production path needs to move elsewhere.
    pub fn is_enabled(&self) -> bool {
        matches!(self.state, ThreadTraceContextState::Enabled(_))
    }

    /// Starts a fresh child thread in this context's rollout tree.
    ///
    /// Callers should use [`ThreadTraceContext::disabled`] for resumed children:
    /// reusing the parent trace would emit a duplicate `ThreadStarted` event
    /// for an existing thread id and make the bundle unreplayable.
    pub fn start_child_thread_trace_or_disabled(
        &self,
        metadata: ThreadStartedTraceMetadata,
    ) -> Self {
        match &self.state {
            ThreadTraceContextState::Disabled => Self::disabled(),
            ThreadTraceContextState::Enabled(context) => Self::start(
                Arc::clone(&context.writer),
                context.task_root_thread_id.clone(),
                context.run_scope,
                metadata,
            ),
        }
    }

    /// Emits terminal trace events for graceful thread shutdown.
    ///
    /// Spawned child sessions share their root task's bundle. In standalone
    /// mode, that root also closes the rollout; in a shared App Server run,
    /// every task shutdown remains thread-local and the authority guard ends
    /// the run after the server drains.
    pub fn record_ended(&self, status: RolloutStatus) {
        let ThreadTraceContextState::Enabled(context) = &self.state else {
            return;
        };
        context.append_thread_context_best_effort(RawTraceEventPayload::ThreadEnded {
            thread_id: context.thread_id.clone(),
            status: status.clone(),
        });
        if context.run_scope == TraceRunScope::StandaloneRoot
            && context.thread_id == context.task_root_thread_id
        {
            context
                .append_thread_context_best_effort(RawTraceEventPayload::RolloutEnded { status });
            deactivate_wire_trace(&context.writer);
        }
    }

    /// Wraps selected protocol events as raw trace breadcrumbs.
    ///
    /// High-volume stream deltas stay out of this wrapper; typed inference,
    /// tool, terminal, and code-mode hooks provide the canonical runtime data.
    pub fn record_protocol_event(&self, event: &EventMsg) {
        let ThreadTraceContextState::Enabled(context) = &self.state else {
            return;
        };
        let Some(event_type) = wrapped_protocol_event_type(event) else {
            return;
        };
        let Some(event_payload) =
            context.write_json_payload_best_effort(RawPayloadKind::ProtocolEvent, event)
        else {
            return;
        };
        context.append_thread_context_best_effort(RawTraceEventPayload::ProtocolEventObserved {
            event_type: event_type.to_string(),
            event_payload,
        });
    }

    /// Allocates a readable trace-only step id for one model sampling cycle.
    pub fn next_step_id(&self, codex_turn_id: &str) -> Option<HarnessStepId> {
        let ThreadTraceContextState::Enabled(context) = &self.state else {
            return None;
        };
        let ordinal = context.next_step_ordinal.fetch_add(1, Ordering::Relaxed);
        Some(format!(
            "step:{}:{codex_turn_id}:{ordinal}",
            context.thread_id
        ))
    }

    /// Records a source-local harness event within one Codex turn.
    pub fn record_harness_event(
        &self,
        codex_turn_id: impl Into<CodexTurnId>,
        event: HarnessTraceEvent,
    ) {
        let ThreadTraceContextState::Enabled(context) = &self.state else {
            return;
        };
        context.append_with_context_best_effort(
            codex_turn_id.into(),
            RawTraceEventPayload::HarnessEventObserved { event },
        );
    }

    /// Records a source-local harness event that is scoped to a thread but not a turn.
    pub fn record_thread_harness_event(&self, event: HarnessTraceEvent) {
        let ThreadTraceContextState::Enabled(context) = &self.state else {
            return;
        };
        context.append_thread_context_best_effort(RawTraceEventPayload::HarnessEventObserved {
            event,
        });
    }

    /// Emits typed Codex turn lifecycle events from protocol lifecycle events.
    pub fn record_codex_turn_event(&self, default_turn_id: &str, event: &EventMsg) {
        let ThreadTraceContextState::Enabled(context) = &self.state else {
            return;
        };
        let Some(trace_event) =
            codex_turn_trace_event(context.thread_id.clone(), default_turn_id, event)
        else {
            return;
        };
        context.append_with_context_best_effort(
            trace_event.context_turn_id.clone(),
            trace_event.payload,
        );
    }

    /// Emits typed runtime tool events from existing protocol lifecycle events.
    ///
    /// These events are runtime observations on an already-dispatched tool. The
    /// dispatch trace records the caller-facing boundary; these payloads explain
    /// what Codex did while executing that boundary.
    pub fn record_tool_call_event(&self, codex_turn_id: impl Into<CodexTurnId>, event: &EventMsg) {
        let ThreadTraceContextState::Enabled(context) = &self.state else {
            return;
        };
        let Some(trace_event) = tool_runtime_trace_event(event) else {
            return;
        };
        let Some(payload) = context.raw_tool_runtime_payload(trace_event) else {
            return;
        };
        context.append_with_context_best_effort(codex_turn_id.into(), payload);
    }

    /// Emits the v2 child-to-parent completion message as an explicit graph edge.
    ///
    /// The notification is runtime delivery from a completed child turn into
    /// the parent's mailbox, not a tool call executed by the child. Recording it
    /// directly preserves timing and source without making the reducer infer
    /// the edge from a later parent prompt snapshot.
    pub fn record_agent_result_interaction(
        &self,
        child_codex_turn_id: impl Into<CodexTurnId>,
        parent_thread_id: impl Into<AgentThreadId>,
        payload: &AgentResultTracePayload<'_>,
    ) {
        let ThreadTraceContextState::Enabled(context) = &self.state else {
            return;
        };
        let child_codex_turn_id = child_codex_turn_id.into();
        let parent_thread_id = parent_thread_id.into();
        let carried_payload =
            context.write_json_payload_best_effort(RawPayloadKind::AgentResult, payload);
        context.append_with_context_best_effort(
            child_codex_turn_id.clone(),
            RawTraceEventPayload::AgentResultObserved {
                edge_id: format!(
                    "edge:agent_result:{}:{child_codex_turn_id}:{parent_thread_id}",
                    context.thread_id
                ),
                child_thread_id: context.thread_id.clone(),
                child_codex_turn_id,
                parent_thread_id,
                message: payload.message.to_string(),
                carried_payload,
            },
        );
    }

    /// Emits a turn-start lifecycle event.
    ///
    /// Most production turn lifecycle wiring lives outside this PR layer, but
    /// trace-focused integration tests need a small explicit hook so reducer
    /// inputs remain valid without exercising the full session loop.
    pub fn record_codex_turn_started(&self, codex_turn_id: impl Into<CodexTurnId>) {
        let ThreadTraceContextState::Enabled(context) = &self.state else {
            return;
        };
        let codex_turn_id = codex_turn_id.into();
        context.append_with_context_best_effort(
            codex_turn_id.clone(),
            RawTraceEventPayload::CodexTurnStarted {
                codex_turn_id,
                thread_id: context.thread_id.clone(),
            },
        );
    }

    /// Starts a first-class code-mode cell lifecycle and returns its trace handle.
    pub fn start_code_cell_trace(
        &self,
        codex_turn_id: impl Into<CodexTurnId>,
        runtime_cell_id: impl Into<String>,
        model_visible_call_id: impl Into<String>,
        source_js: impl Into<String>,
    ) -> CodeCellTraceContext {
        let context = self.code_cell_trace_context(codex_turn_id, runtime_cell_id);
        context.record_started(model_visible_call_id, source_js);
        context
    }

    /// Builds a trace handle for an already-started code-mode runtime cell.
    pub fn code_cell_trace_context(
        &self,
        codex_turn_id: impl Into<CodexTurnId>,
        runtime_cell_id: impl Into<String>,
    ) -> CodeCellTraceContext {
        let ThreadTraceContextState::Enabled(context) = &self.state else {
            return CodeCellTraceContext::disabled();
        };
        CodeCellTraceContext::enabled(
            Arc::clone(&context.writer),
            context.task_root_thread_id.clone(),
            context.thread_id.clone(),
            codex_turn_id,
            runtime_cell_id,
        )
    }

    /// Starts one dispatch-level tool lifecycle and returns its trace handle.
    ///
    /// `invocation` is lazy because adapting core tool objects into trace-owned
    /// payloads can clone large arguments. Disabled tracing should not pay that
    /// cost on the hot tool-dispatch path.
    pub fn start_tool_dispatch_trace(
        &self,
        invocation: impl FnOnce() -> Option<ToolDispatchInvocation>,
    ) -> ToolDispatchTraceContext {
        let ThreadTraceContextState::Enabled(context) = &self.state else {
            return ToolDispatchTraceContext::disabled();
        };
        let Some(invocation) = invocation() else {
            return ToolDispatchTraceContext::disabled();
        };
        ToolDispatchTraceContext::start(
            Arc::clone(&context.writer),
            context.task_root_thread_id.clone(),
            invocation,
        )
    }

    /// Builds reusable inference trace context for one Codex turn.
    ///
    /// The returned context is intentionally not "an inference call" yet.
    /// Transport code owns retry/fallback attempts and calls `start_attempt`
    /// only after it has built the concrete request payload for that attempt.
    pub fn inference_trace_context(
        &self,
        codex_turn_id: impl Into<CodexTurnId>,
        model: impl Into<String>,
        provider_name: impl Into<String>,
    ) -> InferenceTraceContext {
        let ThreadTraceContextState::Enabled(context) = &self.state else {
            return InferenceTraceContext::disabled();
        };
        InferenceTraceContext::enabled_for_task(
            Arc::clone(&context.writer),
            context.task_root_thread_id.clone(),
            context.thread_id.clone(),
            codex_turn_id.into(),
            model.into(),
            provider_name.into(),
        )
    }

    /// Builds remote-compaction trace context for one checkpoint.
    ///
    /// Rollout tracing currently has a first-class checkpoint model only for remote compaction.
    /// The compact endpoint is a model-facing request whose output replaces live history, so it
    /// needs both request/response attempt events and a later checkpoint event when processed
    /// replacement history is installed.
    pub fn compaction_trace_context(
        &self,
        codex_turn_id: impl Into<CodexTurnId>,
        compaction_id: impl Into<CompactionId>,
        model: impl Into<String>,
        provider_name: impl Into<String>,
    ) -> CompactionTraceContext {
        let ThreadTraceContextState::Enabled(context) = &self.state else {
            return CompactionTraceContext::disabled();
        };
        CompactionTraceContext::enabled_for_task(
            Arc::clone(&context.writer),
            context.task_root_thread_id.clone(),
            context.thread_id.clone(),
            codex_turn_id.into(),
            compaction_id.into(),
            model.into(),
            provider_name.into(),
        )
    }

    /// Starts bridge correlation for one concrete MCP backend request.
    ///
    /// Dispatch-level tool IDs remain compact and UI-friendly. This UUID is
    /// deliberately separate: it is only for cross-process log joins where a
    /// rollout-local counter would collide across samples.
    pub fn start_mcp_call_trace(
        &self,
        tool_call_id: impl Into<ToolCallId>,
        codex_turn_id: impl Into<CodexTurnId>,
    ) -> McpCallTraceContext {
        let ThreadTraceContextState::Enabled(context) = &self.state else {
            return McpCallTraceContext::disabled();
        };
        let codex_turn_id = codex_turn_id.into();
        let mcp_call_id = Uuid::new_v4().to_string();
        let trace = McpCallTraceContext::enabled(
            mcp_call_id.clone(),
            McpWireTaskContext {
                root_thread_id: context.task_root_thread_id.clone(),
                thread_id: context.thread_id.clone(),
                codex_turn_id: codex_turn_id.clone(),
            },
        );
        context.append_with_context_best_effort(
            codex_turn_id,
            RawTraceEventPayload::McpToolCallCorrelationAssigned {
                tool_call_id: tool_call_id.into(),
                mcp_call_id,
            },
        );
        trace
    }
}

fn start_root_in_root(
    root: &Path,
    metadata: ThreadStartedTraceMetadata,
    activate_wire_capture: bool,
) -> anyhow::Result<ThreadTraceContext> {
    let trace_id = Uuid::new_v4().to_string();
    let thread_id = metadata.thread_id.clone();
    let bundle_dir = root.join(format!("trace-{trace_id}-{thread_id}"));
    let writer = TraceWriter::create(
        &bundle_dir,
        trace_id.clone(),
        thread_id.clone(),
        thread_id.clone(),
    )?;
    let writer = Arc::new(writer);

    if let Err(err) = writer.append_with_context(
        RawTraceEventContext {
            task_root_thread_id: Some(thread_id.clone()),
            thread_id: Some(thread_id.clone()),
            codex_turn_id: None,
        },
        RawTraceEventPayload::RolloutStarted {
            trace_id,
            root_thread_id: thread_id.clone(),
        },
    ) {
        warn!("failed to append rollout trace event: {err:#}");
    }

    if activate_wire_capture {
        activate_wire_trace(&writer);
    }

    debug!("recording rollout trace at {}", bundle_dir.display());
    Ok(ThreadTraceContext::start(
        writer,
        thread_id,
        TraceRunScope::StandaloneRoot,
        metadata,
    ))
}

fn record_thread_started(
    context: &EnabledThreadTraceContext,
    metadata: ThreadStartedTraceMetadata,
) {
    let metadata_payload =
        context.write_json_payload_best_effort(RawPayloadKind::SessionMetadata, &metadata);
    context.append_thread_context_best_effort(RawTraceEventPayload::ThreadStarted {
        thread_id: metadata.thread_id,
        agent_path: metadata.agent_path,
        metadata_payload,
    });
}

impl EnabledThreadTraceContext {
    fn write_json_payload_best_effort(
        &self,
        kind: RawPayloadKind,
        payload: &impl Serialize,
    ) -> Option<RawPayloadRef> {
        match self.writer.write_json_payload(kind, payload) {
            Ok(payload_ref) => Some(payload_ref),
            Err(err) => {
                warn!("failed to write rollout trace payload: {err:#}");
                None
            }
        }
    }

    fn raw_tool_runtime_payload(
        &self,
        trace_event: crate::protocol_event::ToolRuntimeTraceEvent<'_>,
    ) -> Option<RawTraceEventPayload> {
        match trace_event {
            crate::protocol_event::ToolRuntimeTraceEvent::Started {
                tool_call_id,
                payload,
            } => {
                let runtime_payload = self
                    .write_json_payload_best_effort(RawPayloadKind::ToolRuntimeEvent, &payload)?;
                Some(RawTraceEventPayload::ToolCallRuntimeStarted {
                    tool_call_id: tool_call_id.to_string(),
                    runtime_payload,
                })
            }
            crate::protocol_event::ToolRuntimeTraceEvent::Ended {
                tool_call_id,
                status,
                payload,
            } => {
                let runtime_payload = self
                    .write_json_payload_best_effort(RawPayloadKind::ToolRuntimeEvent, &payload)?;
                Some(RawTraceEventPayload::ToolCallRuntimeEnded {
                    tool_call_id: tool_call_id.to_string(),
                    status,
                    runtime_payload,
                })
            }
        }
    }

    fn append_with_context_best_effort(
        &self,
        codex_turn_id: CodexTurnId,
        payload: RawTraceEventPayload,
    ) {
        let event_context = RawTraceEventContext {
            task_root_thread_id: Some(self.task_root_thread_id.clone()),
            thread_id: Some(self.thread_id.clone()),
            codex_turn_id: Some(codex_turn_id),
        };
        if let Err(err) = self.writer.append_with_context(event_context, payload) {
            warn!("failed to append rollout trace event: {err:#}");
        }
    }

    fn append_thread_context_best_effort(&self, payload: RawTraceEventPayload) {
        let event_context = RawTraceEventContext {
            task_root_thread_id: Some(self.task_root_thread_id.clone()),
            thread_id: Some(self.thread_id.clone()),
            codex_turn_id: None,
        };
        if let Err(err) = self.writer.append_with_context(event_context, payload) {
            warn!("failed to append rollout trace event: {err:#}");
        }
    }
}

#[cfg(test)]
#[path = "thread_tests.rs"]
mod tests;
