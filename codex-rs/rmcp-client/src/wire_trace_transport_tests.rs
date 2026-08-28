use codex_rollout_trace::McpWireTaskContext;
use pretty_assertions::assert_eq;
use rmcp::model::CallToolRequest;
use rmcp::model::CallToolRequestParams;
use rmcp::model::ClientJsonRpcMessage;
use rmcp::model::ClientRequest;
use rmcp::model::RequestId;
use rmcp::model::RequestMetaObject;
use serde_json::Value;
use serde_json::json;

use super::MCP_TRACE_META_KEY;
use super::RequestCorrelation;
use super::WireFrameDirection;
use super::WireTraceTransport;
use super::analyze_frame;
use super::merge_correlation;
use super::take_bridge_trace;

#[test]
fn overlapping_task_contexts_with_reused_json_rpc_ids_keep_responses_attributed() {
    let task_one = task_context("task-root-one", "thread-one", "turn-one");
    let task_two = task_context("task-root-two", "thread-two", "turn-two");
    let mut request_one = call_tool_request("mcp-call-one", &task_one);
    let mut request_two = call_tool_request("mcp-call-two", &task_two);

    let request_one_bridge = take_bridge_trace(&mut request_one).expect("first bridge trace");
    let request_two_bridge = take_bridge_trace(&mut request_two).expect("second bridge trace");
    let request_one_frame = serde_json::to_value(&request_one).expect("first request serializes");
    let request_two_frame = serde_json::to_value(&request_two).expect("second request serializes");
    assert_eq!(
        request_one_frame.pointer("/params/_meta/codex_bridge_mcp_trace"),
        None
    );
    assert_eq!(
        request_two_frame.pointer("/params/_meta/codex_bridge_mcp_trace"),
        None
    );
    assert_eq!(
        request_one_frame.pointer("/params/_meta/source"),
        Some(&json!("test"))
    );
    assert_eq!(
        request_two_frame.pointer("/params/_meta/source"),
        Some(&json!("test"))
    );

    let mut task_one_transport = WireTraceTransport::new((), "filesystem", "stdio");
    let mut task_two_transport = WireTraceTransport::new((), "filesystem", "stdio");
    let task_one_request = correlate_outgoing(
        &mut task_one_transport,
        &request_one_frame,
        request_one_bridge,
    );
    let task_two_request = correlate_outgoing(
        &mut task_two_transport,
        &request_two_frame,
        request_two_bridge,
    );
    let response = json!({
        "jsonrpc": "2.0",
        "id": 7,
        "result": {"content": []}
    });
    let task_one_response = correlate_incoming(&mut task_one_transport, &response);
    let task_two_response = correlate_incoming(&mut task_two_transport, &response);

    assert_eq!(
        task_one_request,
        RequestCorrelation {
            method: Some("tools/call".to_string()),
            mcp_call_id: Some("mcp-call-one".to_string()),
            task_context: Some(task_one),
        }
    );
    assert_eq!(
        task_two_request,
        RequestCorrelation {
            method: Some("tools/call".to_string()),
            mcp_call_id: Some("mcp-call-two".to_string()),
            task_context: Some(task_two),
        }
    );
    assert_eq!(task_one_response, task_one_request);
    assert_eq!(task_two_response, task_two_request);
}

#[test]
fn bridge_trace_in_legacy_request_extensions_stays_off_the_wire() {
    let context = task_context("task-root", "thread", "turn");
    let mut request = call_tool_request("mcp-call", &context);
    let ClientJsonRpcMessage::Request(request_message) = &mut request else {
        panic!("test request should be a JSON-RPC request");
    };
    let ClientRequest::CallToolRequest(call) = &mut request_message.request else {
        panic!("test request should be tools/call");
    };
    let meta = call.params.meta.take().expect("params metadata");
    call.extensions.insert(meta);

    let bridge = take_bridge_trace(&mut request).expect("bridge trace");
    let frame = serde_json::to_value(&request).expect("request serializes");

    assert_eq!(
        bridge,
        RequestCorrelation {
            method: None,
            mcp_call_id: Some("mcp-call".to_string()),
            task_context: Some(context),
        }
    );
    assert_eq!(frame.pointer("/params/_meta/codex_bridge_mcp_trace"), None);
    assert_eq!(frame.pointer("/params/_meta/source"), Some(&json!("test")));
}

fn task_context(root_thread_id: &str, thread_id: &str, codex_turn_id: &str) -> McpWireTaskContext {
    McpWireTaskContext {
        root_thread_id: root_thread_id.to_string(),
        thread_id: thread_id.to_string(),
        codex_turn_id: codex_turn_id.to_string(),
    }
}

fn call_tool_request(mcp_call_id: &str, task_context: &McpWireTaskContext) -> ClientJsonRpcMessage {
    let mut meta = RequestMetaObject::new();
    meta.insert("source".to_string(), json!("test"));
    meta.insert(
        MCP_TRACE_META_KEY.to_string(),
        json!({
            "mcp_call_id": mcp_call_id,
            "root_thread_id": task_context.root_thread_id.as_str(),
            "thread_id": task_context.thread_id.as_str(),
            "codex_turn_id": task_context.codex_turn_id.as_str(),
        }),
    );
    let mut params = CallToolRequestParams::new("read_resource");
    params.meta = Some(meta);
    ClientJsonRpcMessage::request(
        ClientRequest::CallToolRequest(CallToolRequest::new(params)),
        RequestId::Number(7),
    )
}

fn correlate_outgoing(
    transport: &mut WireTraceTransport<()>,
    frame: &Value,
    bridge: RequestCorrelation,
) -> RequestCorrelation {
    let (frame_kind, method, request_id) = analyze_frame(frame);
    transport.correlate(
        WireFrameDirection::ClientToServer,
        frame_kind,
        request_id.as_deref(),
        merge_correlation(
            RequestCorrelation {
                method,
                mcp_call_id: None,
                task_context: None,
            },
            Some(bridge),
        ),
    )
}

fn correlate_incoming(transport: &mut WireTraceTransport<()>, frame: &Value) -> RequestCorrelation {
    let (frame_kind, method, request_id) = analyze_frame(frame);
    transport.correlate(
        WireFrameDirection::ServerToClient,
        frame_kind,
        request_id.as_deref(),
        RequestCorrelation {
            method,
            mcp_call_id: None,
            task_context: None,
        },
    )
}
