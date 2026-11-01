"""One explicit external review of saved suite evidence; never runs an agent."""
import argparse
import json
import os

import mlflow

from src.benchmark.budget import Budget,EXTENDED_PILOT
from src.benchmark.deployment import private
from src.benchmark.privacy import Mask
from src.benchmark.review import build_harness_judge,review_harness
from src.benchmark.wiring import BASE,ROOT


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-trace",required=True)
    args=parser.parse_args()
    from dotenv import load_dotenv
    load_dotenv(ROOT/".env")
    os.environ["MLFLOW_ENABLE_ASYNC_TRACE_LOGGING"]="false"
    os.environ["MLFLOW_HTTP_REQUEST_MAX_RETRIES"]="0"
    os.environ["MLFLOW_HTTP_REQUEST_TIMEOUT"]="10"
    mlflow.set_tracking_uri(os.getenv("MLFLOW_TRACKING_URI","http://localhost:5001"))
    mlflow.set_experiment("breaker-banking-target-agent")
    mask=Mask([os.getenv(key) for key in ("GEMINI_API_KEY","GOOGLE_API_KEY","OPENAI_API_KEY")])
    mlflow.tracing.configure(span_processors=[mask.span_processor])
    source=mlflow.get_trace(args.source_trace)
    if source is None:raise ValueError("saved_suite_trace_missing")
    roots=[span for span in source.data.spans if span.parent_id is None]
    if len(roots)!=1 or roots[0].name!="persisted_suite_evidence":raise ValueError("not_saved_suite_evidence")
    observed=roots[0].outputs
    if not isinstance(observed,dict) or not {"controls","episodes"}<=set(observed):raise ValueError("saved_suite_shape_differs")
    with mlflow.start_run(run_name="external-review-saved-wiring") as run:
        # A new derived target preserves the old error/negative review and every
        # original assessment. No duplicate replacement assessment is attached
        # to the original target, and no agent/tool invocation is repeated.
        with mlflow.start_span(name="persisted_suite_evidence",span_type="CHAIN") as target:
            target.set_inputs(dict(source_trace_id=args.source_trace,protocol=EXTENDED_PILOT))
            target.set_outputs(observed);target_id=target.trace_id
        persisted=mlflow.get_trace(target_id)
        if persisted is None:raise RuntimeError("derived_review_target_not_persisted")
        root=next(span for span in persisted.data.spans if span.parent_id is None)
        budget=Budget(BASE/"combined-budget",EXTENDED_PILOT)
        result=review_harness(build_harness_judge(os.getenv("MLFLOW_GENAI_JUDGE_DEFAULT_MODEL","gemini:/gemini-2.5-flash")),
            observations=root.outputs,target_trace_id=target_id,reserve=lambda **kw:budget.reserve(case_id="suite",**kw))
        result.update(source_trace_id=args.source_trace,review_run_id=run.info.run_id)
        mlflow.log_dict(result,"review/saved-suite-review.json")
        private(BASE/("saved-review-"+run.info.run_id+".json"),result)
        print(json.dumps(result,indent=2))


if __name__=="__main__":main()
