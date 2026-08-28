use std::fs;
use std::path::Path;
use std::path::PathBuf;

use codex_protocol::AgentPath;
use codex_protocol::ThreadId;
use codex_protocol::protocol::SandboxPolicy;
use codex_protocol::protocol::SessionSource;
use codex_protocol::protocol::SubAgentSource;
use pretty_assertions::assert_eq;
use tempfile::TempDir;

use super::AppServerSharedRunGuard;
use crate::ExecutionStatus;
use crate::RawTraceEvent;
use crate::RawTraceEventPayload;
use crate::RolloutStatus;
use crate::ThreadStartedTraceMetadata;
use crate::replay_bundle;

#[test]
fn shared_run_orders_overlapping_roots_and_ends_once() -> anyhow::Result<()> {
    let temp = TempDir::new()?;
    let guard = AppServerSharedRunGuard::install(temp.path().to_path_buf());
    let root_a_id = ThreadId::new();
    let root_b_id = ThreadId::new();
    let child_a_id = ThreadId::new();
    let child_b_id = ThreadId::new();
    let root_a = guard.start_root(root_metadata(root_a_id, "/root/a"))?;
    let root_b = guard.start_root(root_metadata(root_b_id, "/root/b"))?;
    let child_a = root_a.start_child_thread_trace_or_disabled(child_metadata(
        child_a_id,
        root_a_id,
        "/root/a/child",
        "child-a",
    )?);

    root_a.record_codex_turn_started("turn-a");
    child_a.record_codex_turn_started("turn-a-child");

    let child_b = root_b.start_child_thread_trace_or_disabled(child_metadata(
        child_b_id,
        root_b_id,
        "/root/b/child",
        "child-b",
    )?);
    root_b.record_codex_turn_started("turn-b");
    child_b.record_codex_turn_started("turn-b-child");

    // Root A closes while root B remains live. Neither task may terminate the
    // App Server-owned run.
    child_a.record_ended(RolloutStatus::Completed);
    root_a.record_ended(RolloutStatus::Completed);
    child_b.record_ended(RolloutStatus::Completed);
    root_b.record_ended(RolloutStatus::Completed);
    guard.finish(RolloutStatus::Completed);
    guard.finish(RolloutStatus::Completed);

    let bundle_dir = single_bundle_dir(temp.path())?;
    let events = read_events(&bundle_dir)?;
    let root_a_id = root_a_id.to_string();
    let root_b_id = root_b_id.to_string();
    let child_a_id = child_a_id.to_string();
    let child_b_id = child_b_id.to_string();
    assert_eq!(
        events.iter().map(EventProjection::from).collect::<Vec<_>>(),
        vec![
            EventProjection::run_started(/*seq*/ 1),
            EventProjection::thread_started(/*seq*/ 2, &root_a_id, &root_a_id),
            EventProjection::thread_started(/*seq*/ 3, &root_b_id, &root_b_id),
            EventProjection::thread_started(/*seq*/ 4, &root_a_id, &child_a_id),
            EventProjection::turn_started(/*seq*/ 5, &root_a_id, &root_a_id, "turn-a"),
            EventProjection::turn_started(/*seq*/ 6, &root_a_id, &child_a_id, "turn-a-child",),
            EventProjection::thread_started(/*seq*/ 7, &root_b_id, &child_b_id),
            EventProjection::turn_started(/*seq*/ 8, &root_b_id, &root_b_id, "turn-b"),
            EventProjection::turn_started(/*seq*/ 9, &root_b_id, &child_b_id, "turn-b-child",),
            EventProjection::thread_ended(/*seq*/ 10, &root_a_id, &child_a_id),
            EventProjection::thread_ended(/*seq*/ 11, &root_a_id, &root_a_id),
            EventProjection::thread_ended(/*seq*/ 12, &root_b_id, &child_b_id),
            EventProjection::thread_ended(/*seq*/ 13, &root_b_id, &root_b_id),
            EventProjection::run_ended(/*seq*/ 14),
        ]
    );

    let replayed = replay_bundle(&bundle_dir)?;
    assert_eq!(replayed.shared_run, true);
    assert_eq!(
        replayed.task_root_thread_ids,
        vec![root_a_id.clone(), root_b_id.clone()]
    );
    assert_eq!(replayed.status, RolloutStatus::Completed);
    assert_eq!(
        replayed.threads[&root_a_id].execution.status,
        ExecutionStatus::Completed
    );
    assert_eq!(
        replayed.threads[&root_b_id].execution.status,
        ExecutionStatus::Completed
    );

    Ok(())
}

#[derive(Debug, PartialEq, Eq)]
struct EventProjection {
    seq: u64,
    task_root_thread_id: Option<String>,
    thread_id: Option<String>,
    codex_turn_id: Option<String>,
    kind: &'static str,
}

impl EventProjection {
    fn run_started(seq: u64) -> Self {
        Self {
            seq,
            task_root_thread_id: None,
            thread_id: None,
            codex_turn_id: None,
            kind: "run_started",
        }
    }

    fn run_ended(seq: u64) -> Self {
        Self {
            seq,
            task_root_thread_id: None,
            thread_id: None,
            codex_turn_id: None,
            kind: "run_ended",
        }
    }

    fn thread_started(seq: u64, task_root_thread_id: &str, thread_id: &str) -> Self {
        Self {
            seq,
            task_root_thread_id: Some(task_root_thread_id.to_string()),
            thread_id: Some(thread_id.to_string()),
            codex_turn_id: None,
            kind: "thread_started",
        }
    }

    fn thread_ended(seq: u64, task_root_thread_id: &str, thread_id: &str) -> Self {
        Self {
            seq,
            task_root_thread_id: Some(task_root_thread_id.to_string()),
            thread_id: Some(thread_id.to_string()),
            codex_turn_id: None,
            kind: "thread_ended",
        }
    }

    fn turn_started(
        seq: u64,
        task_root_thread_id: &str,
        thread_id: &str,
        codex_turn_id: &str,
    ) -> Self {
        Self {
            seq,
            task_root_thread_id: Some(task_root_thread_id.to_string()),
            thread_id: Some(thread_id.to_string()),
            codex_turn_id: Some(codex_turn_id.to_string()),
            kind: "codex_turn_started",
        }
    }
}

impl From<&RawTraceEvent> for EventProjection {
    fn from(event: &RawTraceEvent) -> Self {
        let kind = match &event.payload {
            RawTraceEventPayload::RunStarted { .. } => "run_started",
            RawTraceEventPayload::RunEnded { .. } => "run_ended",
            RawTraceEventPayload::ThreadStarted { .. } => "thread_started",
            RawTraceEventPayload::ThreadEnded { .. } => "thread_ended",
            RawTraceEventPayload::CodexTurnStarted { .. } => "codex_turn_started",
            payload => panic!("unexpected event in shared-run test: {payload:?}"),
        };
        Self {
            seq: event.seq,
            task_root_thread_id: event.task_root_thread_id.clone(),
            thread_id: event.thread_id.clone(),
            codex_turn_id: event.codex_turn_id.clone(),
            kind,
        }
    }
}

fn root_metadata(thread_id: ThreadId, agent_path: &str) -> ThreadStartedTraceMetadata {
    ThreadStartedTraceMetadata {
        thread_id: thread_id.to_string(),
        agent_path: agent_path.to_string(),
        task_name: Some(
            agent_path
                .rsplit('/')
                .next()
                .unwrap_or(agent_path)
                .to_string(),
        ),
        nickname: None,
        agent_role: Some("worker".to_string()),
        session_source: SessionSource::Exec,
        cwd: PathBuf::from("/workspace"),
        rollout_path: None,
        model: "gpt-test".to_string(),
        provider_name: "test-provider".to_string(),
        approval_policy: "never".to_string(),
        sandbox_policy: format!("{:?}", SandboxPolicy::DangerFullAccess),
    }
}

fn child_metadata(
    thread_id: ThreadId,
    parent_thread_id: ThreadId,
    agent_path: &str,
    task_name: &str,
) -> anyhow::Result<ThreadStartedTraceMetadata> {
    Ok(ThreadStartedTraceMetadata {
        thread_id: thread_id.to_string(),
        agent_path: agent_path.to_string(),
        task_name: Some(task_name.to_string()),
        nickname: None,
        agent_role: Some("worker".to_string()),
        session_source: SessionSource::SubAgent(SubAgentSource::ThreadSpawn {
            parent_thread_id,
            depth: 1,
            agent_path: Some(AgentPath::try_from(agent_path).map_err(anyhow::Error::msg)?),
            agent_nickname: None,
            agent_role: Some("worker".to_string()),
        }),
        cwd: PathBuf::from("/workspace"),
        rollout_path: None,
        model: "gpt-test".to_string(),
        provider_name: "test-provider".to_string(),
        approval_policy: "never".to_string(),
        sandbox_policy: format!("{:?}", SandboxPolicy::DangerFullAccess),
    })
}

fn read_events(bundle_dir: &Path) -> anyhow::Result<Vec<RawTraceEvent>> {
    fs::read_to_string(bundle_dir.join("trace.jsonl"))?
        .lines()
        .map(|line| serde_json::from_str(line).map_err(anyhow::Error::from))
        .collect()
}

fn single_bundle_dir(root: &Path) -> anyhow::Result<PathBuf> {
    let mut entries = fs::read_dir(root)?
        .map(|entry| entry.map(|entry| entry.path()))
        .collect::<Result<Vec<_>, _>>()?;
    entries.sort();
    assert_eq!(entries.len(), 1);
    Ok(entries.remove(0))
}
