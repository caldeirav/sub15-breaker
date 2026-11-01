"""Bounded local-profile HTTP transport; platform identities confer authority."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import socket
import threading
from urllib.parse import urlparse

import httpx

from src.banking_contracts.codec import ContractError
from src.banking_service.store import packed

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
    def __init__(self, base_url, authorization, timeout=15):
        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password:
            raise ValueError("invalid_service_address")
        self.base_url, self.authorization, self.timeout = base_url.rstrip("/"), authorization, timeout

    def call(self, path, value):
        with httpx.Client(timeout=self.timeout, follow_redirects=False, trust_env=False) as client:
            response = client.post(self.base_url+path, content=packed(value, MAX_HTTP_BYTES),
                headers={"Authorization": self.authorization, "Content-Type": "application/json"})
            if len(response.content) > MAX_HTTP_BYTES: raise ContractError("response_too_large", "transport")
            result = body_object(response.content)
            if response.status_code != 200:
                raise ContractError(result.get("code", "runtime_transport_error"), "transport")
            return result


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
            self.reply(403 if exc.stage == "authentication" else 409, {"code": exc.code})
        except (ValueError, TypeError, KeyError):
            self.reply(400, {"code": "invalid_runtime_request"})
        except (socket.timeout, TimeoutError):
            self.close_connection = True
        except Exception:
            # Never return exception bodies that could include synthetic passwords
            # or transport credentials. The caller must reconcile uncertain writes.
            self.reply(503, {"code": "runtime_unavailable"})
