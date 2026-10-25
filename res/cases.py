import copy
import http.client
import json
import math
import sys
import typing
import urllib.parse

DEFAULT_URL = "127.0.0.1:8000/mcp"
JSON_HEADERS = {"Content-Type": "application/json"}
MISSING = object()
EMPTY = object()
TEXT = object()

Check = typing.Callable[[typing.Any], bool]


class Case(typing.NamedTuple):
    name: str
    method: str
    path: str
    body: bytes | None
    status: int
    check: Check | None = None
    numeric: bool = False


class Reply(typing.NamedTuple):
    status: int
    headers: list[tuple[str, str]]
    body: bytes


def at(obj: typing.Any, *keys: str | int) -> typing.Any:
    for key in keys:
        try:
            obj = obj[key]
        except (KeyError, IndexError, TypeError):
            return MISSING
    return obj


def has(*path: str | int, value: typing.Any) -> Check:
    return lambda parsed: at(parsed, *path) == value


def all_of(*checks: Check) -> Check:
    return lambda parsed: all(check(parsed) for check in checks)


def error_is(code: int, id_: typing.Any = None) -> Check:
    return all_of(
        has("jsonrpc", value="2.0"),
        has("id", value=id_),
        has("error", "code", value=code),
    )


def tools_are(parsed: typing.Any) -> bool:
    tools = at(parsed, "result", "tools")
    if not isinstance(tools, list) or len(tools) != 4:
        return False
    expected = (
        ("add", "Add a and b."),
        ("subtract", "Subtract b from a."),
        ("multiply", "Multiply a by b."),
        ("divide", "Divide a by b."),
    )
    schema = {
        "type": "object",
        "properties": {"a": {"type": "number"}, "b": {"type": "number"}},
        "required": ["a", "b"],
    }
    return all(
        at(tool, "name") == name
        and at(tool, "description") == description
        and at(tool, "inputSchema") == schema
        for tool, (name, description) in zip(tools, expected)
    )


def tool_number(parsed: typing.Any) -> float | object:
    if at(parsed, "result", "isError") is not False:
        return MISSING
    content = at(parsed, "result", "content")
    if not isinstance(content, list) or len(content) != 1:
        return MISSING
    text = at(content[0], "text")
    if at(content[0], "type") != "text" or not isinstance(text, str):
        return MISSING
    try:
        value = json.loads(text)
        if type(value) not in (int, float):
            return MISSING
        value = float(value)
    except (ValueError, OverflowError):
        return MISSING
    return value if math.isfinite(value) else MISSING


def tool_is(value: float, id_: typing.Any = 10) -> Check:
    def check(parsed: typing.Any) -> bool:
        number = tool_number(parsed)
        return number is not MISSING and math.isclose(
            number, value, rel_tol=1e-12, abs_tol=0.0
        )

    return all_of(
        has("jsonrpc", value="2.0"), has("id", value=id_), check
    )


def tool_error_is(text: str, id_: typing.Any = 10) -> Check:
    return all_of(
        has("jsonrpc", value="2.0"),
        has("id", value=id_),
        has(
            "result",
            value={
                "content": [{"type": "text", "text": text}],
                "isError": True,
            },
        ),
    )


def rpc(**fields: typing.Any) -> bytes:
    return json.dumps({"jsonrpc": "2.0", **fields}).encode()


def post(
    name: str,
    body: bytes,
    status: int,
    check: Check | None = None,
    numeric: bool = False,
) -> Case:
    return Case(name, "POST", "{base}", body, status, check, numeric)


def call(
    name: str,
    tool: str,
    a: float,
    b: float,
    value: float,
    id_: typing.Any = 10,
) -> Case:
    return post(
        name,
        rpc(
            id=id_,
            method="tools/call",
            params={"name": tool, "arguments": {"a": a, "b": b}},
        ),
        200,
        tool_is(value, id_),
        numeric=True,
    )


def invalid_call(name: str, params: typing.Any = MISSING) -> Case:
    fields = {"id": 10, "method": "tools/call"}
    if params is not MISSING:
        fields["params"] = params
    return post(
        name,
        rpc(**fields),
        200,
        all_of(
            error_is(-32602, 10),
            has("error", "message", value="Invalid params"),
        ),
    )


CASES = (
    post(
        "tools/list id=1",
        rpc(id=1, method="tools/list"),
        200,
        all_of(
            has("id", value=1),
            tools_are,
        ),
    ),
    post(
        "tools/list id='abc'",
        rpc(id="abc", method="tools/list"),
        200,
        all_of(has("id", value="abc"), tools_are),
    ),
    post(
        "notification initialized",
        rpc(method="notifications/initialized"),
        202,
    ),
    post("tools/list without id", rpc(method="tools/list"), 202),
    post(
        "initialize echoes version",
        rpc(
            id=2,
            method="initialize",
            params={"protocolVersion": "2025-03-26"},
        ),
        200,
        all_of(
            has("result", "protocolVersion", value="2025-03-26"),
            has("result", "capabilities", "tools", value={}),
            has("result", "serverInfo", "version", value="0.1.0"),
        ),
    ),
    post(
        "initialize default version",
        rpc(id=5, method="initialize"),
        200,
        has("result", "protocolVersion", value="2025-06-18"),
    ),
    post(
        "initialize params not an object",
        rpc(id=8, method="initialize", params="x"),
        200,
        has("result", "protocolVersion", value="2025-06-18"),
    ),
    post(
        "initialize empty-string version",
        rpc(id=9, method="initialize", params={"protocolVersion": ""}),
        200,
        has("result", "protocolVersion", value=""),
    ),
    post(
        "ping",
        rpc(id=3, method="ping"),
        200,
        all_of(has("id", value=3), has("result", value={})),
    ),
    post(
        "unknown method",
        rpc(id=4, method="foo/bar"),
        200,
        error_is(-32601, 4),
    ),
    post("id without method", rpc(id=6), 200, error_is(-32600, 6)),
    post(
        "method not a string",
        rpc(id=7, method=42),
        200,
        error_is(-32600, 7),
    ),
    post(
        "id null request",
        rpc(id=None, method="ping"),
        200,
        all_of(has("id", value=None), has("result", value={})),
    ),
    post("id float", rpc(id=1.5, method="ping"), 200, has("id", value=1.5)),
    post(
        "id object",
        rpc(id={"a": 1}, method="ping"),
        200,
        has("id", value={"a": 1}),
    ),
    post("malformed JSON", b"{not json", 400, error_is(-32700)),
    post("empty body", b"", 400, error_is(-32700)),
    post("whitespace body", b"   ", 400, error_is(-32700)),
    post("literal null body", b"null", 400, error_is(-32600)),
    post("body []", b"[]", 400, error_is(-32600)),
    post("body 1", b"1", 400, error_is(-32600)),
    Case("GET /mcp", "GET", "{base}", None, 405),
    Case("PUT /mcp", "PUT", "{base}", b"{}", 405),
    Case(
        "POST /mcp/ trailing slash",
        "POST",
        "{base}/",
        rpc(id=1, method="ping"),
        404,
    ),
    Case("POST /other", "POST", "/other", rpc(id=1, method="ping"), 404),
    call("add", "add", 2, 3, 5),
    call("subtract", "subtract", 10, 4, 6),
    call("multiply", "multiply", 6, 7, 42),
    call("divide fractional", "divide", 7, 2, 3.5),
    call("add negative decimals", "add", -2.5, 1.25, -1.25),
    call("subtract operand order", "subtract", 2, 5, -3),
    call("multiply negatives", "multiply", -2.5, -4, 10),
    call("divide negative", "divide", -7, 2, -3.5),
    call("divide repeating", "divide", 1, 3, 0.3333333333333333),
    call("add zero", "add", 0, 0, 0),
    call("decimal rounding", "add", 0.1, 0.2, 0.30000000000000004),
    call("small operands", "add", 1e-100, 1e-100, 2e-100),
    call("large operands", "add", 1e100, 1e100, 2e100),
    call("arithmetic underflow", "multiply", 1e-300, 1e-300, 0),
    call("call string id", "add", 2, 3, 5, "abc"),
    call("call null id", "add", 2, 3, 5, None),
    call("call object id", "add", 2, 3, 5, {"a": 1}),
    post(
        "extra arguments ignored",
        rpc(
            id=10,
            method="tools/call",
            params={"name": "add", "arguments": {"a": 2, "b": 3, "c": 9}},
        ),
        200,
        tool_is(5),
        numeric=True,
    ),
    *(
        post(
            name,
            rpc(
                id=10,
                method="tools/call",
                params={"name": tool, "arguments": {"a": a, "b": b}},
            ),
            200,
            tool_error_is(text),
        )
        for name, tool, a, b, text in (
            ("divide by zero", "divide", 7, 0, "Cannot divide by zero."),
            (
                "divide negative zero", "divide", 7, -0.0,
                "Cannot divide by zero.",
            ),
            ("zero divided by zero", "divide", 0, 0, "Cannot divide by zero."),
            ("add overflow", "add", 1e308, 1e308, "Result is not finite."),
            (
                "subtract overflow", "subtract", -1e308, 1e308,
                "Result is not finite.",
            ),
            (
                "multiply overflow", "multiply", 1e308, 1e308,
                "Result is not finite.",
            ),
            (
                "divide overflow", "divide", 1e308, 1e-308,
                "Result is not finite.",
            ),
        )
    ),
    invalid_call("call missing params"),
    *(
        invalid_call(name, params)
        for name, params in (
            ("call null params", None),
            ("call array params", []),
            ("call string params", "bad"),
            ("call missing name", {"arguments": {"a": 2, "b": 3}}),
            ("call numeric name", {"name": 7, "arguments": {"a": 2, "b": 3}}),
            ("call missing arguments", {"name": "add"}),
            ("call null arguments", {"name": "add", "arguments": None}),
            ("call array arguments", {"name": "add", "arguments": []}),
            ("call string arguments", {"name": "add", "arguments": "bad"}),
            ("unknown tool", {"name": "power", "arguments": {"a": 2, "b": 3}}),
            ("echo removed", {"name": "echo", "arguments": {"a": 2, "b": 3}}),
        )
    ),
    *(
        invalid_call(name, {"name": "add", "arguments": arguments})
        for name, arguments in (
            ("missing a", {"b": 3}),
            ("missing b", {"a": 2}),
            ("null a", {"a": None, "b": 3}),
            ("null b", {"a": 2, "b": None}),
            ("boolean a", {"a": True, "b": 3}),
            ("boolean b", {"a": 2, "b": False}),
            ("string a", {"a": "2", "b": 3}),
            ("string b", {"a": 2, "b": "3"}),
            ("array a", {"a": [], "b": 3}),
            ("object b", {"a": 2, "b": {}}),
            ("out-of-range a", {"a": 10**400, "b": 3}),
            ("out-of-range b", {"a": 2, "b": -(10**400)}),
        )
    ),
    *(
        post(name, rpc(method="tools/call", params=params), 202)
        for name, params in (
            (
                "call notification",
                {"name": "add", "arguments": {"a": 2, "b": 3}},
            ),
            ("invalid call notification", {"name": "add"}),
            (
                "zero division notification",
                {"name": "divide", "arguments": {"a": 1, "b": 0}},
            ),
        )
    ),
)


def split(url: str) -> urllib.parse.SplitResult:
    return urllib.parse.urlsplit(url if "://" in url else f"http://{url}")


def fetch(server: urllib.parse.SplitResult, case: Case) -> Reply | None:
    conn = http.client.HTTPConnection(
        server.hostname or "127.0.0.1", server.port or 80, timeout=5
    )
    headers = JSON_HEADERS if case.body is not None else {}
    try:
        conn.request(
            case.method, case.path.format(base=server.path), case.body, headers
        )
        reply = conn.getresponse()
        return Reply(reply.status, reply.getheaders(), reply.read())
    except (OSError, http.client.HTTPException):
        return None
    finally:
        conn.close()


def parse(body: bytes) -> typing.Any:
    if not body:
        return EMPTY
    try:
        return json.loads(body)
    except ValueError:
        return TEXT


def masked(parsed: typing.Any, numeric: bool = False) -> typing.Any:
    name = at(parsed, "result", "serverInfo", "name")
    number = tool_number(parsed) if numeric else MISSING
    if name is MISSING and number is MISSING:
        return parsed
    copied = copy.deepcopy(parsed)
    if name is not MISSING:
        copied["result"]["serverInfo"]["name"] = "<name>"
    if number is not MISSING:
        copied["result"]["content"][0]["text"] = number
    return copied


def problems(case: Case, reply: Reply) -> list[str]:
    found = []
    parsed = parse(reply.body)
    content_type = {name.lower(): value for name, value in reply.headers}.get(
        "content-type", ""
    )
    if reply.status != case.status:
        found.append(f"status {reply.status}, want {case.status}")
    if case.status == 202 and reply.body:
        found.append("202 with a body")
    if any(value == "None" for _, value in reply.headers):
        found.append("a response header has the value None")
    if parsed is not EMPTY and parsed is not TEXT:
        if not content_type.startswith("application/json"):
            found.append(f"JSON body with content-type {content_type!r}")
    if case.status in (200, 400):
        if (
            not isinstance(parsed, dict)
            or parsed.get("jsonrpc") != "2.0"
            or "id" not in parsed
            or ("result" in parsed) == ("error" in parsed)
        ):
            found.append("invalid JSON-RPC response envelope")
    if case.check is not None:
        if parsed is EMPTY or parsed is TEXT or not case.check(parsed):
            found.append("body check failed")
    return found


def parity(reference: Reply, other: Reply, numeric: bool = False) -> str:
    if reference.status != other.status:
        return f"DIFF status {reference.status} vs {other.status}"
    if reference.status in (404, 405):
        return "same status"
    if masked(parse(reference.body), numeric) == masked(
        parse(other.body), numeric
    ):
        return "same"
    return "DIFF body"


def main(argv: list[str]) -> int:
    urls = argv or [DEFAULT_URL]
    servers = [split(url) for url in urls]
    width = max(len(case.name) for case in CASES) + 2
    details = []
    header = "".join(f"{url:<24}" for url in urls)
    sys.stdout.write(f"{'case':<{width}}{header}parity\n")
    for case in CASES:
        replies = [fetch(server, case) for server in servers]
        cells = []
        for url, reply in zip(urls, replies):
            if reply is None:
                cells.append("down")
                details.append(f"{case.name} [{url}]: unreachable")
                continue
            found = problems(case, reply)
            cells.append(f"{'FAIL' if found else 'ok'}:{reply.status}")
            details.extend(f"{case.name} [{url}]: {text}" for text in found)
        ready = [reply for reply in replies if reply is not None]
        verdicts = []
        if len(ready) > 1 and len(ready) == len(replies):
            verdicts = [
                parity(ready[0], reply, case.numeric) for reply in ready[1:]
            ]
            details.extend(
                f"{case.name}: parity {text}"
                for text in verdicts
                if text.startswith("DIFF")
            )
        row = "".join(f"{cell:<24}" for cell in cells)
        sys.stdout.write(f"{case.name:<{width}}{row}{', '.join(verdicts)}\n")
    for line in details:
        sys.stdout.write(f"  {line}\n")
    if details:
        sys.stdout.write(f"RESULT: {len(details)} problem(s)\n")
        return 1
    sys.stdout.write("RESULT: ALL GOOD\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
