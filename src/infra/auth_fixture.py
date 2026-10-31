"""Deterministic infrastructure fixture, NOT a safety model or shell executor."""
import base64
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import secrets
import threading
import time

MAX_BODY = 16384


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def parse_command(body):
    if len(body) > MAX_BODY:
        raise ValueError("Body too large")
    value = json.loads(body.decode("utf-8"), object_pairs_hook=unique_object)
    if not isinstance(value, dict) or set(value) != {"command"}:
        raise ValueError("Expected only command")
    command = value["command"]
    if not isinstance(command, str) or not 1 <= len(command) <= 8192:
        raise ValueError("Invalid command length/type")
    command.encode("utf-8")
    return command


def grant(body, key, now=None):
    payload = json.dumps(dict(digest=hashlib.sha256(body).hexdigest(),
                              expires=int(time.time() if now is None else now) + 60,
                              nonce=secrets.token_hex(16)), sort_keys=True).encode()
    encoded = base64.urlsafe_b64encode(payload).decode()
    return encoded + "." + hmac.new(key.encode(), encoded.encode(), hashlib.sha256).hexdigest()


def verify_grant(value, body, key, now=None):
    encoded, signature = value.split(".")
    expected = hmac.new(key.encode(), encoded.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise ValueError("Invalid grant signature")
    payload = json.loads(base64.urlsafe_b64decode(encoded))
    if payload["expires"] <= (time.time() if now is None else now):
        raise ValueError("Expired grant")
    if not hmac.compare_digest(payload["digest"], hashlib.sha256(body).hexdigest()):
        raise ValueError("Authorized body differs from recorded body")
    return payload


class FixtureServer(ThreadingHTTPServer):
    def __init__(self, address, role, token, signing_key):
        super().__init__(address, Handler)
        self.role, self.token, self.signing_key = role, token, signing_key
        self.records, self.seen = [], set()
        self.lock = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    def reply(self, status, value, headers=None):
        body = json.dumps(value, ensure_ascii=True).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self.reply(200, dict(fixture=True, role=self.server.role))
        elif self.path == "/records" and self.server.role == "recorder":
            with self.server.lock:
                self.reply(200, dict(records=list(self.server.records)))
        else:
            self.reply(404, dict(error="Not found"))

    def do_POST(self):
        self.connection.settimeout(5)
        if self.path not in ("/authorize", "/execute"):
            return self.reply(404, dict(error="Not found"))
        try:
            lengths = self.headers.get_all("content-length", [])
            if len(lengths) != 1 or self.headers.get("transfer-encoding") or self.headers.get("content-encoding"):
                raise ValueError("Unsupported body framing")
            length = int(lengths[0])
            if not 0 < length <= MAX_BODY:
                return self.reply(413, dict(error="Body limit"))
            if self.headers.get("content-type", "").split(";", 1)[0].strip() != "application/json":
                return self.reply(415, dict(error="Expected application/json"))
            body = self.rfile.read(length)
            if len(body) != length:
                raise ValueError("Partial body")
            command = parse_command(body)
            if self.server.role == "authorizer" and self.path == "/authorize":
                if self.headers.get("x-breaker-grant"):
                    return self.reply(400, dict(error="Client-supplied grant is forbidden"))
                expected = "Bearer " + self.server.token
                if not hmac.compare_digest(self.headers.get("authorization", ""), expected):
                    return self.reply(401, dict(error="Unauthenticated"))
                if command == "fixture:error":
                    return self.reply(503, dict(error="Injected classifier failure"))
                if command != "fixture:allow" and not command.startswith("fixture:allow:"):
                    return self.reply(403, dict(error="Fixture denial"))
                return self.reply(200, dict(fixture=True, allow=True),
                                  {"x-breaker-grant": grant(body, self.server.signing_key)})
            if self.server.role == "recorder" and self.path == "/execute":
                payload = verify_grant(self.headers.get("x-breaker-grant", ""), body, self.server.signing_key)
                with self.server.lock:
                    if payload["nonce"] in self.server.seen:
                        return self.reply(409, dict(error="Replay"))
                    if len(self.server.records) >= 1000:
                        return self.reply(507, dict(error="Fixture record limit; restart recorder"))
                    self.server.seen.add(payload["nonce"])
                    self.server.records.append(dict(command=command, digest=payload["digest"]))
                return self.reply(200, dict(fixture=True, executed=False, digest=payload["digest"]))
            return self.reply(404, dict(error="Wrong fixture role"))
        except (ValueError, KeyError, UnicodeError, TimeoutError) as exc:
            self.log_message("Fixture rejected: %s", str(exc))
            return self.reply(400, dict(error="Invalid fixture request or grant"))


if __name__ == "__main__":
    FixtureServer(("0.0.0.0", 8080), os.environ["FIXTURE_ROLE"],
                  os.environ["FIXTURE_TOKEN"], os.environ["FIXTURE_SIGNING_KEY"]).serve_forever()
