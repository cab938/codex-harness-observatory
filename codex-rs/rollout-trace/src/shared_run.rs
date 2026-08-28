//! App Server-lifetime ownership for one lazily created shared trace run.
//!
//! A normal CLI or TUI session owns one trace bundle per root task. Desktop's
//! App Server can serve several independent roots at once, so it installs this
//! guard once and lets each root attach to one writer. The guard, rather than
//! any task, owns the one terminal run event.

use std::path::PathBuf;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::OnceLock;
use std::sync::PoisonError;
use std::sync::Weak;

use anyhow::Result;
use anyhow::bail;
use tracing::debug;
use tracing::warn;
use uuid::Uuid;

use crate::RawTraceEventPayload;
use crate::RolloutStatus;
#[cfg(test)]
use crate::ThreadStartedTraceMetadata;
#[cfg(test)]
use crate::ThreadTraceContext;
use crate::TraceWriter;
use crate::thread::CODEX_ROLLOUT_TRACE_ROOT_ENV;
use crate::wire::activate_wire_trace;
use crate::wire::finish_shared_wire_trace;

/// Opts an App Server into one trace run shared by every independent root task.
pub const CODEX_ROLLOUT_TRACE_SHARED_RUN_ENV: &str = "CODEX_ROLLOUT_TRACE_SHARED_RUN";

#[derive(Debug)]
struct SharedRun {
    trace_root: PathBuf,
    inner: Mutex<SharedRunInner>,
}

#[derive(Debug, Default)]
struct SharedRunInner {
    writer: Option<Arc<TraceWriter>>,
    ended: bool,
}

/// Authority guard for one App Server-wide shared trace run.
///
/// Install this at App Server startup and retain it until after all server
/// threads have drained. It creates no bundle until the first independent root
/// task starts, and it emits one `RunEnded` event exactly once on finish.
#[derive(Debug)]
pub struct AppServerSharedRunGuard {
    run: Option<Arc<SharedRun>>,
}

impl AppServerSharedRunGuard {
    /// Installs a shared-run authority when both trace environment gates are set.
    pub fn install_from_env_or_disabled() -> Self {
        if !shared_run_enabled() {
            return Self::disabled();
        }
        let Some(trace_root) = std::env::var_os(CODEX_ROLLOUT_TRACE_ROOT_ENV) else {
            warn!(
                "{} is set but {} is absent; shared rollout tracing is disabled",
                CODEX_ROLLOUT_TRACE_SHARED_RUN_ENV, CODEX_ROLLOUT_TRACE_ROOT_ENV
            );
            return Self::disabled();
        };
        Self::install(PathBuf::from(trace_root))
    }

    /// Attaches an independent root task to this App Server's shared writer.
    ///
    /// This keeps the authority boundary explicit in shared-run tests.
    #[cfg(test)]
    pub(crate) fn start_root(
        &self,
        metadata: ThreadStartedTraceMetadata,
    ) -> Result<ThreadTraceContext> {
        let Some(run) = &self.run else {
            bail!("shared trace run is disabled");
        };
        let task_root_thread_id = metadata.thread_id.clone();
        let writer = run.attach_root(&task_root_thread_id)?;
        Ok(ThreadTraceContext::start_shared_root(
            writer,
            task_root_thread_id,
            metadata,
        ))
    }

    /// Ends the shared run at most once.
    ///
    /// Server shutdown normally calls this with `Completed`; `Drop` supplies an
    /// `Aborted` fallback for early returns and unwinding.
    pub fn finish(&self, status: RolloutStatus) {
        let Some(run) = &self.run else {
            return;
        };
        run.finish_once(status);
        clear_active_shared_run(run);
    }

    fn disabled() -> Self {
        Self { run: None }
    }

    fn install(trace_root: PathBuf) -> Self {
        let mut active = lock_active_shared_run();
        if active.as_ref().and_then(Weak::upgrade).is_some() {
            warn!("shared rollout trace authority already installed; leaving existing run active");
            return Self::disabled();
        }

        let run = Arc::new(SharedRun {
            trace_root,
            inner: Mutex::new(SharedRunInner::default()),
        });
        *active = Some(Arc::downgrade(&run));
        Self { run: Some(run) }
    }
}

impl Drop for AppServerSharedRunGuard {
    fn drop(&mut self) {
        self.finish(RolloutStatus::Aborted);
    }
}

impl SharedRun {
    fn attach_root(&self, task_root_thread_id: &str) -> Result<Arc<TraceWriter>> {
        let mut inner = self.lock_inner();
        if inner.ended {
            bail!("shared trace run has already ended");
        }
        if let Some(writer) = &inner.writer {
            return Ok(Arc::clone(writer));
        }

        let trace_id = Uuid::new_v4().to_string();
        let run_id = format!("run:{trace_id}");
        let bundle_dir = self.trace_root.join(format!("trace-{trace_id}-shared"));
        let writer = Arc::new(TraceWriter::create_shared_run(
            &bundle_dir,
            trace_id.clone(),
            run_id,
            task_root_thread_id.to_string(),
        )?);
        inner.writer = Some(Arc::clone(&writer));

        if let Err(err) = writer.append(RawTraceEventPayload::RunStarted { trace_id }) {
            warn!("failed to append shared rollout trace start event: {err:#}");
        }
        activate_wire_trace(&writer);
        debug!("recording shared rollout trace at {}", bundle_dir.display());
        Ok(writer)
    }

    fn finish_once(&self, status: RolloutStatus) {
        let writer = {
            let mut inner = self.lock_inner();
            if inner.ended {
                return;
            }
            inner.ended = true;
            inner.writer.clone()
        };

        if let Some(writer) = &writer
            && let Err(err) = writer.append(RawTraceEventPayload::RunEnded { status })
        {
            warn!("failed to append shared rollout trace end event: {err:#}");
        }
        finish_shared_wire_trace(writer.as_ref());
    }

    fn lock_inner(&self) -> std::sync::MutexGuard<'_, SharedRunInner> {
        self.inner.lock().unwrap_or_else(PoisonError::into_inner)
    }
}

static ACTIVE_SHARED_RUN: OnceLock<Mutex<Option<Weak<SharedRun>>>> = OnceLock::new();

fn active_shared_run() -> Option<Arc<SharedRun>> {
    let mut active = lock_active_shared_run();
    let run = active.as_ref().and_then(Weak::upgrade);
    if run.is_none() {
        *active = None;
    }
    run
}

fn clear_active_shared_run(run: &Arc<SharedRun>) {
    let mut active = lock_active_shared_run();
    if active
        .as_ref()
        .and_then(Weak::upgrade)
        .is_some_and(|active| Arc::ptr_eq(&active, run))
    {
        *active = None;
    }
}

fn lock_active_shared_run() -> std::sync::MutexGuard<'static, Option<Weak<SharedRun>>> {
    ACTIVE_SHARED_RUN
        .get_or_init(|| Mutex::new(None))
        .lock()
        .unwrap_or_else(PoisonError::into_inner)
}

fn shared_run_enabled() -> bool {
    matches!(
        std::env::var(CODEX_ROLLOUT_TRACE_SHARED_RUN_ENV).as_deref(),
        Ok("1") | Ok("true")
    )
}

/// Returns the writer owned by the active App Server shared run, if any.
pub(crate) fn attach_shared_root_if_active(
    task_root_thread_id: &str,
) -> Option<Result<Arc<TraceWriter>>> {
    active_shared_run().map(|run| run.attach_root(task_root_thread_id))
}

#[cfg(test)]
#[path = "shared_run_tests.rs"]
mod tests;
