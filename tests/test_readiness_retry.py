from copy import deepcopy
from types import SimpleNamespace as S
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import threading

import pytest

from src.banking_contracts.codec import ContractError
from src.banking_service.diagnostics import RuntimeCallError
from src.banking_service.http import RuntimeClient
from src.benchmark.readiness import POLICY,ReadinessError,check,retryable


READY=dict(actor_id="actor",actor_uid="uid",ticket_lifetime_seconds=900)


def failure(status=503,*,boundary="actor_to_store_readiness",code="invalid_runtime_json",kind="invalid_json",exception=None):
    return RuntimeCallError(code,dict(boundary=boundary,operation="actor-readiness",status=status,content_type="text/plain",failure=kind,**(dict(exception_type=exception) if exception else {})))


def client(values):
    calls=[];values=iter(values)
    def call(path,body):
        calls.append((path,body));assert path=="/admission-readiness" and body=={}
        value=next(values)
        if isinstance(value,Exception):raise value
        return value
    return S(call=call,timeout=15,last_diagnostics=None),calls


def invoke(c,**kwargs):return check(c,actor_id="actor",actor_uid="uid",ticket_lifetime=900,policy=deepcopy(POLICY),**kwargs)


def test_transient_readiness_failure_recovers_without_model_action_or_hidden_attempts():
    c,calls=client([failure(),READY]);waits=[];saved=[]
    result=invoke(c,wait=waits.append,on_observation=saved.append)
    assert result["ready"] and result["recovered"] and result["retry_count"]==1
    assert len(saved)==2 and saved[0]["attempts"][0]["status"]=="transient_failure" and waits==[.25]
    assert calls==[("/admission-readiness",{})]*2


def test_nested_transient_upstream_is_classified_not_outer_json_envelope():
    inner=failure();outer=RuntimeCallError("invalid_runtime_json",dict(boundary="driver_to_actor",operation="admission-readiness",status=409,content_type="application/json",failure="http_error"),inner.transport)
    assert retryable(outer)
    c,_=client([outer,READY]);assert invoke(c,wait=lambda _:None)["ready"]


@pytest.mark.parametrize("error",[failure(401),failure(403),failure(200),failure(code="trial_capacity"),failure(code="response_too_large"),ContractError("unauthenticated","authentication"),failure(None,kind="transport_error",exception="UnsupportedProtocol")])
def test_auth_protocol_capacity_and_unsupported_errors_fail_once(error):
    c,calls=client([error]);saved=[]
    with pytest.raises(ReadinessError) as caught:invoke(c,wait=lambda _:pytest.fail("nonretryable wait"),on_observation=saved.append)
    assert not caught.value.readiness["ready"] and len(calls)==1 and len(saved)==1


def test_identity_or_ticket_mismatch_never_retried_or_repaired():
    c,calls=client([dict(READY,actor_uid="other")])
    with pytest.raises(ReadinessError,match="identity_or_profile"):invoke(c,wait=lambda _:pytest.fail("identity retried"))
    assert len(calls)==1


def test_exhaustion_retains_all_three_attempts_and_fails_closed():
    c,calls=client([failure(),failure(504),failure(502)]);waits=[]
    with pytest.raises(ReadinessError,match="actor_readiness_unavailable") as caught:invoke(c,wait=waits.append)
    assert len(calls)==3 and waits==[.25,.5] and len(caught.value.readiness["attempts"])==3
    assert not caught.value.readiness["ready"]


def test_connect_and_partial_read_timeout_are_safe_to_retry_only_for_readiness():
    c,calls=client([failure(None,code="runtime_unavailable",kind="transport_error",exception="ReadTimeout"),READY])
    assert invoke(c,wait=lambda _:None)["ready"] and len(calls)==2


def test_policy_limits_cannot_be_quietly_relaxed():
    c,_=client([READY])
    with pytest.raises(ValueError,match="policy_binding"):check(c,actor_id="actor",actor_uid="uid",ticket_lifetime=900,policy=dict(POLICY,max_attempts=4))


def test_real_http_readiness_transient_is_retried_but_no_other_operation_is_sent():
    paths=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            paths.append(self.path);self.rfile.read(int(self.headers["Content-Length"]))
            body=b"temporary upstream unavailable" if len(paths)==1 else json.dumps(READY).encode()
            self.send_response(503 if len(paths)==1 else 200)
            self.send_header("Content-Type","text/plain" if len(paths)==1 else "application/json")
            self.send_header("Content-Length",str(len(body)));self.end_headers();self.wfile.write(body)
    server=ThreadingHTTPServer(("127.0.0.1",0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        c=RuntimeClient(f"http://127.0.0.1:{server.server_port}","Bearer synthetic-readiness-only",timeout=15,boundary="driver_to_actor")
        result=invoke(c,wait=lambda _:None)
        assert result["ready"] and result["recovered"] and paths==["/admission-readiness"]*2
        first=result["attempts"][0]
        assert first["transport"]["hops"][0]["status"]==503 and first["status"]=="transient_failure"
        assert "temporary upstream unavailable" not in json.dumps(result)
    finally:server.shutdown();server.server_close();thread.join(2)
