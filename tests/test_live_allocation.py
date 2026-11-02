"""Fresh UI budget scope and provenance; no real artifacts/providers are loaded."""
from copy import deepcopy
import json
from types import SimpleNamespace as S

import pytest

from src.demo_ui import allocation
from src.demo_ui.allocation import LiveBudget,POLICY
from src.benchmark.campaign_budget import LOCAL,EXTERNAL
from src.integrations.agentdojo.inventory import digest


@pytest.fixture
def prepared(tmp_path,monkeypatch):
    config=tmp_path/".infra/banking-service-03b";config.mkdir(parents=True)
    (config/"deployment.json").write_text(json.dumps(dict(store_limits=dict(trials=256,actions=1000,events=4000))))
    monkeypatch.setattr(allocation,"ROOT",tmp_path)
    monkeypatch.setattr(allocation,"source_hashes",lambda:{"unit.py":"a"*64})
    base=dict(acting_model="unit-model",policy_sha256=digest(POLICY),fixtures={"user_task_0":[{},{}],"injection_task_0":[{}]},
              startup_inputs=[dict(candidate_id=str(i)) for i in range(5)])
    monkeypatch.setattr("src.benchmark.demo.make_plan",lambda *a,**kw:deepcopy(base))
    plan=allocation.make_plan(tmp_path/"artifact","ui1")
    budget=LiveBudget(tmp_path/"budget","ui1")
    monkeypatch.setattr(budget,"baseline",lambda entries:dict(prefix_length=0,prior_accounted_cost_plus_holds_usd="0.0"))
    return budget,plan


def test_exact_one_campaign_caps_include_startup_canaries_and_all_five_pairs(prepared):
    budget,plan=prepared
    assert sum(c.get(r,0) for c in plan["cases"] for r in LOCAL)==63
    assert sum(c.get(r,0) for c in plan["cases"] for r in EXTERNAL)==21
    assert plan["capacity"]["requirements"]["trials"]==18
    assert len(plan["startup_inputs"])*2==10
    assert [s["order"][0] for s in plan["slots"]]==["classifier","llm","classifier","llm","classifier"]
    for c in plan["cases"]:
        if c.get("card_id") in {"D04","D05"}:
            assert c["producer"]=="fault_control" and c["actor"]==c["llm_guard"]==0
    budget.freeze(plan,reason="explicit bounded owner authorization")
    assert budget.plan(current_source=True)==plan
    assert budget.entries()==[]


def test_spent_calls_and_unapproved_roles_models_or_extra_requests_are_not_retried(prepared):
    budget,plan=prepared;budget.freeze(plan,reason="unit")
    case="ui1-startup-actor"
    entry=budget.reserve(role="actor",case_id=case,trace_id="unit",request={},model="unit-model")
    assert entry["spent"] and entry["policy_version"]==POLICY["version"]
    with pytest.raises(RuntimeError):budget.reserve(role="actor",case_id=case,trace_id="unit",model="unit-model")
    with pytest.raises(RuntimeError):budget.reserve(role="gemini_data_generation",case_id=case,trace_id="unit",model=POLICY["gemini_model"])
    with pytest.raises(RuntimeError):budget.reserve(role="llm_guard",case_id="ui1-startup-llm-guard",trace_id="unit",model="other")
    assert len(budget.entries())==1


def test_fresh_ui_extension_is_scoped_and_does_not_rewrite_old_entries(prepared):
    budget,plan=prepared
    with budget.locked():budget._exclusive(budget.directory/"attempt-0001.json",dict(sequence=1,case_id="nd11-old",role="actor",cost_hold_usd="0",policy_version=POLICY["version"]))
    old=(budget.directory/"attempt-0001.json").read_bytes()
    budget.freeze(plan,reason="new namespace only")
    assert (budget.directory/"attempt-0001.json").read_bytes()==old
    with budget.locked():
        budget._exclusive(budget.directory/"attempt-0002.json",dict(sequence=2,case_id="some-later-case",role="actor",cost_hold_usd="0",policy_version=POLICY["version"]))
    assert budget.plan()==plan
    value=json.loads((budget.directory/"attempt-0001.json").read_text());value["case_id"]="changed"
    (budget.directory/"attempt-0001.json").write_text(json.dumps(value))
    with pytest.raises(RuntimeError,match="historical_prefix"):budget.plan()


def test_source_plan_and_global_cost_bounds_fail_closed(prepared,monkeypatch):
    budget,plan=prepared
    with pytest.raises(ValueError):budget.freeze(plan,reason="")
    budget.freeze(plan,reason="unit")
    monkeypatch.setattr(allocation,"source_hashes",lambda:{"unit.py":"changed"})
    with pytest.raises(RuntimeError,match="source_changed"):budget.plan(current_source=True)
    monkeypatch.setattr(allocation,"source_hashes",lambda:{"unit.py":"a"*64})
    altered=deepcopy(plan);altered["cases"][0]["actor"]=1
    with pytest.raises(RuntimeError,match="immutable"):budget.freeze(altered,reason="not authorized")


@pytest.mark.parametrize("mutation",["path","negative","policy","generation"])
def test_bad_scope_never_freezes(prepared,mutation):
    budget,plan=prepared
    if mutation=="path":plan["cases"][0]["case_id"]="ui1-../../escape"
    if mutation=="negative":plan["cases"][0]["actor"]=-1
    if mutation=="policy":plan["policy_sha256"]="wrong"
    if mutation=="generation":plan["cases"][0]["gemini_data_generation"]=1
    with pytest.raises(ValueError,match="invalid_live_scope"):budget.freeze(plan,reason="unit")
    assert not budget.path.exists()
