use axum::body::Bytes;
use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use axum::{Json, Router, routing::post};
use serde_json::{Value, json};

fn env_or(name: &str, fallback: &str) -> String {
    std::env::var(name)
        .ok()
        .filter(|value| !value.is_empty())
        .unwrap_or_else(|| fallback.to_owned())
}

fn string_field<'a>(object: &'a Value, key: &str) -> Option<&'a str> {
    object.get(key).and_then(Value::as_str)
}

fn envelope(id: &Value) -> Value {
    json!({"jsonrpc": "2.0", "id": id})
}

fn reply(id: &Value, result: Value) -> Response {
    let mut message = envelope(id);
    message["result"] = result;
    Json(message).into_response()
}

fn fail(id: &Value, code: i64, text: &str, status: StatusCode) -> Response {
    let mut message = envelope(id);
    message["error"] = json!({"code": code, "message": text});
    (status, Json(message)).into_response()
}

fn initialize_result(message: &Value) -> Value {
    let version = message
        .get("params")
        .and_then(|params| string_field(params, "protocolVersion"))
        .unwrap_or("2025-06-18");
    json!({
        "protocolVersion": version,
        "capabilities": {"tools": {}},
        "serverInfo": {"name": "mcp-axum", "version": "0.1.0"}
    })
}

fn tools_list_result() -> Value {
    json!({
        "tools": [{
            "name": "echo",
            "description": "Dummy tool",
            "inputSchema": {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"]
            }
        }]
    })
}

async fn handle(body: Bytes) -> Response {
    let message: Value = match serde_json::from_slice(&body) {
        Ok(message) => message,
        Err(_) => {
            return fail(&Value::Null, -32700, "Parse error", StatusCode::BAD_REQUEST);
        }
    };
    if !message.is_object() {
        return fail(
            &Value::Null,
            -32600,
            "Invalid Request",
            StatusCode::BAD_REQUEST,
        );
    }
    let Some(id) = message.get("id") else {
        return StatusCode::ACCEPTED.into_response();
    };
    let Some(method) = string_field(&message, "method") else {
        return fail(id, -32600, "Invalid Request", StatusCode::OK);
    };
    match method {
        "initialize" => reply(id, initialize_result(&message)),
        "ping" => reply(id, json!({})),
        "tools/list" => reply(id, tools_list_result()),
        _ => fail(id, -32601, "Method not found", StatusCode::OK),
    }
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let app = Router::new().route("/mcp", post(handle));
    let host = env_or("MCP_BIND", "127.0.0.1");
    let port: u16 = env_or("MCP_PORT", "8080").parse()?;
    let listener = tokio::net::TcpListener::bind((host.as_str(), port)).await?;
    axum::serve(listener, app).await?;
    Ok(())
}
