"""Bounded non-executing model/MCP recorder for managed-gateway capability tests.

Never imports banking executors, starts subprocesses or accesses user files.
Responses are deterministic fixtures, not model inference or task outcomes.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading

LIMIT = 16384


def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def completion(body):
    """The recorder intentionally implements Chat Completions only."""
    messages = body.get("messages")
    if not isinstance(messages, list) or not messages:
        raise ValueError("missing messages")
    if body.get("stream"):
        raise ValueError("streaming not in the initial supported profile")
    tool_results = [item for item in messages if item.get("role") == "tool"]
    message = dict(role="assistant", content="Protocol fixture completed.")
    reason = "stop"
    if body.get("tools") and not tool_results:
        message = dict(role="assistant", content="Fixture call.", tool_calls=[dict(
            id="fixture-call-1", type="function", function=dict(
                name="echo_decimal_fixture", arguments='{"amount":"123.40","note":null}'))])
        reason = "tool_calls"
    return dict(id="chatcmpl-fixture", object="chat.completion", created=1,
                model=body.get("model", "protocol-fixture"),
                choices=[dict(index=0, message=message, finish_reason=reason)],
                usage=dict(prompt_tokens=37, completion_tokens=7, total_tokens=44))


def mcp(body):
    method, params = body.get("method"), body.get("params", {})
    envelope = dict(jsonrpc="2.0", id=body.get("id"))
    modern=params.get("_meta",{}).get("io.modelcontextprotocol/protocolVersion")=="2026-07-28"
    complete={"resultType":"complete"} if modern else {}
    if method == "server/discover":
        return dict(envelope,result=dict(resultType="complete",supportedVersions=["2026-07-28","2025-11-25"],
            capabilities=dict(tools={}),_meta={"io.modelcontextprotocol/serverInfo":{"name":"non-executing-infra-fixture","version":"1"}},ttlMs=60000,cacheScope="public"))
    if method == "initialize":
        if params["protocolVersion"]=="2026-07-28":
            return dict(envelope,error=dict(code=-32601,message="initialize_removed_in_sessionless_protocol"))
        return dict(envelope, result=dict(protocolVersion=params["protocolVersion"],
                    capabilities=dict(tools=dict(listChanged=False)),
                    serverInfo=dict(name="non-executing-infra-fixture", version="1")))
    if method == "tools/list":
        return dict(envelope, result=dict(**complete,tools=[dict(name="echo_fixture", description="Echo a synthetic protocol value; no effects.",
            inputSchema=dict(type="object", properties=dict(text=dict(type="string")), required=["text"], additionalProperties=False))]))
    if method == "tools/call":
        arguments = params.get("arguments", {})
        if params.get("name") != "echo_fixture" or set(arguments) != {"text"} or not isinstance(arguments["text"], str):
            return dict(envelope, result=dict(**complete,isError=True, content=[dict(type="text", text="unsupported_fixture_call")]))
        return dict(envelope, result=dict(**complete,isError=False, content=[dict(type="text", text=arguments["text"])]))
    return dict(envelope, error=dict(code=-32601, message="unsupported_fixture_method"))


class FixtureServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 8

    def __init__(self, address):
        super().__init__(address, Handler)
        self.records = []
        self.lock = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass  # Never echo Authorization, body values or exceptions into logs.

    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def send_json(self, status, value):
        body = json.dumps(value, allow_nan=False, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self.send_json(200, dict(status="fixture-ready", executing=False))
        elif self.path == "/records":
            with self.server.lock:
                self.send_json(200, dict(records=self.server.records))
        else:
            self.send_json(405, dict(error="unsupported_fixture_path"))

    def do_DELETE(self):
        # Stateless MCP fixture: no retained remote session to destroy.
        self.send_json(200, dict(closed=True))

    def do_POST(self):
        try:
            if self.headers.get("transfer-encoding") or len(self.headers.get_all("content-length", [])) != 1:
                raise ValueError("ambiguous body")
            size = int(self.headers["content-length"])
            if not 0 < size <= LIMIT:
                raise ValueError("body limit")
            raw = self.rfile.read(size)
            if len(raw) != size:
                raise ValueError("short body")
            body = json.loads(raw, object_pairs_hook=unique, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
            if not isinstance(body, dict):
                raise ValueError("object required")
            # Request headers are deliberately not retained. Fixtures use only
            # synthetic values; recorder data is not a general safe trace export.
            with self.server.lock:
                if len(self.server.records) >= 100:
                    raise ValueError("fixture capacity")
                self.server.records.append(dict(path=self.path, body=body,
                                                authorization_present=bool(self.headers.get("authorization"))))
            if self.path == "/v1/chat/completions":
                if body.get("model") == "fixture-fail500":
                    self.send_json(500, dict(error=dict(message="deliberate_nonexecuting_fixture_fault")))
                else:
                    self.send_json(200, completion(body))
            elif self.path == "/mcp":
                if "id" not in body:
                    self.send_json(202, {})
                else:
                    self.send_json(200, mcp(body))
            else:
                self.send_json(405, dict(error="unsupported_fixture_path"))
        except (ValueError, TypeError, KeyError, UnicodeError, TimeoutError, RecursionError):
            self.send_json(400, dict(error="invalid_fixture_request"))


if __name__ == "__main__":
    FixtureServer(("0.0.0.0", 8080)).serve_forever()
