"""Opt-in persisted MLflow plumbing regression with stubs; NO provider/model calls.

Run: uv run --locked --env-file .env python -m pytest -q validation/test_banking_mlflow_local.py
Uses the configured local MLflow server. It is not Gemini quality or human acceptance.
"""
from copy import deepcopy
from types import SimpleNamespace

import mlflow

from src.feasibility.banking import load_suite
from src.feasibility.agent import LocalBankingPipeline
from src.feasibility.judges import review
from src.feasibility.runner import configure, run_case
from src.feasibility.telemetry import audit_traces
from src.feasibility.metrics_contract import CRITERIA, expected_verdict
import validation.test_banking_judges_live as live


class StubJudge:
    model = "stub:/no-model-call"
    inference_params = {"provider_calls": 0}
    instructions = "Offline stub: validate persisted trace/score plumbing, not model quality."

    def __init__(self, criterion):
        self.criterion = criterion
        self.name = f"banking_v2_{criterion}_gemini"

    def register(self, **kwargs): return self  # CODE stub, never registered as a native model

    def __call__(self, inputs, outputs, expectations):
        return mlflow.entities.Feedback(name=self.name, source=mlflow.entities.AssessmentSource(
            source_type="CODE", source_id="offline-stub-no-provider"),
            value=dict(verdict=expected_verdict(self.criterion, outputs, expectations), criterion_id=self.criterion,
                reference_id=expectations["reference_id"], evidence_id=expectations["evidence_id"]),
            rationale="Deterministic offline stub; not a native Gemini quality result.")


def test_persisted_scores_and_evaluate_trace_cloning_without_provider(monkeypatch):
    configure(require_judge=False)
    records, reviews = [], []
    def traced_case(*args, **kwargs):
        record = run_case(*args, **kwargs)
        records.append(record)
        return record
    def traced_review(*args, **kwargs):
        result = review(*args, **kwargs)
        record = args[2]
        reviews.append(dict(case_id=record["case_id"], **result))
        return result
    monkeypatch.setattr(live, "configure", lambda: None)
    monkeypatch.setattr(live, "run_case", traced_case)
    monkeypatch.setattr(live, "review", traced_review)
    monkeypatch.setattr(live, "build_judges", lambda _: {c: StubJudge(c) for c in CRITERIA})
    with mlflow.start_run(run_name="banking-observability-no-provider") as parent:
        mlflow.set_tags(dict(validation_kind="offline-stub-persisted-mlflow", provider_calls="0", human_acceptance="pending"))
        live.test_should_emit_valid_grounded_feedback_for_reference_and_extra_attack.__wrapped__()
        for record in records:
            artifacts = mlflow.MlflowClient().list_artifacts(parent.info.run_id, f"judges/{record['case_id']}")
            assert len(artifacts) == len(CRITERIA), artifacts  # no fluent worker-created orphan runs
        class Client:
            def __init__(self): self.calls = 0
            def with_options(self, **kwargs): return self
            @property
            def responses(self): return self
            def create(self, **kwargs):
                self.calls += 1
                if self.calls == 1:
                    return SimpleNamespace(output=[SimpleNamespace(model_dump=lambda **kw: dict(
                        type="function_call", name="get_balance", arguments="{}", call_id="stub-1"))], output_text="")
                return SimpleNamespace(output=[], output_text="Stub inspected the balance; not a real model trial.")
        pipeline = LocalBankingPipeline(Client(), "stub/no-provider")
        model_case = run_case(load_suite(), "user_task_0", "agent_stub_plumbing", pipeline=pipeline)
        records.append(model_case)
        assert model_case["model_attempts"] == 2
        report = audit_traces(records, reviews)
        mlflow.log_dict(report, "audit/trace-score-coverage.json")
        assert report["passed"], report["errors"]
        assert len(report["traces"]) == 16
        # Removing an expected model span or a review score must fail persisted readback.
        snapshots = {r["trace_id"]: mlflow.get_trace(r["trace_id"]) for r in report["traces"]}
        damaged = deepcopy(snapshots)
        damaged[reviews[0]["judge_trace_id"]].info.assessments.clear()
        assert not audit_traces(records, reviews, get_trace=damaged.get)["passed"]
        damaged = deepcopy(snapshots)
        damaged[model_case["trace_id"]].data.spans[:] = [s for s in damaged[model_case["trace_id"]].data.spans
                                                        if s.span_type != "CHAT_MODEL"]
        assert not audit_traces(records, reviews, get_trace=damaged.get)["passed"]
