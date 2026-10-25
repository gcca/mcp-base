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

fn number_field(object: &Value, key: &str) -> Option<f64> {
    object.get(key)?.as_f64().filter(|value| value.is_finite())
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

fn tool_result(text: &str, is_error: bool) -> Value {
    json!({
        "content": [{"type": "text", "text": text}],
        "isError": is_error
    })
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
    let tools: Vec<Value> = [
        ("add", "Add a and b."),
        ("subtract", "Subtract b from a."),
        ("multiply", "Multiply a by b."),
        ("divide", "Divide a by b."),
    ]
    .into_iter()
    .map(|(name, description)| {
        json!({
            "name": name,
            "description": description,
            "inputSchema": {
                "type": "object",
                "properties": {
                    "a": {"type": "number"},
                    "b": {"type": "number"}
                },
                "required": ["a", "b"]
            }
        })
    })
    .collect();
    json!({"tools": tools})
}

fn call_tool(id: &Value, message: &Value) -> Response {
    let params = &message["params"];
    let Some(name) = string_field(params, "name") else {
        return fail(id, -32602, "Invalid params", StatusCode::OK);
    };
    let arguments = &params["arguments"];
    let (Some(a), Some(b)) = (number_field(arguments, "a"), number_field(arguments, "b")) else {
        return fail(id, -32602, "Invalid params", StatusCode::OK);
    };
    let value = match name {
        "add" => a + b,
        "subtract" => a - b,
        "multiply" => a * b,
        "divide" => {
            if b == 0.0 {
                return reply(id, tool_result("Cannot divide by zero.", true));
            }
            a / b
        }
        _ => return fail(id, -32602, "Invalid params", StatusCode::OK),
    };
    if !value.is_finite() {
        return reply(id, tool_result("Result is not finite.", true));
    }
    reply(id, tool_result(&json!(value).to_string(), false))
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
        "tools/call" => call_tool(id, &message),
        _ => fail(id, -32601, "Method not found", StatusCode::OK),
    }
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let app = Router::new().route("/mcp", post(handle));
    let host = env_or("MCP_BIND", "127.0.0.1");
    let port: u16 = env_or("MCP_PORT", "8000").parse()?;
    let listener = tokio::net::TcpListener::bind((host.as_str(), port)).await?;
    axum::serve(listener, app).await?;
    Ok(())
}
