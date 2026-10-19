import json
import os

import sanic
import sanic.response

DEFAULT_PROTOCOL_VERSION = "2025-06-18"

app = sanic.Sanic("mcp_sanic")


def string_field(obj: object, key: str) -> str | None:
    if not isinstance(obj, dict):
        return None
    value = obj.get(key)
    return value if isinstance(value, str) else None


def envelope(id_: object) -> dict[str, object]:
    return {"jsonrpc": "2.0", "id": id_}


def reply(id_: object, result: object) -> sanic.HTTPResponse:
    return sanic.response.json({**envelope(id_), "result": result})


def fail(
    id_: object, code: int, text: str, status: int = 200
) -> sanic.HTTPResponse:
    error = {"code": code, "message": text}
    return sanic.response.json({**envelope(id_), "error": error}, status=status)


def initialize_result(message: dict[str, object]) -> dict[str, object]:
    requested = string_field(message.get("params"), "protocolVersion")
    return {
        "protocolVersion": (
            DEFAULT_PROTOCOL_VERSION if requested is None else requested
        ),
        "capabilities": {"tools": {}},
        "serverInfo": {"name": "mcp-sanic", "version": "0.1.0"},
    }


def tools_list_result() -> dict[str, object]:
    return {
        "tools": [
            {
                "name": "echo",
                "description": "Dummy tool",
                "inputSchema": {
                    "type": "object",
                    "properties": {"text": {"type": "string"}},
                    "required": ["text"],
                },
            }
        ]
    }


@app.post("/mcp", strict_slashes=True)
async def mcp(request: sanic.Request) -> sanic.HTTPResponse:
    try:
        message = json.loads(request.body)
    except (ValueError, RecursionError):
        return fail(None, -32700, "Parse error", 400)
    if not isinstance(message, dict):
        return fail(None, -32600, "Invalid Request", 400)
    if "id" not in message:
        return sanic.response.empty(
            status=202, headers={"content-type": "text/plain"}
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
    return fail(id_, -32601, "Method not found")


if __name__ == "__main__":
    app.run(
        host=os.environ.get("MCP_BIND") or "127.0.0.1",
        port=int(os.environ.get("MCP_PORT") or "8080"),
    )
