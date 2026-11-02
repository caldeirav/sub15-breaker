"""Two explicitly approved API controls after the failed v2 pilot; no pilot rerun."""
import argparse
import hashlib
import json
import os
from pathlib import Path

import mlflow

from src.benchmark.prompt_pilot import APIControl,API_CONTROL_PROMPT,Goals,GOAL_PROMPT,GOALS,generate
from src.benchmark.training_budget import POLICY,TrainingBudget
from src.infra.model_budget import encoded


def diagnostic_plan(pilot):
    return dict(schema_version="banking-v2-api-diagnostic-v1",parent_pilot_sha256=hashlib.sha256(encoded(pilot)).hexdigest(),
        policy_sha256=hashlib.sha256(encoded(POLICY)).hexdigest(),owner_approved_maximum=2,stop_on_control_failure=True,
        generated_content_training_eligible=False,model=POLICY["gemini_model"],
        request_bindings=dict(control_prompt=API_CONTROL_PROMPT,control_schema=APIControl.model_json_schema(),
            original_prompt=GOAL_PROMPT+"\nOriginal request: "+GOALS["refund"],original_schema=Goals.model_json_schema()),
        cases=[dict(case_id="v2-api-diagnostic-minimal",kind="api_control",variant="diagnostic",family="none",diagnostic_only=True,maximum_output_tokens=64),
            dict(case_id="v2-api-diagnostic-original-schema",kind="goal",variant="diagnostic",family="refund",diagnostic_only=True)])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--budget",type=Path,required=True);parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--execute-authorized-diagnostics",action="store_true")
    args=parser.parse_args();budget=TrainingBudget(args.budget);plan=diagnostic_plan(budget.pilot())
    if not args.execute_authorized_diagnostics:print(json.dumps(plan,indent=2));return
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[2]/".env")
    os.environ["MLFLOW_ENABLE_ASYNC_TRACE_LOGGING"]="false";os.environ["MLFLOW_HTTP_REQUEST_MAX_RETRIES"]="0";os.environ["MLFLOW_HTTP_REQUEST_TIMEOUT"]="10"
    budget.freeze_diagnostics(plan);args.output.mkdir(parents=True,exist_ok=False,mode=0o700)
    mlflow.set_tracking_uri(os.getenv("MLFLOW_TRACKING_URI","http://localhost:5001"));mlflow.set_experiment("breaker-banking-guard-development")
    with mlflow.start_run(run_name="v2-explicit-api-controls-no-training-data") as run:
        mlflow.log_dict(plan,"protocol/api-diagnostic.json")
        receipts,accepted,rejected=generate(budget,dict(plan,protocol_sha256=hashlib.sha256(encoded(plan)).hexdigest()),args.output)
        if accepted or rejected:raise RuntimeError("diagnostic_content_must_not_enter_training")
        result=dict(run_id=run.info.run_id,attempts=len(receipts),unattempted_operations=2-len(receipts),
            cases=[dict(case_id=row["case_id"],http_status=row.get("http_status"),error=row["error"],error_detail=row.get("error_detail")) for row in receipts],
            generated_training_examples=0,bulk_started=False,training_started=False)
        for name,value in (("plan.json",plan),("summary.json",result)):
            path=args.output/name;path.write_text(json.dumps(value,indent=2)+"\n");path.chmod(0o600);mlflow.log_artifact(str(path),"diagnostic")
        print(json.dumps(result,indent=2))


if __name__=="__main__":main()
