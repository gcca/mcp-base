import copy
import http.client
import json
import sys
import typing
import urllib.parse

DEFAULT_URL = "127.0.0.1:8080/mcp"
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


def rpc(**fields: typing.Any) -> bytes:
    return json.dumps({"jsonrpc": "2.0", **fields}).encode()


def post(
    name: str, body: bytes, status: int, check: Check | None = None
) -> Case:
    return Case(name, "POST", "{base}", body, status, check)


CASES = (
    post(
        "tools/list id=1",
        rpc(id=1, method="tools/list"),
        200,
        all_of(
            has("id", value=1),
            has("result", "tools", 0, "name", value="echo"),
            has(
                "result", "tools", 0, "inputSchema", "required", value=["text"]
            ),
        ),
    ),
    post(
        "tools/list id='abc'",
        rpc(id="abc", method="tools/list"),
        200,
        has("id", value="abc"),
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


def masked(parsed: typing.Any) -> typing.Any:
    if at(parsed, "result", "serverInfo", "name") is MISSING:
        return parsed
    copied = copy.deepcopy(parsed)
    copied["result"]["serverInfo"]["name"] = "<name>"
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
    if case.check is not None:
        if parsed is EMPTY or parsed is TEXT or not case.check(parsed):
            found.append("body check failed")
    return found


def parity(reference: Reply, other: Reply) -> str:
    if reference.status != other.status:
        return f"DIFF status {reference.status} vs {other.status}"
    if reference.status in (404, 405):
        return "same status"
    if masked(parse(reference.body)) == masked(parse(other.body)):
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
            verdicts = [parity(ready[0], reply) for reply in ready[1:]]
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
