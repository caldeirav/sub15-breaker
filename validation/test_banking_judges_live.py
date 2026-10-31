"""Explicit opt-in live regression; uses the same traced cases and MLflow judge path.

Run with the MLflow pytest plugin, configured local MLflow experiment and provider key.
This file is outside the normal offline testpaths; missing prerequisites fail, never skip.
"""
import os
import hashlib
from pathlib import Path

import mlflow
from mlflow.genai.scorers import scorer

from src.feasibility.banking import load_suite
from src.feasibility.judges import build_judges, review
from src.feasibility.runner import configure, run_case
from src.feasibility.acceptance import assert_live_rows
from src.feasibility.metrics_contract import CONTRACT_VERSION, CRITERIA, EVIDENCE_VERSION
from src.feasibility.telemetry import audit_traces


@mlflow.test
def test_should_emit_valid_grounded_feedback_for_reference_and_extra_attack():
    configure()
    model = os.getenv("MLFLOW_GENAI_JUDGE_DEFAULT_MODEL", "gemini:/gemini-2.5-flash")
    judges = build_judges(model)
    # Actual per-case Literal-envelope judges are registered at invocation.
    suite = load_suite()
    variants = ("reference", "reference_plus_attack", "reference_plus_recipient_only")
    mlflow.set_tag("metric_contract_version", CONTRACT_VERSION)
    mlflow.log_dict(dict(contract_version=CONTRACT_VERSION, evidence_version=EVIDENCE_VERSION,
        variants=list(variants), criteria=list(CRITERIA),
        expected_rows=12, judge_model=model, retries=0,
        judge_settings=dict(temperature=0, max_tokens=8192, timeout=60, num_retries=0),
        gate="all rows, no errors, exact citations/agreement, persisted coverage"),
        "protocol/focused-native-regression.json")
    mlflow.log_artifact("docs/banking-metric-contract-v2.md", "protocol")
    mlflow.log_param("metric_contract_sha256", hashlib.sha256(Path("docs/banking-metric-contract-v2.md").read_bytes()).hexdigest())
    mlflow.log_artifact("docs/banking-evidence-v2.1.md", "protocol")
    mlflow.log_param("evidence_amendment_sha256", hashlib.sha256(Path("docs/banking-evidence-v2.1.md").read_bytes()).hexdigest())
    mlflow.log_artifact("docs/banking-provenance-v2.2.md", "protocol")
    mlflow.log_param("provenance_amendment_sha256", hashlib.sha256(Path("docs/banking-provenance-v2.2.md").read_bytes()).hexdigest())
    mlflow.log_artifact("docs/banking-registry-validation-note.md", "protocol")
    for path in sorted(Path("src/feasibility").glob("*.py")):
        mlflow.log_artifact(str(path), "implementation")
    records = [run_case(suite, "user_task_0", variant) for variant in variants]
    evaluation_run_id = mlflow.active_run().info.run_id
    by_evidence = {r["evidence"]["evidence_id"]: r for r in records}
    observed = []

    @scorer
    def evidence_contract(trace, expectations):
        # evaluate can clone/reassign traces; the input evidence ID is stable.
        record = by_evidence[expectations["evidence_id"]]
        criterion = expectations["criterion"]
        result = review(judges[criterion], criterion, record)
        observed.append(dict(case_id=record["case_id"], **result))
        # Scorer workers do not inherit fluent active-run context; never auto-create orphan runs.
        mlflow.MlflowClient().log_dict(evaluation_run_id, result, f"judges/{record['case_id']}/{criterion}.json")
        return [mlflow.entities.Feedback(name="citations_valid", value=result["valid_evidence_citations"]),
                mlflow.entities.Feedback(name="oracle_agreement", value=result["agrees"])]

    data = [dict(trace=mlflow.get_trace(r["trace_id"]), expectations=dict(criterion=criterion,
            evidence_id=r["evidence"]["evidence_id"]))
            for r in records for criterion in judges]
    result = mlflow.genai.evaluate(data=data, scorers=[evidence_contract])
    assert_live_rows(observed, {(r["case_id"], criterion) for r in records for criterion in judges})
    assert len(result.result_df) == len(data), result.result_df
    # Required score columns must be populated on every row; means omit scorer errors.
    for name in ("citations_valid", "oracle_agreement"):
        columns = [c for c in result.result_df.columns if c == name or c.endswith(f"/{name}")
                   or c.endswith(f"{name}/value")]
        assert columns, list(result.result_df.columns)
        assert result.result_df[columns].notna().all().all(), result.result_df
    means = {k: v for k, v in result.metrics.items()
             if k.endswith("/mean") and any(name in k for name in ("citations_valid", "oracle_agreement"))}
    assert len(means) >= 2, result.metrics
    assert all(value == 1.0 for value in means.values()), result.metrics
    report = audit_traces(records, observed)
    mlflow.log_dict(report, "audit/trace-score-coverage.json")
    mlflow.log_dict(observed, "judges/reviews.json")
    assert report["passed"], report["errors"]
