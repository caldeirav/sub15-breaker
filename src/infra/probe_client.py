"""Benign TCP/HTTP connectivity probe; never interprets or executes a command."""
import json
import socket
import sys


def probe(host, port):
    try:
        connection = socket.create_connection((host, port), timeout=3)
    except TimeoutError:
        return {"reachable": False, "reason": "connect-timeout"}
    try:
        with connection as stream:
            stream.sendall(b"GET / HTTP/1.0\r\nHost: probe\r\n\r\n")
            response = stream.recv(64)
        if not response.startswith((b"HTTP/1.0 200", b"HTTP/1.1 200")):
            raise RuntimeError("Unexpected HTTP response: " + repr(response))
        return {"reachable": True}
    except TimeoutError:
        raise RuntimeError("Connection succeeded but HTTP send/response timed out; this is not isolation evidence")


if __name__ == "__main__":
    result = probe(sys.argv[1], int(sys.argv[2]))
    print(json.dumps(result))
