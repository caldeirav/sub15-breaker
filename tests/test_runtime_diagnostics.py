from contextlib import contextmanager
import hashlib
import json
import socket
import threading
from types import SimpleNamespace as S

import httpx
import pytest

from src.banking_service.app import ActorApplication
from src.banking_service.diagnostics import RuntimeCallError,sanitize_chain
from src.banking_service.http import BoundedServer,RuntimeClient,MAX_HTTP_BYTES


def mocked(monkeypatch,handler):
    original=httpx.Client
    def client(**kwargs):return original(transport=httpx.MockTransport(handler),**kwargs)
    monkeypatch.setattr("src.banking_service.http.httpx.Client",client)


@pytest.mark.parametrize("status,body,media",[(503,b"upstream unavailable","text/plain"),(200,b"","application/json"),(200,b"{", "application/json"),(401,b"<h1>private-secret</h1>","text/html")])
def test_non_json_diagnostics_are_bounded_no_body_or_credentials(monkeypatch,status,body,media):
    calls=[]
    def handler(request):calls.append(request);return httpx.Response(status,headers={"content-type":media},stream=httpx.ByteStream(body))
    mocked(monkeypatch,handler);client=RuntimeClient("http://service","Bearer private-token",boundary="actor_to_store_readiness")
    with pytest.raises(RuntimeCallError) as caught:client.call("/actor-readiness",{})
    hop=caught.value.transport["hops"][0]
    assert hop["status"]==status and hop["content_type"]==media and hop["body_bytes"]==len(body)
    assert hop["body_sha256"]==hashlib.sha256(body).hexdigest() and hop["body_digest_scope"]=="complete"
    assert hop["boundary"]=="actor_to_store_readiness" and hop["failure"]=="invalid_json" and hop["elapsed_ns"]>0
    assert "private-secret" not in json.dumps(hop) and "private-token" not in json.dumps(hop) and "http://service" not in json.dumps(hop)
    assert len(calls)==1  # No retry/response repair.


def test_structured_auth_error_and_upstream_hop_are_preserved_not_guessed(monkeypatch):
    body=dict(code="unauthenticated",transport=dict(schema_version="runtime-transport-chain-v1",hops=[dict(boundary="actor_to_store_readiness",status=403,operation="actor-readiness",body_bytes=26,raw_body="SECRET",content_type="application/json",failure="http_error")]))
    mocked(monkeypatch,lambda request:httpx.Response(409,stream=httpx.ByteStream(json.dumps(body).encode())))
    client=RuntimeClient("http://actor","Bearer SECRET",boundary="driver_to_actor")
    with pytest.raises(RuntimeCallError) as caught:client.call("/admission-readiness",{})
    assert caught.value.code=="unauthenticated"
    assert [h["boundary"] for h in caught.value.transport["hops"]]==["driver_to_actor","actor_to_store_readiness"]
    assert "SECRET" not in json.dumps(caught.value.transport)


@pytest.mark.parametrize("error",[httpx.ConnectTimeout,httpx.ReadTimeout,httpx.RemoteProtocolError])
def test_transport_exception_does_not_expose_message_or_retry(monkeypatch,error):
    calls=[]
    def handler(request):calls.append(request);raise error("private URL and token SECRET")
    mocked(monkeypatch,handler)
    with pytest.raises(RuntimeCallError) as caught:RuntimeClient("http://service","Bearer SECRET").call("/snapshot",{})
    hop=caught.value.transport["hops"][0]
    assert hop["exception_type"]==error.__name__ and hop["failure"]=="transport_error" and hop["status"] is None
    assert "SECRET" not in json.dumps(caught.value.transport) and len(calls)==1


def test_large_response_is_bounded_during_streaming(monkeypatch):
    class Stream(httpx.SyncByteStream):
        def __iter__(self):
            for _ in range(10000):yield b"x"*4096
    mocked(monkeypatch,lambda request:httpx.Response(503,stream=Stream()))
    with pytest.raises(RuntimeCallError) as caught:RuntimeClient("http://service","unused").call("/actor-readiness",{})
    hop=caught.value.transport["hops"][0]
    assert caught.value.code=="response_too_large" and hop["body_bytes"]==MAX_HTTP_BYTES+1 and hop["body_digest_scope"]=="bounded_prefix"


def test_truncated_stream_keeps_partial_status_and_digest_without_repair(monkeypatch):
    class Stream(httpx.SyncByteStream):
        def __iter__(self):
            yield b"{"
            raise httpx.RemoteProtocolError("SECRET truncated upstream response")
    mocked(monkeypatch,lambda request:httpx.Response(200,headers={"content-type":"application/json"},stream=Stream()))
    with pytest.raises(RuntimeCallError) as caught:RuntimeClient("http://service","SECRET").call("/actor-readiness",{})
    hop=caught.value.transport["hops"][0]
    assert hop["status"]==200 and hop["body_bytes"]==1 and hop["body_digest_scope"]=="partial"
    assert hop["body_sha256"]==hashlib.sha256(b"{").hexdigest() and "SECRET" not in json.dumps(hop)


def test_hostile_diagnostic_fields_are_dropped_and_depth_is_bounded():
    value=dict(schema_version="runtime-transport-chain-v1",hops=[dict(boundary="SECRET",operation="SECRET",status="SECRET",content_type="SECRET",body_bytes=True,authorization="SECRET",body_sha256="a"*64)]*100)
    hops=sanitize_chain(value)
    assert len(hops)==4 and all(h==dict(body_sha256="a"*64) for h in hops)


def test_actor_propagates_safe_metadata_and_logs_before_cleanup(capsys):
    hop=dict(boundary="actor_to_store_readiness",operation="actor-readiness",status=503,content_type="text/plain",failure="invalid_json")
    def call(*args):raise RuntimeCallError("invalid_runtime_json",hop)
    app=ActorApplication(S(call=call),S(driver=lambda auth:None))
    server=BoundedServer(("127.0.0.1",0),app);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        with pytest.raises(RuntimeCallError) as caught:RuntimeClient(f"http://127.0.0.1:{server.server_port}","Bearer SECRET",boundary="driver_to_actor").call("/admission-readiness",{})
        assert [h["status"] for h in caught.value.transport["hops"]]==[409,503]
    finally:server.shutdown();server.server_close();thread.join(2)
    text=capsys.readouterr().err
    assert "runtime_transport_failure" in text and "SECRET" not in text and "actor_to_store_readiness" in text
