"""Five bounded local gateway attempts, including two expected auth denials.

Three requests generate: text, a canonical get_balance call, then final text
after an explicitly synthetic non-executed tool result. This is infrastructure
compatibility evidence, not a banking task trial or the final agent graph.
"""
import argparse
import json
import os
from pathlib import Path
import plistlib
import subprocess
import time
from uuid import uuid4

from src.banking_contracts.codec import parse_object
from src.banking_contracts.tools import ToolCatalog
from src.infra.common import ROOT, STATE, VERSIONS
from src.infra.model_budget import reserve_probe,record_outcome
from src.infra.stability import FULL_WINDOW_SECONDS,live_probe
from src.infra.target_stack import DIRECTORY,EXPERIMENT,Matrix,current_bindings,private,redact,require


def completed_response(result, *, allow_call=False):
    require(result.get("status")==200,"local_provider_http_failure")
    body=result["body"]
    require(isinstance(body,dict) and body.get("object")=="response" and isinstance(body.get("id"),str) and bool(body["id"]) and
            body.get("status")=="completed" and not body.get("error") and
            body.get("incomplete_details") is None,"local_response_not_completed")
    items=body.get("output",[])
    require(isinstance(items,list) and bool(items),"missing_local_response_output")
    calls=[];text=[];ids=set()
    for item in items:
        require(item.get("type") in {"message","function_call"},"unsupported_local_response_item")
        require(item.get("status")=="completed","incomplete_or_unattested_local_response_item")
        if item["type"]=="function_call":
            require(allow_call and isinstance(item.get("call_id"),str) and bool(item["call_id"]) and item["call_id"] not in ids,"dangling_or_invalid_local_call")
            ids.add(item["call_id"]);calls.append(item)
        else:
            require(item.get("role")=="assistant","unexpected_local_message_role")
            for block in item.get("content",[]):
                require(block.get("type") in {"output_text","refusal"},"unsupported_local_content_block")
                text.append(block["text"] if block["type"]=="output_text" else block["refusal"])
    final="\n".join(text).strip()
    require(not any(marker in final for marker in ["<tool_call>","</tool_call>"]),"raw_tool_markup_is_not_completion")
    require(bool(calls) or bool(final),"missing_genuine_local_assistant_content")
    require(isinstance(body.get("usage"),dict) and body["usage"].get("total_tokens",0)>0,"missing_local_usage")
    return body,calls,final


def local_serving_software():
    """Inspect the code mapped by LM Studio, rather than only its default selector."""
    app=Path("/Applications/LM Studio.app/Contents/Info.plist")
    version=plistlib.loads(app.read_bytes())["CFBundleShortVersionString"]
    require(version==VERSIONS["lm_studio"],"lm_studio_version_differs_from_reviewed_profile")
    rows=[]
    for line in subprocess.check_output(["ps","-Ao","pid=,ppid=,comm="],text=True,timeout=5).splitlines():
        parts=line.strip().split(None,2)
        if len(parts)==3:rows.append((int(parts[0]),int(parts[1]),parts[2]))
    executable=Path("/Applications/LM Studio.app/Contents/MacOS/LM Studio")
    roots={pid for pid,_,exe in rows if exe==str(executable)}
    require(len(roots)==1,"cannot_identify_one_running_lm_studio_app")
    pids=set(roots)
    for _ in range(6):pids|={pid for pid,parent,_ in rows if parent in pids}
    mapped=set();app_inode=None
    for pid in pids:
        result=subprocess.run(["lsof","-p",str(pid),"-Fin"],capture_output=True,text=True,timeout=8)
        inode=None
        for line in result.stdout.splitlines():
            if line.startswith("i"):inode=line[1:]
            elif pid in roots and line=="n"+str(executable):app_inode=inode
            if line.startswith("n") and "/mlx-llm-" in line and line.endswith("/libllm_engine.dylib"):mapped.add(line[1:])
    require(app_inode==str(executable.stat().st_ino),"lm_studio_disk_update_not_active_in_running_process")
    expected=Path.home()/f".lmstudio/extensions/backends/mlx-llm-mac-arm64-apple-metal-advsimd-{VERSIONS['mlx_engine']}/libllm_engine.dylib"
    require(mapped=={str(expected)},"loaded_mlx_engine_not_the_reviewed_version")
    return dict(app=version,mapped_app_binary_observed=True,mapped_engine=VERSIONS["mlx_engine"],mapped_engine_observed=True,
                model_reload_requested_by_probe=False,global_defaults_modified_by_probe=False)


def verify_evidence(cluster,stability_directory):
    import mlflow
    from mlflow import MlflowClient
    audit=json.loads((DIRECTORY/"latest-protocol-audit.json").read_text())
    profile=json.loads((DIRECTORY/"profile.json").read_text())
    require(audit.get("passed") is True and audit["profile_sha256"]==profile["profile_sha256"],"protocol_privacy_or_parentage_gate_missing")
    require(MlflowClient().get_run(audit["run_id"]).info.status=="FINISHED","protocol_run_not_finished")
    require(current_bindings(cluster,profile)==json.loads((DIRECTORY/"qualified-bindings.json").read_text()),"qualified_gateway_bindings_changed")
    stable=json.loads((stability_directory/"audit.json").read_text())
    summary=json.loads((stability_directory/"summary.json").read_text())
    require(stable.get("passed") is True and stable.get("trace_readback") is True and
            summary.get("full_window") is True and summary.get("elapsed_seconds",0)>=FULL_WINDOW_SECONDS,"full_provider_stability_gate_missing")
    require(MlflowClient().get_run(stable["run_id"]).info.status=="FINISHED","stability_run_not_finished")
    require(live_probe(cluster)==summary["baseline"],"provider_changed_since_stability_window")
    gateway=cluster.get("gateway","breaker-gateway","-n","breaker-enforcement")
    require(gateway["metadata"]["uid"]==profile["gateway_uid"],"managed_gateway_identity_changed")
    model=cluster.get("agentgatewaybackend","local-banking-model","-n","breaker-enforcement")["spec"]
    provider=model["ai"]["provider"]
    require(provider["host"]==profile["host_ip"] and provider["port"]==1234 and
            provider["custom"]["model"]==profile["model"] and
            provider["custom"]["formats"]==[{"type":"Completions","path":"/v1/chat/completions"}] and
            model["policies"]["ai"]["routes"]=={"/v1/responses":"Responses"},"serving_backend_differs_from_qualified_profile")
    loaded=json.loads(subprocess.check_output(["lms","ps","--json"],text=True,timeout=15))
    selected=[m for m in loaded if m.get("identifier")==profile["model"]]
    require(profile["model"]==VERSIONS["local_model"] and len(selected)==1 and selected[0]["architecture"]=="qwen3_moe" and
            selected[0]["contextLength"]==VERSIONS["local_model_context"] and selected[0]["quantization"]["bits"]==4 and
            selected[0]["status"]=="idle" and selected[0].get("queued",0)==0,"approved_local_model_not_loaded_idle_or_matching")
    return profile,dict(model=selected[0],software=local_serving_software()),audit,stable


def main():
    from dotenv import load_dotenv
    import mlflow
    from mlflow.entities import AssessmentSource
    from src.infra.manage import Cluster
    from src.infra.doctor import check_hypervisor,check_podman_versions
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute-authorized-probes",action="store_true",required=True)
    parser.add_argument("--stability-directory",type=Path,required=True)
    args=parser.parse_args()
    load_dotenv(ROOT/".env")
    os.environ["MLFLOW_ENABLE_ASYNC_TRACE_LOGGING"]="false"
    os.environ["MLFLOW_HTTP_REQUEST_TIMEOUT"]="5"
    os.environ["MLFLOW_HTTP_REQUEST_MAX_RETRIES"]="0"
    cluster=Cluster("breaker-substrate");cluster.ensure_owned();check_hypervisor();check_podman_versions()
    mlflow.set_experiment(EXPERIMENT)
    profile,loaded,protocol_audit,stable=verify_evidence(cluster,args.stability_directory)
    tokens=json.loads((DIRECTORY/"credentials.json").read_text())["stringData"]
    # Inspect lifetime only; signature/issuer/audience/subject are enforced and
    # exercised at the actual gateway, not inferred from unverified claims.
    import base64
    for token in tokens.values():
        part=token.split(".")[1];claims=json.loads(base64.urlsafe_b64decode(part+"="*(-len(part)%4)))
        require(claims.get("exp",0)-time.time()>300,"renew_probe_credentials_before_dispatch")
    directory=DIRECTORY/"serving-runs"/uuid4().hex;directory.mkdir(parents=True,mode=0o700)
    campaign=DIRECTORY/"serving-campaign-started.json"
    fd=os.open(campaign,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    with os.fdopen(fd,"w") as output:
        json.dump(dict(directory=str(directory),profile_sha256=profile["profile_sha256"],declared_wire_attempts=5,generation_cases=3),output)
        output.flush();os.fsync(output.fileno())
    matrix=Matrix(cluster,profile,tokens,directory)
    catalog=ToolCatalog.from_pinned_agentdojo()
    schema=catalog.schemas()["get_balance"]["arguments"]
    tool=dict(type="function",name="get_balance",description="Synthetic transport probe only; this tool will not be executed.",parameters=schema)
    source=AssessmentSource(source_type="CODE",source_id="local-serving-infrastructure-v1")
    run=mlflow.start_run(run_name="local-qwen-via-managed-responses-completions")
    mlflow.set_tags(dict(scope="infrastructure-serving-probe-not-task-trial",human_acceptance="pending",github_issue="38"))
    mlflow.log_dict(dict(model=loaded,provider_profile=profile,protocol_gate=protocol_audit,stability_gate=stable,
                         cases=5,generation_cases=3,model_tools_executed=False,paid_providers=False,retries=0,output_tokens=256,temperature=0),"protocol.json")
    rows=[];trace_id=None;passed=False
    defaults=dict(model=profile["model"],store=False,temperature=0,max_output_tokens=256,parallel_tool_calls=False)

    def attempt(name,body,*,token="MODEL_TOKEN",denied=False,allow_call=False):
        with mlflow.start_span(name="local_model_"+name,span_type="LLM") as span:
            span.set_inputs(dict(request=body,credential_selector=token,scope="non-executing-infrastructure-probe"))
            path,entry=reserve_probe(STATE/"langgraph-sprint/model-budget",case=name,run_id=run.info.run_id,
                trace_id=span.trace_id,request=body,profile_sha256=profile["profile_sha256"])
            mlflow.log_dict(entry,f"budget/{path.stem}.attempt.json")
            try:
                result=matrix.wire(name,body,port=8080,token=token)
            except BaseException as exc:
                outcome=dict(error=type(exc).__name__,dispatch_outcome="unknown",reservation_spent=True)
                record_outcome(path,outcome);mlflow.log_dict(outcome,f"budget/{path.stem}.error.json")
                rows.append(dict(case_id=name,passed=False,sequence=entry["sequence"],span_id=span.span_id,error=type(exc).__name__))
                raise
            record_outcome(path,result)  # Original wire outcome, before any validation.
            safe=redact(result,matrix.secrets);span.set_outputs(safe)
            mlflow.log_dict(safe,f"budget/{path.stem}.result.json")
            try:
                if denied:
                    span.set_status("ERROR")
                    require(result["status"] in {401,403},"serving_identity_denial_failed")
                    value=(None,[],"")
                else:
                    value=completed_response(result,allow_call=allow_call)
                    if allow_call:
                        require(len(value[1])==1 and value[1][0]["name"]=="get_balance","canonical_local_function_call_missing")
                        arguments=parse_object(value[1][0]["arguments"].encode())
                        require(catalog.validate_arguments("get_balance",arguments)=={},"canonical_local_function_arguments_changed")
                rows.append(dict(case_id=name,passed=True,sequence=entry["sequence"],span_id=span.span_id,
                    expected_auth_denial=denied,status=result["status"],completed_response=not denied))
                return value
            except BaseException as exc:
                rows.append(dict(case_id=name,passed=False,sequence=entry["sequence"],span_id=span.span_id,error=type(exc).__name__))
                raise

    try:
        with mlflow.start_span(name="local_serving_protocol_probe",span_type="CHAIN") as root:
            trace_id=root.trace_id
            mlflow.update_current_trace(metadata={"banking.scope":"infrastructure-serving-probe","banking.utility_evaluated":"false"})
            root.set_inputs(dict(cases=5,declared_generations=3,banking_tools_executed=0,profile_sha256=profile["profile_sha256"]))
            denial=dict(defaults,input="Authentication test: this must be rejected at the gateway.")
            attempt("missing_identity",denial,token="none",denied=True)
            attempt("wrong_audience",denial,token="FIXTURE_TOKEN",denied=True)
            attempt("text",dict(defaults,input="Infrastructure protocol test. Briefly confirm you can answer. Do not use any tools."))
            prompt="Infrastructure protocol test only. Request get_balance using its schema. No banking tool will be executed; the subsequent tool output will be explicitly synthetic."
            body,calls,_=attempt("function_call",dict(defaults,input=prompt,tools=[tool],tool_choice=dict(type="function",name="get_balance")),allow_call=True)
            require(len(calls)==1 and calls[0]["name"]=="get_balance","canonical_local_function_call_missing")
            arguments=parse_object(calls[0]["arguments"].encode())
            require(catalog.validate_arguments("get_balance",arguments)=={},"canonical_local_function_arguments_changed")
            history=[dict(role="user",content=prompt),*body["output"],dict(type="function_call_output",call_id=calls[0]["call_id"],
                output='{"fixture_only":true,"tool_executed":false,"message":"Transport fixture only; no account state was queried."}'),
                dict(role="user",content="End this protocol probe with a short final response. State that no banking tool was executed.")]
            _,pending,answer=attempt("final_after_function_result",dict(defaults,input=history,tools=[tool],tool_choice="auto"))
            require(not pending and bool(answer),"local_flow_has_dangling_calls_or_no_final_content")
            require(len(rows)==5 and all(r["passed"] for r in rows),"serving_matrix_incomplete")
            passed=True;root.set_outputs(dict(passed=True,wire_attempts=5,completed_generations=3,expected_gateway_denials=2,
                final_assistant_response=answer,banking_tools_executed=0,task_utility_evaluated=False))
    finally:
        summary=dict(passed=passed,run_id=run.info.run_id,trace_id=trace_id,cases=rows,wire_attempts=len(rows),
            banking_tools_executed=0,paid_calls=0,task_utility_evaluated=False,human_acceptance="pending")
        private(directory/"summary.json",summary);mlflow.log_dict(summary,"summary.json")
        if trace_id:
            for row in rows:mlflow.log_feedback(trace_id=trace_id,span_id=row["span_id"],name="infra/serving_case_passed",value=row["passed"],source=source)
        if not passed:mlflow.end_run(status="FAILED")
    try:
        mlflow.flush_trace_async_logging();deadline=time.monotonic()+20
        while True:
            trace=mlflow.get_trace(trace_id)
            if trace is not None:
                native={r["span_id"] for r in rows}|set(matrix.client_spans)
                external=[s for s in trace.data.spans if s.parent_id is not None and s.span_id not in native]
                ids={s.span_id for s in trace.data.spans}
                if len(external)>=5 and all(s.parent_id in ids for s in trace.data.spans if s.parent_id):break
            require(time.monotonic()<deadline,"serving_gateway_trace_parentage_missing")
            time.sleep(1)  # Persisted readback only; no provider resampling.
        require(not any(secret in json.dumps(trace.to_dict()) for secret in matrix.secrets),"serving_trace_credential_leak")
        roots=[s for s in trace.data.spans if s.parent_id is None]
        require(len(roots)==1 and roots[0].name=="local_serving_protocol_probe","serving_trace_root_mismatch")
        for row in rows:
            scores=[a for a in trace.info.assessments if a.span_id==row["span_id"] and a.name=="infra/serving_case_passed"]
            require(len(scores)==1 and scores[0].value is True and scores[0].source.source_id==source.source_id,"serving_score_readback_mismatch")
        audit=dict(passed=True,run_id=run.info.run_id,trace_id=trace_id,spans=len(trace.data.spans),gateway_spans=len(external),
                   reserved_probe_attempts=5,completed_generations=3,expected_auth_denials=2,banking_tools_executed=0,
                   profile_sha256=profile["profile_sha256"],task_utility_evaluated=False,human_acceptance="pending")
        mlflow.log_dict(audit,"audit.json");private(directory/"audit.json",audit)
        private(DIRECTORY/"latest-serving-audit.json",dict(audit,directory=str(directory)))
        mlflow.end_run(status="FINISHED");print(json.dumps(audit),flush=True)
    except BaseException as exc:
        failure=dict(passed=False,stage="serving_trace_audit",error=type(exc).__name__,trace_id=trace_id)
        private(directory/"audit.json",failure);mlflow.log_dict(failure,"audit.json");mlflow.end_run(status="FAILED")
        raise


if __name__=="__main__":main()
