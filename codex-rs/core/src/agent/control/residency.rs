use super::AgentControl;
use crate::agent::AgentStatus;
use crate::codex_thread::CodexThread;
use crate::config::Config;
use crate::thread_manager::ThreadManagerState;
use codex_protocol::ThreadId;
use codex_protocol::error::CodexErr;
use codex_protocol::error::CodexErrorDetails;
use codex_protocol::error::Result as CodexResult;
use codex_protocol::protocol::MultiAgentVersion;
use codex_protocol::protocol::SessionSource;
use codex_rollout_trace::HARNESS_CATEGORY_MULTI_AGENT;
use codex_rollout_trace::HarnessTraceEvent;
use serde_json::json;
use std::collections::VecDeque;
use std::sync::Arc;
use std::sync::Mutex;
use tracing::warn;

#[derive(Default)]
pub(super) struct V2Residency {
    state: Mutex<V2ResidencyState>,
}

#[derive(Default)]
struct V2ResidencyState {
    residents: VecDeque<ThreadId>,
    pending_slots: usize,
}

pub(super) struct V2ResidencySlot {
    residency: Arc<V2Residency>,
    active: bool,
}

impl V2ResidencySlot {
    pub(super) fn commit(mut self, thread_id: ThreadId) {
        self.residency.commit_slot(thread_id);
        self.active = false;
    }
}

impl Drop for V2ResidencySlot {
    fn drop(&mut self) {
        if self.active {
            self.residency.release_pending_slot();
        }
    }
}

impl AgentControl {
    pub(super) async fn reserve_v2_residency_slot(
        &self,
        state: &Arc<ThreadManagerState>,
        config: &Config,
        protected_thread_id: Option<ThreadId>,
        parent_thread_id: Option<ThreadId>,
        task_thread_id: Option<ThreadId>,
    ) -> CodexResult<V2ResidencySlot> {
        let capacity = config
            .effective_agent_max_threads(MultiAgentVersion::V2)
            .unwrap_or(usize::MAX);
        self.record_v2_thread_event(
            state,
            task_thread_id,
            parent_thread_id,
            "agent_residency",
            "requested",
            None,
        )
        .await;
        match Arc::clone(&self.v2_residency)
            .reserve_slot(self, state, capacity, protected_thread_id)
            .await
        {
            Ok(slot) => {
                self.record_v2_thread_event(
                    state,
                    task_thread_id,
                    parent_thread_id,
                    "agent_residency",
                    "reserved",
                    None,
                )
                .await;
                Ok(slot)
            }
            Err(err) => {
                self.record_v2_thread_event(
                    state,
                    task_thread_id,
                    parent_thread_id,
                    "agent_residency",
                    "rejected",
                    Some("capacity_unavailable"),
                )
                .await;
                Err(err)
            }
        }
    }

    pub(super) async fn touch_loaded_v2_residency(
        &self,
        state: &Arc<ThreadManagerState>,
        thread_id: ThreadId,
    ) {
        if let Ok(thread) = state.get_thread(thread_id).await
            && is_resident_candidate(thread.as_ref())
        {
            self.v2_residency.touch(thread_id);
            self.record_v2_thread_event(
                state,
                Some(thread_id),
                thread.config_snapshot().await.parent_thread_id,
                "agent_residency",
                "touched",
                None,
            )
            .await;
        }
    }

    pub(super) async fn forget_v2_residency(
        &self,
        state: &ThreadManagerState,
        thread_id: ThreadId,
    ) {
        let resident_parent_thread_id = match state.get_thread(thread_id).await {
            Ok(thread) if is_resident_candidate(thread.as_ref()) => {
                Some(thread.config_snapshot().await.parent_thread_id)
            }
            Ok(_) | Err(_) => None,
        };
        if let Some(parent_thread_id) = resident_parent_thread_id {
            self.record_v2_thread_event(
                state,
                Some(thread_id),
                parent_thread_id,
                "agent_identity",
                "forgotten",
                Some("closed"),
            )
            .await;
            self.record_v2_thread_event(
                state,
                Some(thread_id),
                parent_thread_id,
                "agent_residency",
                "released",
                Some("closed"),
            )
            .await;
        }
        self.v2_residency.remove(thread_id);
    }

    pub(super) async fn record_v2_thread_event(
        &self,
        state: &ThreadManagerState,
        task_thread_id: Option<ThreadId>,
        parent_thread_id: Option<ThreadId>,
        name: &str,
        phase: &str,
        reason: Option<&str>,
    ) {
        let event = self.v2_harness_event(name, phase, task_thread_id, parent_thread_id, reason);
        for trace_thread_id in task_thread_id
            .into_iter()
            .chain(parent_thread_id)
            .chain(self.state.root_thread_id())
        {
            if let Ok(thread) = state.get_thread(trace_thread_id).await {
                thread
                    .session
                    .services
                    .rollout_thread_trace
                    .record_thread_harness_event(event);
                return;
            }
        }
    }

    fn v2_harness_event(
        &self,
        name: &str,
        phase: &str,
        task_thread_id: Option<ThreadId>,
        parent_thread_id: Option<ThreadId>,
        reason: Option<&str>,
    ) -> HarnessTraceEvent {
        let task_metadata = task_thread_id.and_then(|thread_id| {
            self.state
                .agent_metadata_for_thread(thread_id)
                .and_then(|metadata| metadata.agent_path.map(|agent_path| agent_path.to_string()))
        });
        let mut event = HarnessTraceEvent::new(HARNESS_CATEGORY_MULTI_AGENT, name, phase)
            .with_details(json!({"implementation": "v2"}));
        if let Some(root_thread_id) = self.state.root_thread_id() {
            event = event.with_correlation("root_thread_id", root_thread_id.to_string());
        }
        if let Some(parent_thread_id) = parent_thread_id {
            event = event.with_correlation("parent_thread_id", parent_thread_id.to_string());
        }
        if let Some(task_thread_id) = task_thread_id {
            event = event.with_correlation("task_thread_id", task_thread_id.to_string());
        }
        if let Some(task_path) = task_metadata {
            event = event.with_correlation("task_path", task_path);
        }
        if let Some(reason) = reason {
            event = event.with_reason(reason);
        }
        event
    }
}

impl V2Residency {
    async fn reserve_slot(
        self: Arc<Self>,
        control: &AgentControl,
        manager: &Arc<ThreadManagerState>,
        capacity: usize,
        protected_thread_id: Option<ThreadId>,
    ) -> CodexResult<V2ResidencySlot> {
        loop {
            if self.try_reserve_pending_slot(capacity) {
                return Ok(V2ResidencySlot {
                    residency: self,
                    active: true,
                });
            }
            if !self
                .try_unload_one_resident(control, manager, protected_thread_id)
                .await
            {
                return Err(CodexErr::new(CodexErrorDetails::AgentLimitReached {
                    max_threads: capacity,
                }));
            }
        }
    }

    fn try_reserve_pending_slot(&self, capacity: usize) -> bool {
        let mut state = self
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        if state.residents.len().saturating_add(state.pending_slots) >= capacity {
            return false;
        }
        state.pending_slots += 1;
        true
    }

    async fn try_unload_one_resident(
        &self,
        control: &AgentControl,
        manager: &Arc<ThreadManagerState>,
        protected_thread_id: Option<ThreadId>,
    ) -> bool {
        let candidates_to_scan = self.resident_count();
        for _ in 0..candidates_to_scan {
            let Some(candidate_thread_id) = self.pop_lru_candidate(protected_thread_id) else {
                return false;
            };
            let Some(candidate_thread) = manager
                .get_thread(candidate_thread_id)
                .await
                .ok()
                .filter(|thread| is_resident_candidate(thread))
            else {
                control
                    .record_v2_thread_event(
                        manager,
                        Some(candidate_thread_id),
                        None,
                        "agent_eviction",
                        "skipped",
                        Some("not_resident"),
                    )
                    .await;
                continue;
            };
            let parent_thread_id = candidate_thread.config_snapshot().await.parent_thread_id;
            control
                .record_v2_thread_event(
                    manager,
                    Some(candidate_thread_id),
                    parent_thread_id,
                    "agent_residency",
                    "selected_for_eviction",
                    None,
                )
                .await;
            if !is_unloadable(candidate_thread.as_ref()).await {
                self.touch(candidate_thread_id);
                control
                    .record_v2_thread_event(
                        manager,
                        Some(candidate_thread_id),
                        parent_thread_id,
                        "agent_eviction",
                        "skipped",
                        Some("not_idle"),
                    )
                    .await;
                continue;
            }
            control
                .record_v2_thread_event(
                    manager,
                    Some(candidate_thread_id),
                    parent_thread_id,
                    "agent_eviction",
                    "requested",
                    Some("idle_terminal"),
                )
                .await;
            candidate_thread.ensure_rollout_materialized().await;
            if let Err(err) = candidate_thread.shutdown_and_wait().await {
                warn!(
                    "failed to shut down v2 resident thread before unloading {candidate_thread_id}: {err}"
                );
                self.touch(candidate_thread_id);
                control
                    .record_v2_thread_event(
                        manager,
                        Some(candidate_thread_id),
                        parent_thread_id,
                        "agent_eviction",
                        "failed",
                        Some("shutdown_failed"),
                    )
                    .await;
                continue;
            }
            let environments = candidate_thread.environment_selections().await;
            candidate_thread
                .session
                .services
                .agent_control
                .state
                .save_evicted_environments(candidate_thread_id, environments);
            let eviction_phase = if manager.remove_thread(&candidate_thread_id).await.is_some() {
                "completed"
            } else {
                "skipped"
            };
            let eviction_reason = if eviction_phase == "completed" {
                "idle_terminal"
            } else {
                "already_nonresident"
            };
            control
                .record_v2_thread_event(
                    manager,
                    Some(candidate_thread_id),
                    parent_thread_id,
                    "agent_eviction",
                    eviction_phase,
                    Some(eviction_reason),
                )
                .await;
            control
                .record_v2_thread_event(
                    manager,
                    Some(candidate_thread_id),
                    parent_thread_id,
                    "agent_residency",
                    "released",
                    Some("eviction"),
                )
                .await;
            return true;
        }
        false
    }

    fn resident_count(&self) -> usize {
        self.state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .residents
            .len()
    }

    fn pop_lru_candidate(&self, protected_thread_id: Option<ThreadId>) -> Option<ThreadId> {
        let mut state = self
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        let candidates_to_scan = state.residents.len();
        for _ in 0..candidates_to_scan {
            let candidate_thread_id = state.residents.pop_front()?;
            if Some(candidate_thread_id) == protected_thread_id {
                state.residents.push_back(candidate_thread_id);
                continue;
            }
            return Some(candidate_thread_id);
        }
        None
    }

    fn touch(&self, thread_id: ThreadId) {
        let mut state = self
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        touch_resident(&mut state.residents, thread_id);
    }

    fn remove(&self, thread_id: ThreadId) {
        self.state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .residents
            .retain(|resident_thread_id| *resident_thread_id != thread_id);
    }

    fn commit_slot(&self, thread_id: ThreadId) {
        let mut state = self
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        state.pending_slots = state.pending_slots.saturating_sub(1);
        touch_resident(&mut state.residents, thread_id);
    }

    fn release_pending_slot(&self) {
        let mut state = self
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        state.pending_slots = state.pending_slots.saturating_sub(1);
    }
}

fn touch_resident(residents: &mut VecDeque<ThreadId>, thread_id: ThreadId) {
    residents.retain(|resident_thread_id| *resident_thread_id != thread_id);
    residents.push_back(thread_id);
}

fn is_resident_candidate(thread: &CodexThread) -> bool {
    thread.multi_agent_version() == Some(MultiAgentVersion::V2)
        && is_v2_resident_session_source(&thread.session_source)
}

pub(super) fn is_v2_resident_session_source(session_source: &SessionSource) -> bool {
    matches!(session_source, SessionSource::SubAgent(_))
}

async fn is_unloadable(thread: &CodexThread) -> bool {
    matches!(
        thread.agent_status().await,
        AgentStatus::Completed(_) | AgentStatus::Errored(_) | AgentStatus::Interrupted
    ) && thread.session.active_turn.lock().await.is_none()
        && !thread.session.input_queue.has_pending_mailbox_items().await
}

#[cfg(test)]
#[path = "residency_tests.rs"]
mod tests;
