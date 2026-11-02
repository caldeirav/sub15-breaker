"""Real observation context/projection mechanics, without providers or cluster calls."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from types import SimpleNamespace as S

import pytest

from src.agent_runtime.observability import observing,emit
from src.benchmark.guards import ReviewInput,Verdict
from src.demo_ui.runtime import ObservedRegistry,ObservedBridge,Runtime,summarize,validate_case_evidence


def test_observation_context_is_reset_and_no_observer_has_no_side_effects():
    first=[];second=[]
    emit("unit","not_observed")
    with observing(first.append):
        emit("unit","first")
        with observing(second.append):emit("unit","second")
        emit("unit","first_again")
    emit("unit","not_observed")
    assert [e["phase"] for e in first]==["first","first_again"]
    assert [e["phase"] for e in second]==["second"]
    assert all(e["monotonic_ns"]>0 and e["timestamp_ns"]>0 for e in first+second)


def test_native_worker_observes_the_ticket_owning_lane_not_ambient_thread(monkeypatch):
    class Span:
        trace_id="trace";span_id="span"
        def set_inputs(self,value):pass
        def set_outputs(self,value):pass
        def end(self):pass
    monkeypatch.setattr("src.benchmark.native.mlflow.start_span_no_context",lambda **kwargs:Span())
    monkeypatch.setattr("mlflow.tracing.fluent.with_active_span",lambda span:nullcontext())
    class Guard:
        guard_id="unit"
        def review(self,value):return Verdict(value.digest(),"allow",self.guard_id,.1)
    value=ReviewInput("goal","policy","policy","get_balance",{})
    registry=ObservedRegistry();first=[];second=[]
    with observing(first.append):registry.register("a"*32,value,Guard())
    with observing(second.append):registry.register("b"*32,value,Guard())
    with ThreadPoolExecutor(max_workers=1) as worker:
        assert worker.submit(registry.admit,"a"*32).result()["decision"]=="allow"
        assert worker.submit(registry.admit,"b"*32).result()["decision"]=="allow"
    assert [e["stage"] for e in first]==["guard_review","guard_review","native_admission"]
    assert [e["stage"] for e in second]==["guard_review","guard_review","native_admission"]


def test_bridge_http_worker_attaches_the_selected_observer(monkeypatch):
    def dispatch(self,call,parent):emit("dispatch","unit");return "outcome"
    monkeypatch.setattr("src.benchmark.bridge.Bridge.dispatch",dispatch)
    bridge=ObservedBridge(None,None,None);events=[];bridge.observer=events.append
    with ThreadPoolExecutor(max_workers=1) as worker:assert worker.submit(bridge.dispatch,None,None).result()=="outcome"
    assert len(events)==1 and events[0]["stage"]=="dispatch"


def record(fault=False):
    gate=dict(decision="error" if fault else "allow",ticket="ticket",input_digest="digest",span_id="guard",
              review_latency_ns=20_000_000,classifier_decision_core_ns=10_000_000,error="fault" if fault else None)
    action=dict(tool="send_money",canonical_arguments=dict(amount="1",recipient="synthetic",password="private"),
        action_id="action",ticket="ticket",span_id="tool",native_admission_attempted=True,status="error" if fault else "executed",
        guard=gate,before_fingerprint="before",after_fingerprint="before" if fault else "after",
        snapshot_prepare_ns=3_000_000,review_materialization_ns=2_000_000,
        actor_timings=dict(claim_roundtrip_ns=30_000_000,tool_evaluation_ns=4_000_000,commit_roundtrip_ns=5_000_000))
    if not fault:action["execution_receipt"]=dict(executed=True,action_id="action",trial_id="trial")
    return dict(case_id="unit",trial_id="trial",trace_id="trace",child_run_id="run",experiment_id="5",
        producer="scripted" if fault else "acting_model",status="error" if fault else "completed",tool_attempts=1,
        evidence=dict(actions=[action],final_answer="fixture"),measured=dict(utility=not fault),
        store_events=[] if fault else [dict(kind="tool_attempt",payload=dict(ticket="ticket"))],
        cleanup_errors=[],telemetry_reconciliation=dict(status="complete"),
        post_reconciliation_state=dict(fingerprint_matches_final=True,tool_attempts_match_final=True),
        trace_audit=dict(managed_responses_dispatches=0 if fault else 1,guard_managed_responses_dispatches=0))


@pytest.mark.parametrize("fault",[False,True])
def test_summary_uses_independent_golden_and_nested_timer_boundaries(monkeypatch,fault):
    client=S(name="managed_responses_http",span_id="http",parent_id=None,span_type="CLIENT",start_time_ns=0,end_time_ns=100)
    gateway=S(name="qwen",span_id="gateway",parent_id="http",span_type="CHAT_MODEL",start_time_ns=10,end_time_ns=90)
    mcp=S(name="tools/call",span_id="mcp",parent_id=None,span_type="TOOL",start_time_ns=0,end_time_ns=200)
    monkeypatch.setattr("src.demo_ui.runtime.mlflow.get_trace",lambda trace_id:S(data=S(spans=[] if fault else [client,gateway,mcp])))
    spec=dict(kind="control" if fault else "card",mode="error" if fault else None,card_id="D04" if fault else "D01",arm="classifier",producer="fault_control" if fault else "acting_model")
    result=summarize(spec,record(fault),[],dict(accuracy=dict(rows=[dict(input_digest="digest",golden_decision="allow")])))
    assert result["golden_pass"] and result["cleanup_ok"]
    assert result["actions"][0]["arguments"]["password"]=="[WITHHELD]"
    if fault:
        assert result["timing"]["classifier_core"] is result["timing"]["guard_whole_review"] is None
        assert not result["actions"][0]["golden_covered"] and result["actions"][0]["golden_decision"] is None
    else:
        assert result["timing"]["classifier_core"]["median_ms"]==10
        assert result["timing"]["guard_whole_review"]["median_ms"]==20
        assert result["timing"]["native_claim_roundtrip"]["median_ms"]==30
        assert result["timing"]["gateway_model_server"]["count"]==1
        assert result["timing"]["gateway_mcp_server"]["count"]==1


def test_runtime_restoration_attempts_still_run_when_final_capacity_read_fails(tmp_path):
    runtime=Runtime({},None,tmp_path,tmp_path/"artifact")
    runtime.directory.mkdir()
    def unavailable(*args):raise RuntimeError("capacity unavailable")
    runtime.store=S(call=unavailable)
    cleaned=[];runtime.stack.callback(lambda:cleaned.append(True))
    with pytest.raises(RuntimeError,match="capacity unavailable"):runtime.close()
    assert cleaned==[True]


def test_clarification_quality_failure_is_not_relabelled_as_enforcement_failure():
    value=record(False);value["evidence"]["actions"]=[];value["tool_attempts"]=0
    value["measured"]["utility"]=False;value["store_events"]=[]
    spec=dict(kind="card",card_id="D01",expected="allow",arm="classifier")
    card=validate_case_evidence(spec,value)
    assert not card["demo_ready"] and card["observed_review"] is None
    value["tool_attempts"]=1
    with pytest.raises(RuntimeError,match="enforcement_or_effect"):validate_case_evidence(spec,value)


def test_live_external_rubric_declares_scripted_fault_applicability_without_erasing_wiring_gates():
    from src.demo_ui.review import INSTRUCTIONS,VERSION
    assert VERSION=="live-native-card-review-v1"
    assert "zero physical ACTOR model requests" in INSTRUCTIONS
    assert "not classifier/LLM quality evidence" in INSTRUCTIONS
    assert "supported only if ALL required wiring criteria" in INSTRUCTIONS
    assert "receipts and state versions" in INSTRUCTIONS
    assert "Do not certify browser layout" in INSTRUCTIONS


def test_authority_renewal_changes_credentials_only_and_does_not_invoke_a_model(tmp_path,monkeypatch):
    from src.benchmark.privacy import Mask
    runtime=Runtime({},None,tmp_path,tmp_path/"artifact")
    (tmp_path/"runtime.token").write_text("new-private-driver-token")
    monkeypatch.setattr("src.demo_ui.runtime.DIRECTORY",tmp_path)
    renewed=[];models=[]
    runtime.deployment=S(refresh_credentials=lambda:renewed.append(True))
    runtime.mask=Mask(["old"]);runtime.store=S(authorization="old");runtime.mcp=S(token="old")
    runtime.model_common=dict(model="unchanged-model",api_key="old",http_client=object(),temperature=0,max_retries=0)
    monkeypatch.setattr("src.demo_ui.runtime.ChatOpenAI",lambda **kwargs:models.append(kwargs) or S())
    monkeypatch.setattr("src.demo_ui.runtime.llm_guard",lambda model,**kwargs:S(model=model,**kwargs))
    runtime.renew_authority()
    assert renewed==[True] and runtime.store.authorization=="Bearer new-private-driver-token"
    assert runtime.mcp.token=="new-private-driver-token" and models[0]["model"]=="unchanged-model"
    assert models[0]["temperature"]==0 and models[0]["max_retries"]==0
    assert "new-private-driver-token" in runtime.mask.secrets
