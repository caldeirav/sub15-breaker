import json

from src.benchmark import extproc_wire as pb
import pytest

from src.benchmark.budget import Budget
from src.benchmark.guards import ReviewInput
from src.benchmark.native import ControlGuard,Processor,Registry
from src.benchmark.privacy import Mask


def request(path,host="store",method="POST"):
    return pb.ProcessingRequest(request_headers={"headers":{"headers":[
        {"key":":authority","raw_value":host.encode()},{"key":":path","raw_value":path.encode()},
        {"key":":method","raw_value":method.encode()}]}})


def test_header_only_wire_matches_upstream_envoy_protobuf_bytes():
    golden="125a0a580a130a0a3a617574686f726974791a0573746f72650a300a053a706174681a272f636c61696d2f61616161616161616161616161616161616161616161616161616161616161610a0f0a073a6d6574686f641a04504f5354"
    assert request("/claim/"+"a"*32).SerializeToString().hex()==golden
    assert pb.ProcessingResponse(immediate_response=dict(status=dict(code=403),body=b"blocked",details="blocked")).SerializeToString().hex()=="3a170a030893031a07626c6f636b65642a07626c6f636b6564"
    assert pb.ProcessingResponse(request_headers=pb.HeadersResponse()).SerializeToString().hex()=="0a00"


@pytest.mark.parametrize("decision,status",[("allow",None),("block",403),("error",503)])
def test_native_processor_translates_bound_verdicts(tmp_path,decision,status,monkeypatch):
    # Protocol unit control only; actual Actor effects are a separate live test.
    import mlflow
    monkeypatch.setattr("src.benchmark.native.mlflow.start_span_no_context",lambda **kw:FakeSpan())
    monkeypatch.setattr("mlflow.tracing.fluent.with_active_span",lambda span:NullContext())
    registry=Registry();ticket="a"*32
    registry.register(ticket,ReviewInput("goal","policy","policy","echo",{}),ControlGuard(decision))
    response=list(Processor(registry,"store").Process(iter([request("/claim/"+ticket)]),None))[0]
    if status is None:assert response.WhichOneof("response")=="request_headers"
    else:assert response.immediate_response.status.code==status
    assert registry.result(ticket)["decision"]==decision
    replay=list(Processor(registry,"store").Process(iter([request("/claim/"+ticket)]),None))[0]
    assert replay.immediate_response.status.code==503


class FakeSpan:
    trace_id="unit-trace";span_id="unit-span"
    def set_inputs(self,value):pass
    def set_outputs(self,value):pass
    def end(self):pass


class NullContext:
    def __enter__(self):return self
    def __exit__(self,*args):pass


def test_native_processor_refuses_body_only_and_decoy_ticket_paths():
    processor=Processor(Registry(),"store")
    for path in ("/claim","/claim/"+"b"*32,"/claim/"+"a"*32+"?ticket="+"b"*32):
        response=list(processor.Process(iter([request(path)]),None))[0]
        assert response.immediate_response.status.code in {403,503}


def test_budget_accounts_all_roles_without_charging_external_to_local(tmp_path):
    budget=Budget(tmp_path)
    for i in range(6):budget.reserve(role="actor",case_id="user_task_0",trace_id="trace")
    with pytest.raises(RuntimeError,match="exhausted"):budget.reserve(role="actor",case_id="user_task_0",trace_id="trace")
    budget.reserve(role="gemini_harness_judge",case_id="suite",trace_id="review")
    assert len(list(tmp_path.glob("attempt-*.json")))==7
    with pytest.raises(RuntimeError,match="exhausted"):budget.reserve(role="llm_guard",case_id="user_task_2",trace_id="trace")


def test_budget_extension_preserves_spent_entries_and_original_policy(tmp_path):
    from src.benchmark.budget import EXTENDED_PILOT,PILOT
    old=Budget(tmp_path)
    for i in range(6):old.reserve(role="actor",case_id="user_task_2",trace_id="old")
    before=(tmp_path/"attempt-0001.json").read_bytes()
    extended=Budget(tmp_path,EXTENDED_PILOT)
    entry=extended.reserve(role="actor",case_id="user_task_2",trace_id="new")
    assert entry["sequence"]==7 and entry["policy_version"]==EXTENDED_PILOT["version"]
    assert (tmp_path/"attempt-0001.json").read_bytes()==before
    assert json.loads((tmp_path/"policy.json").read_text())==PILOT
    assert json.loads((tmp_path/"policy-v2.json").read_text())["local_total"]==160
    with pytest.raises(RuntimeError,match="superseded"):old.reserve(role="actor",case_id="user_task_0",trace_id="old")


def test_privacy_preserves_tool_schema_while_masking_values():
    mask=Mask(["known-secret"])
    schema={"type":"object","properties":{"password":{"type":"string"}},"required":["password"]}
    assert mask(schema)==schema
    exported=mask({"password":"actual-value","text":'result {"password":"known-secret"}'})
    assert exported["password"]=="[WITHHELD]" and "known-secret" not in json.dumps(exported)


def test_store_claim_consumes_only_the_path_ticket_and_rejects_decoy_body():
    from types import SimpleNamespace
    from src.banking_service.app import StoreApplication
    from src.banking_contracts.codec import ContractError
    observed=[]
    identities=SimpleNamespace(actor=lambda auth:SimpleNamespace(name="actor",uid="uid"))
    store=SimpleNamespace(claim=lambda *args:observed.append(args) or {"status":"executing"})
    app=StoreApplication(store,identities)
    ticket="a"*32
    assert app("/claim/"+ticket,{},"Bearer fixture")["status"]=="executing"
    assert observed==[(ticket,"actor","uid")]
    with pytest.raises(ContractError):app("/claim/"+ticket,{"ticket":"b"*32},"Bearer fixture")
    assert len(observed)==1


def test_actor_benchmark_claim_path_cannot_be_changed_by_model_body(monkeypatch):
    from types import SimpleNamespace
    from src.banking_service.app import ActorApplication
    observed=[]
    store=SimpleNamespace(call=lambda path,body:observed.append((path,body)) or {"status":"completed"})
    app=ActorApplication(store,SimpleNamespace(driver=lambda auth:None),benchmark_claim_path=True)
    assert app("/execute",{"ticket":"a"*32},"fixture")=={"status":"completed"}
    assert observed==[("/claim/"+"a"*32,{})]


def test_bridge_refuses_a_gateway_payload_different_from_bound_call():
    from src.agent_runtime.contracts import ToolCall
    from src.benchmark.bridge import Bridge
    bridge=Bridge(None,None,Mask())
    bridge.pending=(ToolCall("call","read_file",{"file_path":"approved"}),None)
    with pytest.raises(ValueError,match="binding_mismatch"):
        bridge.rpc(dict(jsonrpc="2.0",id=1,method="tools/call",params=dict(name="read_file",arguments={"file_path":"decoy"})))
    assert bridge.actions==[]


def test_trace_audit_accepts_untyped_imported_gateway_spans(monkeypatch):
    from types import SimpleNamespace as S
    from src.benchmark.wiring import audit_record
    spans=[S(span_id="root",parent_id=None,span_type="AGENT",name="root"),
        S(span_id="gateway",parent_id="root",span_type=None,name="gateway_http")]
    monkeypatch.setattr("src.benchmark.wiring.mlflow.get_trace",lambda trace_id:S(data=S(spans=spans),info=S(trace_id=trace_id)))
    result=audit_record(dict(trace_id="trace",evidence=dict(actions=[]),model_attempts=0,guard_control="allow"))
    assert result["span_types"]==["AGENT","UNKNOWN"] and result["orphan_count"]==0


def test_trace_audit_validates_mlflow_numeric_scores_as_doubles(monkeypatch):
    from types import SimpleNamespace as S
    from src.benchmark.wiring import audit_record
    span=S(span_id="root",parent_id=None,span_type="AGENT",name="root")
    assessment=S(name="wiring/model_attempts",value=0.0,span_id=None,
        source=S(source_type="CODE",source_id="benchmark-wiring-v1"))
    monkeypatch.setattr("src.benchmark.wiring.mlflow.get_trace",lambda trace_id:S(data=S(spans=[span]),info=S(trace_id=trace_id,assessments=[assessment])))
    assert audit_record(dict(trace_id="trace",evidence=dict(actions=[]),model_attempts=0,
        guard_control="allow",expected_scores={"wiring/model_attempts":0.0}))["root_count"]==1


def test_client_and_gateway_chat_spans_are_one_physical_model_attempt(monkeypatch):
    from types import SimpleNamespace as S
    from src.benchmark.wiring import audit_record
    def span(id,parent,name,type):return S(span_id=id,parent_id=parent,name=name,span_type=type,inputs={},outputs={})
    spans=[span("root",None,"episode","AGENT"),span("node","root","model","CHAIN"),
        span("client","node","ChatOpenAI","CHAT_MODEL"),span("http","client","managed_responses_http","CLIENT"),
        span("gateway","http","POST /v1/responses","CHAT_MODEL")]
    monkeypatch.setattr("src.benchmark.wiring.mlflow.get_trace",lambda trace_id:S(data=S(spans=spans),info=S(trace_id=trace_id,assessments=[])))
    result=audit_record(dict(trace_id="trace",evidence=dict(actions=[]),model_attempts=1,guard_control=None))
    assert result["chat_model_spans"]==result["managed_responses_dispatches"]==result["gateway_chat_model_spans"]==1
