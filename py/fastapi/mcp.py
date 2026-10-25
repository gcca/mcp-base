import json
import math
import os

import fastapi
import fastapi.responses
import uvicorn


def env_or(name: str, fallback: str) -> str:
    return os.environ.get(name) or fallback


def string_field(obj: object, key: str) -> str | None:
    if not isinstance(obj, dict):
        return None
    value = obj.get(key)
    return value if isinstance(value, str) else None


def number_field(obj: object, key: str) -> float | None:
    if not isinstance(obj, dict):
        return None
    value = obj.get(key)
    if type(value) not in (int, float):
        return None
    try:
        value = float(value)
    except OverflowError:
        return None
    return value if math.isfinite(value) else None


def envelope(id_: object) -> dict[str, object]:
    return {"jsonrpc": "2.0", "id": id_}


def reply(id_: object, result: object) -> fastapi.Response:
    return fastapi.responses.JSONResponse(
        {**envelope(id_), "result": result}
    )


def fail(
    id_: object, code: int, text: str, status: int = 200
) -> fastapi.Response:
    error = {"code": code, "message": text}
    return fastapi.responses.JSONResponse(
        {**envelope(id_), "error": error}, status_code=status
    )


def tool_result(text: str, is_error: bool) -> dict[str, object]:
    return {
        "content": [{"type": "text", "text": text}],
        "isError": is_error,
    }


def initialize_result(message: dict[str, object]) -> dict[str, object]:
    version = "2025-06-18"
    requested = string_field(message.get("params"), "protocolVersion")
    if requested is not None:
        version = requested
    return {
        "protocolVersion": version,
        "capabilities": {"tools": {}},
        "serverInfo": {"name": "mcp-fastapi", "version": "0.1.0"},
    }


def tools_list_result() -> dict[str, object]:
    return {
        "tools": [
            {
                "name": name,
                "description": description,
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "a": {"type": "number"},
                        "b": {"type": "number"},
                    },
                    "required": ["a", "b"],
                },
            }
            for name, description in (
                ("add", "Add a and b."),
                ("subtract", "Subtract b from a."),
                ("multiply", "Multiply a by b."),
                ("divide", "Divide a by b."),
            )
        ]
    }


def call_tool(
    id_: object, message: dict[str, object]
) -> fastapi.Response:
    params = message.get("params")
    if not isinstance(params, dict):
        return fail(id_, -32602, "Invalid params")
    name = string_field(params, "name")
    arguments = params.get("arguments")
    a = number_field(arguments, "a")
    b = number_field(arguments, "b")
    if name is None or a is None or b is None:
        return fail(id_, -32602, "Invalid params")
    if name == "add":
        value = a + b
    elif name == "subtract":
        value = a - b
    elif name == "multiply":
        value = a * b
    elif name == "divide":
        if b == 0:
            return reply(id_, tool_result("Cannot divide by zero.", True))
        value = a / b
    else:
        return fail(id_, -32602, "Invalid params")
    if not math.isfinite(value):
        return reply(id_, tool_result("Result is not finite.", True))
    return reply(id_, tool_result(json.dumps(value), False))


app = fastapi.FastAPI(
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    redirect_slashes=False,
)


@app.post("/mcp", response_model=None)
async def handle(request: fastapi.Request) -> fastapi.Response:
    try:
        message = json.loads(await request.body())
    except (ValueError, RecursionError):
        return fail(None, -32700, "Parse error", 400)
    if not isinstance(message, dict):
        return fail(None, -32600, "Invalid Request", 400)
    if "id" not in message:
        return fastapi.responses.Response(
            b"", status_code=202, media_type="text/plain"
        )

    id_ = message["id"]
    method = string_field(message, "method")
    if method is None:
        return fail(id_, -32600, "Invalid Request")
    if method == "initialize":
        return reply(id_, initialize_result(message))
    if method == "ping":
        return reply(id_, {})
    if method == "tools/list":
        return reply(id_, tools_list_result())
    if method == "tools/call":
        return call_tool(id_, message)
    return fail(id_, -32601, "Method not found")


if __name__ == "__main__":
    uvicorn.run(
        app,
        host=env_or("MCP_BIND", "127.0.0.1"),
        port=int(env_or("MCP_PORT", "8000")),
    )
