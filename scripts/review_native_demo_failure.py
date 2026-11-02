"""One frozen post-run harness review of the retained incomplete nd1 validation.

No agent/provider diagnostic rerun. Does not change original records or spending.
All missing declared cases remain required evidence, not silently scoped away.
"""
import json
import os
from uuid import uuid4

import mlflow
from dotenv import load_dotenv

from src.benchmark.compare import claim_case
from src.benchmark.demo_budget import DemoBudget
from src.benchmark.deployment import private
from src.benchmark.privacy import Mask
from src.benchmark.review import build_harness_judge,review_harness
from src.benchmark.training_budget import POLICY
from src.benchmark.wiring import BASE,ROOT,audit_record


def main():
    load_dotenv(ROOT/".env")
    os.environ["MLFLOW_ENABLE_ASYNC_TRACE_LOGGING"]="false"
    os.environ["MLFLOW_HTTP_REQUEST_MAX_RETRIES"]="0"
    mlflow.set_tracking_uri(os.getenv("MLFLOW_TRACKING_URI","http://localhost:5001"))
    mlflow.set_experiment("breaker-banking-target-agent")
    mask=Mask([os.getenv(k) for k in ("GEMINI_API_KEY","GOOGLE_API_KEY","OPENAI_API_KEY")])
    mlflow.tracing.configure(span_processors=[mask.span_processor])
    budget=DemoBudget(BASE/"combined-budget");plan=budget.demo()
    sources=[BASE/"native-demo-a7fc121dda644e2290b134b401ab144d",BASE/"native-demo-9df88e1fed1d4b6db1a229e438ad2b14"]
    records=[];reconciliation=[]
    for source in sources:
        for path in sorted(source.glob("nd1-*.json")):
            record=json.loads(path.read_text());latest=audit_record(record)
            reconciliation.append(dict(case_id=record["case_id"],trace_id=record["trace_id"],
                original_span_count=record["trace_audit"]["span_count"],latest_span_count=latest["span_count"],
                original_gateway_model_spans=record["trace_audit"]["gateway_chat_model_spans"],latest_gateway_model_spans=latest["gateway_chat_model_spans"],latest_trace_audit=latest))
            records.append(record)
    required=[c["case_id"] for c in plan["cases"] if c["kind"]!="external_review"]
    missing=sorted(set(required)-{r["case_id"] for r in records})
    diagnosis=BASE/"native-demo-timeout-diagnosis-1ae6e25126e94af19f151bbd3f922f71"
    tail=json.loads((diagnosis/"provider-tail-observation.json").read_text())
    output=BASE/("native-demo-failure-review-"+uuid4().hex);output.mkdir(mode=0o700)
    private(output/"reconciled-traces.json",reconciliation)
    observations=dict(plan=plan,records=records,late_trace_reconciliation=reconciliation,provider_tail=tail,
        missing_declared_cases=missing,incomplete_validation=True,automatic_case_rerun=False,
        retained_setup_failure=json.loads((BASE/"native-demo-53deef133eaa4183a006ad7a3297386d/failure.json").read_text()))
    private(output/"observations.json",observations)
    with mlflow.start_run(run_name="native-demo-incomplete-validation-reconciliation") as run:
        with mlflow.start_span(name="persisted_incomplete_native_demo_evidence",span_type="CHAIN") as suite:
            suite.set_inputs(dict(required_cases=required,review_scope="whole-declared-matrix-with-explicit-missing-cases"));suite.set_outputs(observations)
        persisted=mlflow.get_trace(suite.trace_id)
        if persisted is None:raise RuntimeError("failure_evidence_not_persisted")
        root=next(span for span in persisted.data.spans if span.parent_id is None)
        source=mlflow.entities.AssessmentSource(source_type="CODE",source_id="native-demo-postrun-reconciliation-v1")
        target=tail["target_trace_id"]
        for name,value in {"validation/incomplete":True,"provider_tail/completion_tokens":0.0,
                "provider_tail/after_disconnect_seconds_approx":11.0}.items():
            mlflow.log_feedback(trace_id=target,name=name,value=value,source=source)
        claim_case(budget,"nd1-review",plan);entries=[]
        def reserve(**kw):
            entries.append(budget.reserve(role="gemini_harness_judge",case_id="nd1-review",trace_id=kw["trace_id"],
                request=dict(evidence_trace_id=suite.trace_id,required_cases=required,missing_cases=missing),model=POLICY["gemini_model"]))
        result=review_harness(build_harness_judge(POLICY["gemini_model"]),observations=root.outputs,target_trace_id=suite.trace_id,reserve=reserve,
            scope="incomplete-native-demo-validation-all-declared-cases-still-required",required_cases=required)
        for entry in entries:
            usage=result.get("transport",{}).get("raw_response",{}).get("usageMetadata",{})
            complete_cost=result.get("cost_usd") is not None and not usage.get("thoughtsTokenCount",0)
            budget.settle(entry["sequence"],accounted_cost_usd=result.get("cost_usd"),usage_verified=complete_cost)
        result.update(incomplete_validation=True,missing_cases=missing,run_id=run.info.run_id,output_directory=str(output),
            final_card_readiness=False,remaining_task_review_operations_unspent=16)
        private(output/"review.json",result);mlflow.log_dict(result,"demo/incomplete-validation-review.json")
        mlflow.log_dict(reconciliation,"demo/late-trace-reconciliation.json")
        mlflow.log_artifact(str(diagnosis/"provider-request-tail.log"),"demo/provider-tail")
        print(json.dumps(dict(review_path=str(output/"review.json"),run_id=run.info.run_id,verdict=result["value"],error=result["error"],missing_cases=missing)),flush=True)


if __name__=="__main__":main()
