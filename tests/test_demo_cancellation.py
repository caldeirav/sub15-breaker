from contextlib import nullcontext
import threading
from types import SimpleNamespace

import httpx
import pytest

from src.agent_runtime.contracts import ToolCall
from src.banking_contracts.tools import ToolCatalog
from src.banking_service.upstream import initial_state
from src.benchmark.bridge import Bridge,MCPClient
from src.benchmark.guards import ReviewInput
from src.benchmark.native import Registry,LateAllowGuard
from src.benchmark.privacy import Mask


class Span:
    trace_id="unit";span_id="unit"
    def set_inputs(self,value):pass
    def set_outputs(self,value):pass
    def end(self):pass


@pytest.fixture
def spans(monkeypatch):
    monkeypatch.setattr("mlflow.start_span",lambda **kw:nullcontext(Span()))
    monkeypatch.setattr("mlflow.start_span_no_context",lambda **kw:Span())
    monkeypatch.setattr("mlflow.tracing.fluent.with_active_span",lambda span:nullcontext(span))
    monkeypatch.setattr("src.benchmark.bridge.with_active_span",lambda span:nullcontext(span))


def test_registry_cancellation_discards_late_allow_and_finishes_span(spans):
    registry=Registry();guard=LateAllowGuard();ticket="a"*32
    registry.register(ticket,ReviewInput("goal","policy","policy","read_file",{}),guard)
    worker=threading.Thread(target=lambda:registry.admit(ticket));worker.start()
    assert guard.started.wait(2)
    registry.cancel(ticket,"unit_caller_cancel")
    worker.join(2);assert not worker.is_alive() and registry.wait(ticket,0)
    result=registry.result(ticket)
    assert result["decision"]=="error" and result["discarded_decision"]=="allow"
    assert result["cancellation_reason"]=="unit_caller_cancel"


def test_mcp_error_fences_and_drains_before_collecting_action(spans):
    registry=Registry();guard=LateAllowGuard();ticket="a"*32;fences=[]
    class Store:
        def call(self,path,body):
            if path=="/snapshot":return dict(fingerprint="unchanged",context=dict(context_version=1,user_request="read"),generation=1,state_version=0,state=initial_state())
            if path=="/prepare":return dict(status="prepared",ticket=ticket)
            if path=="/fence":fences.append(True);return dict(fenced=True)
            if path=="/status":return dict(status="fenced_not_dispatched" if fences else "prepared")
            raise AssertionError(path)
    class Actor:
        def call(self,path,body):
            result=registry.admit(body["ticket"])
            assert result["decision"]=="error"
            return dict(status="admission_failed",actor_timings=dict(claim_roundtrip_ns=10))
    bridge=Bridge(ToolCatalog.from_pinned_agentdojo(),registry,Mask());bridge.configure(Store(),Actor(),"trial",guard)
    client=MCPClient("unused","unused",bridge,drain_timeout=2);client.names={"get_balance":"get_balance"};workers=[]
    def rpc(method,params):
        worker=threading.Thread(target=lambda:bridge.rpc(dict(id=1,method=method,params=params)));workers.append(worker);worker.start()
        assert guard.started.wait(2)
        with pytest.raises(RuntimeError,match="still_running"):bridge.configure(Store(),Actor(),"other",guard)
        raise httpx.ReadTimeout("controlled")
    client.rpc=rpc
    outcome=client.execute(ToolCall("call","get_balance",{}))
    for worker in workers:worker.join(2);assert not worker.is_alive()
    assert outcome.status=="error" and fences and bridge.wait_idle(0)
    assert len(bridge.actions)==1 and bridge.actions[0]["guard"]["discarded_decision"]=="allow"
    assert bridge.actions[0]["transport_reconciliation"]["initial_outcome"]=="unknown"


def test_demo_deadline_chain_covers_claim_worker_commit_and_response():
    from src.banking_service.deadlines import DEMO
    assert DEMO.actor_store+15+5+DEMO.commit+5<=DEMO.actor_server
    assert DEMO.reviewer<DEMO.native_hook<DEMO.actor_store<DEMO.actor_server<DEMO.actor_client<DEMO.mcp_client<DEMO.mcp_route<DEMO.ticket


def test_denied_claim_reports_same_clock_timing_without_tool_execution(monkeypatch):
    from src.banking_service.app import ActorApplication
    from src.banking_contracts.codec import ContractError
    def deny(*args):raise ContractError("denied","transport")
    monkeypatch.setattr("src.banking_service.app.bounded_evaluate",lambda *a:pytest.fail("tool executed after denial"))
    app=ActorApplication(SimpleNamespace(call=deny),SimpleNamespace(driver=lambda auth:None),benchmark_claim_path=True)
    result=app("/execute",{"ticket":"a"*32},"test")
    assert result["status"]=="admission_failed" and result["actor_timings"]["claim_roundtrip_ns"]>0


@pytest.mark.parametrize("code,expected",[("unauthenticated","unauthenticated"),("actor_identity_mismatch","actor_identity_mismatch"),("unsafe credential detail","unclassified_claim_error")])
def test_claim_diagnostics_preserve_only_allowlisted_safe_codes(code,expected):
    from src.banking_service.app import ActorApplication
    from src.banking_contracts.codec import ContractError
    def deny(*a):raise ContractError(code,"transport")
    app=ActorApplication(SimpleNamespace(call=deny),SimpleNamespace(driver=lambda auth:None),benchmark_claim_path=True)
    result=app("/execute",dict(ticket="a"*32),"test")
    assert result["claim_error_code"]==expected


def test_real_grpc_deadline_callback_collects_and_discards_late_allow(spans):
    from concurrent.futures import ThreadPoolExecutor
    import grpc
    from src.benchmark import extproc_wire as pb
    from src.benchmark.native import Processor
    registry=Registry();guard=LateAllowGuard();ticket="b"*32
    registry.register(ticket,ReviewInput("goal","policy","policy","read_file",{}),guard)
    service=grpc.server(ThreadPoolExecutor(max_workers=1));pb.add_processor(Processor(registry,"store"),service)
    port=service.add_insecure_port("127.0.0.1:0");service.start()
    try:
        with grpc.insecure_channel(f"127.0.0.1:{port}") as channel:
            invoke=channel.stream_stream("/envoy.service.ext_proc.v3.ExternalProcessor/Process",
                request_serializer=pb.ProcessingRequest.SerializeToString,response_deserializer=pb.ProcessingResponse.FromString)
            request=pb.ProcessingRequest(request_headers={"headers":{"headers":[
                {"key":":authority","value":"store"},{"key":":method","value":"POST"},{"key":":path","value":"/claim/"+ticket}]}})
            with pytest.raises(grpc.RpcError):list(invoke(iter([request]),timeout=.2))
            assert guard.started.is_set() and registry.wait(ticket,2)
            result=registry.result(ticket)
            assert result["decision"]=="error" and result["discarded_decision"]=="allow"
            assert result["cancellation_reason"]=="grpc_request_closed"
    finally:service.stop(0).wait(2)


def test_normal_completion_callback_does_not_relabel_success(spans):
    from src.benchmark.native import ControlGuard
    registry=Registry();ticket="c"*32
    registry.register(ticket,ReviewInput("goal","policy","policy","read_file",{}),ControlGuard("allow"))
    result=registry.admit(ticket);registry.cancel(ticket,"grpc_request_closed")
    assert registry.result(ticket)==result and result["decision"]=="allow"
    assert not registry.entries[ticket].cancelled.is_set()
