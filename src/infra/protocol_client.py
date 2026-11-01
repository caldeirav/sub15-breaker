"""Single-attempt, bounded in-cluster client; credentials never enter argv/output."""
import base64
from copy import deepcopy
from http.client import HTTPConnection
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit

LIMIT = 131072
MODERN = "2026-07-28"
LEGACY = "2025-11-25"


def mcp_context(body, version):
    """2026 MCP carries context per request and no initialize/session handshake."""
    body=deepcopy(body)
    headers={"mcp-protocol-version":version}
    if version==MODERN:
        params=body.setdefault("params",{})
        meta=params.setdefault("_meta",{})
        meta.update({"io.modelcontextprotocol/protocolVersion":MODERN,
                     "io.modelcontextprotocol/clientInfo":{"name":"infra-probe","version":"1"},
                     "io.modelcontextprotocol/clientCapabilities":{}})
        headers["mcp-method"]=body["method"]
        if "name" in params:headers["mcp-name"]=params["name"]
    elif version!=LEGACY:
        raise ValueError("unsupported_probe_protocol")
    return body,headers


def call(request):
    url = urlsplit(request["url"])
    if url.scheme != "http" or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise ValueError("invalid_probe_url")
    token_key = request.get("token", "FIXTURE_TOKEN")
    if token_key not in {"FIXTURE_TOKEN", "MODEL_TOKEN", "WRONG_SUBJECT_TOKEN", "none", "invalid"}:
        raise ValueError("invalid_probe_credential_selector")
    headers = {"accept": "application/json, text/event-stream", "content-type": "application/json"}
    if request.get("protocol"):
        if request.get("session") and request["protocol"]==MODERN:
            raise ValueError("modern_mcp_has_no_session")
        if "body" in request:
            request["body"],extra=mcp_context(request["body"],request["protocol"])
            headers.update(extra)
        else:headers["mcp-protocol-version"]=request["protocol"]
    if token_key in {"FIXTURE_TOKEN", "MODEL_TOKEN", "WRONG_SUBJECT_TOKEN"}:
        credentials = Path(os.getenv("PROBE_CREDENTIAL_DIRECTORY", "/credentials"))
        headers["authorization"] = "Bearer " + (credentials/token_key).read_text().strip()
    elif token_key == "invalid":
        headers["authorization"] = "Bearer invalid-probe-token"
    if request.get("traceparent"):
        headers["traceparent"] = request["traceparent"]
    session_path = Path("/tmp/protocol-sessions.json")
    sessions = json.loads(session_path.read_text()) if session_path.exists() else {}
    key = f"{url.hostname}:{url.port}{url.path}"
    if request.get("session") and key in sessions:
        headers["mcp-session-id"] = sessions[key]
        headers["mcp-protocol-version"] = request.get("protocol", LEGACY)
    body = json.dumps(request["body"], allow_nan=False).encode() if "body" in request else None
    if body is not None and len(body) > LIMIT:
        raise ValueError("probe_request_too_large")
    connection = HTTPConnection(url.hostname, url.port or 80, timeout=request.get("timeout", 20))
    try:
        connection.request(request.get("method", "POST"), url.path or "/", body=body, headers=headers)
        response = connection.getresponse()
        session = response.getheader("mcp-session-id")
        if session and request.get("protocol")==MODERN:
            raise ValueError("modern_mcp_returned_session_id")
        if session:
            sessions[key] = session
            session_path.write_text(json.dumps(sessions));session_path.chmod(0o600)
        content_type = response.getheader("content-type", "")
        if "text/event-stream" in content_type:
            total, data, payload = 0, [], None
            while total <= LIMIT:
                line = response.readline(LIMIT+1-total)
                total += len(line)
                if not line:
                    break
                if line.startswith(b"data:"):
                    data.append(line[5:].strip())
                elif line in {b"\n", b"\r\n"} and data:
                    value = json.loads(b"\n".join(data));data=[]
                    if value.get("id") == request.get("body", {}).get("id"):
                        payload = value
                        break
            if payload is None:
                raise ValueError("missing_bounded_rpc_response")
        else:
            raw = response.read(LIMIT+1)
            if len(raw) > LIMIT:
                raise ValueError("probe_response_too_large")
            try:payload = json.loads(raw) if raw else None
            except ValueError:payload = {"non_json":raw.decode("utf-8",errors="replace")}
        return dict(status=response.status, content_type=content_type, body=payload,
                    session_received=bool(session), physical_client_attempts=1)
    finally:
        connection.close()


if __name__ == "__main__":
    try:
        request = json.loads(base64.b64decode(sys.argv[1], validate=True))
        print(json.dumps(call(request), allow_nan=False))
    except Exception as exc:
        print(json.dumps(dict(transport_error=type(exc).__name__, physical_client_attempts=1)))
        sys.exit(1)
