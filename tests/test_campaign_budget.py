import json

import pytest

from src.benchmark.budget import Budget,EXTENDED_PILOT
from src.benchmark.campaign_budget import CampaignBudget,POLICY


def campaign(tmp_path):
    Budget(tmp_path).reserve(role="actor",case_id="user_task_0",trace_id="old-local")
    Budget(tmp_path,EXTENDED_PILOT).reserve(role="gemini_harness_judge",case_id="suite",trace_id="old-external")
    value=CampaignBudget(tmp_path);value.freeze()
    return value


def matrix(**limits):
    return dict(policy_id="unit-policy",input_version="unit-input",dataset_manifest_sha256="a"*64,
        artifact_manifest_sha256="b"*64,cases=[dict(case_id="unit-case",task_id="user_task_0",phase="episodes",**limits)])


def test_campaign_retains_history_and_refuses_unreviewed_matrix(tmp_path):
    value=campaign(tmp_path)
    before=(tmp_path/"attempt-0001.json").read_bytes()
    assert json.loads((tmp_path/"policy-v3.json").read_text())["local_total"]==2048
    assert json.loads((tmp_path/"campaign-baseline.json").read_text())["historical_external_hold_usd"]=="0.50"
    with pytest.raises(RuntimeError,match="matrix_not_frozen"):
        value.reserve(role="actor",case_id="unit-case",trace_id="new")
    value.freeze_matrix(matrix(actor=2,llm_guard=1))
    entry=value.reserve(role="actor",case_id="unit-case",trace_id="new")
    assert entry["sequence"]==3 and entry["policy_version"]==POLICY["version"]
    assert (tmp_path/"attempt-0001.json").read_bytes()==before
    with pytest.raises(RuntimeError,match="superseded"):
        Budget(tmp_path,EXTENDED_PILOT).reserve(role="actor",case_id="user_task_13",trace_id="old")


def test_unknown_cost_keeps_hold_and_verified_cost_releases_only_difference(tmp_path,monkeypatch):
    monkeypatch.setitem(POLICY,"gemini_cost_cap_usd","1.00")
    value=campaign(tmp_path);value.freeze_matrix(matrix(gemini_harness_judge=3))
    first=value.reserve(role="gemini_harness_judge",case_id="unit-case",trace_id="first",model=POLICY["gemini_model"])
    value.settle(first["sequence"],usage_verified=False)
    with pytest.raises(RuntimeError,match="cost_cap"):
        value.reserve(role="gemini_harness_judge",case_id="unit-case",trace_id="second",model=POLICY["gemini_model"])
    with pytest.raises(FileExistsError):value.settle(first["sequence"],usage_verified=True,accounted_cost_usd="0.10")


def test_verified_settlement_and_provider_binding(tmp_path,monkeypatch):
    monkeypatch.setitem(POLICY,"gemini_cost_cap_usd","1.00")
    value=campaign(tmp_path);value.freeze_matrix(matrix(gemini_harness_judge=3))
    with pytest.raises(RuntimeError,match="cost_profile"):
        value.reserve(role="gemini_harness_judge",case_id="unit-case",trace_id="wrong",model="other")
    first=value.reserve(role="gemini_harness_judge",case_id="unit-case",trace_id="first",model=POLICY["gemini_model"])
    value.settle(first["sequence"],usage_verified=True,accounted_cost_usd="0.00")
    second=value.reserve(role="gemini_harness_judge",case_id="unit-case",trace_id="second",model=POLICY["gemini_model"])
    assert second["sequence"]==4
    with pytest.raises(ValueError):value.settle(second["sequence"],usage_verified=True,accounted_cost_usd="NaN")


def test_matrix_and_history_changes_fail_closed(tmp_path):
    value=campaign(tmp_path);definition=matrix(actor=1)
    value.freeze_matrix(definition)
    changed=matrix(actor=2)
    with pytest.raises(RuntimeError,match="matrix_changed"):value.freeze_matrix(changed)
    (tmp_path/"matrix-v3.json").write_text(json.dumps(changed))
    with pytest.raises(RuntimeError,match="matrix_changed"):value.reserve(role="actor",case_id="unit-case",trace_id="new")
    first=json.loads((tmp_path/"attempt-0001.json").read_text());first["spent"]=False
    (tmp_path/"attempt-0001.json").write_text(json.dumps(first))
    with pytest.raises(RuntimeError,match="historical_ledger_changed"):value.freeze()


def test_native_matrix_counts_pretraining_generation_against_cumulative_cap(tmp_path,monkeypatch):
    from src.benchmark.hybrid import generation_plan
    value=campaign(tmp_path)
    plan=generation_plan(dict(derived_dataset_sha256="a"*64))
    value.freeze_generation_plan(plan)
    value.reserve(role="gemini_data_generation",case_id="hybrid-train-0",trace_id="generated",model=POLICY["gemini_model"])
    monkeypatch.setitem(POLICY,"gemini_total",3)
    # Keep the persisted policy consistent for this deliberately tiny cap.
    (tmp_path/"policy-v3.json").write_text(json.dumps(POLICY))
    with pytest.raises(ValueError,match="matrix_exceeds_gemini_total"):
        value.freeze_matrix(matrix(gemini_harness_judge=2))
