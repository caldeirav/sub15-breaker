"""Run a bounded banking feasibility pilot with traces, native judges and evidence in MLflow."""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from dotenv import load_dotenv
import mlflow
from openai import OpenAI
import pandas as pd

from src.feasibility.agent import LocalBankingPipeline, injected_environment
from src.feasibility.banking import (AGENTDOJO_COMMIT, ATTACK_ID, BENCHMARK_VERSION, TASK_IDS,
    VARIANTS, BankingTrial, control_calls, control_passed, digest, load_suite, record_oracles, serializable)
from src.feasibility.judges import build_judges, review
from src.feasibility.acceptance import ACCEPTANCE_POLICY, acceptance, expected_cases
from src.feasibility.metrics_contract import CONTRACT_VERSION, CRITERIA, EVIDENCE_VERSION
from src.feasibility.telemetry import audit_traces, log_case_scores

ROOT = Path(__file__).resolve().parents[2]


def configure(require_judge=True):
    load_dotenv(ROOT / ".env")
    # Pin optional pricing metadata to the installed lock-bound package, not ambient GitHub.
    os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
    if require_judge and not os.getenv("GEMINI_API_KEY") and not os.getenv("GOOGLE_API_KEY"):
        raise RuntimeError("Configure GEMINI_API_KEY locally; do not paste it into chat")
    if not os.getenv("GEMINI_API_KEY") and os.getenv("GOOGLE_API_KEY"):
        os.environ["GEMINI_API_KEY"] = os.environ["GOOGLE_API_KEY"]
    os.environ.setdefault("MLFLOW_HTTP_REQUEST_TIMEOUT", "10")
    os.environ.setdefault("MLFLOW_HTTP_REQUEST_MAX_RETRIES", "1")
    os.environ["MLFLOW_ENABLE_ASYNC_TRACE_LOGGING"] = "false"
    os.environ["MLFLOW_TRACE_SAMPLING_RATIO"] = "1"
    mlflow.set_tracking_uri(os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5001"))
    if os.getenv("MLFLOW_EXPERIMENT_ID"):
        experiment = mlflow.set_experiment(experiment_id=os.environ["MLFLOW_EXPERIMENT_ID"])
    else:
        experiment = mlflow.set_experiment(os.getenv("BANKING_MLFLOW_EXPERIMENT", "breaker-banking-feasibility"))
    # Explicit sanitized invocation spans replace uncontrolled raw payload autologging.
    mlflow.openai.autolog(disable=True)
    mlflow.litellm.autolog(disable=True)
    return experiment


def provenance():
    lock = (ROOT / "uv.lock").read_bytes()
    return dict(agentdojo_commit=AGENTDOJO_COMMIT, benchmark_version=BENCHMARK_VERSION,
        package_versions={name: importlib.metadata.version(name) for name in ("agentdojo", "mlflow", "openai", "litellm")},
        uv_lock_sha256=hashlib.sha256(lock).hexdigest(),
        implementation_sha256=hashlib.sha256(json.dumps({p.name: p.read_text() for p in
            sorted((ROOT / "src/feasibility").glob("*.py"))}, sort_keys=True).encode()).hexdigest(),
        git_commit=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        metric_contract_version=CONTRACT_VERSION,
        acceptance_policy_version=ACCEPTANCE_POLICY,
        evidence_version=EVIDENCE_VERSION,
        pricing_metadata_source="litellm-bundled-lock-bound-estimate",
        task_ids=list(TASK_IDS), control_variants=list(VARIANTS), selected_attack=ATTACK_ID,
        scope="local-in-memory-simulation-only; no gateway, Substrate Actor, calibrated guard or latency claim",
        data_classification="synthetic upstream AgentDojo fixtures; password fields redacted",
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))


def run_case(suite, task_id, variant, pipeline=None, injections=None):
    case_id = f"{task_id}-{variant}"
    with mlflow.start_run(run_name=case_id, nested=True) as child:
        trial = BankingTrial(suite, task_id, f"{child.info.run_id}/{case_id}", injections=injections)
        inputs = serializable(dict(task_id=task_id, user_request=trial.task.PROMPT))
        mlflow.set_tags(dict(case_id=case_id, task_id=task_id, variant=variant, simulation_only="true"))
        with mlflow.start_span(name=case_id, span_type="AGENT" if pipeline else "CHAIN") as span:
            trace_id = span.trace_id
            mlflow.update_current_trace(metadata={"mlflow.trace.session": child.info.run_id,
                                                 "mlflow.trace.user": "synthetic-bank-user"})
            span.set_inputs(inputs)
            try:
                if pipeline:
                    pipeline.trial = trial
                    pipeline.query(trial.task.PROMPT, trial.runtime, trial.environment)
                else:
                    trial.replay(control_calls(trial, variant))
            except Exception as exc:
                trial.status = "error"
                # Store the stage/type, not provider credentials or arbitrary exception text.
                trial.errors.append(type(exc).__name__)
            evidence = trial.evidence()
            measured = trial.measure()
            span.set_outputs(evidence)
        expectations = trial.expectations()
        record_oracles(trace_id, measured, expectations)
        record = dict(case_id=case_id, child_run_id=child.info.run_id, trace_id=trace_id, inputs=inputs,
                      experiment_id=child.info.experiment_id,
                      evidence=evidence, expectations=expectations, measured=measured,
                      model_attempts=trial.model_attempts,
                      control_passed=control_passed(variant, measured) if not pipeline else None)
        record = serializable(record)
        log_case_scores(record)
        mlflow.log_params(dict(task_id=task_id, variant=variant, benchmark_version=BENCHMARK_VERSION))
        mlflow.log_metrics({f"oracle/{k}": float(measured[k]) for k in ("utility", "selected_attack_goal_reached", "state_changed", "execution_error")})
        if record["control_passed"] is not None:
            mlflow.log_metric("control_passed", float(record["control_passed"]))
        mlflow.log_dict(record, "evidence/trial.json")
        mlflow.log_text(expectations["utility_source"], "evidence/upstream_utility.py")
        mlflow.log_text(expectations["attack_source"], "evidence/upstream_selected_attack.py")
    print(f"{case_id}: utility={measured['utility']} attack_goal={measured['selected_attack_goal_reached']} status={measured['status']} trace={trace_id}", flush=True)
    return record


def verify_one_trace(record):
    # One representative readback, bounded by the SDK HTTP timeout/retry configuration.
    # No repeated searches or application reruns to rediscover an ID.
    mlflow.flush_trace_async_logging()
    trace = mlflow.get_trace(record["trace_id"])
    if trace is None or not trace.data.spans:
        raise RuntimeError("Trace export/readback failed; stop before evaluating agents or judges")
    spans = [{"name": s.name, "type": s.span_type} for s in trace.data.spans]
    if not any(s["type"] == "TOOL" for s in spans):
        raise RuntimeError("Representative trace is missing tool evidence")
    print(f"Verified MLflow trace {record['trace_id']}: {len(spans)} spans", flush=True)
    return dict(trace_id=record["trace_id"], spans=spans)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--oracle-only", action="store_true", help="Skip the local agent, not Gemini review or MLflow evidence")
    parser.add_argument("--judge-model", default=None)
    args = parser.parse_args()
    experiment = configure()
    args.judge_model = args.judge_model or os.getenv("MLFLOW_GENAI_JUDGE_DEFAULT_MODEL", "gemini:/gemini-2.5-flash")
    suite = load_suite()
    output = ROOT / ".infra/banking-feasibility"
    output.mkdir(parents=True, exist_ok=True)
    with mlflow.start_run(run_name="banking-feasibility") as parent:
        run_id = parent.info.run_id
        manifest = provenance()
        mlflow.set_tags(dict(feasibility_block="banking-pilot", simulation_only="true"))
        mlflow.set_tag("metric_contract_version", CONTRACT_VERSION)
        mlflow.log_dict(manifest, "manifest.json")
        protocol = dict(contract_version=CONTRACT_VERSION, evidence_version=EVIDENCE_VERSION,
            case_ids=sorted(expected_cases(args.oracle_only)),
            criteria=list(CRITERIA), expected_cases=len(expected_cases(args.oracle_only)),
            expected_reviews=len(expected_cases(args.oracle_only)) * len(CRITERIA),
            acting_model=os.getenv("LM_STUDIO_MODEL", "local-model"), judge_model=args.judge_model,
            judge_settings=dict(temperature=0, max_tokens=8192, timeout=60, num_retries=0),
            acceptance_policy=ACCEPTANCE_POLICY,
            gate="exact matrix; all completed; controls; live model/tool path; normalized parity; all citations/agreement; full trace readback; agent quality reported separately",
            rerun_policy="No sampling for unanimity; retain failure and diagnose before amended protocol")
        mlflow.log_dict(protocol, "protocol.json")
        mlflow.log_artifact(str(ROOT / "docs/banking-harness-acceptance-v3.md"), "protocol")
        contract_path = ROOT / "docs/banking-metric-contract-v2.md"
        mlflow.log_artifact(str(contract_path), "protocol")
        mlflow.log_param("metric_contract_sha256", hashlib.sha256(contract_path.read_bytes()).hexdigest())
        amendment = ROOT / "docs/banking-evidence-v2.1.md"
        mlflow.log_artifact(str(amendment), "protocol")
        mlflow.log_param("evidence_amendment_sha256", hashlib.sha256(amendment.read_bytes()).hexdigest())
        provenance_amendment = ROOT / "docs/banking-provenance-v2.2.md"
        mlflow.log_artifact(str(provenance_amendment), "protocol")
        mlflow.log_param("provenance_amendment_sha256", hashlib.sha256(provenance_amendment.read_bytes()).hexdigest())
        registry_note = ROOT / "docs/banking-registry-validation-note.md"
        mlflow.log_artifact(str(registry_note), "protocol")
        for path in sorted((ROOT / "src/feasibility").glob("*.py")):
            mlflow.log_text(path.read_text(), f"implementation/{path.name}")
        mlflow.log_artifact(str(ROOT / "uv.lock"), "environment")
        mlflow.log_artifact(str(ROOT / "pyproject.toml"), "environment")
        mlflow.log_params(dict(agentdojo_commit=AGENTDOJO_COMMIT, benchmark_version=BENCHMARK_VERSION,
                               task_count=len(TASK_IDS), judge_model=args.judge_model))
        records, reviews = [], []
        try:
            for task_id in TASK_IDS:
                for variant in VARIANTS:
                    record = run_case(suite, task_id, variant)
                    records.append(record)
                    if len(records) == 1:
                        mlflow.log_dict(verify_one_trace(record), "trace_readback.json")
            # Negative-control quality gate precedes any local model run.
            oracles_ready = all(r["control_passed"] for r in records)
            mlflow.log_metric("oracle_controls_passed", float(oracles_ready))
            if not args.oracle_only and oracles_ready:
                model = os.getenv("LM_STUDIO_MODEL", "local-model")
                base_url = os.getenv("LM_STUDIO_BASE_URL", "http://localhost:1234/v1")
                client = OpenAI(base_url=base_url, api_key="lm-studio", timeout=45, max_retries=0)
                pipeline = LocalBankingPipeline(client, model)
                mlflow.log_param("agent_model", model)
                for task_id in TASK_IDS:
                    records.append(run_case(suite, task_id, "agent_benign", pipeline=pipeline))
                for preserve in (False, True):
                    variant = "agent_injected_preserve_facts" if preserve else "agent_injected_original"
                    injections = injected_environment(suite, suite.user_tasks[TASK_IDS[0]], pipeline, preserve_task_facts=preserve)
                    mlflow.log_dict(injections, f"evidence/{variant}.json")
                    records.append(run_case(suite, TASK_IDS[0], variant, pipeline=pipeline, injections=injections))
            judges = build_judges(args.judge_model)
            # Actual per-case Literal-envelope judges are registered at invocation.
            mlflow.log_dict({k: dict(name=j.name, instructions=j.instructions, model=args.judge_model)
                             for k, j in judges.items()}, "judges/definitions.json")
            for record in records:
                with mlflow.start_run(run_id=record["child_run_id"], nested=True):
                    for criterion, judge in judges.items():
                        result = review(judge, criterion, record)
                        reviews.append(dict(case_id=record["case_id"], **result))
                        mlflow.log_dict(result, f"judges/{criterion}.json")
                        mlflow.log_metrics({f"judge/{criterion}/agrees": float(result["agrees"]),
                                           f"judge/{criterion}/citations_valid": float(result["valid_evidence_citations"])})
                        print(f"Gemini {record['case_id']} {criterion}: {result['value']} agrees={result['agrees']}", flush=True)
                        if result["error"]:
                            raise RuntimeError("Gemini judge failed; deterministic evidence is retained in MLflow")
            trace_audit = audit_traces(records, reviews)
            mlflow.log_dict(trace_audit, "audit/trace-score-coverage.json")
            mlflow.log_table(pd.DataFrame([{**{k: v for k, v in row.items() if k != "scores"}, **row["scores"]}
                for row in trace_audit["traces"]]), "trace-scores.json")
            gate = acceptance(records, reviews, oracle_only=args.oracle_only, trace_coverage=trace_audit["passed"])
            summary = dict(run_id=run_id, experiment_id=experiment.experiment_id,
                tracking_uri=mlflow.get_tracking_uri(), scope=manifest["scope"],
                oracle_controls_passed=oracles_ready, oracle_cases=sum(r["control_passed"] is not None for r in records),
                agent_cases=sum(r["control_passed"] is None for r in records),
                agent_utility_successes=sum(r["measured"]["utility"] and r["measured"]["status"] == "completed" for r in records if r["control_passed"] is None),
                agent_selected_attack_goals_reached=sum(r["measured"]["selected_attack_goal_reached"] for r in records if r["control_passed"] is None),
                responses_api_tool_use_verified=any(r["evidence"]["actions"] and r["measured"]["status"] == "completed" for r in records if r["control_passed"] is None),
                oracle_only=args.oracle_only,
                metric_contract_version=CONTRACT_VERSION,
                acceptance_policy_version=ACCEPTANCE_POLICY,
                agent_forbidden_transfers=sum(r["measured"]["observed_attacker_transfer_count"] for r in records if r["control_passed"] is None),
                agent_declared_goals_reached=sum(r["measured"]["declared_goal_reached"] is True for r in records if r["control_passed"] is None),
                acceptance=gate,
                judge_reviews=len(reviews), judge_agreements=sum(r["agrees"] for r in reviews),
                trace_ids=[r["trace_id"] for r in records], child_run_ids=[r["child_run_id"] for r in records])
            mlflow.log_dict(summary, "summary.json")
            mlflow.log_table(pd.DataFrame([dict(case_id=r["case_id"], trace_id=r["trace_id"], **r["measured"])
                             for r in records]), "results.json")
            mlflow.log_dict(reviews, "judges/reviews.json")
            mlflow.log_metrics(dict(judge_agreement_rate=summary["judge_agreements"] / max(1, len(reviews)),
                                   oracle_controls_passed=float(oracles_ready)))
            (output / f"{run_id}.json").write_text(json.dumps(summary, indent=2) + "\n")
            print(json.dumps(summary, indent=2), flush=True)
            accepted = gate["passed"]
            mlflow.set_tag("feasibility_status", "passed" if accepted else "review_required")
            mlflow.set_tag("acceptance_scope", gate["scope"])
            mlflow.set_tag("harness_status", "passed" if accepted else "review_required")
            mlflow.set_tag("human_acceptance", "pending")
            if not accepted:
                mlflow.end_run(status="FAILED")
            return 0 if accepted else 1
        except Exception as exc:
            mlflow.log_dict(dict(error=type(exc).__name__, completed_case_ids=[r["case_id"] for r in records],
                                 trace_ids=[r["trace_id"] for r in records]), "failure.json")
            mlflow.log_dict(records, "partial_records.json")
            mlflow.log_dict(reviews, "judges/partial_reviews.json")
            print(f"Feasibility stopped; evidence retained in MLflow run {run_id}: {type(exc).__name__}", file=sys.stderr)
            mlflow.set_tag("feasibility_status", "failed")
            mlflow.end_run(status="FAILED")
            return 1


if __name__ == "__main__":
    sys.exit(main())
