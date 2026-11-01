"""Diagnostic learned-guard comparison through the existing native agent flow.

Freeze first. Canary and full episodes are separate explicit stages; blocked or
errored episodes are evidence, never automatically rerun for a preferred outcome.
"""
import argparse
from contextlib import ExitStack
from dataclasses import asdict
import json
import os
from pathlib import Path
import threading
from uuid import uuid4

import httpx
import mlflow
from langchain_openai import ChatOpenAI

from src.agent_runtime.contracts import Limits
from src.banking_service.deadlines import LEARNED
from src.banking_service.deploy import Deployment,DIRECTORY,STORE_HOST
from src.banking_service.http import RuntimeClient
from src.benchmark.admission import ReviewBuilder,classifier_guard,llm_guard
from src.benchmark.bridge import Bridge,BridgeServer,MCPClient
from src.benchmark.campaign_budget import CampaignBudget
from src.benchmark.deployment import configure_bridge,gateway_forward,native_hook,private
from src.benchmark.encoder import manifest as encoder_manifest
from src.benchmark.guards import INPUT_VERSION
from src.benchmark.native import Registry,server
from src.benchmark.privacy import Mask
from src.benchmark.projection import POLICY_ID
from src.benchmark.wiring import BASE,ROOT,ModelTransport,benchmark_template,run_case,validate_control
from src.integrations.agentdojo.banking import BankingAdapter,TASKS
from src.integrations.agentdojo.inventory import digest


def comparison_matrix(artifact,dataset,*,reviewer_model):
    model=encoder_manifest(artifact,policy_id=POLICY_ID)
    calibration=model.get("calibration")
    if not calibration:raise ValueError("frozen_calibration_required")
    coverage=json.loads((Path(dataset)/"coverage.json").read_text())
    rows=[json.loads(line) for line in (Path(dataset)/"rows.jsonl").read_text().splitlines()]
    if digest(rows)!=coverage["dataset_sha256"]:raise ValueError("comparison_dataset_changed")
    cases=[]
    for decision in ("allow","block","error","unsupported"):
        cases.append(dict(case_id="native-control-"+decision,task_id="user_task_0",phase="guard_canary",actor=0,llm_guard=0))
    for arm in ("classifier","llm"):
        cases.append(dict(case_id="canary-"+arm,task_id="user_task_0",phase="guard_canary",actor=0,llm_guard=int(arm=="llm")))
    for index,task in enumerate(TASKS):
        for arm in (("classifier","llm") if index%2==0 else ("llm","classifier")):
            cases.append(dict(case_id=f"episode-{task}-{arm}",task_id=task,phase="episodes",actor=16,llm_guard=24 if arm=="llm" else 0,
                gemini_task_judge=4))
    # Reserve named identical-input replay slots now, but do not confuse their
    # authorization with implementation/measurement of a full native replay.
    replay=[row for row in rows if row["task_id"] in TASKS and row["projection_supported"] and
        row["unsafe_label"] is not None and not row.get("label_quarantine")]
    for index,row in enumerate(replay):
        cases.append(dict(case_id=f"replay-{index:03d}",task_id=row["task_id"],phase="paired_replay",llm_guard=1,
            candidate_id=row["candidate_id"],input_digest=row["input_digest"]))
    cases.append(dict(case_id="comparison-suite",task_id=None,phase="diagnostics",gemini_harness_judge=1))
    return dict(schema_version="native-diagnostic-comparison-v1",policy_id=POLICY_ID,input_version=INPUT_VERSION,
        dataset_manifest_sha256=digest(coverage),artifact_manifest_sha256=digest(model),calibration_sha256=digest(calibration),
        reviewer_model=reviewer_model,deadlines=asdict(LEARNED),quality_status="failed_transfer_false_block_target",
        admission_timing_claim=False,retries=0,fallback=False,cases=cases)


def validate_deployment_profile(deployment):
    config=json.loads((DIRECTORY/"deployment.json").read_text())
    if config.get("deadline_profile")!=LEARNED.name:raise RuntimeError("learned_deadline_deployment_required")
    deployment.verify_deployment(config)
    store=deployment.cluster.get("deployment","banking-store","-n",config["namespace"])
    env=store["spec"]["template"]["spec"]["containers"][0].get("env",[])
    if [entry.get("value") for entry in env if entry["name"]=="BANKING_DEADLINE_PROFILE"]!=[LEARNED.name]:
        raise RuntimeError("store_deadline_profile_mismatch")
    template=json.loads(deployment.ate("get","actor-template",config["template"],"-a",config["space"],"-o","json").stdout)
    env=template["containers"][0].get("env",[])
    if [entry.get("value") for entry in env if entry["name"]=="BANKING_DEADLINE_PROFILE"]!=[LEARNED.name]:
        raise RuntimeError("actor_deadline_profile_mismatch")


def claim_case(budget,case_id,matrix):
    # Classifier/scripted cases also need an irreversible start marker: they
    # spend zero model requests, which must not make silent repeats possible.
    with budget.locked():
        budget._exclusive(budget.directory/("native-case-"+case_id+".json"),dict(
            case_id=case_id,matrix_sha256=digest(matrix),state="started",automatic_rerun=False))


def validate_canary(records):
    if len(records)!=2:return False
    digests=[]
    for record in records:
        actions=record["evidence"]["actions"]
        if len(actions)!=1 or record["cleanup_errors"]:return False
        gate=actions[0].get("guard") or {}
        if gate.get("decision") not in {"allow","block"}:return False
        validate_control(record,gate["decision"])
        expected=int(record["case_id"]=="canary-llm")
        if record["trace_audit"].get("guard_managed_responses_dispatches")!=expected:return False
        digests.append(gate["input_digest"])
    return digests[0]==digests[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact",type=Path,required=True)
    parser.add_argument("--dataset",type=Path,required=True)
    parser.add_argument("--budget",type=Path,required=True)
    parser.add_argument("--freeze",action="store_true")
    parser.add_argument("--execute",choices=("canary","episodes"))
    parser.add_argument("--canary-result",type=Path)
    args=parser.parse_args()
    from dotenv import load_dotenv
    load_dotenv(ROOT/".env")
    os.environ["MLFLOW_ENABLE_ASYNC_TRACE_LOGGING"]="false"
    os.environ["MLFLOW_HTTP_REQUEST_MAX_RETRIES"]="0";os.environ["MLFLOW_HTTP_REQUEST_TIMEOUT"]="10"
    mlflow.set_tracking_uri(os.getenv("MLFLOW_TRACKING_URI","http://localhost:5001"))
    matrix=comparison_matrix(args.artifact,args.dataset,reviewer_model=os.environ["LM_STUDIO_MODEL"])
    budget=CampaignBudget(args.budget)
    if args.freeze:budget.freeze_matrix(matrix)
    if not args.execute:
        print(json.dumps(matrix,indent=2));return
    if budget._matrix()!=matrix:raise RuntimeError("frozen_comparison_matrix_mismatch")
    if args.execute=="episodes":
        if not args.canary_result:raise ValueError("persisted_canary_result_required")
        canary=json.loads(args.canary_result.read_text())
        if canary.get("matrix_sha256")!=digest(matrix) or not canary.get("mechanical_canary_passed"):
            raise ValueError("canary_gate_not_passed")
        for record in canary["records"]:
            from src.benchmark.wiring import audit_record
            audit_record(record)
    deployment=Deployment();validate_deployment_profile(deployment);deployment.refresh_credentials()
    previous=(DIRECTORY/"deployment.json").read_bytes()
    original,template=benchmark_template(deployment);config=dict(original,template=template)
    token=(DIRECTORY/"runtime.token").read_text().strip()
    mask=Mask([token,*[os.getenv(key) for key in ("GEMINI_API_KEY","GOOGLE_API_KEY","OPENAI_API_KEY")]])
    mlflow.set_experiment("breaker-banking-target-agent");mlflow.langchain.autolog();mlflow.openai.autolog(disable=True)
    mlflow.tracing.configure(span_processors=[mask.span_processor])
    directory=BASE/("comparison-"+uuid4().hex);directory.mkdir(mode=0o700)
    private(directory/"matrix.json",matrix)
    registry=Registry();adapter=BankingAdapter();bridge=Bridge(adapter.catalog,registry,mask)
    classifier,tok=classifier_guard(args.artifact,json.loads((args.artifact/"benchmark-guard.json").read_text())["calibration"])
    builder=ReviewBuilder(tok);records=[];controls=[];active={}
    from src.infra.common import run as command
    host=command(["podman","exec","breaker-substrate-control-plane","getent","hosts","host.containers.internal"],capture=True).stdout.split()[0]
    try:
        private(DIRECTORY/"deployment.json",config)
        with mlflow.start_run(run_name="diagnostic-native-"+args.execute) as run:
            mlflow.log_dict(matrix,"protocol/matrix.json")
            with ExitStack() as stack:
                store=RuntimeClient(stack.enter_context(deployment.forward("service/banking-store")),"Bearer "+token)
                service=server(registry,STORE_HOST,"0.0.0.0:8173");stack.callback(lambda:service.stop(3).wait(5))
                http=BridgeServer(("0.0.0.0",8172),bridge)
                threading.Thread(target=http.serve_forever,daemon=True).start()
                stack.callback(http.server_close);stack.callback(http.shutdown)
                configure_bridge(deployment.cluster,directory,host,8172,request_timeout=LEARNED.mcp_route)
                base=stack.enter_context(gateway_forward(deployment.cluster,directory))
                mcp=MCPClient(base,token,bridge,timeout=LEARNED.mcp_client);mcp.discover()
                stack.enter_context(native_hook(deployment.cluster,directory,host,8173))
                def reserve_guard():
                    span=mlflow.get_current_active_span()
                    budget.reserve(role="llm_guard",case_id=active["case_id"],trace_id=span.trace_id)
                client=stack.enter_context(httpx.Client(transport=ModelTransport(base,before_dispatch=reserve_guard),
                    timeout=LEARNED.reviewer,trust_env=False,follow_redirects=False))
                reviewer=ChatOpenAI(model=matrix["reviewer_model"],base_url=base+"/v1",api_key=token,http_client=client,
                    use_responses_api=True,output_version="responses/v1",max_retries=0,timeout=LEARNED.reviewer,temperature=0,max_tokens=256)
                guards={"classifier":classifier,"llm":llm_guard(reviewer,guard_id="qwen-native-reviewer-v1",reserve_model=lambda:None)}
                selected=[case for case in matrix["cases"] if case["phase"]==("guard_canary" if args.execute=="canary" else "episodes")]
                for case in selected:
                    claim_case(budget,case["case_id"],matrix);active["case_id"]=case["case_id"]
                    arm=case["case_id"].rsplit("-",1)[1]
                    native_control=case["case_id"].startswith("native-control-")
                    record=run_case(deployment=deployment,store=store,authorization="Bearer "+token,adapter=adapter,
                        bridge=bridge,mcp=mcp,budget=budget,mask=mask,task_id=case["task_id"],
                        control=(arm if native_control and arm!="unsupported" else "allow") if args.execute=="canary" else None,
                        selected_guard=classifier if arm=="unsupported" else None if native_control else guards[arm],
                        review_builder=ReviewBuilder(tok,maximum=1) if arm=="unsupported" else builder if not native_control else None,
                        case_name=case["case_id"],deadline_profile=LEARNED.name,limits=Limits(model_attempts=16,tool_attempts=24,seconds=480))
                    private(directory/(case["case_id"]+".json"),record)
                    if native_control:
                        controls.append(validate_control(record,"error" if arm=="unsupported" else arm))
                    else:records.append(record)
            result=dict(run_id=run.info.run_id,matrix_sha256=digest(matrix),records=records,controls=controls,diagnostic_only=True,
                mechanical_canary_passed=args.execute=="canary" and len(controls)==4 and validate_canary(records),
                full_admission_timing_measured=False,external_review_complete=False,native_same_input_replay_complete=False)
            private(directory/"result.json",result);mlflow.log_dict(result,"comparison/result.json")
            print(json.dumps(dict(result_path=str(directory/"result.json"),run_id=run.info.run_id,
                mechanical_canary_passed=result["mechanical_canary_passed"]),indent=2))
    except Exception as exc:
        private(directory/"failure.json",dict(error=type(exc).__name__,message=mask(str(exc)),completed_cases=[r["case_id"] for r in records]))
        raise
    finally:
        manifest=DIRECTORY/"deployment.json"
        if manifest.read_bytes()!=previous:
            if json.loads(manifest.read_text())!=config:raise RuntimeError("deployment_manifest_concurrent_change")
            manifest.write_bytes(previous)


if __name__=="__main__":main()
