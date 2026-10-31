"""Reassess existing evidence under an explicit harness policy; no model/tool reruns."""
import argparse
import hashlib
import json
from pathlib import Path

import mlflow

from src.feasibility.acceptance import ACCEPTANCE_POLICY, acceptance
from src.feasibility.banking import (AGENTDOJO_COMMIT, BENCHMARK_VERSION, VARIANTS,
    control_passed, load_suite)
from src.feasibility.metrics_contract import normalized_outcomes
from src.feasibility.runner import ROOT, configure
from src.feasibility.telemetry import audit_traces


def recheck_golden(records, suite):
    """Recompute state-only upstream predicates, never relabel stored model outcomes."""
    environment_type = type(suite.load_and_inject_default_environment({}))
    rows = []
    for record in records:
        evidence, measured = record["evidence"], record["measured"]
        initial = environment_type.model_validate(evidence["initial_state"])
        actual = environment_type.model_validate(evidence["actual_state"])
        task_id = record["inputs"]["task_id"]
        utility = bool(suite.user_tasks[task_id].utility(evidence["final_answer"], initial, actual, strict=True))
        attack = bool(suite.injection_tasks["injection_task_0"].security(evidence["final_answer"], initial, actual))
        normalized = normalized_outcomes(record)
        expected = dict(utility=utility, selected_attack_goal_reached=attack,
            observed_attacker_transfer_count=normalized["observed_attacker_transfer_count"],
            forbidden_recipient_transfer=normalized["forbidden_recipient_transfer"],
            declared_goal_reached=normalized["declared_goal_reached"])
        checks = {name: measured.get(name) == value for name, value in expected.items()}
        variant = record["case_id"].removeprefix(task_id + "-")
        if variant in VARIANTS:
            checks["control_expected_outcome"] = control_passed(variant, dict(measured, **expected))
        rows.append(dict(case_id=record["case_id"], trace_id=record["trace_id"],
            recomputed=expected, checks=checks, passed=all(checks.values())))
    return dict(passed=bool(rows) and all(row["passed"] for row in rows), cases=rows,
        limitation="Private equality/service extraction facts are reused from source; no secret reconstruction, tool execution or model resampling.")


def reassess(source_run_id):
    experiment = configure(require_judge=False)
    client = mlflow.MlflowClient()
    source = client.get_run(source_run_id)
    if source.info.status not in {"FINISHED", "FAILED"}:
        raise ValueError("Only completed source runs with persisted evidence can be reassessed")
    destination = ROOT / ".infra/harness-reassessment" / source_run_id
    destination.mkdir(parents=True, exist_ok=True)

    def artifact(run_id, path):
        local = destination / run_id
        local.mkdir(exist_ok=True)
        return Path(client.download_artifacts(run_id, path, str(local)))

    summary = json.loads(artifact(source_run_id, "summary.json").read_text())
    manifest = json.loads(artifact(source_run_id, "manifest.json").read_text())
    if manifest["agentdojo_commit"] != AGENTDOJO_COMMIT or manifest["benchmark_version"] != BENCHMARK_VERSION:
        raise ValueError("Source benchmark version is not the reviewed pinned profile")
    original_source = {path.name: path.read_text() for path in artifact(source_run_id, "implementation").glob("*.py")}
    source_hash = hashlib.sha256(json.dumps(original_source, sort_keys=True).encode()).hexdigest()
    source_hash_matches = source_hash == manifest["implementation_sha256"]
    # Only acceptance and its report integration change. Evaluation/tracing/model code
    # must be byte-identical to the source that produced these observations.
    unchanged = {name: (ROOT / "src/feasibility" / name).read_text() == original_source.get(name)
        for name in ("__init__.py", "agent.py", "banking.py", "judges.py", "metrics_contract.py", "telemetry.py")}
    lock_matches = hashlib.sha256((ROOT / "uv.lock").read_bytes()).hexdigest() == manifest["uv_lock_sha256"]
    records = [json.loads(artifact(child, "evidence/trial.json").read_text()) for child in summary["child_run_ids"]]
    reviews = json.loads(artifact(source_run_id, "judges/reviews.json").read_text())
    policy_path = ROOT / "docs/banking-harness-acceptance-v3.md"
    with mlflow.start_run(run_name="banking-harness-acceptance-v3") as run:
        mlflow.set_tags(dict(evaluation_kind="derived-existing-evidence-no-rerun", acceptance_policy=ACCEPTANCE_POLICY,
            acceptance_scope="local-banking-harness", source_run_id=source_run_id, human_acceptance="pending",
            new_model_calls="0", new_tool_calls="0", new_judge_calls="0"))
        mlflow.log_artifact(str(policy_path), "protocol")
        mlflow.log_dict(dict(policy_version=ACCEPTANCE_POLICY, source_run_id=source_run_id,
            owner_approval="Explicit owner approval in conversation: correct harness acceptance, agent quality non-gating",
            policy_sha256=hashlib.sha256(policy_path.read_bytes()).hexdigest(), new_model_calls=0,
            new_tool_calls=0, new_judge_calls=0), "protocol.json")
        for path in sorted((ROOT / "src/feasibility").glob("*.py")):
            mlflow.log_artifact(str(path), "implementation")
        with mlflow.start_span(name="reassess_existing_banking_harness_evidence", span_type="CHAIN") as span:
            decision_trace_id = span.trace_id
            span.set_inputs(dict(source_run_id=source_run_id, source_run_status=source.info.status,
                policy_version=ACCEPTANCE_POLICY, source_case_trace_ids=[r["trace_id"] for r in records],
                source_judge_trace_ids=[r["judge_trace_id"] for r in reviews], new_model_calls=0))
            with mlflow.start_span(name="golden_outcome_recheck", span_type="CHAIN") as golden_span:
                golden_span.set_inputs(dict(benchmark_version=BENCHMARK_VERSION, source_cases=len(records)))
                golden = recheck_golden(records, load_suite())
                golden_span.set_outputs(golden)
            with mlflow.start_span(name="persisted_source_trace_score_readback", span_type="CHAIN") as audit_span:
                audit_span.set_inputs(dict(source_cases=len(records), source_reviews=len(reviews)))
                trace_audit = audit_traces(records, reviews)
                audit_span.set_outputs(dict(passed=trace_audit["passed"], errors=trace_audit["errors"],
                    source_trace_count=len(trace_audit["traces"])))
            result = acceptance(records, reviews, oracle_only=summary["oracle_only"], trace_coverage=trace_audit["passed"])
            result["gates"].update(golden_evaluation_recheck=golden["passed"],
                source_integrity=source_hash_matches and lock_matches and all(unchanged.values()))
            result["passed"] = all(result["gates"].values())
            report = dict(assessment_run_id=run.info.run_id, decision_trace_id=decision_trace_id,
                source_run_id=source_run_id, source_run_status=source.info.status,
                assessment_kind="derived-acceptance-policy-reassessment-not-a-new-agent-trial",
                acceptance=result, source_cases=len(records), source_reviews=len(reviews),
                source_audited_traces=len(trace_audit["traces"]), new_model_calls=0, new_tool_calls=0, new_judge_calls=0,
                source_outcomes_preserved=True, human_acceptance="pending")
            span.set_outputs(report)
        code_source = mlflow.entities.AssessmentSource(source_type="CODE", source_id=ACCEPTANCE_POLICY)
        for name, value in {"passed": result["passed"], **result["gates"]}.items():
            mlflow.log_feedback(trace_id=decision_trace_id, name=f"harness/{name}", value=value, source=code_source)
        for name, value in result["agent_quality"].items():
            if isinstance(value, (bool, int, float, str)):
                mlflow.log_feedback(trace_id=decision_trace_id, name=f"agent_quality/{name}", value=value, source=code_source)
        mlflow.log_dict(report, "harness-acceptance.json")
        mlflow.log_dict(golden, "audit/golden-outcome-recheck.json")
        mlflow.log_dict(trace_audit, "audit/source-trace-score-coverage.json")
        mlflow.log_dict(dict(original_source_hash_verified=source_hash_matches, runtime_files_unchanged=unchanged,
            lock_unchanged=lock_matches, changed_scope="acceptance/reporting only; source outcomes and source status unchanged"),
            "audit/source-integrity.json")
        assert client.get_run(source_run_id).info.status == source.info.status
        mlflow.set_tag("harness_status", "passed" if result["passed"] else "review_required")
        if not result["passed"]:
            mlflow.end_run(status="FAILED")
        print(json.dumps(report, indent=2))
        return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-run", required=True)
    args = parser.parse_args()
    return 0 if reassess(args.source_run)["acceptance"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
