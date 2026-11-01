"""Opt-in, budgeted local-agent and native Gemini validation of the Actor path."""
import argparse
import json
import os
from uuid import uuid4

import mlflow
from openai import OpenAI

from src.banking_service.agent import ActorBankingTrial, DurableModelClient
from src.banking_service.deploy import Deployment, DIRECTORY, ROOT
from src.banking_service.http import RuntimeClient
from src.banking_service.telemetry import export_outbox,log_receipt_scores
from src.banking_service.validation import runtime_proof
from src.feasibility.agent import LocalBankingPipeline
from src.feasibility.banking import TASK_IDS, load_suite, record_oracles, serializable
from src.feasibility.judges import build_judges, review
from src.feasibility.runner import configure
from src.feasibility.telemetry import audit_traces, log_case_scores


def validate_judge_provider(model):
    if not isinstance(model,str) or not model.startswith("gemini:/") or len(model)<=len("gemini:/"):
        raise ValueError("Only the explicitly authorized native Gemini provider may consume this budget")


def validate_controls(summary,run,protocol,audit,validated_manifest,current_manifest,expected_experiment):
    from src.banking_contracts.tools import READ_TOOLS,WRITE_TOOLS
    from src.banking_service.runtime_controls import EXTRA_CASES
    expected={"valid_"+name for name in READ_TOOLS|WRITE_TOOLS}|set(EXTRA_CASES)
    if (run.status!="FINISHED" or run.experiment_id!=expected_experiment or
            summary.get("full_runtime_controls_passed") is not True or summary.get("cases")!=len(expected) or
            summary.get("expected_cases")!=len(expected) or protocol.get("protocol")!="banking-runtime-controls-v1" or
            protocol.get("cases")!=len(expected) or sorted(protocol.get("case_ids",[]))!=sorted(expected)):
        raise ValueError("Runtime control status/protocol/matrix is not accepted for live validation")
    if len(audit)!=len(expected) or {r.get("case_id") for r in audit}!=expected or any(r.get("passed") is not True for r in audit):
        raise ValueError("Runtime control persisted readback is incomplete")
    for key in ("image","template","space","namespace"):
        if not validated_manifest.get(key) or validated_manifest.get(key)!=current_manifest.get(key):
            raise ValueError("Live deployment differs from the controlled image/template")


def live_summary(records,reviews,base_passed,export_passed):
    from collections import Counter
    from src.feasibility.metrics_contract import CRITERIA
    cases={"actor-agent-"+task for task in TASK_IDS}
    exact=(len(records)==3 and {r.get("case_id") for r in records}==cases and
        Counter((r.get("case_id"),r.get("criterion")) for r in reviews)==Counter({(case,criterion):1 for case in cases for criterion in CRITERIA}))
    return dict(passed=bool(base_passed and export_passed and exact),agent_utility_successes=sum(r["measured"]["utility"] for r in records),
        trials=len(records),reviews=len(reviews),human_acceptance="pending",financial_authorization=False,
        durable_export_readback_passed=bool(export_passed))


def reserve_budget(key, run_id):
    directory=DIRECTORY/"live-budget"
    directory.mkdir(mode=0o700,exist_ok=True)
    # Exclusive durable reservation is never silently removed after an error.
    # Another live sampling pass needs a new explicit owner-approved budget.
    with (directory/(key+".json")).open("x") as f:
        json.dump(dict(key=key,run_id=run_id,owner_authorized=True,automatic_retry=False),f)
        f.flush();os.fsync(f.fileno())
    directory_fd=os.open(directory,os.O_RDONLY)
    try:os.fsync(directory_fd)
    finally:os.close(directory_fd)


def review_durably(store,judge,criterion,record):
    trial_id=record["evidence"]["evidence_id"].rsplit("/observed-state",1)[0]
    common=dict(target_trace_id=record["trace_id"],criterion=criterion,model=judge.model)
    store.call("/client-event",dict(trial_id=trial_id,kind="validation_result",
        payload=dict(operation_kind="judge_attempt",**common)))
    try:result=review(judge,criterion,record)
    except Exception as exc:
        store.call("/client-event",dict(trial_id=trial_id,kind="validation_result",
            payload=dict(operation_kind="judge_error",error=type(exc).__name__,**common)))
        raise
    store.call("/client-event",dict(trial_id=trial_id,kind="validation_result",
        payload=dict(operation_kind="judge_result",result=serializable(result),**common)))
    return result


def run_live_case(deployment,store,authorization,suite,task_id,model):
    with mlflow.start_run(run_name="actor-agent-"+task_id,nested=True) as run:
        trial_id="trial-"+uuid4().hex
        actor=None;trial=None
        try:
            with mlflow.start_span(name="allocate_trial_actor",span_type="CHAIN") as span:
                actor=deployment.create_actor()
                span.set_outputs(actor)
            mlflow.log_dict(runtime_proof(deployment,actor),"runtime/platform-assignment.json")
            store.call("/create",dict(trial_id=trial_id,actor_id=actor["metadata"]["name"],
                actor_uid=actor["metadata"]["uid"],user_request=suite.user_tasks[task_id].PROMPT))
            with deployment.forward(actor["metadata"]["name"],actor=True) as base:
                probe=RuntimeClient(base,authorization).call("/probe",{})
                mlflow.log_dict(probe,"runtime/sandbox-probe.json")
                if (probe["uid"],probe["gid"],probe["effective_capabilities"],probe["no_new_privs"],probe["ambient_kubernetes_token"])!=(10001,10001,"0000000000000000","1",False):
                    raise RuntimeError("Live Actor security profile differs from validated runtime")
                trial=ActorBankingTrial(suite,task_id,trial_id,store,base,authorization)
                client=OpenAI(base_url=os.getenv("LM_STUDIO_BASE_URL","http://localhost:1234/v1"),
                    api_key="lm-studio",timeout=45,max_retries=0)
                pipeline=LocalBankingPipeline(DurableModelClient(client,store,trial_id),model)
                pipeline.trial=trial
                reserve_budget("local-"+task_id,run.info.run_id)
                inputs=dict(task_id=task_id,user_request=trial.task.PROMPT)
                with mlflow.start_span(name="actor_agent_"+task_id,span_type="AGENT") as span:
                    span.set_inputs(inputs);trace_id=span.trace_id
                    try:pipeline.query(trial.task.PROMPT,trial.runtime,trial.environment)
                    except Exception as exc:
                        trial.status="error";trial.errors.append(type(exc).__name__)
                    evidence=trial.evidence()
                    measured=trial.measure()
                    span.set_outputs(evidence)
                expectations=trial.expectations()
                record_oracles(trace_id,measured,expectations)
                record=serializable(dict(case_id="actor-agent-"+task_id,child_run_id=run.info.run_id,
                    trace_id=trace_id,inputs=inputs,experiment_id=run.info.experiment_id,evidence=evidence,
                    expectations=expectations,measured=measured,model_attempts=trial.model_attempts,control_passed=None))
                log_case_scores(record)
                log_receipt_scores(record)
                mlflow.log_dict(record,"evidence/trial.json")
                return record
        finally:
            actor=actor or deployment.last_actor
            errors=[]
            if actor is not None:
                with mlflow.start_span(name="cleanup_trial_actor",span_type="CHAIN") as span:
                    try:store.call("/fence",dict(trial_id=trial_id))
                    except Exception as exc:errors.append(dict(stage="fence",error=type(exc).__name__))
                    try:
                        deployment.delete_actor(actor["metadata"]["name"])
                        span.set_outputs(dict(deleted_actor=actor["metadata"]["name"],uid=actor["metadata"]["uid"]))
                    except Exception as exc:errors.append(dict(stage="delete",error=type(exc).__name__))
            mlflow.log_dict(dict(errors=errors),"audit/cleanup.json")
            if errors:raise RuntimeError("Live-trial cleanup incomplete")


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--controls-run",required=True)
    parser.add_argument("--execute-authorized-live-budget",action="store_true",required=True,
        help="Explicitly run the owner-authorized three local trials and twelve paid native Gemini reviews, once")
    args=parser.parse_args()
    judge_model=os.getenv("MLFLOW_GENAI_JUDGE_DEFAULT_MODEL","gemini:/gemini-2.5-flash")
    # configure loads .env, so validate again after that load and before calls.
    from dotenv import load_dotenv
    load_dotenv(ROOT/".env")
    judge_model=os.getenv("MLFLOW_GENAI_JUDGE_DEFAULT_MODEL","gemini:/gemini-2.5-flash")
    validate_judge_provider(judge_model)
    configure(require_judge=True)
    experiment=mlflow.set_experiment("breaker-banking-actor-service-03b")
    from pathlib import Path
    def artifact(name):return json.loads(Path(mlflow.artifacts.download_artifacts(run_id=args.controls_run,artifact_path=name)).read_text())
    controls=artifact("summary.json")
    manifest=json.loads((DIRECTORY/"deployment.json").read_text())
    validate_controls(controls,mlflow.MlflowClient().get_run(args.controls_run).info,artifact("protocol.json"),
        artifact("audit/case-trace-score-readback.json"),artifact("runtime/deployment.json"),manifest,experiment.experiment_id)
    if any((DIRECTORY/"live-budget"/("local-"+task+".json")).exists() for task in TASK_IDS):
        raise SystemExit("Existing live budget reservation: no automatic resampling is permitted")
    suite=load_suite();deployment=Deployment()
    deployment.verify_deployment(manifest)
    authorization="Bearer "+(DIRECTORY/"runtime.token").read_text().strip()
    model=os.getenv("LM_STUDIO_MODEL","local-model")
    with mlflow.start_run(run_name="actor-backed-agent-native-review") as parent:
        mlflow.log_dict(dict(task_ids=list(TASK_IDS),controls_run=args.controls_run,acting_model=model,judge_model=judge_model,
            local_trial_budget=3,native_review_budget=12,model_turn_limit=8,tool_attempt_limit=16,
            task_seconds=180,max_model_retries=0,canonical_decimal_schemas=True,financial_authorization=False,
            agent_win_rate_gate=False,rerun_policy="No automatic resampling; retain all outcomes"),"protocol.json")
        records=[];reviews=[];passed=False
        with deployment.forward("service/banking-store") as base:
            store=RuntimeClient(base,authorization)
            try:
                for task_id in TASK_IDS:
                    records.append(run_live_case(deployment,store,authorization,suite,task_id,model))
                    mlflow.log_dict(records,"evidence/partial-trials.json")
                judges=build_judges(judge_model)
                for record in records:
                    with mlflow.start_run(run_id=record["child_run_id"],nested=True):
                        for criterion,judge in judges.items():
                            task_id=record["inputs"]["task_id"]
                            reserve_budget("gemini-"+task_id+"-"+criterion,parent.info.run_id)
                            result=review_durably(store,judge,criterion,record)
                            reviews.append(dict(case_id=record["case_id"],**result))
                            mlflow.log_dict(result,f"judges/{criterion}.json")
                audit=audit_traces(records,reviews)
                mlflow.log_dict(audit,"audit/live-trace-score-coverage.json")
                passed=(len(records)==3 and len(reviews)==12 and audit["passed"] and
                    all(not r["error"] and r["valid_evidence_citations"] and r["agrees"] for r in reviews) and
                    all(r["measured"]["status"]=="completed" and not r["measured"]["execution_error"] for r in records))
                if not passed:raise RuntimeError("Live validation gates failed; retain all outcomes and budget reservations")
            finally:
                mlflow.log_dict(records,"evidence/trials.json")
                mlflow.log_dict(reviews,"judges/reviews.json")
                export_passed=False
                try:
                    mlflow.log_dict(export_outbox(store,experiment.experiment_id),"audit/outbox-readback.json")
                    export_passed=True
                finally:
                    mlflow.log_dict(live_summary(records,reviews,passed,export_passed),"summary.json")


if __name__=="__main__":main()
