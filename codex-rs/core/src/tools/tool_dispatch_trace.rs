//! Adapter between core tool dispatch objects and rollout-trace events.
//!
//! `codex-rollout-trace` owns the event schema and writer behavior. This module
//! keeps the core-specific mapping from registry invocations/results out of the
//! registry control flow.

use crate::function_tool::FunctionCallError;
use crate::session::session::Session;
use crate::session::step_context::StepContext;
use crate::tools::context::ToolCallSource;
use crate::tools::context::ToolInvocation;
use crate::tools::context::ToolOutput;
use crate::tools::context::ToolPayload;
use crate::tools::router::ToolCall;
use codex_rollout_trace::ExecutionStatus;
use codex_rollout_trace::HarnessTraceEvent;
use codex_rollout_trace::ToolDispatchInvocation;
use codex_rollout_trace::ToolDispatchPayload;
use codex_rollout_trace::ToolDispatchRequester;
use codex_rollout_trace::ToolDispatchResult;
use codex_rollout_trace::ToolDispatchTraceContext;
use serde_json::Value;
use std::collections::BTreeMap;

pub(crate) fn record_tool_catalog(
    invocation: &ToolInvocation,
    family_counts: BTreeMap<String, usize>,
) {
    record_tool_event(
        invocation,
        "tool_catalog",
        "observed",
        Some("model_visible"),
        None,
        serde_json::json!({ "family_counts": family_counts }),
    );
}

pub(crate) fn record_tool_event(
    invocation: &ToolInvocation,
    name: &str,
    phase: &str,
    outcome: Option<&str>,
    reason: Option<&str>,
    details: Value,
) {
    let mut event = HarnessTraceEvent::new(codex_rollout_trace::HARNESS_CATEGORY_TOOL, name, phase)
        .with_optional_step_id(invocation.step_context.trace_step_id.clone())
        .with_correlation("tool_call_id", invocation.call_id.clone())
        .with_details(details);
    if let Some(outcome) = outcome {
        event = event.with_outcome(outcome);
    }
    if let Some(reason) = reason {
        event = event.with_reason(reason);
    }
    invocation
        .session
        .services
        .rollout_thread_trace
        .record_harness_event(invocation.turn.sub_id.clone(), event);
}

pub(crate) fn record_tool_call_event(
    session: &Session,
    step_context: &StepContext,
    call: &ToolCall,
    name: &str,
    phase: &str,
    outcome: Option<&str>,
    reason: Option<&str>,
    details: Value,
) {
    record_tool_context_event(
        session,
        step_context,
        &call.call_id,
        name,
        phase,
        outcome,
        reason,
        details,
    );
}

pub(crate) fn record_tool_context_event(
    session: &Session,
    step_context: &StepContext,
    call_id: &str,
    name: &str,
    phase: &str,
    outcome: Option<&str>,
    reason: Option<&str>,
    details: Value,
) {
    let mut event = HarnessTraceEvent::new(codex_rollout_trace::HARNESS_CATEGORY_TOOL, name, phase)
        .with_optional_step_id(step_context.trace_step_id.clone())
        .with_correlation("tool_call_id", call_id.to_string())
        .with_details(details);
    if let Some(outcome) = outcome {
        event = event.with_outcome(outcome);
    }
    if let Some(reason) = reason {
        event = event.with_reason(reason);
    }
    session
        .services
        .rollout_thread_trace
        .record_harness_event(step_context.turn.sub_id.clone(), event);
}

/// Keeps registry early-return paths paired with trace end events.
pub(crate) struct ToolDispatchTrace {
    context: ToolDispatchTraceContext,
}

impl ToolDispatchTrace {
    pub(crate) fn start(invocation: &ToolInvocation) -> Self {
        let context = invocation
            .session
            .services
            .rollout_thread_trace
            .start_tool_dispatch_trace(|| tool_dispatch_invocation(invocation));
        Self { context }
    }

    pub(crate) fn record_completed(
        &self,
        invocation: &ToolInvocation,
        call_id: &str,
        payload: &ToolPayload,
        result: &dyn ToolOutput,
    ) {
        if !self.context.is_enabled() {
            return;
        }

        let Some(result_payload) = tool_dispatch_result(invocation, call_id, payload, result)
        else {
            return;
        };
        let status = if result.success_for_logging() {
            ExecutionStatus::Completed
        } else {
            ExecutionStatus::Failed
        };
        self.context.record_completed(status, result_payload);
    }

    pub(crate) fn record_failed(&self, error: &FunctionCallError) {
        self.context.record_failed(error);
    }
}

fn tool_dispatch_invocation(invocation: &ToolInvocation) -> Option<ToolDispatchInvocation> {
    let requester = match &invocation.source {
        ToolCallSource::Direct | ToolCallSource::DirectPlaintextMessage => {
            ToolDispatchRequester::Model {
                model_visible_call_id: invocation.call_id.clone(),
            }
        }
        ToolCallSource::CodeMode {
            cell_id,
            runtime_tool_call_id,
        } => ToolDispatchRequester::CodeCell {
            runtime_cell_id: cell_id.clone(),
            runtime_tool_call_id: runtime_tool_call_id.clone(),
        },
    };

    Some(ToolDispatchInvocation {
        thread_id: invocation.session.thread_id.to_string(),
        codex_turn_id: invocation.turn.sub_id.clone(),
        tool_call_id: invocation.call_id.clone(),
        tool_name: invocation.tool_name.name.clone(),
        tool_namespace: invocation
            .tool_name
            .namespace
            .as_ref()
            .filter(|_| !invocation.tool_name.is_default_namespace())
            .cloned(),
        requester,
        payload: tool_dispatch_payload(&invocation.payload),
    })
}

fn tool_dispatch_result(
    invocation: &ToolInvocation,
    call_id: &str,
    payload: &ToolPayload,
    result: &dyn ToolOutput,
) -> Option<ToolDispatchResult> {
    match invocation.source {
        ToolCallSource::Direct | ToolCallSource::DirectPlaintextMessage => {
            Some(ToolDispatchResult::DirectResponse {
                response_item: result.to_response_item(call_id, payload),
            })
        }
        ToolCallSource::CodeMode { .. } => Some(ToolDispatchResult::CodeModeResponse {
            value: result.code_mode_result(payload),
        }),
    }
}

fn tool_dispatch_payload(payload: &ToolPayload) -> ToolDispatchPayload {
    match payload {
        ToolPayload::Function { arguments } => ToolDispatchPayload::Function {
            arguments: arguments.clone(),
        },
        ToolPayload::ToolSearch { arguments } => ToolDispatchPayload::ToolSearch {
            arguments: arguments.clone(),
        },
        ToolPayload::Custom { input } => ToolDispatchPayload::Custom {
            input: input.clone(),
        },
    }
}

#[cfg(test)]
#[path = "tool_dispatch_trace_tests.rs"]
mod tests;
