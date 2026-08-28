//! App Server and MCP JSON-RPC packet evidence for the teaching trace.

use std::collections::HashMap;
use std::collections::VecDeque;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::OnceLock;
use std::sync::PoisonError;
use std::sync::Weak;

use serde::Deserialize;
use serde::Serialize;
use serde_json::Value;
use tracing::warn;

use crate::RawPayloadKind;
use crate::RawTraceEventContext;
use crate::RawTraceEventPayload;
use crate::TraceWriter;
use crate::thread::CODEX_ROLLOUT_TRACE_ROOT_ENV;
use crate::writer::unix_time_ms;

/// Direction of a JSON-RPC frame at a recorded boundary.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum WireFrameDirection {
    ClientToServer,
    ServerToClient,
}

/// JSON-RPC message role derived from its wire members.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum WireFrameKind {
    Request,
    Response,
    Error,
    Notification,
    Unknown,
}

/// One MCP frame and its transport-level correlation metadata.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct McpWireTaskContext {
    /// Independent root task that owns this MCP operation.
    pub root_thread_id: String,
    /// Concrete Codex thread that dispatched the operation.
    pub thread_id: String,
    /// Concrete Codex turn that dispatched the operation.
    pub codex_turn_id: String,
}

/// One MCP frame and its transport-level correlation metadata.
#[derive(Debug, Clone, PartialEq)]
pub struct McpWireFrameObservation {
    pub server_name: String,
    pub transport: String,
    pub direction: WireFrameDirection,
    pub frame_kind: WireFrameKind,
    pub method: Option<String>,
    pub request_id: Option<String>,
    pub mcp_call_id: Option<String>,
    /// Task attribution carried through the private bridge metadata, when one
    /// concrete Codex operation caused this frame.
    pub task_context: Option<McpWireTaskContext>,
    pub frame: Value,
}

#[derive(Debug)]
struct AppServerConnection {
    transport: String,
    client_requests: HashMap<String, AppServerFrameMetadata>,
    server_requests: HashMap<String, AppServerFrameMetadata>,
}

impl AppServerConnection {
    fn new(transport: String) -> Self {
        Self {
            transport,
            client_requests: HashMap::new(),
            server_requests: HashMap::new(),
        }
    }

    fn request_context(
        &mut self,
        direction: WireFrameDirection,
        frame_kind: WireFrameKind,
        request_id: Option<&str>,
    ) -> Option<AppServerFrameMetadata> {
        let Some(request_id) = request_id else {
            return None;
        };
        match (direction, frame_kind) {
            (
                WireFrameDirection::ServerToClient,
                WireFrameKind::Response | WireFrameKind::Error,
            ) => self.client_requests.remove(request_id),
            (
                WireFrameDirection::ClientToServer,
                WireFrameKind::Response | WireFrameKind::Error,
            ) => self.server_requests.remove(request_id),
            _ => None,
        }
    }

    fn remember_request(
        &mut self,
        direction: WireFrameDirection,
        frame_kind: WireFrameKind,
        request_id: Option<&str>,
        metadata: &AppServerFrameMetadata,
    ) {
        let Some(request_id) = request_id else {
            return;
        };
        match (direction, frame_kind) {
            (WireFrameDirection::ClientToServer, WireFrameKind::Request) => {
                self.client_requests
                    .insert(request_id.to_string(), metadata.clone());
            }
            (WireFrameDirection::ServerToClient, WireFrameKind::Request) => {
                self.server_requests
                    .insert(request_id.to_string(), metadata.clone());
            }
            _ => {}
        }
    }
}

/// Compact, filterable identities normalized from an App Server frame.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
struct AppServerFrameMetadata {
    method: Option<String>,
    source_thread_id: Option<String>,
    new_thread_id: Option<String>,
    codex_turn_id: Option<String>,
    item_id: Option<String>,
    forked_from_id: Option<String>,
    session_id: Option<String>,
    task_root_thread_id: Option<String>,
}

impl AppServerFrameMetadata {
    fn inherit_request_context(&mut self, request: Self) {
        self.method = self.method.take().or(request.method);
        self.source_thread_id = self.source_thread_id.take().or(request.source_thread_id);
        self.new_thread_id = self.new_thread_id.take().or(request.new_thread_id);
        self.codex_turn_id = self.codex_turn_id.take().or(request.codex_turn_id);
        self.item_id = self.item_id.take().or(request.item_id);
        self.forked_from_id = self.forked_from_id.take().or(request.forked_from_id);
        self.session_id = self.session_id.take().or(request.session_id);
        // A response belongs to the task that issued the request even when its
        // result introduces a thread that has already registered as another
        // root (notably `thread/fork`). Keep the result identity separately in
        // `new_thread_id` while preserving the originating task lane.
        self.task_root_thread_id = request
            .task_root_thread_id
            .or(self.task_root_thread_id.take());
    }
}

#[derive(Debug)]
enum PendingWireFrame {
    AppServer {
        observed_at_unix_ms: i64,
        context: RawTraceEventContext,
        connection_id: String,
        transport: String,
        direction: WireFrameDirection,
        frame_kind: WireFrameKind,
        method: Option<String>,
        request_id: Option<String>,
        metadata: AppServerFrameMetadata,
        frame: Value,
    },
    Mcp {
        observed_at_unix_ms: i64,
        observation: McpWireFrameObservation,
    },
}

#[derive(Default)]
struct WireTraceHub {
    active_writer: Option<Weak<TraceWriter>>,
    buffered: VecDeque<PendingWireFrame>,
    app_server_connections: HashMap<String, AppServerConnection>,
    task_roots_by_thread_id: HashMap<String, String>,
}

impl WireTraceHub {
    fn writer(&mut self) -> Option<Arc<TraceWriter>> {
        let writer = self.active_writer.as_ref().and_then(Weak::upgrade);
        if writer.is_none() {
            self.active_writer = None;
        }
        writer
    }

    fn append_or_buffer(&mut self, pending: PendingWireFrame) {
        match self.writer() {
            Some(writer) => append_pending(&writer, pending),
            None => self.buffered.push_back(pending),
        }
    }
}

static WIRE_TRACE_HUB: OnceLock<Mutex<WireTraceHub>> = OnceLock::new();

fn hub() -> &'static Mutex<WireTraceHub> {
    WIRE_TRACE_HUB.get_or_init(|| Mutex::new(WireTraceHub::default()))
}

fn lock_hub() -> std::sync::MutexGuard<'static, WireTraceHub> {
    hub().lock().unwrap_or_else(PoisonError::into_inner)
}

fn capture_enabled() -> bool {
    std::env::var_os(CODEX_ROLLOUT_TRACE_ROOT_ENV).is_some()
}

/// Records one App Server connection for subsequent JSON-RPC frame capture.
pub fn register_app_server_connection(
    connection_id: impl Into<String>,
    transport: impl Into<String>,
) {
    if !capture_enabled() {
        return;
    }
    lock_hub().app_server_connections.insert(
        connection_id.into(),
        AppServerConnection::new(transport.into()),
    );
}

/// Removes App Server connection metadata after disconnect.
pub fn unregister_app_server_connection(connection_id: &str) {
    if !capture_enabled() {
        return;
    }
    lock_hub().app_server_connections.remove(connection_id);
}

/// Registers the owning root task for a thread whose trace context is live.
///
/// The App Server's raw JSON-RPC frames may reference only a thread or turn.
/// Keeping this small lookup inside the trace hub lets those frames join the
/// right independent task tree without relying on timing heuristics.
pub(crate) fn register_task_root_thread(
    thread_id: impl Into<String>,
    task_root_thread_id: impl Into<String>,
) {
    lock_hub()
        .task_roots_by_thread_id
        .insert(thread_id.into(), task_root_thread_id.into());
}

/// Records one exact App Server JSON-RPC frame.
pub fn record_app_server_frame(
    connection_id: impl Into<String>,
    direction: WireFrameDirection,
    frame: &impl Serialize,
) {
    if !capture_enabled() {
        return;
    }
    let frame = match serde_json::to_value(frame) {
        Ok(frame) => frame,
        Err(error) => {
            warn!("failed to serialize App Server frame for rollout trace: {error}");
            return;
        }
    };
    let connection_id = connection_id.into();
    let (frame_kind, method, request_id) = analyze_frame(&frame);
    let mut hub = lock_hub();
    let request_metadata = hub
        .app_server_connections
        .entry(connection_id.clone())
        .or_insert_with(|| AppServerConnection::new("unknown".to_string()))
        .request_context(direction, frame_kind, request_id.as_deref());
    let method = method.or_else(|| {
        request_metadata
            .as_ref()
            .and_then(|metadata| metadata.method.clone())
    });
    let mut metadata = app_server_frame_metadata(&frame, method.clone());
    metadata.task_root_thread_id = task_root_thread_id(&metadata, &hub.task_roots_by_thread_id);
    if let Some(request_metadata) = request_metadata {
        metadata.inherit_request_context(request_metadata);
    }
    let connection = hub
        .app_server_connections
        .entry(connection_id.clone())
        .or_insert_with(|| AppServerConnection::new("unknown".to_string()));
    connection.remember_request(direction, frame_kind, request_id.as_deref(), &metadata);
    let context = app_server_frame_context(&metadata);
    let pending = PendingWireFrame::AppServer {
        observed_at_unix_ms: unix_time_ms(),
        context,
        connection_id,
        transport: connection.transport.clone(),
        direction,
        frame_kind,
        method: metadata.method.clone(),
        request_id,
        metadata,
        frame,
    };
    hub.append_or_buffer(pending);
}

/// Records one exact MCP JSON-RPC frame.
pub fn record_mcp_frame(observation: McpWireFrameObservation) {
    if !capture_enabled() {
        return;
    }
    lock_hub().append_or_buffer(PendingWireFrame::Mcp {
        observed_at_unix_ms: unix_time_ms(),
        observation,
    });
}

pub(crate) fn activate_wire_trace(writer: &Arc<TraceWriter>) {
    let mut hub = lock_hub();
    if let Some(active) = hub.writer()
        && !Arc::ptr_eq(&active, writer)
    {
        warn!("rollout wire trace already has an active root; keeping the first trace sink");
        return;
    }
    hub.active_writer = Some(Arc::downgrade(writer));
    while let Some(pending) = hub.buffered.pop_front() {
        append_pending(writer, pending);
    }
}

pub(crate) fn deactivate_wire_trace(writer: &Arc<TraceWriter>) {
    let mut hub = lock_hub();
    if hub
        .writer()
        .is_some_and(|active| Arc::ptr_eq(&active, writer))
    {
        hub.active_writer = None;
    }
}

/// Clears App Server-specific wire state after a shared trace run ends.
///
/// A process-local hub outlives individual App Server instances in tests and
/// embedded hosts. Shared-run ownership is the authority that can safely clear
/// queued frames, connection correlations, and task attribution together.
pub(crate) fn finish_shared_wire_trace(writer: Option<&Arc<TraceWriter>>) {
    let mut hub = lock_hub();
    if writer.is_none_or(|writer| {
        hub.writer()
            .is_some_and(|active| Arc::ptr_eq(&active, writer))
    }) {
        hub.active_writer = None;
    }
    hub.buffered.clear();
    hub.app_server_connections.clear();
    hub.task_roots_by_thread_id.clear();
}

fn append_pending(writer: &TraceWriter, pending: PendingWireFrame) {
    let result = match pending {
        PendingWireFrame::AppServer {
            observed_at_unix_ms,
            context,
            connection_id,
            transport,
            direction,
            frame_kind,
            method,
            request_id,
            metadata,
            frame,
        } => writer
            .write_json_payload(RawPayloadKind::AppServerFrame, &frame)
            .and_then(|frame_payload| {
                writer.append_with_context_at(
                    context,
                    RawTraceEventPayload::AppServerFrameObserved {
                        connection_id,
                        transport,
                        direction,
                        frame_kind,
                        method,
                        request_id,
                        source_thread_id: metadata.source_thread_id,
                        new_thread_id: metadata.new_thread_id,
                        item_id: metadata.item_id,
                        forked_from_id: metadata.forked_from_id,
                        session_id: metadata.session_id,
                        frame_payload,
                    },
                    observed_at_unix_ms,
                )
            }),
        PendingWireFrame::Mcp {
            observed_at_unix_ms,
            observation,
        } => writer
            .write_json_payload(RawPayloadKind::McpFrame, &observation.frame)
            .and_then(|frame_payload| {
                writer.append_with_context_at(
                    observation.task_context.as_ref().map_or_else(
                        RawTraceEventContext::default,
                        |task_context| RawTraceEventContext {
                            task_root_thread_id: Some(task_context.root_thread_id.clone()),
                            thread_id: Some(task_context.thread_id.clone()),
                            codex_turn_id: Some(task_context.codex_turn_id.clone()),
                        },
                    ),
                    RawTraceEventPayload::McpFrameObserved {
                        server_name: observation.server_name,
                        transport: observation.transport,
                        direction: observation.direction,
                        frame_kind: observation.frame_kind,
                        method: observation.method,
                        request_id: observation.request_id,
                        mcp_call_id: observation.mcp_call_id,
                        frame_payload,
                    },
                    observed_at_unix_ms,
                )
            }),
    };
    if let Err(error) = result {
        warn!("failed to append wire frame to rollout trace: {error:#}");
    }
}

fn analyze_frame(frame: &Value) -> (WireFrameKind, Option<String>, Option<String>) {
    let method = frame
        .get("method")
        .and_then(Value::as_str)
        .map(str::to_string);
    let request_id = frame.get("id").and_then(request_id_string);
    let frame_kind = if method.is_some() {
        if request_id.is_some() {
            WireFrameKind::Request
        } else {
            WireFrameKind::Notification
        }
    } else if frame.get("error").is_some() {
        WireFrameKind::Error
    } else if frame.get("result").is_some() {
        WireFrameKind::Response
    } else {
        WireFrameKind::Unknown
    };
    (frame_kind, method, request_id)
}

fn request_id_string(value: &Value) -> Option<String> {
    match value {
        Value::String(value) => Some(value.clone()),
        Value::Number(value) => Some(value.to_string()),
        _ => None,
    }
}

fn app_server_frame_metadata(frame: &Value, method: Option<String>) -> AppServerFrameMetadata {
    let is_new_thread_result = matches!(method.as_deref(), Some("thread/start" | "thread/fork"));
    let is_thread_started = method.as_deref() == Some("thread/started");
    AppServerFrameMetadata {
        method,
        source_thread_id: if is_thread_started {
            None
        } else {
            value_at_paths(frame, ["/params/threadId", "/params/thread/id"]).or_else(|| {
                if is_new_thread_result {
                    None
                } else {
                    value_at_paths(frame, ["/result/threadId", "/result/thread/id"])
                }
            })
        },
        new_thread_id: (is_new_thread_result
            .then(|| value_at_paths(frame, ["/result/thread/id", "/result/threadId"]))
            .flatten())
        .or_else(|| {
            is_thread_started
                .then(|| value_at_paths(frame, ["/params/thread/id", "/params/threadId"]))
                .flatten()
        }),
        codex_turn_id: value_at_paths(
            frame,
            [
                "/params/turnId",
                "/params/expectedTurnId",
                "/params/turn/id",
                "/result/turn/id",
                "/result/turnId",
            ],
        ),
        item_id: value_at_paths(frame, ["/params/item/id"]),
        forked_from_id: value_at_paths(
            frame,
            ["/result/thread/forkedFromId", "/params/thread/forkedFromId"],
        ),
        session_id: value_at_paths(
            frame,
            ["/result/thread/sessionId", "/params/thread/sessionId"],
        ),
        task_root_thread_id: None,
    }
}

fn task_root_thread_id(
    metadata: &AppServerFrameMetadata,
    task_roots_by_thread_id: &HashMap<String, String>,
) -> Option<String> {
    metadata
        .source_thread_id
        .as_ref()
        .or(metadata.new_thread_id.as_ref())
        .and_then(|thread_id| task_roots_by_thread_id.get(thread_id))
        .cloned()
}

fn app_server_frame_context(metadata: &AppServerFrameMetadata) -> RawTraceEventContext {
    RawTraceEventContext {
        task_root_thread_id: metadata.task_root_thread_id.clone(),
        thread_id: metadata
            .source_thread_id
            .clone()
            .or_else(|| metadata.new_thread_id.clone()),
        codex_turn_id: metadata.codex_turn_id.clone(),
    }
}

fn value_at_paths<const N: usize>(frame: &Value, paths: [&str; N]) -> Option<String> {
    paths.into_iter().find_map(|path| {
        frame
            .pointer(path)
            .and_then(Value::as_str)
            .map(str::to_string)
    })
}

#[cfg(test)]
#[path = "wire_tests.rs"]
mod tests;
