from contextlib import nullcontext
from types import SimpleNamespace as S
import json

import pytest

from src.benchmark.guards import ReviewInput,Verdict
from src.benchmark.startup import PROFILE,prepare


def setup(monkeypatch,tmp_path,*,actor_ok=True,provider="idle"):
    active={};claimed=[];observations=[]
    value=ReviewInput("synthetic startup","policy","reads permitted","get_balance",{})
    plan=dict(acting_model="frozen",serving=dict(shared_context=8192),startup_profile=PROFILE,
        startup_inputs=[dict(candidate_id="read",model_input=value.serialized(),input_digest=value.digest())],
        cases=[dict(case_id="startup-"+role,kind="startup",stage="native",**{role:1}) for role in ("actor","llm_guard")])
    class Span:
        trace_id="trace"
        def set_inputs(self,value):pass
        def set_outputs(self,value):pass
    monkeypatch.setattr("src.benchmark.startup.provider_status",lambda *a,**k:dict(state=provider,context_length=8192))
    monkeypatch.setattr("src.benchmark.startup.httpx.get",lambda *a,**k:S(status_code=200))
    monkeypatch.setattr("src.benchmark.startup.mlflow.get_tracking_uri",lambda:"http://tracking")
    monkeypatch.setattr("src.benchmark.startup.mlflow.start_span",lambda **k:nullcontext(Span()))
    monkeypatch.setattr("src.benchmark.startup.mlflow.log_dict",lambda *a:None)
    monkeypatch.setattr("src.benchmark.startup.claim_case",lambda budget,case,plan:claimed.append(case))
    monkeypatch.setattr("src.benchmark.reconciliation.reconcile_record",lambda *a,**k:dict(status="complete"))
    class Resources:
        primed=False
        def select(self,arm):assert arm=="classifier"
        def prepare(self,values,passes):
            assert passes==2 and len(claimed)==2;self.primed=True;observations.append("prime")
        def snapshot(self):return dict(classifier_primed=self.primed,startup_priming=[])
    class Guard:
        guard_id="frozen"
        def review(self,value):active["physical_attempts"]+=1;return Verdict(value.digest(),"allow",self.guard_id)
    class Actor:
        def invoke(self,messages):
            active["physical_attempts"]+=1
            return S(tool_calls=[dict(name="get_balance",args={})] if actor_ok else [],invalid_tool_calls=[],response_metadata={})
    return plan,active,claimed,Resources(),Guard(),Actor()


def test_both_real_model_probes_reserved_then_classifier_primed_before_ready(monkeypatch,tmp_path):
    plan,active,claimed,resources,guard,actor=setup(monkeypatch,tmp_path)
    report=prepare(plan=plan,budget=None,directory=tmp_path,stage="native",resources=resources,reviewer=guard,actor_model=actor,active=active)
    assert report["ready"] and report["measured_requests_started_after_ready"] and resources.primed
    assert claimed==["startup-actor","startup-llm_guard"] and sum(r["physical_attempts"] for r in report["model_probes"])==2
    assert all(r["phase"]=="startup_not_scored" for r in report["model_probes"])


def test_unavailable_provider_stops_before_any_model_or_classifier_work(monkeypatch,tmp_path):
    plan,active,claimed,resources,guard,actor=setup(monkeypatch,tmp_path,provider="unobserved")
    with pytest.raises(RuntimeError,match="provider_not_idle"):
        prepare(plan=plan,budget=None,directory=tmp_path,stage="native",resources=resources,reviewer=guard,actor_model=actor,active=active)
    assert not claimed and not resources.primed
    assert not json.loads((tmp_path/"services-startup.json").read_text())["ready"]


def test_model_probe_failure_is_not_repaired_or_scored(monkeypatch,tmp_path):
    plan,active,claimed,resources,guard,actor=setup(monkeypatch,tmp_path,actor_ok=False)
    with pytest.raises(RuntimeError,match="model_probe_failed"):
        prepare(plan=plan,budget=None,directory=tmp_path,stage="native",resources=resources,reviewer=guard,actor_model=actor,active=active)
    report=json.loads((tmp_path/"services-startup.json").read_text())
    assert not report["ready"] and len(claimed)==1 and not resources.primed
    assert report["model_probes"][0]["physical_attempts"]==1 and report["model_probes"][0]["status"]=="error"
