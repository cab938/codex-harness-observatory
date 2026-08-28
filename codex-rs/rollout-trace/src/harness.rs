//! Teaching-oriented events for observing Codex harness decisions.
//!
//! These events deliberately use a small stable envelope plus string-valued
//! names and phases. That keeps the raw trace append-only while allowing
//! independently developed instrumentation points to share one format.

use std::collections::BTreeMap;

use serde::Deserialize;
use serde::Serialize;
use serde_json::Value;

use crate::AgentThreadId;
use crate::CodexTurnId;
use crate::RawEventSeq;
use crate::RawPayloadRef;

pub type HarnessStepId = String;

pub const HARNESS_CATEGORY_AGENT_LOOP: &str = "agent_loop";
pub const HARNESS_CATEGORY_CONTEXT: &str = "context";
pub const HARNESS_CATEGORY_DECISION: &str = "decision";
pub const HARNESS_CATEGORY_MULTI_AGENT: &str = "multi_agent";
pub const HARNESS_CATEGORY_SUPERVISION: &str = "supervision";
pub const HARNESS_CATEGORY_TOOL: &str = "tool";

pub const HARNESS_PHASE_CANCELLED: &str = "cancelled";
pub const HARNESS_PHASE_COMPLETED: &str = "completed";
pub const HARNESS_PHASE_DECIDED: &str = "decided";
pub const HARNESS_PHASE_DEQUEUED: &str = "dequeued";
pub const HARNESS_PHASE_DISPATCHED: &str = "dispatched";
pub const HARNESS_PHASE_ENQUEUED: &str = "enqueued";
pub const HARNESS_PHASE_FAILED: &str = "failed";
pub const HARNESS_PHASE_OBSERVED: &str = "observed";
pub const HARNESS_PHASE_REQUESTED: &str = "requested";
pub const HARNESS_PHASE_RESOLVED: &str = "resolved";
pub const HARNESS_PHASE_RETRYING: &str = "retrying";
pub const HARNESS_PHASE_STARTED: &str = "started";

/// Producer-owned description of one harness transition or decision.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct HarnessTraceEvent {
    pub category: String,
    pub name: String,
    pub phase: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub step_id: Option<HarnessStepId>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub outcome: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub reason: Option<String>,
    #[serde(default, skip_serializing_if = "BTreeMap::is_empty")]
    pub correlations: BTreeMap<String, String>,
    #[serde(default, skip_serializing_if = "Value::is_null")]
    pub details: Value,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub payloads: Vec<RawPayloadRef>,
}

impl HarnessTraceEvent {
    pub fn new(
        category: impl Into<String>,
        name: impl Into<String>,
        phase: impl Into<String>,
    ) -> Self {
        Self {
            category: category.into(),
            name: name.into(),
            phase: phase.into(),
            step_id: None,
            outcome: None,
            reason: None,
            correlations: BTreeMap::new(),
            details: Value::Null,
            payloads: Vec::new(),
        }
    }

    pub fn with_step_id(mut self, step_id: impl Into<HarnessStepId>) -> Self {
        self.step_id = Some(step_id.into());
        self
    }

    pub fn with_optional_step_id(mut self, step_id: Option<HarnessStepId>) -> Self {
        self.step_id = step_id;
        self
    }

    pub fn with_outcome(mut self, outcome: impl Into<String>) -> Self {
        self.outcome = Some(outcome.into());
        self
    }

    pub fn with_reason(mut self, reason: impl Into<String>) -> Self {
        self.reason = Some(reason.into());
        self
    }

    pub fn with_correlation(mut self, key: impl Into<String>, value: impl Into<String>) -> Self {
        self.correlations.insert(key.into(), value.into());
        self
    }

    pub fn with_details(mut self, details: Value) -> Self {
        self.details = details;
        self
    }

    pub fn with_payload(mut self, payload: RawPayloadRef) -> Self {
        self.payloads.push(payload);
        self
    }
}

/// Reducer-owned harness event with raw ordering and envelope context restored.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct HarnessEvent {
    pub seq: RawEventSeq,
    pub wall_time_unix_ms: i64,
    pub task_root_thread_id: Option<AgentThreadId>,
    pub thread_id: Option<AgentThreadId>,
    pub codex_turn_id: Option<CodexTurnId>,
    #[serde(flatten)]
    pub trace: HarnessTraceEvent,
}

impl HarnessEvent {
    pub(crate) fn from_raw(
        seq: RawEventSeq,
        wall_time_unix_ms: i64,
        task_root_thread_id: Option<AgentThreadId>,
        thread_id: Option<AgentThreadId>,
        codex_turn_id: Option<CodexTurnId>,
        trace: HarnessTraceEvent,
    ) -> Self {
        Self {
            seq,
            wall_time_unix_ms,
            task_root_thread_id,
            thread_id,
            codex_turn_id,
            trace,
        }
    }
}

#[cfg(test)]
mod tests {
    use tempfile::TempDir;

    use crate::ExecutionStatus;
    use crate::RawTraceEventContext;
    use crate::RawTraceEventPayload;
    use crate::RolloutStatus;
    use crate::TraceWriter;
    use crate::replay_bundle;

    use super::HARNESS_CATEGORY_AGENT_LOOP;
    use super::HARNESS_PHASE_DECIDED;
    use super::HarnessTraceEvent;

    #[test]
    fn harness_event_replays_with_turn_and_step_context() -> anyhow::Result<()> {
        let temp = TempDir::new()?;
        let writer = TraceWriter::create(
            temp.path(),
            "trace-1".to_string(),
            "rollout-1".to_string(),
            "thread-root".to_string(),
        )?;
        writer.append(RawTraceEventPayload::RolloutStarted {
            trace_id: "trace-1".to_string(),
            root_thread_id: "thread-root".to_string(),
        })?;
        writer.append(RawTraceEventPayload::ThreadStarted {
            thread_id: "thread-root".to_string(),
            agent_path: "/root".to_string(),
            metadata_payload: None,
        })?;
        let context = RawTraceEventContext {
            task_root_thread_id: Some("thread-root".to_string()),
            thread_id: Some("thread-root".to_string()),
            codex_turn_id: Some("turn-1".to_string()),
        };
        writer.append_with_context(
            context.clone(),
            RawTraceEventPayload::CodexTurnStarted {
                codex_turn_id: "turn-1".to_string(),
                thread_id: "thread-root".to_string(),
            },
        )?;
        writer.append_with_context(
            context.clone(),
            RawTraceEventPayload::HarnessEventObserved {
                event: HarnessTraceEvent::new(
                    HARNESS_CATEGORY_AGENT_LOOP,
                    "agent_step_next_action",
                    HARNESS_PHASE_DECIDED,
                )
                .with_step_id("step:thread-root:turn-1:1")
                .with_outcome("continue_for_tool_output")
                .with_reason("model_requested_tool"),
            },
        )?;
        writer.append_with_context(
            context,
            RawTraceEventPayload::CodexTurnEnded {
                codex_turn_id: "turn-1".to_string(),
                status: ExecutionStatus::Completed,
            },
        )?;
        writer.append(RawTraceEventPayload::RolloutEnded {
            status: RolloutStatus::Completed,
        })?;

        let reduced = replay_bundle(temp.path())?;
        assert_eq!(reduced.schema_version, 3);
        assert_eq!(reduced.harness_events.len(), 1);
        let event = &reduced.harness_events[0];
        assert_eq!(event.thread_id.as_deref(), Some("thread-root"));
        assert_eq!(event.codex_turn_id.as_deref(), Some("turn-1"));
        assert_eq!(
            event.trace.step_id.as_deref(),
            Some("step:thread-root:turn-1:1")
        );
        assert_eq!(
            event.trace.outcome.as_deref(),
            Some("continue_for_tool_output")
        );
        Ok(())
    }
}
