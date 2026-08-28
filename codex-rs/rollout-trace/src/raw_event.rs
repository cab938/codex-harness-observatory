//! Append-only raw trace events.

use crate::HarnessTraceEvent;
use crate::WireFrameDirection;
use crate::WireFrameKind;
use crate::model::AgentThreadId;
use crate::model::CodeCellRuntimeStatus;
use crate::model::CodexTurnId;
use crate::model::CompactionId;
use crate::model::CompactionRequestId;
use crate::model::EdgeId;
use crate::model::ExecutionStatus;
use crate::model::InferenceCallId;
use crate::model::McpCallId;
use crate::model::ModelVisibleCallId;
use crate::model::RolloutStatus;
use crate::model::ToolCallId;
use crate::model::ToolCallKind;
use crate::model::ToolCallSummary;
use crate::payload::RawPayloadRef;
use serde::Deserialize;
use serde::Serialize;
use serde_json::Value;

/// Monotonic sequence number assigned by the raw trace writer.
pub type RawEventSeq = u64;

/// Current raw event envelope schema version.
pub(crate) const RAW_TRACE_EVENT_SCHEMA_VERSION: u32 = 4;

/// One append-only raw trace event.
///
/// Every event uses the same envelope so partial replay and corruption checks
/// can run before the reducer understands the event-specific payload.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct RawTraceEvent {
    pub schema_version: u32,
    /// Contiguous writer-assigned order inside one rollout event log.
    pub seq: RawEventSeq,
    /// Unix wall-clock timestamp in milliseconds. Use for display/latency.
    pub wall_time_unix_ms: i64,
    pub rollout_id: String,
    /// Independent root task that owns this event's thread tree.
    ///
    /// A shared App Server trace can contain several independent roots. Frames
    /// that belong to the connection/server rather than one task deliberately
    /// leave this unset.
    #[serde(default)]
    pub task_root_thread_id: Option<AgentThreadId>,
    pub thread_id: Option<AgentThreadId>,
    pub codex_turn_id: Option<CodexTurnId>,
    pub payload: RawTraceEventPayload,
}

/// Writer-supplied context that appears in the raw event envelope.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct RawTraceEventContext {
    pub task_root_thread_id: Option<AgentThreadId>,
    pub thread_id: Option<AgentThreadId>,
    pub codex_turn_id: Option<CodexTurnId>,
}

/// Runtime requester as observed at the raw tool boundary.
///
/// This intentionally uses runtime-local identifiers. The reducer is the only
/// place that maps these handles to graph identities such as `CodeCellId`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case", tag = "type")]
pub enum RawToolCallRequester {
    Model,
    CodeCell {
        /// Runtime-local code-mode cell handle.
        runtime_cell_id: String,
    },
}

/// Typed payload for a raw trace event.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case", tag = "type")]
pub enum RawTraceEventPayload {
    /// Lifecycle start for a trace run that can span several independent task roots.
    RunStarted { trace_id: String },
    /// Lifecycle end for a trace run that can span several independent task roots.
    RunEnded { status: RolloutStatus },
    /// Legacy lifecycle start for a single-root rollout bundle.
    RolloutStarted {
        trace_id: String,
        root_thread_id: AgentThreadId,
    },
    /// Legacy lifecycle end for a single-root rollout bundle.
    RolloutEnded { status: RolloutStatus },
    ThreadStarted {
        thread_id: AgentThreadId,
        /// Stable agent path.
        agent_path: String,
        metadata_payload: Option<RawPayloadRef>,
    },
    ThreadEnded {
        thread_id: AgentThreadId,
        status: RolloutStatus,
    },
    CodexTurnStarted {
        codex_turn_id: CodexTurnId,
        thread_id: AgentThreadId,
    },
    CodexTurnEnded {
        codex_turn_id: CodexTurnId,
        status: ExecutionStatus,
    },
    InferenceStarted {
        inference_call_id: InferenceCallId,
        thread_id: AgentThreadId,
        codex_turn_id: CodexTurnId,
        model: String,
        provider_name: String,
        request_payload: RawPayloadRef,
    },
    InferenceCompleted {
        inference_call_id: InferenceCallId,
        /// Responses API `response.id`; used by `previous_response_id`.
        response_id: Option<String>,
        /// Provider transport request id, such as `x-request-id`.
        upstream_request_id: Option<String>,
        response_payload: RawPayloadRef,
    },
    InferenceFailed {
        inference_call_id: InferenceCallId,
        /// Provider transport request id, such as `x-request-id`, when the
        /// provider returned one before the stream failed.
        upstream_request_id: Option<String>,
        error: String,
        /// Partial response payload, when stream events arrived before failure.
        partial_response_payload: Option<RawPayloadRef>,
    },
    InferenceCancelled {
        inference_call_id: InferenceCallId,
        /// Provider transport request id, such as `x-request-id`, when observed
        /// before Codex stopped consuming the stream.
        upstream_request_id: Option<String>,
        /// Why Codex stopped consuming the provider stream before a terminal response event.
        reason: String,
        /// Completed output items observed before cancellation, if any.
        partial_response_payload: Option<RawPayloadRef>,
    },
    ToolCallStarted {
        tool_call_id: ToolCallId,
        /// Protocol/model call ID when this runtime call came from model output.
        model_visible_call_id: Option<String>,
        /// Code-mode runtime bridge ID when model-authored code issued this call.
        code_mode_runtime_tool_id: Option<String>,
        /// Runtime requester that caused this tool lifecycle.
        requester: RawToolCallRequester,
        kind: ToolCallKind,
        summary: ToolCallSummary,
        invocation_payload: Option<RawPayloadRef>,
    },
    /// Bridge correlation UUID assigned only when a tool reaches an MCP backend.
    McpToolCallCorrelationAssigned {
        tool_call_id: ToolCallId,
        mcp_call_id: McpCallId,
    },
    ToolCallRuntimeStarted {
        tool_call_id: ToolCallId,
        /// Runtime/protocol observation for how Codex began executing the tool.
        runtime_payload: RawPayloadRef,
    },
    ToolCallRuntimeEnded {
        tool_call_id: ToolCallId,
        status: ExecutionStatus,
        /// Runtime/protocol observation for how Codex finished executing the tool.
        runtime_payload: RawPayloadRef,
    },
    ToolCallEnded {
        tool_call_id: ToolCallId,
        status: ExecutionStatus,
        result_payload: Option<RawPayloadRef>,
    },
    CodeCellStarted {
        /// Runtime-local handle allocated by code mode for waits and nested tools.
        runtime_cell_id: String,
        /// Custom tool call id on the model-visible `exec` item.
        model_visible_call_id: ModelVisibleCallId,
        /// JavaScript source after the public `exec` wrapper has been parsed.
        source_js: String,
    },
    CodeCellInitialResponse {
        /// Runtime-local handle, matching `CodeCellStarted`.
        runtime_cell_id: String,
        status: CodeCellRuntimeStatus,
        response_payload: Option<RawPayloadRef>,
    },
    CodeCellEnded {
        /// Runtime-local handle, matching `CodeCellStarted`.
        runtime_cell_id: String,
        status: CodeCellRuntimeStatus,
        response_payload: Option<RawPayloadRef>,
    },
    CompactionRequestStarted {
        compaction_id: CompactionId,
        compaction_request_id: CompactionRequestId,
        thread_id: AgentThreadId,
        codex_turn_id: CodexTurnId,
        model: String,
        provider_name: String,
        request_payload: RawPayloadRef,
    },
    CompactionRequestCompleted {
        compaction_id: CompactionId,
        compaction_request_id: CompactionRequestId,
        response_payload: RawPayloadRef,
    },
    CompactionRequestFailed {
        compaction_id: CompactionId,
        compaction_request_id: CompactionRequestId,
        error: String,
    },
    /// Checkpoint installation event for remote-compacted replacement history.
    CompactionInstalled {
        compaction_id: CompactionId,
        /// Trace-only checkpoint payload. Do not route this through public UI protocol.
        checkpoint_payload: RawPayloadRef,
    },
    /// Multi-agent v2 child-to-parent completion delivery.
    AgentResultObserved {
        edge_id: EdgeId,
        child_thread_id: AgentThreadId,
        child_codex_turn_id: CodexTurnId,
        parent_thread_id: AgentThreadId,
        message: String,
        /// Raw notification payload. This is evidence for the runtime delivery,
        /// not the parent-side model-visible item.
        carried_payload: Option<RawPayloadRef>,
    },
    /// Existing UI/protocol event wrapped into trace format.
    ProtocolEventObserved {
        event_type: String,
        event_payload: RawPayloadRef,
    },
    /// One exact JSON-RPC message at the App Server client boundary.
    AppServerFrameObserved {
        connection_id: String,
        transport: String,
        direction: WireFrameDirection,
        frame_kind: WireFrameKind,
        method: Option<String>,
        request_id: Option<String>,
        /// Existing thread targeted by this operation, when the wire frame identifies one.
        #[serde(default)]
        source_thread_id: Option<AgentThreadId>,
        /// Thread introduced by a start or fork result/notification, when present.
        #[serde(default)]
        new_thread_id: Option<AgentThreadId>,
        /// Conversation item carried by an item lifecycle notification, when present.
        #[serde(default)]
        item_id: Option<String>,
        /// Source thread recorded by a returned forked thread, when present.
        #[serde(default)]
        forked_from_id: Option<AgentThreadId>,
        /// Session tree identity recorded by a returned thread, when present.
        #[serde(default)]
        session_id: Option<String>,
        frame_payload: RawPayloadRef,
    },
    /// One exact JSON-RPC message exchanged with an MCP server.
    McpFrameObserved {
        server_name: String,
        transport: String,
        direction: WireFrameDirection,
        frame_kind: WireFrameKind,
        method: Option<String>,
        request_id: Option<String>,
        mcp_call_id: Option<McpCallId>,
        frame_payload: RawPayloadRef,
    },
    /// Source-local transition or decision in the Codex agent harness.
    HarnessEventObserved { event: HarnessTraceEvent },
    /// Structured payload for early instrumentation before a dedicated variant exists.
    Other {
        kind: String,
        summary: String,
        payloads: Vec<RawPayloadRef>,
        /// Small structured metadata. Large data belongs in `payloads`.
        metadata: Value,
    },
}

impl RawTraceEventPayload {
    /// Raw payload refs that must exist before this raw event is appended.
    pub(crate) fn raw_payload_refs(&self) -> Vec<&RawPayloadRef> {
        match self {
            RawTraceEventPayload::RunStarted { .. }
            | RawTraceEventPayload::RunEnded { .. }
            | RawTraceEventPayload::RolloutStarted { .. }
            | RawTraceEventPayload::RolloutEnded { .. }
            | RawTraceEventPayload::ThreadEnded { .. }
            | RawTraceEventPayload::CodexTurnStarted { .. }
            | RawTraceEventPayload::CodexTurnEnded { .. }
            | RawTraceEventPayload::CompactionRequestFailed { .. }
            | RawTraceEventPayload::CodeCellStarted { .. }
            | RawTraceEventPayload::McpToolCallCorrelationAssigned { .. }
            | RawTraceEventPayload::AgentResultObserved {
                carried_payload: None,
                ..
            } => Vec::new(),
            RawTraceEventPayload::ThreadStarted {
                metadata_payload, ..
            } => metadata_payload.iter().collect(),
            RawTraceEventPayload::InferenceStarted {
                request_payload, ..
            }
            | RawTraceEventPayload::InferenceCompleted {
                response_payload: request_payload,
                ..
            }
            | RawTraceEventPayload::CompactionRequestStarted {
                request_payload, ..
            }
            | RawTraceEventPayload::CompactionRequestCompleted {
                response_payload: request_payload,
                ..
            }
            | RawTraceEventPayload::CompactionInstalled {
                checkpoint_payload: request_payload,
                ..
            }
            | RawTraceEventPayload::ProtocolEventObserved {
                event_payload: request_payload,
                ..
            }
            | RawTraceEventPayload::AppServerFrameObserved {
                frame_payload: request_payload,
                ..
            }
            | RawTraceEventPayload::McpFrameObserved {
                frame_payload: request_payload,
                ..
            } => vec![request_payload],
            RawTraceEventPayload::HarnessEventObserved { event } => event.payloads.iter().collect(),
            RawTraceEventPayload::InferenceFailed {
                partial_response_payload,
                ..
            }
            | RawTraceEventPayload::InferenceCancelled {
                partial_response_payload,
                ..
            }
            | RawTraceEventPayload::ToolCallStarted {
                invocation_payload: partial_response_payload,
                ..
            }
            | RawTraceEventPayload::ToolCallEnded {
                result_payload: partial_response_payload,
                ..
            }
            | RawTraceEventPayload::CodeCellInitialResponse {
                response_payload: partial_response_payload,
                ..
            }
            | RawTraceEventPayload::CodeCellEnded {
                response_payload: partial_response_payload,
                ..
            } => partial_response_payload.iter().collect(),
            RawTraceEventPayload::AgentResultObserved {
                carried_payload: Some(carried_payload),
                ..
            } => vec![carried_payload],
            RawTraceEventPayload::ToolCallRuntimeStarted {
                runtime_payload, ..
            }
            | RawTraceEventPayload::ToolCallRuntimeEnded {
                runtime_payload, ..
            } => vec![runtime_payload],
            RawTraceEventPayload::Other { payloads, .. } => payloads.iter().collect(),
        }
    }
}
