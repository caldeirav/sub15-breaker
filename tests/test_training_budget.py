import hashlib
import json

import pytest

from src.benchmark.budget import Budget,EXTENDED_PILOT
from src.benchmark.campaign_budget import CampaignBudget
from src.benchmark.training_budget import TrainingBudget,POLICY
from src.infra.model_budget import encoded


def budget(tmp_path):
    Budget(tmp_path).reserve(role="actor",case_id="user_task_0",trace_id="old")
    Budget(tmp_path,EXTENDED_PILOT).reserve(role="gemini_harness_judge",case_id="suite",trace_id="old")
    CampaignBudget(tmp_path).freeze()
    value=TrainingBudget(tmp_path);value.freeze();return value


def plan():return dict(schema_version="banking-v2-prompt-pilot-v1",policy_sha256=hashlib.sha256(encoded(POLICY)).hexdigest(),
    protocol_sha256="a"*64,audit_sha256="b"*64,source_decision_sha256="c"*64,cases=[dict(case_id=f"pilot-{i}") for i in range(12)])


def test_v2_budget_extends_history_and_blocks_old_dispatch(tmp_path):
    value=budget(tmp_path);before=(tmp_path/"attempt-0001.json").read_bytes()
    value.freeze_pilot(plan())
    entry=value.reserve(role="gemini_data_generation",case_id="pilot-0",trace_id="new",model=POLICY["gemini_model"])
    assert entry["sequence"]==3 and entry["policy_version"]==POLICY["version"]
    assert (tmp_path/"attempt-0001.json").read_bytes()==before
    with value.locked():
        entries=value.entries();base=value.baseline(entries)
        assert str(value.accounted(entries,base))=="1.00"
    with pytest.raises(RuntimeError,match="superseded"):
        CampaignBudget(tmp_path).reserve(role="actor",case_id="anything",trace_id="bypass")
    with pytest.raises(RuntimeError,match="already_spent"):
        value.reserve(role="gemini_data_generation",case_id="pilot-0",trace_id="again",model=POLICY["gemini_model"])


def test_v2_budget_immutable_settlements_and_pilot_scope(tmp_path):
    value=budget(tmp_path);value.freeze_pilot(plan())
    with pytest.raises(RuntimeError,match="not_authorized"):
        value.reserve(role="llm_guard",case_id="pilot-0",trace_id="no-artifact")
    with pytest.raises(RuntimeError,match="undeclared"):
        value.reserve(role="gemini_data_generation",case_id="bulk-not-frozen",trace_id="new",model=POLICY["gemini_model"])
    entry=value.reserve(role="gemini_data_generation",case_id="pilot-0",trace_id="new",model=POLICY["gemini_model"])
    value.settle(entry["sequence"],accounted_cost_usd="0.02",usage_verified=True)
    with pytest.raises(FileExistsError):value.settle(entry["sequence"],usage_verified=False)
    with value.locked():
        entries=value.entries();assert str(value.accounted(entries,value.baseline(entries)))=="0.52"


def test_v2_budget_detects_pilot_and_historical_changes(tmp_path):
    value=budget(tmp_path);definition=plan();value.freeze_pilot(definition)
    definition["protocol_sha256"]="d"*64
    with pytest.raises(RuntimeError,match="pilot_changed"):value.freeze_pilot(definition)
    prior=json.loads((tmp_path/"attempt-0001.json").read_text());prior["spent"]=False
    (tmp_path/"attempt-0001.json").write_text(json.dumps(prior))
    with pytest.raises(RuntimeError,match="historical_ledger_changed"):value.freeze()
