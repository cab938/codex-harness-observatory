//! Exact MCP JSON-RPC frame capture at the rmcp transport boundary.

use std::collections::HashMap;
use std::future::Future;

use codex_rollout_trace::CODEX_ROLLOUT_TRACE_ROOT_ENV;
use codex_rollout_trace::MCP_TRACE_META_KEY;
use codex_rollout_trace::McpWireFrameObservation;
use codex_rollout_trace::McpWireTaskContext;
use codex_rollout_trace::WireFrameDirection;
use codex_rollout_trace::WireFrameKind;
use codex_rollout_trace::record_mcp_frame;
use rmcp::model::ClientRequest;
use rmcp::model::JsonRpcMessage;
use rmcp::model::RequestMetaObject;
use rmcp::service::RoleClient;
use rmcp::service::RxJsonRpcMessage;
use rmcp::service::TxJsonRpcMessage;
use rmcp::transport::Transport;
use serde::Serialize;
use serde_json::Value;
use tracing::warn;

const LEGACY_MCP_CALL_ID_META_KEY: &str = "codex_bridge_mcp_call_id";

#[derive(Debug, Clone, PartialEq)]
struct RequestCorrelation {
    method: Option<String>,
    mcp_call_id: Option<String>,
    task_context: Option<McpWireTaskContext>,
}

/// Transparent transport wrapper that records the typed frames rmcp sends and receives.
pub(crate) struct WireTraceTransport<T> {
    inner: T,
    enabled: bool,
    server_name: String,
    transport: String,
    client_requests: HashMap<String, RequestCorrelation>,
    server_requests: HashMap<String, RequestCorrelation>,
}

impl<T> WireTraceTransport<T> {
    pub(crate) fn new(
        inner: T,
        server_name: impl Into<String>,
        transport: impl Into<String>,
    ) -> Self {
        Self {
            inner,
            enabled: std::env::var_os(CODEX_ROLLOUT_TRACE_ROOT_ENV).is_some(),
            server_name: server_name.into(),
            transport: transport.into(),
            client_requests: HashMap::new(),
            server_requests: HashMap::new(),
        }
    }

    fn observe(
        &mut self,
        direction: WireFrameDirection,
        message: &impl Serialize,
        bridge_trace: Option<RequestCorrelation>,
    ) {
        if !self.enabled {
            return;
        }
        let frame = match serde_json::to_value(message) {
            Ok(frame) => frame,
            Err(error) => {
                warn!("failed to serialize MCP frame for rollout trace: {error}");
                return;
            }
        };
        let (frame_kind, method, request_id) = analyze_frame(&frame);
        let observed = RequestCorrelation {
            method,
            mcp_call_id: None,
            task_context: None,
        };
        let correlation = self.correlate(
            direction,
            frame_kind,
            request_id.as_deref(),
            merge_correlation(observed, bridge_trace),
        );
        record_mcp_frame(McpWireFrameObservation {
            server_name: self.server_name.clone(),
            transport: self.transport.clone(),
            direction,
            frame_kind,
            method: correlation.method,
            request_id,
            mcp_call_id: correlation.mcp_call_id,
            task_context: correlation.task_context,
            frame,
        });
    }

    fn correlate(
        &mut self,
        direction: WireFrameDirection,
        frame_kind: WireFrameKind,
        request_id: Option<&str>,
        correlation: RequestCorrelation,
    ) -> RequestCorrelation {
        let Some(request_id) = request_id else {
            return correlation;
        };
        match (direction, frame_kind) {
            (WireFrameDirection::ClientToServer, WireFrameKind::Request) => {
                self.client_requests
                    .insert(request_id.to_string(), correlation.clone());
                correlation
            }
            (WireFrameDirection::ServerToClient, WireFrameKind::Request) => {
                self.server_requests
                    .insert(request_id.to_string(), correlation.clone());
                correlation
            }
            (
                WireFrameDirection::ServerToClient,
                WireFrameKind::Response | WireFrameKind::Error,
            ) => merge_correlation(correlation, self.client_requests.remove(request_id)),
            (
                WireFrameDirection::ClientToServer,
                WireFrameKind::Response | WireFrameKind::Error,
            ) => merge_correlation(correlation, self.server_requests.remove(request_id)),
            (_, WireFrameKind::Notification | WireFrameKind::Unknown) => correlation,
        }
    }
}

impl<T> Transport<RoleClient> for WireTraceTransport<T>
where
    T: Transport<RoleClient> + 'static,
{
    type Error = T::Error;

    fn send(
        &mut self,
        mut message: TxJsonRpcMessage<RoleClient>,
    ) -> impl Future<Output = Result<(), Self::Error>> + Send + 'static {
        let bridge_trace = take_bridge_trace(&mut message);
        self.observe(WireFrameDirection::ClientToServer, &message, bridge_trace);
        self.inner.send(message)
    }

    async fn receive(&mut self) -> Option<RxJsonRpcMessage<RoleClient>> {
        let message = self.inner.receive().await;
        if let Some(message) = message.as_ref() {
            self.observe(
                WireFrameDirection::ServerToClient,
                message,
                /*bridge_trace*/ None,
            );
        }
        message
    }

    fn close(&mut self) -> impl Future<Output = Result<(), Self::Error>> + Send {
        self.inner.close()
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

fn merge_correlation(
    observed: RequestCorrelation,
    correlation: Option<RequestCorrelation>,
) -> RequestCorrelation {
    let Some(correlation) = correlation else {
        return observed;
    };
    RequestCorrelation {
        method: observed.method.or(correlation.method),
        mcp_call_id: observed.mcp_call_id.or(correlation.mcp_call_id),
        task_context: observed.task_context.or(correlation.task_context),
    }
}

/// Moves bridge-only trace metadata out of one outgoing MCP tool request.
///
/// The wrapper saves the correlation before forwarding the typed message, so
/// task attribution remains local to Codex and never reaches the MCP server.
/// Both parameter metadata and the legacy request-extension metadata path are
/// supported because rmcp uses each depending on the negotiated protocol mode.
fn take_bridge_trace(message: &mut TxJsonRpcMessage<RoleClient>) -> Option<RequestCorrelation> {
    let JsonRpcMessage::Request(request) = message else {
        return None;
    };
    let ClientRequest::CallToolRequest(call) = &mut request.request else {
        return None;
    };

    merge_optional_correlation(
        take_bridge_trace_from_params_meta(&mut call.params.meta),
        take_bridge_trace_from_extensions(&mut call.extensions),
    )
}

fn take_bridge_trace_from_params_meta(
    meta: &mut Option<RequestMetaObject>,
) -> Option<RequestCorrelation> {
    let mut request_meta = meta.take()?;
    let trace = take_bridge_trace_from_meta(&mut request_meta);
    if !request_meta.is_empty() {
        *meta = Some(request_meta);
    }
    trace
}

fn take_bridge_trace_from_extensions(
    extensions: &mut rmcp::model::Extensions,
) -> Option<RequestCorrelation> {
    let mut meta = extensions.remove::<RequestMetaObject>()?;
    let trace = take_bridge_trace_from_meta(&mut meta);
    if !meta.is_empty() {
        extensions.insert(meta);
    }
    trace
}

fn take_bridge_trace_from_meta(meta: &mut RequestMetaObject) -> Option<RequestCorrelation> {
    let trace = meta.remove(MCP_TRACE_META_KEY);
    let legacy_mcp_call_id = meta
        .remove(LEGACY_MCP_CALL_ID_META_KEY)
        .and_then(|value| value.as_str().map(str::to_string));
    let trace = trace.and_then(|trace| trace.as_object().cloned());

    let mcp_call_id = trace
        .as_ref()
        .and_then(|trace| trace.get("mcp_call_id"))
        .and_then(Value::as_str)
        .map(str::to_string)
        .or(legacy_mcp_call_id);
    let task_context = trace.as_ref().and_then(|trace| {
        Some(McpWireTaskContext {
            root_thread_id: trace.get("root_thread_id")?.as_str()?.to_string(),
            thread_id: trace.get("thread_id")?.as_str()?.to_string(),
            codex_turn_id: trace.get("codex_turn_id")?.as_str()?.to_string(),
        })
    });

    (mcp_call_id.is_some() || task_context.is_some()).then_some(RequestCorrelation {
        method: None,
        mcp_call_id,
        task_context,
    })
}

fn merge_optional_correlation(
    first: Option<RequestCorrelation>,
    second: Option<RequestCorrelation>,
) -> Option<RequestCorrelation> {
    match (first, second) {
        (Some(first), Some(second)) => Some(merge_correlation(first, Some(second))),
        (Some(correlation), None) | (None, Some(correlation)) => Some(correlation),
        (None, None) => None,
    }
}

#[cfg(test)]
#[path = "wire_trace_transport_tests.rs"]
mod tests;
