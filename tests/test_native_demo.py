from copy import deepcopy
import hashlib
import json
import sys

import pytest

from src.benchmark.demo import main,make_card,make_plan,performance,require_prior_evidence,select_cases,uncovered_store_action,write_report
from src.benchmark.demo_budget import DemoBudget
from src.benchmark.budget import Budget,EXTENDED_PILOT
from src.benchmark.campaign_budget import CampaignBudget
from src.benchmark.training_budget import TrainingBudget,POLICY
from src.infra.model_budget import encoded


def budget(path):
    Budget(path).reserve(role="actor",case_id="user_task_0",trace_id="old")
    Budget(path,EXTENDED_PILOT).reserve(role="gemini_harness_judge",case_id="suite",trace_id="old")
    CampaignBudget(path).freeze();TrainingBudget(path).freeze()


def plan():
    return dict(schema_version="native-demo-matrix-v1",policy_sha256=hashlib.sha256(encoded(POLICY)).hexdigest(),
        artifact_manifest_sha256="a"*64,calibration_sha256="b"*64,fixtures_sha256="c"*64,code_sha256="d"*64,acting_model="frozen",
        cases=[dict(case_id="nd1-test",task_id="user_task_0",actor=1,llm_guard=1),
            dict(case_id="nd1-review",task_id=None,gemini_harness_judge=1)])


def test_budget_retains_history_binds_models_and_exhausts_allocations(tmp_path):
    budget(tmp_path);value=DemoBudget(tmp_path);definition=plan();prior=(tmp_path/"attempt-0001.json").read_bytes()
    value.freeze_demo(definition);value.freeze_demo(definition)
    with pytest.raises(RuntimeError,match="model_binding"):
        value.reserve(role="actor",case_id="nd1-test",trace_id="unit",model="wrong")
    entry=value.reserve(role="actor",case_id="nd1-test",trace_id="unit",model="frozen")
    assert entry["sequence"]==3 and (tmp_path/"attempt-0001.json").read_bytes()==prior
    with pytest.raises(RuntimeError,match="exhausted"):
        value.reserve(role="actor",case_id="nd1-test",trace_id="again",model="frozen")
    value.reserve(role="gemini_harness_judge",case_id="nd1-review",trace_id="unit",model=POLICY["gemini_model"])
    definition["code_sha256"]="e"*64
    with pytest.raises(RuntimeError,match="matrix_changed"):value.freeze_demo(definition)


def test_budget_rejects_overallocation_and_tampering(tmp_path):
    budget(tmp_path);value=DemoBudget(tmp_path);definition=plan()
    definition["cases"][0]["actor"]=769
    with pytest.raises(ValueError,match="local_cap"):value.freeze_demo(definition)
    definition=plan();value.freeze_demo(definition)
    (tmp_path/"native-demo-matrix-v1.json").write_text("{}")
    with pytest.raises(RuntimeError,match="matrix_changed"):value.demo()


def test_matrix_binds_full_prefixes_producers_and_exact_planning_caps(monkeypatch,tmp_path):
    monkeypatch.setattr("src.benchmark.demo.DIRECTORY",tmp_path)
    (tmp_path/"deployment.json").write_text(json.dumps(dict(deadline_profile="native-demo-v1",image="image@sha256:"+"a"*64,template="owned")))
    monkeypatch.setattr("src.benchmark.demo.manifest",lambda *a,**kw:dict(model_id="frozen-v1",calibration=dict(threshold=.5)))
    value=make_plan(tmp_path,acting_model="frozen")
    assert sum(c.get("actor",0)+c.get("llm_guard",0) for c in value["cases"])==120
    assert sum(c.get("gemini_task_judge",0)+c.get("gemini_harness_judge",0) for c in value["cases"])==17
    assert [c["tool_name"] for c in value["fixtures"]["user_task_0"]]==["read_file","send_money"]
    assert len(value["fixtures"]["injection_task_0"])==1
    assert len(value["code_hashes"])>=18
    budget(tmp_path/"ledger");DemoBudget(tmp_path/"ledger").freeze_demo(value)


def test_real_case_cannot_skip_required_native_controls(tmp_path):
    value=DemoBudget(tmp_path)
    definition=dict(cases=[dict(case_id="nd1-control-allow",kind="control")])
    with pytest.raises(RuntimeError,match="required_native_evidence_missing"):
        require_prior_evidence(value,definition,dict(kind="card"))


def correction_plan():
    value=plan();value["cases"][0]["kind"]="canary"
    value["cases"][1]["kind"]="external_review"
    value["code_hashes"]={name:"old" for name in ("src/benchmark/deployment.py","src/benchmark/demo.py","src/benchmark/demo_budget.py","src/benchmark/native.py")}
    return value


def test_setup_correction_is_additive_scoped_and_preserves_original_matrix(tmp_path):
    budget(tmp_path);value=DemoBudget(tmp_path);parent=correction_plan();value.freeze_demo(parent)
    original=(tmp_path/"native-demo-matrix-v1.json").read_bytes();current=deepcopy(parent)
    for path in ("src/benchmark/deployment.py","src/benchmark/demo.py","src/benchmark/demo_budget.py"):current["code_hashes"][path]="new"
    current["code_sha256"]="e"*64
    effective=value.freeze_setup_correction(current,failed_setup_run_id="f"*32)
    assert value.demo()==effective and (tmp_path/"native-demo-matrix-v1.json").read_bytes()==original
    assert effective["setup_correction"]["repeated_cases"]==[] and effective["cases"]==parent["cases"]
    wrong=deepcopy(current);wrong["cases"][0]["actor"]=2
    with pytest.raises(ValueError,match="protocol_or_allocation"):value.freeze_setup_correction(wrong,failed_setup_run_id="f"*32)


def test_setup_correction_rejects_started_learned_cases(tmp_path):
    budget(tmp_path);value=DemoBudget(tmp_path);parent=correction_plan();value.freeze_demo(parent)
    current=deepcopy(parent)
    for path in ("src/benchmark/deployment.py","src/benchmark/demo.py","src/benchmark/demo_budget.py"):current["code_hashes"][path]="new"
    (tmp_path/"native-case-nd1-test.json").write_text(json.dumps(dict(case_id="nd1-test")))
    with pytest.raises(RuntimeError,match="unstarted"):value.freeze_setup_correction(current,failed_setup_run_id="f"*32)


def cases():
    return dict(cases=[dict(kind="control",mode=mode,case_id="nd1-control-"+mode) for mode in ("allow","block","error","timeout","cancel")]+
        [dict(kind="canary",arm="llm",case_id="nd1-canary-llm")]+
        [dict(kind="card",card_id=card,arm=arm,case_id=card+arm) for card in ("D01","D02","D03") for arm in ("classifier","llm")])


def test_selector_intersects_stage_card_and_backend():
    chosen=select_cases(cases(),stage="cards")
    assert len(chosen)==8 and not any(c["kind"]=="canary" or c.get("mode")=="allow" for c in chosen)
    assert len(select_cases(cases(),stage="cards",demo_case="deny-extra-transfer",guard="classifier"))==1
    assert select_cases(cases(),demo_case="D05")[0]["mode"]=="cancel"
    with pytest.raises(ValueError,match="empty"):select_cases(cases(),stage="canary",demo_case="D01")


def record(decision="allow"):
    action=dict(tool="send_money",call_id="call",ticket="ticket",action_id="action",native_admission_attempted=True,span_id="tool",
        status="executed" if decision=="allow" else "blocked" if decision=="block" else "error",before_fingerprint="before",after_fingerprint="after" if decision=="allow" else "before",
        guard=dict(ticket="ticket",decision=decision,input_digest="digest",span_id="guard",review_latency_ns=1000000,admission_service_ns=2000000),
        actor_timings=dict(claim_roundtrip_ns=3000000),actor_roundtrip_ns=5000000)
    events=[]
    if decision=="allow":
        action["execution_receipt"]=dict(executed=True,action_id="action",trial_id="trial")
        events=[dict(kind="tool_attempt",payload=dict(ticket="ticket"))]
    return dict(case_id="unit",trial_id="trial",trace_id="trace",child_run_id="run",producer="scripted",status="completed",tool_attempts=1,measured=dict(utility=True),
        evidence=dict(actions=[action]),store_events=events,cleanup_errors=[],trace_audit=dict(root_count=1),
        telemetry_reconciliation=dict(status="complete"),post_reconciliation_state=dict(fingerprint_matches_final=True,tool_attempts_match_final=True))


def test_cards_require_bound_evidence_and_separate_reviewer_mistakes():
    spec=dict(kind="card",card_id="D01");value=record()
    assert make_card(spec,value)["demo_ready"]
    denied=make_card(spec,record("block"))
    assert denied["enforcement_correct"] and not denied["reviewer_matches_intent"] and not denied["demo_ready"]
    for key in ("guard","execution_receipt","native_admission_attempted"):
        broken=deepcopy(value);broken["evidence"]["actions"][0].pop(key)
        assert not make_card(spec,broken)["demo_ready"]
    value["evidence"]["actions"][0]["execution_receipt"]["action_id"]="unrelated"
    assert not make_card(spec,value)["enforcement_correct"]


def test_cards_cannot_be_ready_before_reconciliation_and_late_state_readback():
    spec=dict(kind="card",card_id="D01")
    for key in ("telemetry_reconciliation","post_reconciliation_state"):
        value=record();value.pop(key)
        assert not make_card(spec,value)["demo_ready"]
    value=record();value["telemetry_reconciliation"]["status"]="incomplete"
    assert not make_card(spec,value)["demo_ready"] and make_card(spec,value)["enforcement_correct"]


def test_bad_proposal_and_fault_cards_use_their_declared_expectations():
    value=record("block");action=value["evidence"]["actions"][0]
    value["evidence"]["actions"]=[dict(action,tool="read_file"),dict(action,tool="send_money"),action]
    value["tool_attempts"]=3
    card=make_card(dict(kind="card",card_id="D02"),value)
    assert card["expected_review"]=="block" and card["demo_ready"] and card["prefix_actions"]==2
    value=record("error")
    assert not make_card(dict(kind="control",mode="cancel"),value)["demo_ready"]
    value["evidence"]["actions"][0]["guard"]["discarded_decision"]="allow"
    assert make_card(dict(kind="control",mode="cancel"),value)["demo_ready"]
    assert make_card(dict(kind="control",mode="error"),value)["card_id"]=="D04"


def test_uncovered_logical_proposal_cannot_inherit_a_read_dispatch_enforcement_pass():
    value=record();value["status"]="unknown";value["tool_attempts"]=2
    card=make_card(dict(kind="card",card_id="D01"),value)
    assert card["observed_dispatch_enforcement_correct"] is True
    assert card["enforcement_evidence_complete"] is False and card["uncovered_logical_tool_attempts"]==1
    assert card["enforcement_correct"] is False and card["demo_ready"] is False
    assert uncovered_store_action(value) is False
    value["store_events"].append(dict(kind="action_prepared",payload=dict(ticket="unobserved-ticket")))
    assert uncovered_store_action(value) is True


def test_performance_keeps_raw_nested_samples_and_report_escapes_html(tmp_path):
    data=performance(record())
    assert data["distributions"]["review_latency_ns"]["raw_ms"]==[1.0]
    assert data["distributions"]["claim_roundtrip_ns"]["raw_ms"]==[3.0]
    write_report(tmp_path,[dict(case_id="</script><img src=x>",demo_ready=False)])
    assert "</script><img" not in (tmp_path/"review.html").read_text()


@pytest.mark.parametrize("flag",["--dry-run","--list-demo-cases"])
def test_listing_needs_no_keys_cluster_or_inference(monkeypatch,capsys,flag):
    monkeypatch.setattr(sys,"argv",["demo",flag])
    monkeypatch.setattr("src.benchmark.demo.Deployment",lambda:pytest.fail("cluster touched"))
    monkeypatch.delenv("GEMINI_API_KEY",raising=False);monkeypatch.delenv("LM_STUDIO_MODEL",raising=False)
    main();result=json.loads(capsys.readouterr().out)
    assert result["inference_requests"]==0 and result["cluster_mutations"]==0 and len(result["cards"])==5
