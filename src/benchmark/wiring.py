"""One supported wiring command: native controls, optional live three-task pilot.

No classifier training or performance claim. The first pilot uses an explicitly
deterministic native guard to test plumbing, followed by external Gemini review.
"""
import argparse
from contextlib import ExitStack
from dataclasses import asdict
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import threading
from uuid import uuid4

import mlflow
import httpx
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI

from src.agent_runtime.contracts import Limits
from src.agent_runtime.runner import run
from src.banking_service.deploy import Deployment,DIRECTORY,SPACE,STORE_HOST
from src.banking_service.http import RuntimeClient
from src.banking_service.validation import runtime_proof
from src.benchmark.bridge import Bridge,BridgeServer,MCPClient
from src.benchmark.budget import Budget,PILOT
from src.benchmark.deployment import configure_bridge,gateway_forward,native_hook,private
from src.benchmark.native import ControlGuard,Registry,server
from src.benchmark.privacy import Mask
from src.benchmark.review import build_harness_judge,review_harness
from src.feasibility.judges import build_judges,review
from src.feasibility.metrics_contract import CRITERIA,SERVICES,normalized_outcomes
from src.integrations.agentdojo.banking import BankingAdapter,TASKS

ROOT=Path(__file__).resolve().parents[2]
BASE=ROOT/".infra/benchmark-guard-harness"
SOURCE=mlflow.entities.AssessmentSource(source_type="CODE",source_id="benchmark-wiring-v1")


class ModelTransport(httpx.BaseTransport):
    """Trace exactly the gateway HTTP dispatch; no SDK retries or direct route."""
    def __init__(self,base):self.base=base;self.transport=httpx.HTTPTransport(retries=0)
    def handle_request(self,request):
        if str(request.url)!=self.base+"/v1/responses":raise RuntimeError("unexpected_model_route")
        with mlflow.start_span(name="managed_responses_http",span_type="CLIENT") as span:
            span.set_inputs(dict(url=str(request.url),method=request.method,request=json.loads(request.content)))
            from mlflow.tracing.distributed import get_tracing_context_headers_for_http_request
            request.headers.update(get_tracing_context_headers_for_http_request())
            response=self.transport.handle_request(request)
            span.set_outputs(dict(status=response.status_code,physical_attempts=1))
            return response
    def close(self):self.transport.close()


def benchmark_template(deployment):
    config=json.loads((DIRECTORY/"deployment.json").read_text())
    template=json.loads(deployment.ate("get","actor-template",config["template"],"-a",SPACE,"-o","json").stdout)
    name=config["template"]+"-benchmark-v1"
    template["metadata"]={"name":name,"atespace":SPACE}
    template["containers"][0].setdefault("env",[]).append(dict(name="BANKING_BENCHMARK_CLAIM_PATH",value="1"))
    existing=json.loads(deployment.ate("get","actor-templates","-a",SPACE,"-o","json").stdout)
    if not any(t["metadata"]["name"]==name for t in existing.get("actorTemplates",existing.get("items",[]))):
        deployment.ate("create","actor-template","-f",private(BASE/"benchmark-template.json",template))
    return config,name


def evidence(episode,result,final,actions,mask):
    initial=episode.initial_state.model_dump(mode="json")
    before=initial["bank_account"]["transactions"];after=final["bank_account"]["transactions"]
    key=secrets.token_bytes(32)
    def identities(rows):return [hmac.new(key,json.dumps(row,sort_keys=True).encode(),hashlib.sha256).hexdigest() for row in rows]
    def mentions(rows):return [[s for s in SERVICES if s in row["subject"].lower()] for row in rows]
    return mask(dict(evidence_id=episode.public.episode_id+"/observed-state",task_id=episode.task_id,
        initial_state=initial,actual_state=final,transaction_row_ids=dict(initial=identities(before),actual=identities(after)),
        transaction_service_mentions=dict(initial=mentions(before),actual=mentions(after)),actions=actions,
        final_answer=result.answer,status=result.status,execution_errors=[] if result.status=="completed" else [result.error or result.status]))


def audit_record(record):
    """Read one persisted tree; report facts, not a manufactured overall pass."""
    trace=mlflow.get_trace(record["trace_id"])
    if trace is None:raise RuntimeError("wiring_trace_missing")
    spans=trace.data.spans;ids={span.span_id for span in spans}
    if len([span for span in spans if span.parent_id is None])!=1:raise RuntimeError("wiring_trace_root_count")
    if any(span.parent_id not in ids for span in spans if span.parent_id is not None):raise RuntimeError("wiring_trace_orphan")
    gate=[span for span in spans if span.name=="substrate_native_admission"]
    tools=[span for span in spans if span.name=="banking_actor_dispatch"]
    if len(gate)!=len(record["evidence"]["actions"]) or len(tools)!=len(gate):raise RuntimeError("wiring_span_dispatch_counts_differ")
    for action in record["evidence"]["actions"]:
        if not any(span.span_id==action["span_id"] for span in tools):raise RuntimeError("action_span_ownership_missing")
    models=[span for span in spans if span.span_type=="CHAT_MODEL"]
    if len(models)!=record["model_attempts"]:raise RuntimeError("model_attempt_span_count_differs")
    physical=[span for span in spans if span.name=="managed_responses_http"]
    if record.get("guard_control") is None and len(physical)!=record["model_attempts"]:
        raise RuntimeError("physical_model_dispatch_count_differs")
    for name,value in record.get("expected_scores",{}).items():
        found=[a for a in trace.info.assessments if a.name==name and a.span_id is None]
        if (len(found)!=1 or type(found[0].value) is not type(value) or found[0].value!=value or
                found[0].source is None or found[0].source.source_type!="CODE" or found[0].source.source_id!="benchmark-wiring-v1"):
            raise RuntimeError("wiring_score_value_or_ownership_differs")
    return dict(trace_id=trace.info.trace_id,span_count=len(spans),chat_model_spans=len(models),
        managed_responses_dispatches=len(physical),
        native_admission_spans=len(gate),actor_dispatch_spans=len(tools),root_count=1,orphan_count=0,
        span_types=sorted({span.span_type or "UNKNOWN" for span in spans}),
        span_names=[span.name for span in spans])


def run_case(*,deployment,store,authorization,adapter,bridge,mcp,budget,mask,task_id,control=None):
    case_id=("control-"+control if control else "live-"+task_id)
    trial_id="benchmark-"+uuid4().hex
    actor=None;record=None;cleanup=[]
    with mlflow.start_run(run_name=case_id,nested=True) as child:
        with mlflow.start_span(name="benchmark_episode",span_type="AGENT") as root:
            root.set_inputs(dict(case_id=case_id,task_id=task_id,live=control is None,guard="deterministic-native-"+(control or "allow")))
            try:
                with mlflow.start_span(name="allocate_substrate_actor",span_type="CHAIN") as allocation:
                    actor=deployment.create_actor();allocation.set_outputs(actor)
                proof=runtime_proof(deployment,actor)
                episode=adapter.episode(task_id,trial_id)
                snapshot=store.call("/create",dict(trial_id=trial_id,actor_id=actor["metadata"]["name"],
                    actor_uid=actor["metadata"]["uid"],user_request=episode.public.prompt))
                if snapshot["state"]!=episode.initial_state.model_dump(mode="json"):raise RuntimeError("suite_backend_initial_state_differs")
                mask.learn(snapshot["state"])
                with deployment.forward(actor["metadata"]["name"],actor=True) as base:
                    actor_client=RuntimeClient(base,authorization,timeout=40)
                    probe=actor_client.call("/probe",{})
                    if (probe["uid"],probe["gid"],probe["effective_capabilities"],probe["no_new_privs"],probe["ambient_kubernetes_token"])!=(10001,10001,"0000000000000000","1",False):
                        raise RuntimeError("actor_runtime_probe_differs")
                    bridge.configure(store,actor_client,trial_id,ControlGuard(control or "allow"))
                    if control:
                        reference=list(episode.task.ground_truth(episode.initial_state))[-1]
                        arguments=dict(reference.args)
                        # Canonical transport forbids upstream binary float amounts.
                        if isinstance(arguments.get("amount"),float):arguments["amount"]=str(arguments["amount"])
                        arguments=adapter.catalog.validate_arguments(reference.function,arguments)
                        model=FakeMessagesListChatModel(responses=[AIMessage(content="",tool_calls=[dict(id="control-call",name=reference.function,args=arguments)]),AIMessage(content="Control finished.")])
                        reserve=lambda:None
                    else:
                        definitions=[dict(type="function",function=dict(name=name,description=f"Pinned synthetic banking tool: {name}.",
                            parameters=schema["arguments"])) for name,schema in adapter.catalog.schemas().items()]
                        model_http=httpx.Client(transport=ModelTransport(mcp.base),timeout=45,trust_env=False)
                        model=ChatOpenAI(model=os.environ["LM_STUDIO_MODEL"],base_url=mcp.base+"/v1",api_key=authorization.removeprefix("Bearer "),
                            http_client=model_http,use_responses_api=True,output_version="responses/v1",max_retries=0,timeout=45,
                            temperature=0,max_tokens=2048).bind_tools(definitions,parallel_tool_calls=False)
                        def reserve():
                            active=mlflow.get_current_active_span()
                            entry=budget.reserve(role="actor",case_id=task_id,trace_id=active.trace_id)
                            store.call("/client-event",dict(trial_id=trial_id,kind="model_attempt",payload=entry))
                    try:
                        result=run(episode.public,model=model,execute=mcp.execute,reserve_model=reserve,limits=Limits(model_attempts=6,tool_attempts=12,seconds=180))
                    finally:
                        if not control:model_http.close()
                    final=store.call("/snapshot",dict(trial_id=trial_id))
                    measured=adapter.evaluate(episode,result,final["state"])
                    observed=evidence(episode,result,final["state"],bridge.actions,mask)
                    normalized=normalized_outcomes(dict(evidence=observed,inputs=dict(task_id=task_id),expectations=dict(reference_id=task_id)))
                    events=store.call("/trial-events",dict(trial_id=trial_id))["events"]
                    record=mask(dict(case_id=case_id,task_id=task_id,trial_id=trial_id,trace_id=root.trace_id,child_run_id=child.info.run_id,
                        experiment_id=child.info.experiment_id,inputs=dict(task_id=task_id),expectations=dict(reference_id=f"{measured['source_commit']}/{task_id}/upstream-checkers"),
                        evidence=observed,measured=dict(measured,**normalized),status=result.status,model_attempts=result.model_attempts,
                        tool_attempts=result.tool_attempts,runtime_proof=proof,sandbox_probe=probe,store_events=events,
                        initial_fingerprint=snapshot["fingerprint"],final_fingerprint=final["fingerprint"],guard_control=control))
                    root.set_outputs(record)
            finally:
                actor=actor or deployment.last_actor
                if actor:
                    with mlflow.start_span(name="cleanup_substrate_actor",span_type="CHAIN") as span:
                        span.set_inputs(dict(trial_id=trial_id,actor=actor["metadata"]["name"]))
                        try:store.call("/fence",dict(trial_id=trial_id))
                        except Exception as exc:cleanup.append(dict(stage="fence",error=type(exc).__name__))
                        try:deployment.delete_actor(actor["metadata"]["name"])
                        except Exception as exc:cleanup.append(dict(stage="delete",error=type(exc).__name__))
                        span.set_outputs(dict(errors=cleanup,deleted=not cleanup))
        if record is not None:
            record["cleanup_errors"]=cleanup
            scores=dict(completed=record["status"]=="completed",status=record["status"],
                utility=record["measured"]["utility"],model_attempts=record["model_attempts"],tool_attempts=record["tool_attempts"],
                selected_attack_goal_reached=record["measured"]["selected_attack_goal_reached"],
                forbidden_recipient_transfer=record["measured"]["forbidden_recipient_transfer"])
            record["expected_scores"]={"wiring/"+name:value for name,value in scores.items() if value is not None}
            for name,value in scores.items():
                if value is None:continue
                mlflow.log_feedback(trace_id=record["trace_id"],name="wiring/"+name,value=value,source=SOURCE)
            for action in record["evidence"]["actions"]:
                gate=action.get("guard")
                if gate:
                    for name,value in {"guard/decision":gate["decision"],"guard/input_digest":gate["input_digest"]}.items():
                        mlflow.log_feedback(trace_id=record["trace_id"],span_id=gate["span_id"],name=name,value=value,source=SOURCE)
                if action.get("execution_receipt"):
                    mlflow.log_feedback(trace_id=record["trace_id"],span_id=action["span_id"],name="tool/executed",value=action["execution_receipt"]["executed"],source=SOURCE)
            mlflow.log_dict(record,"wiring/episode.json")
            record["trace_audit"]=audit_record(record)
            mlflow.log_dict(record["trace_audit"],"wiring/trace-audit.json")
        if cleanup:raise RuntimeError("benchmark_cleanup_incomplete")
        return record


def validate_control(record,decision):
    events=record["store_events"]
    attempts=sum(event["kind"]=="tool_attempt" for event in events)
    expected=int(decision=="allow")
    if attempts!=expected:raise RuntimeError("native_control_tool_dispatch_count_differs")
    changed=record["initial_fingerprint"]!=record["final_fingerprint"]
    if changed!=(decision=="allow"):raise RuntimeError("native_control_state_effect_differs")
    if record["status"]!={"allow":"completed","block":"blocked","error":"error"}[decision]:
        raise RuntimeError("native_control_terminal_status_differs")
    return dict(case_id=record["case_id"],trace_id=record["trace_id"],decision=decision,
        store_tool_attempts=attempts,state_changed=changed,actions=record["evidence"]["actions"],trace_audit=record["trace_audit"])


def suite_observations(controls,records,mask,*,failure=None):
    return mask(dict(controls=controls,episodes=[dict(task_id=r["task_id"],trace_id=r["trace_id"],
        status=r["status"],model_attempts=r["model_attempts"],tool_attempts=r["tool_attempts"],evidence=r["evidence"],
        store_events=r["store_events"],runtime_proof=r["runtime_proof"],trace_audit=r["trace_audit"],cleanup_errors=r["cleanup_errors"]) for r in records],
        failure=failure))


def external_suite_review(observations,model,budget):
    with mlflow.start_span(name="persisted_suite_evidence",span_type="CHAIN") as suite:
        suite.set_inputs(dict(protocol=PILOT));suite.set_outputs(observations);suite_id=suite.trace_id
    persisted=mlflow.get_trace(suite_id)
    if persisted is None:raise RuntimeError("external_review_evidence_not_persisted")
    root=next(s for s in persisted.data.spans if s.parent_id is None)
    return review_harness(build_harness_judge(model),observations=root.outputs,target_trace_id=suite_id,
        reserve=lambda **kw:budget.reserve(case_id="suite",**kw))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live",action="store_true",help="Spend the frozen initial local pilot and authorized Gemini review requests")
    parser.add_argument("--image",help="Deploy a newly built digest-bound banking image before controls")
    args=parser.parse_args()
    from dotenv import load_dotenv
    load_dotenv(ROOT/".env")
    os.environ["MLFLOW_ENABLE_ASYNC_TRACE_LOGGING"]="false"
    os.environ["MLFLOW_HTTP_REQUEST_MAX_RETRIES"]="0"
    os.environ["MLFLOW_HTTP_REQUEST_TIMEOUT"]="10"
    mlflow.set_tracking_uri(os.environ.get("MLFLOW_TRACKING_URI","http://localhost:5001"))
    experiment=mlflow.set_experiment("breaker-banking-target-agent")
    mlflow.langchain.autolog();mlflow.openai.autolog(disable=True)
    mask=Mask([os.getenv(key) for key in ("GEMINI_API_KEY","GOOGLE_API_KEY","OPENAI_API_KEY")])
    mlflow.tracing.configure(span_processors=[mask.span_processor])
    deployment=Deployment()
    if args.image:
        if "@sha256:" not in args.image:raise ValueError("digest_bound_image_required")
        deployment.setup(args.image)
    else:deployment.refresh_credentials()
    original_config,template=benchmark_template(deployment)
    config=dict(original_config,template=template)
    # create_actor reads its existing manifest; use an explicit subclass-free
    # local override only while this owned command runs, then restore it.
    manifest=DIRECTORY/"deployment.json";previous=manifest.read_bytes()
    native_directory=BASE/("run-"+uuid4().hex)
    native_directory.mkdir(mode=0o700)
    private(native_directory/"pilot.json",PILOT)
    budget=Budget(BASE/"combined-budget")
    token=(DIRECTORY/"runtime.token").read_text().strip();mask.secrets.add(token)
    registry=Registry();adapter=BankingAdapter();bridge=Bridge(adapter.catalog,registry,mask)
    from src.infra.common import run as command
    host_ip=command(["podman","exec","breaker-substrate-control-plane","getent","hosts","host.containers.internal"],capture=True).stdout.split()[0]
    records=[];controls=[];reviews=[];failure=None;parent_id=None;attempted_controls=[]
    try:
        private(manifest,config)
        with mlflow.start_run(run_name="benchmark-wiring-live" if args.live else "benchmark-wiring-controls") as parent:
            parent_id=parent.info.run_id
            mlflow.log_dict(PILOT,"protocol/pilot.json")
            with ExitStack() as stack:
                store_base=stack.enter_context(deployment.forward("service/banking-store"))
                store=RuntimeClient(store_base,"Bearer "+token)
                service=server(registry,STORE_HOST,"0.0.0.0:8173")
                stack.callback(lambda:service.stop(3).wait(5))
                bridge_server=BridgeServer(("0.0.0.0",8172),bridge)
                thread=threading.Thread(target=bridge_server.serve_forever,daemon=True);thread.start()
                stack.callback(bridge_server.server_close);stack.callback(bridge_server.shutdown)
                configure_bridge(deployment.cluster,native_directory,host_ip,8172)
                base=stack.enter_context(gateway_forward(deployment.cluster,native_directory))
                mcp=MCPClient(base,token,bridge)
                tools=mcp.discover()
                mlflow.log_dict(mask(tools),"protocol/discovered-tools.json")
                stack.enter_context(native_hook(deployment.cluster,native_directory,host_ip,8173))
                for decision in ("allow","block","error"):
                    record=run_case(deployment=deployment,store=store,authorization="Bearer "+token,adapter=adapter,
                        bridge=bridge,mcp=mcp,budget=budget,mask=mask,task_id="user_task_0",control=decision)
                    private(native_directory/("control-"+decision+".json"),record)
                    attempted_controls.append(record)
                    controls.append(validate_control(record,decision))
                if args.live:
                    for task_id in TASKS:
                        record=run_case(deployment=deployment,store=store,authorization="Bearer "+token,adapter=adapter,
                            bridge=bridge,mcp=mcp,budget=budget,mask=mask,task_id=task_id)
                        records.append(record);private(native_directory/(task_id+".json"),record)
                        if record["status"]!="completed":raise RuntimeError("live_wiring_case_not_completed")
            mlflow.log_dict(dict(controls=controls,records=records),"wiring/persisted-cases.json")
            if args.live:
                model=os.getenv("MLFLOW_GENAI_JUDGE_DEFAULT_MODEL","gemini:/gemini-2.5-flash")
                judges=build_judges(model)
                for record in records:
                    for criterion,judge in judges.items():
                        budget.reserve(role="gemini_task_judge",case_id=record["task_id"],trace_id=record["trace_id"],request=dict(criterion=criterion,model=model))
                        reviews.append(review(judge,criterion,record))
                verdict=external_suite_review(suite_observations(controls,records,mask),model,budget)
                reviews.append(verdict)
                mlflow.log_dict(reviews,"review/external-gemini.json")
            result=dict(run_id=parent_id,experiment_id=experiment.experiment_id,controls=controls,
                episodes=[dict(task_id=r["task_id"],status=r["status"],trace_id=r["trace_id"],utility=r["measured"]["utility"]) for r in records],
                external_reviews=reviews,claims=dict(trained_classifier=False,performance=False,human_acceptance=False))
            private(native_directory/"result.json",result);mlflow.log_dict(result,"wiring/result.json")
            print(json.dumps(result,indent=2))
    except Exception as exc:
        failure=dict(error=type(exc).__name__,message=mask(str(exc)),run_id=parent_id,completed_cases=[r["task_id"] for r in records])
        private(native_directory/"failure.json",failure)
        # Keep the execution run FAILED; a separate review does not turn it green.
        # No acting-agent rerun is needed to obtain an external view of a fault.
        if args.live and (records or attempted_controls):
            with mlflow.start_run(run_name="external-review-failed-wiring"):
                observations=suite_observations(controls,records,mask,failure=failure)
                if not controls:observations["attempted_native_controls"]=mask(attempted_controls)
                verdict=external_suite_review(observations,os.getenv("MLFLOW_GENAI_JUDGE_DEFAULT_MODEL","gemini:/gemini-2.5-flash"),budget)
                private(native_directory/"external-failure-review.json",verdict)
                mlflow.log_dict(verdict,"review/external-failure-review.json")
        raise
    finally:
        if manifest.read_bytes()!=previous:
            if json.loads(manifest.read_text())!=config:raise RuntimeError("deployment_manifest_concurrent_change")
            manifest.write_bytes(previous)


if __name__=="__main__":main()
