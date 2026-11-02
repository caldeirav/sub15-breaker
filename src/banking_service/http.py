"""Bounded local-profile HTTP transport; platform identities confer authority."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import json
import re
import socket
import sys
import threading
from time import perf_counter_ns
from urllib.parse import urlparse
from uuid import uuid4

import httpx

from src.banking_contracts.codec import ContractError
from src.banking_service.store import packed
from src.banking_service.diagnostics import BOUNDARIES,MEDIA,RuntimeCallError,operation,sanitize_chain

MAX_HTTP_BYTES = 262144


def body_object(data):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result: raise ValueError("duplicate_json_key")
            result[key] = value
        return result
    try:
        if not 0 < len(data) <= MAX_HTTP_BYTES: raise ValueError("invalid_body_size")
        value = json.loads(data.decode("utf-8"), object_pairs_hook=unique,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite_json")))
        if not isinstance(value, dict): raise ValueError("expected_object")
        packed(value, MAX_HTTP_BYTES)
        return value
    except (ValueError, UnicodeError, RecursionError):
        raise ContractError("invalid_runtime_json", "parse") from None


def fields(value, required, optional=()):
    if set(value) - set(required) - set(optional) or not set(required) <= set(value):
        raise ContractError("invalid_runtime_fields", "parse")
    return value


class RuntimeClient:
    def __init__(self, base_url, authorization, timeout=15,*,boundary="runtime_client"):
        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password:
            raise ValueError("invalid_service_address")
        self.base_url, self.authorization, self.timeout = base_url.rstrip("/"), authorization, timeout
        if boundary not in BOUNDARIES:raise ValueError("invalid_runtime_boundary")
        self.boundary=boundary;self.last_diagnostics=None

    def call(self, path, value):
        started=perf_counter_ns();raw=bytearray()
        hop=dict(boundary=self.boundary,operation=operation(path),operation_id=uuid4().hex,status=None,content_type="absent",body_digest_scope="partial")
        def finish(failure):
            hop.update(failure=failure,elapsed_ns=perf_counter_ns()-started,body_bytes=len(raw),body_sha256=hashlib.sha256(raw).hexdigest())
            self.last_diagnostics=dict(schema_version="runtime-transport-chain-v1",hops=sanitize_chain(dict(schema_version="runtime-transport-chain-v1",hops=[hop])))
            return dict(hop)
        try:
            with httpx.Client(timeout=self.timeout, follow_redirects=False, trust_env=False) as client:
                with client.stream("POST",self.base_url+path,content=packed(value,MAX_HTTP_BYTES),
                        headers={"Authorization":self.authorization,"Content-Type":"application/json","Accept-Encoding":"identity","x-breaker-runtime-call-id":hop["operation_id"]}) as response:
                    media=response.headers.get("content-type","").split(";",1)[0].strip().lower() or "absent"
                    hop.update(status=response.status_code,content_type=media if media in MEDIA else "other")
                    if response.headers.get("content-encoding", "identity").lower() not in {"identity",""}:
                        raise RuntimeCallError("invalid_runtime_json",finish("unsupported_encoding"))
                    for chunk in response.iter_raw():
                        raw.extend(chunk[:MAX_HTTP_BYTES+1-len(raw)])
                        if len(raw)>MAX_HTTP_BYTES:
                            hop["body_digest_scope"]="bounded_prefix"
                            raise RuntimeCallError("response_too_large",finish("too_large"))
                    hop["body_digest_scope"]="complete"
                    try:result=body_object(bytes(raw))
                    except ContractError:raise RuntimeCallError("invalid_runtime_json",finish("invalid_json")) from None
                    if response.status_code!=200:
                        code=result.get("code")
                        if not isinstance(code,str) or not re.fullmatch(r"[a-z_][a-z0-9_]{0,79}",code):code="runtime_transport_error"
                        raise RuntimeCallError(code,finish("http_error"),result.get("transport"))
                    finish("success");return result
        except httpx.TransportError as exc:
            hop["exception_type"]=type(exc).__name__
            raise RuntimeCallError("runtime_unavailable",finish("transport_error")) from None


class BoundedServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, application, request_deadline=45):
        self.application, self.slots = application, threading.BoundedSemaphore(8)
        self.request_deadline=request_deadline
        super().__init__(address, Handler)

    def process_request(self, request, address):
        if not self.slots.acquire(blocking=False):
            request.close()
            return
        try: super().process_request(request, address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, address):
        try: super().process_request_thread(request, address)
        finally: self.slots.release()


class Handler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(min(15,self.server.request_deadline))
        # Header parsing precedes do_POST. Enforce an absolute lifetime too,
        # so dribbling bytes cannot refresh a socket timeout indefinitely.
        self.deadline_timer=threading.Timer(self.server.request_deadline,self.abort)
        self.deadline_timer.daemon=True
        self.deadline_timer.start()

    def abort(self):
        try:self.connection.shutdown(socket.SHUT_RDWR)
        except OSError:pass

    def finish(self):
        self.deadline_timer.cancel()
        super().finish()

    def log_message(self, *_): pass

    def reply(self, status, value):
        data = packed(value, MAX_HTTP_BYTES).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self.reply(200 if self.path == "/health" else 404, {"ready": self.path == "/health"})

    def do_POST(self):
        self.connection.settimeout(15)
        try:
            lengths = self.headers.get_all("Content-Length", [])
            auth = self.headers.get_all("Authorization", [])
            if len(lengths) != 1 or len(auth) != 1 or self.headers.get("Transfer-Encoding"):
                raise ContractError("invalid_http_framing", "transport")
            size = int(lengths[0])
            if not 0 < size <= MAX_HTTP_BYTES or self.headers.get("Content-Type") != "application/json":
                raise ContractError("invalid_http_body", "transport")
            data = self.rfile.read(size)
            if len(data) != size: raise ContractError("incomplete_http_body", "transport")
            result = self.server.application(self.path, body_object(data), auth[0])
            self.reply(200, result)
        except ContractError as exc:
            value={"code":exc.code}
            if isinstance(exc,RuntimeCallError):
                value["transport"]=exc.transport
                print(json.dumps(dict(kind="runtime_transport_failure",operation=operation(self.path),transport=exc.transport)),file=sys.stderr,flush=True)
            self.reply(403 if exc.stage == "authentication" else 409,value)
        except (ValueError, TypeError, KeyError):
            self.reply(400, {"code": "invalid_runtime_request"})
        except (socket.timeout, TimeoutError):
            self.close_connection = True
        except Exception:
            # Never return exception bodies that could include synthetic passwords
            # or transport credentials. The caller must reconcile uncertain writes.
            self.reply(503, {"code": "runtime_unavailable"})
