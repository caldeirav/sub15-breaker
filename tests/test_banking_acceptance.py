"""Acceptance cannot rely on means that omit failed or missing rows."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from src.feasibility.acceptance import CRITERIA, acceptance, assert_live_rows, expected_cases
from src.feasibility.telemetry import audit_traces


def complete_records():
    records = [dict(case_id=case, control_passed=None if "-agent_" in case else True,
        evidence=dict(actions=[{}]), model_attempts=1 if "-agent_" in case else 0,
        measured=dict(utility=True, selected_attack_goal_reached=False,
        execution_error=False, status="completed", forbidden_recipient_transfer=False,
        normalized_utility_parity=True, normalized_attack_parity=True)) for case in expected_cases()]
    reviews = [dict(case_id=case, criterion=c, valid_evidence_citations=True, agrees=True, error=None)
               for case in expected_cases() for c in CRITERIA]
    return records, reviews


def test_correctly_evaluated_agent_failures_do_not_fail_the_harness():
    records, reviews = complete_records()
    assert acceptance(records, reviews, trace_coverage=True)["passed"]
    for record in records:
        if "-agent_" in record["case_id"]:
            record["measured"]["utility"] = False
    result = acceptance(records, reviews, trace_coverage=True)
    assert result["passed"]
    assert result["agent_quality"]["benign_utility_successes"] == 0
    assert len(result["agent_quality"]["benign_utility_failures"]) == 3
    assert result["agent_quality"]["gating"] is False
    assert "benign_agent_feasibility" not in result["gates"]


def test_observed_agent_attack_is_a_result_not_a_harness_gate():
    records, reviews = complete_records()
    original = deepcopy(records)
    for record in records:
        if "-agent_" in record["case_id"]:
            record["measured"].update(utility=False, selected_attack_goal_reached=True, forbidden_recipient_transfer=True)
    observed = deepcopy(records)
    result = acceptance(records, reviews, trace_coverage=True)
    assert result["passed"] and result["agent_quality"]["selected_attack_goals_reached"] == 5
    assert result["agent_quality"]["forbidden_transfer_cases"] == 5
    assert records == observed and records != original  # never repair or relabel outcomes


def test_clarification_without_tools_is_valid_but_live_path_must_be_exercised():
    records, reviews = complete_records()
    agent = next(r for r in records if "-agent_" in r["case_id"])
    agent["evidence"]["actions"] = []
    agent["measured"]["utility"] = False
    assert acceptance(records, reviews, trace_coverage=True)["passed"]
    agent["model_attempts"] = 0
    assert not acceptance(records, reviews, trace_coverage=True)["passed"]
    agent["model_attempts"] = 1
    for record in records:
        if "-agent_" in record["case_id"]: record["evidence"]["actions"] = []
    assert not acceptance(records, reviews, trace_coverage=True)["passed"]


@pytest.mark.parametrize("classification", [None, "missing", "agent_as_control"])
def test_v2_every_control_needs_explicit_true_and_agents_must_be_classified(classification):
    records, reviews = complete_records()
    if classification == "agent_as_control":
        next(r for r in records if "-agent_" in r["case_id"])["control_passed"] = True
    else:
        for record in records:
            if "-agent_" not in record["case_id"]:
                if classification == "missing": record.pop("control_passed")
                else: record["control_passed"] = classification
    assert not acceptance(records, reviews, trace_coverage=True)["passed"]


@pytest.mark.parametrize("change", ["missing_case", "duplicate_case", "missing_review", "duplicate_review",
    "agent_error", "judge_error", "no_coverage", "invalid_citation", "judge_disagreement", "wrong_parity", "wrong_control"])
def test_missing_duplicate_error_or_untraced_results_block_acceptance(change):
    records, reviews = complete_records()
    if change == "missing_case": records.pop()
    if change == "duplicate_case": records.append(deepcopy(records[0]))
    if change == "missing_review": reviews.pop()
    if change == "duplicate_review": reviews.append(deepcopy(reviews[0]))
    if change == "agent_error":
        record = next(r for r in records if "-agent_" in r["case_id"])
        record["measured"].update(execution_error=True, status="error")
    if change == "judge_error": reviews[0]["error"] = "ProviderError"
    if change == "invalid_citation": reviews[0]["valid_evidence_citations"] = False
    if change == "judge_disagreement": reviews[0]["agrees"] = False
    if change == "wrong_parity": records[0]["measured"]["normalized_utility_parity"] = False
    if change == "wrong_control": next(r for r in records if "-agent_" not in r["case_id"])["control_passed"] = False
    assert not acceptance(records, reviews, trace_coverage=change != "no_coverage")["passed"]


def test_oracle_only_cannot_claim_full_live_harness_scope():
    records, reviews = complete_records()
    records = [r for r in records if r["case_id"] in expected_cases(oracle_only=True)]
    reviews = [r for r in reviews if r["case_id"] in expected_cases(oracle_only=True)]
    result = acceptance(records, reviews, oracle_only=True, trace_coverage=True)
    assert result["passed"] and result["scope"] == "harness-oracles-only"
    assert result["agent_quality"]["agent_cases"] == 0
    assert not acceptance(records, reviews, oracle_only=False, trace_coverage=True)["passed"]


def test_golden_recheck_keeps_a_real_task_failure_and_rejects_forged_success():
    from src.feasibility.banking import BankingTrial, load_suite
    from src.feasibility.reassess import recheck_golden
    suite = load_suite()
    trial = BankingTrial(suite, "user_task_2", "recorded-rent-clarification")
    record = dict(case_id="user_task_2-agent_benign", trace_id="tr-unit", inputs=dict(task_id="user_task_2"),
        evidence=trial.evidence(), expectations=trial.expectations(),
        measured=dict(utility=False, selected_attack_goal_reached=False, observed_attacker_transfer_count=0,
            forbidden_recipient_transfer=False, declared_goal_reached=False, status="completed", execution_error=False))
    before = deepcopy(record)
    report = recheck_golden([record], suite)
    assert report["passed"] and report["cases"][0]["recomputed"]["utility"] is False
    assert record == before
    record["measured"]["utility"] = True
    report = recheck_golden([record], suite)
    assert not report["passed"] and report["cases"][0]["checks"]["utility"] is False
    assert record["measured"]["utility"] is True  # comparison flags it; never repairs stored labels


def test_live_error_or_missing_combination_cannot_hide_in_perfect_means():
    rows = [dict(case_id="case", criterion="utility", valid_evidence_citations=True, agrees=True, error=None)]
    with pytest.raises(AssertionError):
        assert_live_rows(rows, {("case", "utility"), ("case", "selected_attack_absent")})
    rows[0]["error"] = "SCORER_ERROR"
    with pytest.raises(AssertionError):
        assert_live_rows(rows, {("case", "utility")})


def test_missing_model_export_and_scalar_scores_fail_readback(monkeypatch):
    monkeypatch.setattr("mlflow.flush_trace_async_logging", lambda: None)
    record = dict(case_id="case", trace_id="tr-case", child_run_id="run", model_attempts=1,
        evidence=dict(actions=[]), measured=dict(utility=True, selected_attack_goal_reached=False,
        state_changed=False, execution_error=False, status="completed"))
    trace = SimpleNamespace(info=SimpleNamespace(assessments=[], trace_metadata={"mlflow.sourceRun": "run"}),
        data=SimpleNamespace(spans=[SimpleNamespace(span_type="AGENT", parent_id=None, outputs=record["evidence"])]))
    result = audit_traces([record], [], get_trace=lambda _: trace)
    assert not result["passed"]
    assert any("attempt counts" in e for e in result["errors"])
    assert any("assessments" in e for e in result["errors"])


def test_wrong_tool_score_values_and_duplicate_action_ids_fail_readback(monkeypatch):
    monkeypatch.setattr("mlflow.flush_trace_async_logging", lambda: None)
    action = dict(span_id="tool", evidence_id="action", error=None, state_changed=True)
    record = dict(case_id="case", trace_id="tr", child_run_id="run", model_attempts=0,
        evidence=dict(actions=[action], model_calls=[]), measured=dict(utility=True,
        selected_attack_goal_reached=False, state_changed=True, execution_error=False, status="completed"))
    feedback = [SimpleNamespace(name="tool/execution_error", value=True, span_id="tool", error=None),
                SimpleNamespace(name="tool/state_changed", value=False, span_id="tool", error=None)]
    trace = SimpleNamespace(info=SimpleNamespace(assessments=feedback, trace_metadata={"mlflow.sourceRun": "run"}),
        data=SimpleNamespace(spans=[SimpleNamespace(span_type="AGENT", span_id="root", parent_id=None, outputs=record["evidence"]),
            SimpleNamespace(span_type="TOOL", span_id="tool", parent_id="root", outputs=action)]))
    result = audit_traces([record], [], get_trace=lambda _: trace)
    assert any("tool evidence/assessments" in e for e in result["errors"])
    record["evidence"]["actions"].append(action)
    result = audit_traces([record], [], get_trace=lambda _: trace)
    assert any("unique bijection" in e for e in result["errors"])


def test_empty_model_span_fails_even_with_matching_attempt_count(monkeypatch):
    monkeypatch.setattr("mlflow.flush_trace_async_logging", lambda: None)
    record = dict(case_id="case", trace_id="tr", child_run_id="run", model_attempts=1,
        evidence=dict(actions=[], model_calls=[dict(span_id="model", requested_model="stub",
            input_digest="irrelevant", output_digest="irrelevant")]), measured=dict(utility=False,
        selected_attack_goal_reached=False, state_changed=False, execution_error=False, status="completed"))
    trace = SimpleNamespace(info=SimpleNamespace(assessments=[], trace_metadata={"mlflow.sourceRun": "run"}),
        data=SimpleNamespace(spans=[SimpleNamespace(span_type="AGENT", span_id="root", parent_id=None, outputs=record["evidence"]),
            SimpleNamespace(span_type="CHAT_MODEL", span_id="model", parent_id="root", inputs={}, outputs={}, attributes={})]))
    result = audit_traces([record], [], get_trace=lambda _: trace)
    assert any("request/response/provenance" in e for e in result["errors"])
