from copy import deepcopy
import hashlib
import json

import pytest

from src.benchmark.budget import Budget,EXTENDED_PILOT
from src.benchmark.campaign_budget import CampaignBudget
from src.benchmark.demo import make_plan
from src.benchmark.demo_budget import DemoBudget
from src.benchmark.measurement import distribution,server_projection,summary
from src.benchmark.training_budget import TrainingBudget,POLICY
from src.infra.model_budget import encoded


def budget(path):
    Budget(path).reserve(role="actor",case_id="user_task_0",trace_id="old")
    Budget(path,EXTENDED_PILOT).reserve(role="gemini_harness_judge",case_id="suite",trace_id="old")
    CampaignBudget(path).freeze();TrainingBudget(path).freeze();return DemoBudget(path)


def phase():
    return dict(namespace="nd2",phase="measurement",policy_sha256=hashlib.sha256(encoded(POLICY)).hexdigest(),acting_model="frozen",
        **{key:"a"*64 for key in ("artifact_manifest_sha256","calibration_sha256","fixtures_sha256","code_sha256")},
        cases=[dict(case_id="nd2-probe",task_id="user_task_0",actor=1)])


def test_fresh_phase_never_resets_old_history_and_allocations_are_irreversible(tmp_path):
    b=budget(tmp_path);old=(tmp_path/"attempt-0001.json").read_bytes();p=phase();b.freeze_phase(p);b.freeze_phase(p)
    assert b.phase("nd2")==p
    row=b.reserve(role="actor",case_id="nd2-probe",trace_id="new",model="frozen")
    assert row["sequence"]==3 and (tmp_path/"attempt-0001.json").read_bytes()==old
    with pytest.raises(RuntimeError,match="exhausted"):b.reserve(role="actor",case_id="nd2-probe",trace_id="repeat",model="frozen")
    changed=deepcopy(p);changed["acting_model"]="changed"
    with pytest.raises(RuntimeError,match="phase_changed"):b.freeze_phase(changed)


def test_measurement_phase_is_bounded_and_tamper_evident(tmp_path):
    b=budget(tmp_path);p=phase();p["cases"][0]["actor"]=129
    with pytest.raises(ValueError,match="allocation_cap"):b.freeze_phase(p)
    p=phase();b.freeze_phase(p)
    path=tmp_path/"native-demo-nd2.json";value=json.loads(path.read_text());value["plan"]["acting_model"]="tampered";path.write_text(json.dumps(value))
    with pytest.raises(RuntimeError,match="phase_changed"):b.phase("nd2")


def test_review_allowance_is_additive_scoped_and_preserves_v4_history(tmp_path):
    b=budget(tmp_path);before={p.name:p.read_bytes() for p in tmp_path.iterdir() if p.is_file()}
    assert b.approve_review_extension(namespaces=["nd7","nd8"],reason="explicit owner approval for new pair")==136
    assert b.external_limit("nd7")==136 and b.external_limit("nd8")==136
    assert b.external_limit("nd6")==128 and b.external_limit("nd9")==128
    assert all((tmp_path/name).read_bytes()==value for name,value in before.items())
    path=tmp_path/"demo-review-extension-v1.json";value=json.loads(path.read_text());value["additional_external"]=9;path.write_text(json.dumps(value))
    with pytest.raises(RuntimeError,match="extension_changed"):b.external_limit("nd7")


def test_acceptance_allowance_is_new_exact_eighteen_and_does_not_rewrite_history(tmp_path):
    b=budget(tmp_path);before={p.name:p.read_bytes() for p in tmp_path.iterdir() if p.is_file()}
    assert b.approve_acceptance_allowance(reason="owner authorized full acceptance with readiness-only retries")==18
    assert b.external_limit("nd9")==18 and b.external_limit("nd10")==18
    assert b.external_limit("nd8")==128 and b.external_limit("nd11")==128
    assert all((tmp_path/name).read_bytes()==value for name,value in before.items())
    path=tmp_path/"demo-acceptance-allowance-v1.json";value=json.loads(path.read_text());value["new_external_limit"]=19;path.write_text(json.dumps(value))
    with pytest.raises(RuntimeError,match="allowance_changed"):b.external_limit("nd9")


def test_golden_retest_allowance_is_exact_scoped_and_additive(tmp_path):
    b=budget(tmp_path);before={p.name:p.read_bytes() for p in tmp_path.iterdir() if p.is_file()}
    assert b.approve_golden_allowance(reason="owner requested primed golden accuracy retest")==18
    assert b.external_limit("nd11")==18 and b.external_limit("nd12")==18 and b.external_limit("nd13")==128
    assert all((tmp_path/name).read_bytes()==value for name,value in before.items())
    path=tmp_path/"golden-demo-allowance-v1.json";v=json.loads(path.read_text());v["maximum_new_external_operations"]=19;path.write_text(json.dumps(v))
    with pytest.raises(RuntimeError,match="golden_allowance_changed"):b.external_limit("nd11")


def test_new_matrix_declares_fixed_eight_diagnostics_and_twelve_encoder_calls(monkeypatch,tmp_path):
    monkeypatch.setattr("src.benchmark.demo.DIRECTORY",tmp_path)
    (tmp_path/"deployment.json").write_text(json.dumps(dict(deadline_profile="native-measure-v2",image="image@sha256:"+"a"*64,template="owned")))
    monkeypatch.setattr("src.benchmark.demo.manifest",lambda *a,**kw:dict(model_id="frozen-v1",calibration=dict(threshold=.5)))
    p=make_plan(tmp_path,acting_model="frozen",namespace="nd2")
    assert sum(c.get("actor",0)+c.get("llm_guard",0) for c in p["cases"])==128
    assert sum(c.get("gemini_task_judge",0)+c.get("gemini_harness_judge",0) for c in p["cases"])==17
    assert len([c for c in p["cases"] if c["kind"]=="diagnostic"])==8
    assert next(c for c in p["cases"] if c["kind"]=="encoder_measurement")["encoder_forward_cap"]==12
    assert p["deadlines"]["reviewer"]==300 and p["model_backend_timeout"]>300
    budget(tmp_path/"ledger").freeze_phase(p)
    continuation=make_plan(tmp_path,acting_model="frozen",namespace="nd3")
    assert sum(c.get("actor",0)+c.get("llm_guard",0) for c in continuation["cases"])==120
    assert not any(c["kind"] in {"diagnostic","encoder_measurement"} for c in continuation["cases"])


def test_full_comparison_is_fixed_117_local_with_all_three_native_workflows(monkeypatch,tmp_path):
    monkeypatch.setattr("src.benchmark.demo.DIRECTORY",tmp_path)
    (tmp_path/"deployment.json").write_text(json.dumps(dict(deadline_profile="native-measure-v2",image="image@sha256:"+"a"*64,template="owned")))
    monkeypatch.setattr("src.benchmark.demo.manifest",lambda *a,**kw:dict(model_id="frozen",calibration=dict(threshold=.5)))
    monkeypatch.setattr("src.benchmark.demo.cohort",lambda base:dict(rows=[dict(candidate_id=str(i),task_id="user_task_0",input_digest=str(i)) for i in range(19)]))
    p=make_plan(tmp_path,acting_model="frozen",namespace="nd4")
    assert sum(c.get("actor",0)+c.get("llm_guard",0) for c in p["cases"])==117
    assert sum(c.get("gemini_task_judge",0)+c.get("gemini_harness_judge",0) for c in p["cases"])==17
    assert {(c["task_id"],c["arm"]) for c in p["cases"] if c["kind"]=="card" and c["producer"]=="acting_model"}=={
        (task,arm) for task in ("user_task_0","user_task_2","user_task_13") for arm in ("classifier","llm")}
    assert p["reviewer_prompt_version"]=="v2" and p["decision_latency_target_ms"]==15
    budget(tmp_path/"ledger").freeze_phase(p)


def test_completion_profile_covers_full_chain_without_changing_legacy():
    from src.banking_service.deadlines import MEASURE,DEMO
    assert MEASURE.actor_store+15+5+MEASURE.commit+5<=MEASURE.actor_server
    assert MEASURE.reviewer<MEASURE.native_hook<MEASURE.actor_store<MEASURE.actor_server<MEASURE.actor_client<430<MEASURE.mcp_client<MEASURE.mcp_route<MEASURE.ticket
    assert DEMO.reviewer==20 and DEMO.native_hook==25


def test_new_demo_and_full_harness_share_resident_startup_and_reserved_probes(monkeypatch,tmp_path):
    from src.benchmark.guards import ReviewInput
    monkeypatch.setattr("src.benchmark.demo.DIRECTORY",tmp_path)
    (tmp_path/"deployment.json").write_text(json.dumps(dict(deadline_profile="native-measure-v2",image="pinned",template="owned")))
    monkeypatch.setattr("src.benchmark.demo.manifest",lambda *a,**k:dict(model_id="frozen",calibration=dict(threshold=.5)))
    def rows(count,prefix):
        result=[]
        for i in range(count):
            value=ReviewInput(prefix+str(i),"policy","policy","get_balance",{})
            result.append(dict(candidate_id=prefix+str(i),task_id="user_task_0",input_digest=value.digest(),model_input=value.serialized()))
        return result
    monkeypatch.setattr("src.benchmark.demo_qualification.fixture_cohort",lambda *a,**k:dict(rows=rows(5,"gold")))
    monkeypatch.setattr("src.benchmark.demo.cohort",lambda *a:dict(rows=rows(19,"dev")))
    q=make_plan(tmp_path,acting_model="frozen",namespace="nd11",protocol="demo-qualification-v1")
    r=make_plan(tmp_path,acting_model="frozen",namespace="nd12",protocol="demo-rehearsal-v1",rehearsal_of="nd11")
    full=make_plan(tmp_path,acting_model="frozen",namespace="nd13")
    assert q["startup_profile"]==r["startup_profile"]==full["startup_profile"]
    assert q["startup_inputs"]==r["startup_inputs"] and len(q["accuracy"]["rows"])==5
    assert sum(c.get("actor",0)+c.get("llm_guard",0) for c in q["cases"])==88
    assert sum(c.get("actor",0)+c.get("llm_guard",0) for c in r["cases"])==66
    assert sum(c.get("actor",0)+c.get("llm_guard",0) for c in full["cases"])==121
    assert next(c["encoder_forward_cap"] for c in q["cases"] if c["kind"]=="encoder_measurement")==30
    assert all(p["serving"]["classifier_lifetime"]=="resident-primed-for-run" for p in (q,r,full))
    assert all("unsafe_label" not in item for item in q["startup_inputs"])


def test_errors_stay_visible_but_never_become_fast_completion_samples():
    value=summary([dict(probe="read",index=0,status="error",elapsed_ms=300000),dict(probe="read",index=1,status="completed",elapsed_ms=2000)])
    assert value["read"]["errors"]==1 and value["read"]["completed"]["minimum_ms"]==2000
    assert distribution([])==dict(count=0)


def test_server_estimates_scale_only_measured_stages_and_are_not_claims():
    rows=[dict(index=1,review=dict(decision="allow",review_latency_ns=100000000,encoder_stage_timings_ns=dict(forward_and_host_result_ns=80000000)))]
    result=server_projection(rows)
    assumed=next(s for s in result["scenarios"] if s["assumed_forward_speedup"]==10 and s["assumed_host_speedup"]==1)
    assert assumed["projected_review"]["median_ms"]==28
    assert result["measured_server"] is False and result["full_admission_claim"] is False and result["sub15ms_claim"] is False
