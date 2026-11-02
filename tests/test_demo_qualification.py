from copy import deepcopy
from contextlib import nullcontext
import hashlib
import json
from types import SimpleNamespace

import pytest

from src.benchmark.demo import make_plan
from src.benchmark.demo_qualification import binding,freeze_campaign,require_campaign,paired_marker,effective_settings,duration_seconds,failure_report
from src.integrations.agentdojo.inventory import digest


def plans(monkeypatch,tmp_path):
    monkeypatch.setattr("src.benchmark.demo.DIRECTORY",tmp_path)
    (tmp_path/"deployment.json").write_text(json.dumps(dict(deadline_profile="native-measure-v2",image="pinned",template="owned")))
    monkeypatch.setattr("src.benchmark.demo.manifest",lambda *a,**k:dict(model_id="frozen",calibration=dict(threshold=.5)))
    monkeypatch.setattr("src.benchmark.demo_qualification.fixture_cohort",lambda *a:dict(rows=[dict(candidate_id=str(i),task_id="user_task_0",input_digest=str(i)) for i in range(4)]))
    q=make_plan(tmp_path,acting_model="frozen",namespace="nd5",protocol="demo-qualification-v1")
    r=make_plan(tmp_path,acting_model="frozen",namespace="nd6",protocol="demo-rehearsal-v1",rehearsal_of="nd5")
    return q,r


def test_explicit_protocol_keeps_original_cards_and_separates_rehearsal(monkeypatch,tmp_path):
    q,r=plans(monkeypatch,tmp_path)
    assert binding(q)==binding(r) and q["reviewer_prompt_version"]=="v2"
    for p,local,external in ((q,80,17),(r,64,1)):
        assert sum(c.get("actor",0)+c.get("llm_guard",0) for c in p["cases"])==local
        assert sum(c.get("gemini_task_judge",0)+c.get("gemini_harness_judge",0) for c in p["cases"])==external
        assert len([c for c in p["cases"] if c["kind"] in {"control","canary","card"}])==14
        assert not any(c.get("card_id")=="E02" for c in p["cases"])
    assert "accuracy" not in r
    with pytest.raises(ValueError,match="rehearsal_parent"):make_plan(tmp_path,acting_model="frozen",namespace="nd6",protocol="demo-rehearsal-v1")


def test_rehearsal_cannot_start_without_source_bound_qualification(monkeypatch,tmp_path):
    q,r=plans(monkeypatch,tmp_path)
    preflight=tmp_path/"preflight.json";preflight.write_text("verified")
    (tmp_path/"demo-campaign-nd5.json").write_text(json.dumps(dict(qualification="nd5",rehearsal="nd6",qualification_sha256=digest(q),rehearsal_sha256=digest(r),transport_preflight_hashes={str(preflight):hashlib.sha256(preflight.read_bytes()).hexdigest()})))
    budget=SimpleNamespace(directory=tmp_path,phase=lambda n:{"nd5":q,"nd6":r}[n])
    require_campaign(budget,q)
    with pytest.raises(FileNotFoundError):require_campaign(budget,r)
    report=tmp_path/"report.json";report.write_text(json.dumps(dict(qualified=False,source_hashes={})))
    marker=tmp_path/"demo-qualified-nd5.json"
    marker.write_text(json.dumps(dict(matrix_sha256=digest(q),report_path=str(report),report_sha256=hashlib.sha256(report.read_bytes()).hexdigest())))
    with pytest.raises(RuntimeError,match="qualification_failed"):require_campaign(budget,r)
    report.write_text(json.dumps(dict(qualified=True,source_hashes={})))
    with pytest.raises(RuntimeError,match="evidence_changed"):require_campaign(budget,r)


def test_campaign_refuses_different_serving_or_parent_before_freezing(monkeypatch,tmp_path):
    q,r=plans(monkeypatch,tmp_path);r["mcp_connect_timeout"]=31
    with pytest.raises(ValueError,match="binding_differs"):freeze_campaign(None,q,r)


def test_paired_failures_cannot_write_readiness_marker(tmp_path):
    plan=dict(protocol="demo-qualification-v1")
    with pytest.raises(RuntimeError,match="paired_qualification_failed"):paired_marker(None,plan,tmp_path,[])


def test_effective_gateway_duration_normalization_is_semantic_not_text_matching():
    policies=[dict(policy=dict(backend=dict(tcp=dict(connectTimeout="30s")))),dict(policy=dict(backend=dict(http=dict(requestTimeout="7m10s"))))]
    assert effective_settings(policies) and duration_seconds("100ms")==.1
    policies[0]["policy"]["backend"]["tcp"]["connectTimeout"]="10s"
    assert not effective_settings(policies)


def test_incomplete_rehearsal_report_preserves_failure_and_cannot_create_acceptance(tmp_path):
    native=tmp_path/"native";native.mkdir();ledger=tmp_path/"ledger";ledger.mkdir()
    plan=dict(namespace="nd6",cases=[dict(case_id=name,kind="card") for name in ("nd6-ok","nd6-failed","nd6-unstarted")])
    record=dict(trace_audit=dict(managed_responses_dispatches=0,guard_managed_responses_dispatches=0))
    data={"plan.json":plan,"failure.json":dict(message="trial_capacity",completed_cases=["nd6-ok"]),"cards.json":[dict(case_id="nd6-ok",demo_ready=True)],
        "capacity-readback.json":dict(trials=100,trial_capacity=100),"failed-case-cleanup.json":dict(case_id="nd6-failed",sources=[dict(physical_model_spans=0,cleanup=[dict(deleted=False)])]),
        "final-runtime-readback.json":dict(no_actors_remaining=True,owned_resources_restored=True),"bridge-restoration.json":dict(restored=True),
        "bridge-effective-backend.json":[],"bridge-transport.json":[],"nd6-ok.json":record}
    for name,value in data.items():(native/name).write_text(json.dumps(value))
    (ledger/"native-result-nd6-ok.json").write_text(json.dumps(dict(matrix_sha256=digest(plan),record_sha256=hashlib.sha256((native/"nd6-ok.json").read_bytes()).hexdigest())))
    budget=SimpleNamespace(directory=ledger,phase=lambda n:plan,locked=nullcontext,entries=lambda:[])
    result=failure_report(budget,native,tmp_path/"report")
    assert result["qualified"] is False and result["rehearsal_complete"] is False
    assert result["unstarted"]==["nd6-unstarted"] and result["failed_case"]=="nd6-failed"
    assert result["failed_setup_cleanup"]["sources"][0]["cleanup"][0]["deleted"] is False
    assert not list(ledger.glob("demo-qualified-*")) and result["physical_local_requests"]==0
    (native/"nd6-ok.json").write_text("changed")
    with pytest.raises((ValueError,json.JSONDecodeError)):failure_report(budget,native,tmp_path/"new-report")


def test_capacity_binding_headroom_and_unknown_readiness_are_fail_closed():
    from src.benchmark.capacity import validate_capacity
    wanted=dict(campaign_id="campaign",requirements=dict(trials=42,actions=192,events=1200),store_limits=dict(trials=256,actions=1000,events=4000))
    view=dict(schema_version="banking-capacity-v1",limits=wanted["store_limits"],available=dict(trials=156,actions=811,events=3000),
        campaign=dict(id="campaign",binding="a"*64,limits=wanted["requirements"],used=dict(trials=0,actions=0,events=0)))
    assert validate_capacity(view,dict(capacity=wanted),binding="a"*64,minimum_trials=42)==view
    bad=deepcopy(view);bad["campaign"]["used"]["trials"]=15
    with pytest.raises(RuntimeError,match="trials_insufficient"):validate_capacity(bad,dict(capacity=wanted),binding="a"*64,minimum_trials=28)
    bad=deepcopy(view);bad["available"].pop("events")
    with pytest.raises(RuntimeError,match="headroom_insufficient"):validate_capacity(bad,dict(capacity=wanted),binding="a"*64,minimum_trials=42)
