use crate::function_tool::FunctionCallError;
use crate::session::session::Session;
use crate::session::turn_context::TurnContext;
use codex_protocol::ThreadId;
use codex_protocol::error::CodexErrorDetails;
use codex_rollout_trace::HARNESS_CATEGORY_MULTI_AGENT;
use codex_rollout_trace::HarnessTraceEvent;
use serde_json::json;
use std::sync::Arc;

/// Resolves a single tool-facing agent target to a thread id.
pub(crate) async fn resolve_agent_target(
    session: &Arc<Session>,
    turn: &Arc<TurnContext>,
    trace_step_id: Option<codex_rollout_trace::HarnessStepId>,
    target: &str,
) -> Result<ThreadId, FunctionCallError> {
    register_session_root(session, turn);
    if let Ok(thread_id) = ThreadId::from_string(target) {
        session.services.rollout_thread_trace.record_harness_event(
            turn.sub_id.clone(),
            HarnessTraceEvent::new(
                HARNESS_CATEGORY_MULTI_AGENT,
                "agent_target_resolution",
                "resolved",
            )
            .with_optional_step_id(trace_step_id.clone())
            .with_correlation("target_thread_id", thread_id.to_string())
            .with_details(
                json!({"requested_target": target, "requested_target_kind": "thread_id"}),
            ),
        );
        return Ok(thread_id);
    }

    let result = session
        .services
        .agent_control
        .resolve_agent_reference(session.thread_id, &turn.session_source, target)
        .await;
    match result {
        Ok(thread_id) => {
            session.services.rollout_thread_trace.record_harness_event(
                turn.sub_id.clone(),
                HarnessTraceEvent::new(
                    HARNESS_CATEGORY_MULTI_AGENT,
                    "agent_target_resolution",
                    "resolved",
                )
                .with_optional_step_id(trace_step_id.clone())
                .with_correlation("target_thread_id", thread_id.to_string())
                .with_details(
                    json!({"requested_target": target, "requested_target_kind": "agent_path"}),
                ),
            );
            Ok(thread_id)
        }
        Err(err) => {
            let reason = match err.details() {
                CodexErrorDetails::UnsupportedOperation(_) => "unresolved_path",
                _ => "resolution_error",
            };
            session.services.rollout_thread_trace.record_harness_event(
                turn.sub_id.clone(),
                HarnessTraceEvent::new(
                    HARNESS_CATEGORY_MULTI_AGENT,
                    "agent_target_resolution",
                    "failed",
                )
                .with_optional_step_id(trace_step_id)
                .with_reason(reason)
                .with_details(
                    json!({"requested_target": target, "requested_target_kind": "agent_path"}),
                ),
            );
            Err(match err.details() {
                CodexErrorDetails::UnsupportedOperation(message) => {
                    FunctionCallError::RespondToModel(message.clone())
                }
                _ => FunctionCallError::RespondToModel(err.to_string()),
            })
        }
    }
}

fn register_session_root(session: &Arc<Session>, turn: &Arc<TurnContext>) {
    session
        .services
        .agent_control
        .register_session_root(session.thread_id, turn.parent_thread_id);
}
