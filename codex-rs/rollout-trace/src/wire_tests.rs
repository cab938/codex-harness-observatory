use std::collections::HashMap;
use std::fs::File;
use std::io::BufRead;
use std::io::BufReader;

use pretty_assertions::assert_eq;
use serde_json::json;
use tempfile::TempDir;

use super::AppServerConnection;
use super::AppServerFrameMetadata;
use super::PendingWireFrame;
use super::WireFrameDirection;
use super::WireFrameKind;
use super::analyze_frame;
use super::app_server_frame_context;
use super::app_server_frame_metadata;
use super::append_pending;
use super::task_root_thread_id;
use crate::RawPayloadKind;
use crate::RawPayloadRef;
use crate::RawTraceEvent;
use crate::RawTraceEventContext;
use crate::RawTraceEventPayload;
use crate::TraceWriter;
use crate::bundle::RAW_EVENT_LOG_FILE_NAME;

fn metadata(frame: serde_json::Value, method: &str) -> AppServerFrameMetadata {
    app_server_frame_metadata(&frame, Some(method.to_string()))
}

fn expected_metadata(
    method: &str,
    source_thread_id: Option<&str>,
    new_thread_id: Option<&str>,
    codex_turn_id: Option<&str>,
    item_id: Option<&str>,
    forked_from_id: Option<&str>,
    session_id: Option<&str>,
    task_root_thread_id: Option<&str>,
) -> AppServerFrameMetadata {
    AppServerFrameMetadata {
        method: Some(method.to_string()),
        source_thread_id: source_thread_id.map(str::to_string),
        new_thread_id: new_thread_id.map(str::to_string),
        codex_turn_id: codex_turn_id.map(str::to_string),
        item_id: item_id.map(str::to_string),
        forked_from_id: forked_from_id.map(str::to_string),
        session_id: session_id.map(str::to_string),
        task_root_thread_id: task_root_thread_id.map(str::to_string),
    }
}

#[test]
fn thread_start_result_normalizes_new_thread_identity() {
    assert_eq!(
        metadata(
            json!({
                "result": {"thread": {
                    "id": "thread-new",
                    "sessionId": "session-new",
                    "forkedFromId": null
                }}
            }),
            "thread/start"
        ),
        expected_metadata(
            "thread/start",
            None,
            Some("thread-new"),
            None,
            None,
            None,
            Some("session-new"),
            None,
        )
    );
}

#[test]
fn turn_start_response_inherits_request_context() {
    let request = json!({
        "id": 42,
        "method": "turn/start",
        "params": {"threadId": "thread-source", "input": []}
    });
    let response = json!({"id": 42, "result": {"turn": {"id": "turn-new"}}});
    let task_roots = HashMap::from([("thread-source".to_string(), "thread-root".to_string())]);
    let mut connection = AppServerConnection::new("websocket".to_string());

    let (request_kind, request_method, request_id) = analyze_frame(&request);
    let mut request_metadata = app_server_frame_metadata(&request, request_method);
    request_metadata.task_root_thread_id = task_root_thread_id(&request_metadata, &task_roots);
    connection.remember_request(
        WireFrameDirection::ClientToServer,
        request_kind,
        request_id.as_deref(),
        &request_metadata,
    );

    let (response_kind, response_method, response_id) = analyze_frame(&response);
    let inherited = connection
        .request_context(
            WireFrameDirection::ServerToClient,
            response_kind,
            response_id.as_deref(),
        )
        .expect("request metadata");
    let mut response_metadata = app_server_frame_metadata(&response, inherited.method.clone());
    response_metadata.task_root_thread_id = task_root_thread_id(&response_metadata, &task_roots);
    response_metadata.inherit_request_context(inherited);

    assert_eq!(response_kind, WireFrameKind::Response);
    assert_eq!(response_method, None);
    assert_eq!(
        response_metadata,
        expected_metadata(
            "turn/start",
            Some("thread-source"),
            None,
            Some("turn-new"),
            None,
            None,
            None,
            Some("thread-root"),
        )
    );
    assert_eq!(
        app_server_frame_context(&response_metadata),
        RawTraceEventContext {
            task_root_thread_id: Some("thread-root".to_string()),
            thread_id: Some("thread-source".to_string()),
            codex_turn_id: Some("turn-new".to_string()),
        }
    );
}

#[test]
fn item_lifecycle_notifications_normalize_thread_turn_and_item() {
    let frames = [
        (
            "item/started",
            json!({"params": {
                "threadId": "thread-1", "turnId": "turn-1", "item": {"id": "item-1"}
            }}),
        ),
        (
            "item/completed",
            json!({"params": {
                "threadId": "thread-1", "turnId": "turn-1", "item": {"id": "item-1"}
            }}),
        ),
    ];

    assert_eq!(
        frames
            .into_iter()
            .map(|(method, frame)| metadata(frame, method))
            .collect::<Vec<_>>(),
        vec![
            expected_metadata(
                "item/started",
                Some("thread-1"),
                None,
                Some("turn-1"),
                Some("item-1"),
                None,
                None,
                None,
            ),
            expected_metadata(
                "item/completed",
                Some("thread-1"),
                None,
                Some("turn-1"),
                Some("item-1"),
                None,
                None,
                None,
            ),
        ]
    );
}

#[test]
fn turn_steer_and_completion_normalize_turn_identity() {
    assert_eq!(
        vec![
            metadata(
                json!({"params": {"threadId": "thread-1", "expectedTurnId": "turn-active"}}),
                "turn/steer"
            ),
            metadata(
                json!({"params": {"threadId": "thread-1", "turn": {"id": "turn-active"}}}),
                "turn/completed"
            ),
        ],
        vec![
            expected_metadata(
                "turn/steer",
                Some("thread-1"),
                None,
                Some("turn-active"),
                None,
                None,
                None,
                None,
            ),
            expected_metadata(
                "turn/completed",
                Some("thread-1"),
                None,
                Some("turn-active"),
                None,
                None,
                None,
                None,
            ),
        ]
    );
}

#[test]
fn thread_fork_response_keeps_source_context_and_exposes_lineage() {
    let request = json!({
        "id": "fork-1",
        "method": "thread/fork",
        "params": {"threadId": "thread-source"}
    });
    let response = json!({"id": "fork-1", "result": {"thread": {
        "id": "thread-fork",
        "sessionId": "session-root",
        "forkedFromId": "thread-source"
    }}});
    let task_roots = HashMap::from([
        ("thread-source".to_string(), "thread-root".to_string()),
        ("thread-fork".to_string(), "thread-fork-root".to_string()),
    ]);
    let mut connection = AppServerConnection::new("stdio".to_string());

    let (request_kind, request_method, request_id) = analyze_frame(&request);
    let mut request_metadata = app_server_frame_metadata(&request, request_method);
    request_metadata.task_root_thread_id = task_root_thread_id(&request_metadata, &task_roots);
    connection.remember_request(
        WireFrameDirection::ClientToServer,
        request_kind,
        request_id.as_deref(),
        &request_metadata,
    );

    let (response_kind, _, response_id) = analyze_frame(&response);
    let inherited = connection
        .request_context(
            WireFrameDirection::ServerToClient,
            response_kind,
            response_id.as_deref(),
        )
        .expect("fork request metadata");
    let mut response_metadata = app_server_frame_metadata(&response, inherited.method.clone());
    response_metadata.task_root_thread_id = task_root_thread_id(&response_metadata, &task_roots);
    response_metadata.inherit_request_context(inherited);

    assert_eq!(
        response_metadata,
        expected_metadata(
            "thread/fork",
            Some("thread-source"),
            Some("thread-fork"),
            None,
            None,
            Some("thread-source"),
            Some("session-root"),
            Some("thread-root"),
        )
    );
    assert_eq!(
        app_server_frame_context(&response_metadata),
        RawTraceEventContext {
            task_root_thread_id: Some("thread-root".to_string()),
            thread_id: Some("thread-source".to_string()),
            codex_turn_id: None,
        }
    );
}

#[test]
fn thread_started_notification_uses_new_thread_context() {
    let metadata = metadata(
        json!({"params": {"thread": {
            "id": "thread-fork",
            "sessionId": "session-root",
            "forkedFromId": "thread-source"
        }}}),
        "thread/started",
    );

    assert_eq!(
        metadata,
        expected_metadata(
            "thread/started",
            None,
            Some("thread-fork"),
            None,
            None,
            Some("thread-source"),
            Some("session-root"),
            None,
        )
    );
    assert_eq!(
        app_server_frame_context(&metadata),
        RawTraceEventContext {
            task_root_thread_id: None,
            thread_id: Some("thread-fork".to_string()),
            codex_turn_id: None,
        }
    );
}

#[test]
fn server_request_response_correlation_is_bidirectional_and_preserves_frames() {
    let request = json!({
        "id": "server-1",
        "method": "turn/steer",
        "params": {"threadId": "thread-1", "expectedTurnId": "turn-1", "input": []}
    });
    let response = json!({"id": "server-1", "result": {"turnId": "turn-1"}});
    let mut connection = AppServerConnection::new("websocket".to_string());

    let (request_kind, request_method, request_id) = analyze_frame(&request);
    let request_metadata = app_server_frame_metadata(&request, request_method);
    connection.remember_request(
        WireFrameDirection::ServerToClient,
        request_kind,
        request_id.as_deref(),
        &request_metadata,
    );
    let (response_kind, _, response_id) = analyze_frame(&response);
    let inherited = connection
        .request_context(
            WireFrameDirection::ClientToServer,
            response_kind,
            response_id.as_deref(),
        )
        .expect("server request metadata");
    let mut response_metadata = app_server_frame_metadata(&response, inherited.method.clone());
    response_metadata.inherit_request_context(inherited);

    assert_eq!(
        response_metadata,
        expected_metadata(
            "turn/steer",
            Some("thread-1"),
            None,
            Some("turn-1"),
            None,
            None,
            None,
            None,
        )
    );

    let temp = TempDir::new().expect("temp dir");
    let bundle = temp.path().join("bundle");
    let writer = TraceWriter::create(
        &bundle,
        "trace-1".to_string(),
        "rollout-1".to_string(),
        "thread-1".to_string(),
    )
    .expect("trace writer");
    append_pending(
        &writer,
        PendingWireFrame::AppServer {
            observed_at_unix_ms: 100,
            context: app_server_frame_context(&response_metadata),
            connection_id: "connection-1".to_string(),
            transport: "websocket".to_string(),
            direction: WireFrameDirection::ClientToServer,
            frame_kind: response_kind,
            method: response_metadata.method.clone(),
            request_id: response_id,
            metadata: response_metadata,
            frame: response.clone(),
        },
    );

    let event =
        BufReader::new(File::open(bundle.join(RAW_EVENT_LOG_FILE_NAME)).expect("event log"))
            .lines()
            .map(|line| {
                serde_json::from_str::<RawTraceEvent>(&line.expect("event line"))
                    .expect("raw event")
            })
            .next()
            .expect("app server event");
    assert_eq!(
        event,
        RawTraceEvent {
            schema_version: 4,
            seq: 1,
            wall_time_unix_ms: 100,
            rollout_id: "rollout-1".to_string(),
            task_root_thread_id: None,
            thread_id: Some("thread-1".to_string()),
            codex_turn_id: Some("turn-1".to_string()),
            payload: RawTraceEventPayload::AppServerFrameObserved {
                connection_id: "connection-1".to_string(),
                transport: "websocket".to_string(),
                direction: WireFrameDirection::ClientToServer,
                frame_kind: WireFrameKind::Response,
                method: Some("turn/steer".to_string()),
                request_id: Some("server-1".to_string()),
                source_thread_id: Some("thread-1".to_string()),
                new_thread_id: None,
                item_id: None,
                forked_from_id: None,
                session_id: None,
                frame_payload: RawPayloadRef {
                    raw_payload_id: "raw_payload:1".to_string(),
                    kind: RawPayloadKind::AppServerFrame,
                    path: "payloads/1.json".to_string(),
                },
            },
        }
    );
    let saved_response: serde_json::Value = serde_json::from_reader(
        File::open(bundle.join("payloads/1.json")).expect("response frame"),
    )
    .expect("response JSON");
    assert_eq!(saved_response, response);
}
