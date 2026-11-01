"""One explicitly authorized local parser replay; never execute returned tools."""
import argparse
from copy import deepcopy
import hashlib
import json
import os
from urllib.parse import urlparse

from dotenv import load_dotenv
import mlflow
from openai import OpenAI

from src.banking_service.agent import canonical_suite_view
from src.banking_service.deploy import DIRECTORY,ROOT
from src.banking_service.live import reserve_budget
from src.feasibility.agent import tool_specs
from src.feasibility.banking import load_suite,serializable


def replay_request(exported,canonical_tools):
    request=deepcopy(exported)
    # Secret-field redaction also withholds the public password-schema property.
    # Restore schema declarations from the same pinned catalog, never user data.
    request["tools"]=canonical_tools
    if serializable(request)!=exported:raise ValueError("Pinned request/schema reconstruction differs")
    other={k:v for k,v in request.items() if k!="tools"}
    if "[REDACTED]" in json.dumps(other) or "[WITHHELD]" in json.dumps(other):
        raise ValueError("Cannot exactly replay privacy-withheld message values")
    if request.get("max_output_tokens")!=2048:raise ValueError("Replay exceeds approved token settings")
    return request


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-trace",required=True)
    parser.add_argument("--span-name",required=True)
    parser.add_argument("--one-authorized-local-replay",required=True,action="store_true")
    args=parser.parse_args()
    load_dotenv(ROOT/".env")
    os.environ["MLFLOW_ENABLE_ASYNC_TRACE_LOGGING"]="false"
    mlflow.set_tracking_uri(os.getenv("MLFLOW_TRACKING_URI","http://localhost:5001"))
    mlflow.set_experiment("breaker-banking-actor-service-03b")
    mlflow.openai.autolog(disable=True)
    source=mlflow.get_trace(args.source_trace)
    spans=[s for s in source.data.spans if s.name==args.span_name and s.span_type=="CHAT_MODEL"]
    if len(spans)!=1 or (spans[0].outputs or {}).get("status")!="error":raise SystemExit("An exact failed model span is required")
    request=replay_request(spans[0].inputs,tool_specs(canonical_suite_view(load_suite())))
    if request["model"]!=os.getenv("LM_STUDIO_MODEL","local-model"):raise SystemExit("Configured local model changed")
    base=os.getenv("LM_STUDIO_BASE_URL","http://localhost:1234/v1")
    if urlparse(base).hostname not in {"localhost","127.0.0.1","::1"}:raise SystemExit("Only the configured loopback local model is authorized")
    with mlflow.start_run(run_name="one-local-tool-parser-replay") as run:
        protocol=dict(source_trace=args.source_trace,source_span=args.span_name,scope="single diagnostic inference; no tool execution",
            max_output_tokens=2048,timeout_seconds=45,max_retries=0,gemini_calls=0,banking_tool_calls=0,
            schema_reconstruction="Only public schema declarations restored from pinned catalog; exported view matches exactly",
            public_schema_sha256=hashlib.sha256(json.dumps(request["tools"],sort_keys=True).encode()).hexdigest())
        mlflow.log_dict(protocol,"protocol.json")
        reserve_budget("diagnostic-"+args.source_trace+"-"+args.span_name,run.info.run_id)
        journal=DIRECTORY/("diagnostic-"+run.info.run_id+".jsonl")
        def persist(value):
            with journal.open("a") as f:
                f.write(json.dumps(serializable(value))+"\n");f.flush();os.fsync(f.fileno())
            journal.chmod(0o600)
        persist(dict(stage="attempt",protocol=protocol,request=serializable(request)))
        with mlflow.start_span(name="diagnostic_local_response",span_type="CHAT_MODEL") as span:
            span.set_inputs(serializable(request));span.set_attribute("mlflow.llm.model",request["model"])
            try:
                response=OpenAI(base_url=base,api_key="lm-studio",timeout=45,max_retries=0).responses.create(**request)
                output=serializable(response.model_dump(mode="json"))
                summary=dict(outcome="not_reproduced",returned_status=response.status,
                    returned_tool_calls=sum(item.type=="function_call" for item in response.output),
                    local_inference_calls=1,banking_tool_calls=0,gemini_calls=0)
            except Exception as exc:
                parser_error=getattr(exc,"status_code",None)==500 and "Failed to parse tool call" in str(exc)
                output=dict(error=type(exc).__name__,http_status=getattr(exc,"status_code",None),parser_error=parser_error)
                summary=dict(outcome="parser_error_reproduced" if parser_error else "other_error",
                    local_inference_calls=1,banking_tool_calls=0,gemini_calls=0,**output)
            persist(dict(stage="result",summary=summary,response=output))
            span.set_outputs(dict(summary=summary,response=output));trace_id=span.trace_id
        mlflow.log_feedback(trace_id=trace_id,name="diagnostic/outcome",value=summary["outcome"],
            source=mlflow.entities.AssessmentSource(source_type="CODE",source_id="local-parser-replay-v1"))
        mlflow.log_dict(summary,"summary.json")
        mlflow.log_artifact(str(journal),"durable-evidence")
        print(json.dumps(dict(run_id=run.info.run_id,trace_id=trace_id,**summary)))


if __name__=="__main__":main()
