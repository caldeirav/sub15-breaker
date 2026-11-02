from contextlib import contextmanager
from http.client import HTTPConnection
import json
import socket
import threading
from types import SimpleNamespace

import pytest

from src.benchmark.bridge import BridgeServer,MCPClient


@contextmanager
def running(**kwargs):
    server=BridgeServer(("127.0.0.1",0),SimpleNamespace(rpc=lambda body:dict(jsonrpc="2.0",id=body["id"],result={})),**kwargs)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:yield server
    finally:server.shutdown();server.server_close();thread.join(2)


def post(client,body):
    client.request("POST","/mcp",json.dumps(body));response=client.getresponse();data=response.read()
    assert int(response.getheader("content-length"))==len(data)
    return response,json.loads(data)


def test_http11_reuses_socket_and_frames_notifications_and_errors():
    with running() as server:
        client=HTTPConnection(*server.server_address,timeout=2)
        for i in range(3):
            response,body=post(client,dict(id=i,method="tools/list"))
            assert response.version==11 and body["id"]==i
        response,body=post(client,dict(method="notifications/initialized"))
        assert response.status==202 and body=={}
        assert len([e for e in server.transport_snapshot() if e["kind"]=="connection_open"])==1
        client.close()


@pytest.mark.parametrize("headers",["Content-Length: 2\r\nContent-Length: 2", "Content-Length: 2\r\nTransfer-Encoding: chunked", "Content-Length: -2", "Content-Length: 131073"])
def test_invalid_framing_closes_without_processing_pipelined_tail(headers):
    with running() as server:
        with socket.create_connection(server.server_address,timeout=2) as sock:
            sock.sendall((f"POST /mcp HTTP/1.1\r\nHost: localhost\r\n{headers}\r\n\r\n{{}}GET /health HTTP/1.1\r\nHost: localhost\r\n\r\n").encode())
            stream=sock.makefile("rb");data=stream.read()
        assert data.count(b"HTTP/1.1")==1 and b"400" in data and b"connection: close" in data.lower()


def test_header_idle_and_overload_are_bounded_and_slot_recovers():
    with running(max_connections=1,idle_timeout=.1) as server:
        with socket.create_connection(server.server_address,timeout=2) as first:
            first.sendall(b"POST /mcp HTTP/1.1\r\nHost:")
            # Wait for acceptance using a condition-free event from the handler.
            deadline=threading.Event()
            for _ in range(100):
                if server.transport_snapshot():break
                deadline.wait(.001)
            with socket.create_connection(server.server_address,timeout=2) as second:
                try:assert second.recv(1)==b""
                except ConnectionResetError:pass
            assert first.recv(1)==b""
        assert any(e["kind"]=="connection_rejected" for e in server.transport_snapshot())
        client=HTTPConnection(*server.server_address,timeout=2)
        assert post(client,dict(id=1,method="tools/list"))[0].status==200
        client.close()


def test_active_rpc_can_outlast_socket_idle_timeout_and_connection_has_request_cap():
    with running(idle_timeout=.05,max_requests=2) as server:
        def rpc(body):
            threading.Event().wait(.1);return dict(id=body["id"],result={})
        server.bridge.rpc=rpc;client=HTTPConnection(*server.server_address,timeout=2)
        assert post(client,dict(id=1,method="tools/list"))[0].status==200
        response,_=post(client,dict(id=2,method="tools/list"))
        assert response.getheader("connection")=="close"
        client.close()
        assert all(set(e)<={"kind","connection","requests","reason","status","bytes","method","elapsed_ns"} for e in server.transport_snapshot())


def test_repeated_discovery_validates_each_catalog_without_stale_duplicate_state():
    catalog=SimpleNamespace(names=["read"],schemas=lambda:{"read":dict(arguments={"type":"object"})})
    client=MCPClient("unused","not-a-token",SimpleNamespace(catalog=catalog))
    client.rpc=lambda *args:dict(tools=[dict(name="banking_read",inputSchema=dict(type="object"))])
    assert client.discover()==client.discover() and client.names=={"read":"banking_read"}
