"""CODE-only actual-Actor controls; live-model budget is an explicit separate option."""
import argparse
from copy import deepcopy
import hashlib
import json
import os
import sys
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv
import mlflow

from src.banking_contracts.codec import ContractError, public_view
from src.banking_contracts.fixtures import argument_examples
from src.banking_service.deploy import Deployment, DIRECTORY, ROOT, SPACE
from src.banking_service.http import RuntimeClient
from src.banking_service.telemetry import SOURCE, export_outbox


def runtime_proof(deployment, actor):
    # Platform-observed assignment, runtime and actual worker process evidence
    # are required together; a desired sandbox class alone cannot pass.
    metadata,status=actor["metadata"],actor.get("status",{})
    assignment=status.get("workerAssignment",{})
    runtime=assignment.get("sandboxRuntime",{})
    if status.get("state")!="ACTOR_STATE_RUNNING" or runtime.get("sandboxClass")!="gvisor":
        raise RuntimeError("Actor is not observed running under gVisor")
    worker=deployment.cluster.get("pod",assignment["workerPod"],"-n",assignment["workerNamespace"])
    if worker["metadata"]["uid"]!=assignment["workerPodUid"]:
        raise RuntimeError("Assigned worker UID differs from observed pod")
    logs=deployment.cluster.kubectl("logs",assignment["workerPod"],"-n",assignment["workerNamespace"],"--tail=300",capture=True).stdout
    messages=[]
    for line in logs.splitlines():
        try: item=json.loads(line)
        except ValueError: continue
        if item.get("labels",{}).get("ate.actor.uid")==metadata["uid"]:messages.append(item)
    if not any("gVisor" in str(item.get("message","")) for item in messages):
        raise RuntimeError("Missing Actor-UID-correlated actual gVisor runtime log")
    proof=dict(actor=public_view(actor),status=status,worker=dict(metadata=worker["metadata"],spec=worker["spec"],status=worker["status"]),
        actor_runtime_logs=messages)
    return proof


def proposal(snapshot,name,args,action_id=None):
    action_id=action_id or "action-"+uuid4().hex
    return dict(schema_version="banking-action-v1",action_id=action_id,idempotency_key=action_id,
        expected_context_version=snapshot["context"]["context_version"],expected_actor_generation=snapshot["generation"],
        expected_state_version=snapshot["state_version"],tool_name=name,arguments=args)


def control(store,actor,trial_id,name,args):
    with mlflow.start_span(name="actor_"+name,span_type="TOOL") as span:
        snapshot=store.call("/snapshot",dict(trial_id=trial_id))
        value=proposal(snapshot,name,args)
        span.set_inputs(public_view(dict(trial_id=trial_id,proposal=value)))
        prepared=store.call("/prepare",dict(trial_id=trial_id,proposal=value))
        result=actor.call("/execute",dict(ticket=prepared["ticket"]))
        output=dict(case_id="valid_"+name,ticket=prepared["ticket"],result=result,proposal=value,
            passed=result["status"]=="completed" and result["result"]["error"] is None and
                result["result"]["receipt"]["executed"] is True and result["result"]["receipt"]["fixture_only"] is False)
        span.set_outputs(public_view(output));trace_id=span.trace_id
    mlflow.log_feedback(trace_id=trace_id,name="runtime/passed",value=output["passed"],source=SOURCE)
    for field,value in {"execution_error":bool(result["result"]["error"]),
                        "state_changed":result["result"]["state_changed"],"executed":result["result"]["receipt"]["executed"]}.items():
        mlflow.log_feedback(trace_id=trace_id,span_id=span.span_id,name="tool/"+field,value=value,source=SOURCE)
    output["trace_id"]=trace_id
    return output


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    args=parser.parse_args()
    load_dotenv(ROOT/".env")
    os.environ["MLFLOW_ENABLE_ASYNC_TRACE_LOGGING"]="false"
    os.environ["MLFLOW_HTTP_REQUEST_TIMEOUT"]="10"
    mlflow.set_tracking_uri(os.getenv("MLFLOW_TRACKING_URI","http://localhost:5001"))
    experiment=mlflow.set_experiment("breaker-banking-actor-service-03b")
    deployment=Deployment()
    authorization="Bearer "+(DIRECTORY/"runtime.token").read_text().strip()
    with mlflow.start_run(run_name="actor-runtime-controls") as run:
        mlflow.set_tags(dict(scope="actual-Actor-controlled-tools-only",human_acceptance="pending",financial_authorization="false"))
        mlflow.log_dict(dict(tools=list(argument_examples()),new_model_calls=0,banking_tools="actual-substrate-Actor",
            gateway_enforcement=False,tool_cpu_seconds=8,tool_wall_seconds=15,expected_cases=11,
            protocol="all11-positive-runtime-canary-v2; bounded cold imports; not full03bacceptance"),"protocol.json")
        for path in sorted((ROOT/"src/banking_service").glob("*.py")):mlflow.log_artifact(str(path),"implementation")
        with deployment.forward("service/banking-store") as base:
            store=RuntimeClient(base,authorization)
            actor=None;trial_id="trial-"+uuid4().hex
            results=[]
            try:
                with mlflow.start_span(name="allocate_resume_actor",span_type="CHAIN") as span:
                    actor=deployment.create_actor()
                    span.set_outputs(public_view(actor))
                mlflow.log_dict(runtime_proof(deployment,actor),"runtime/platform-assignment.json")
                store.call("/create",dict(trial_id=trial_id,actor_id=actor["metadata"]["name"],
                    actor_uid=actor["metadata"]["uid"],user_request="Controlled synthetic tool validation only"))
                with deployment.forward(actor["metadata"]["name"],actor=True) as actor_base:
                    actor_client=RuntimeClient(actor_base,authorization)
                    probe=actor_client.call("/probe",{})
                    mlflow.log_dict(probe,"runtime/sandbox-probe.json")
                    if probe["uid"]!=10001 or probe["gid"]!=10001 or probe["no_new_privs"]!="1" or int(probe["effective_capabilities"],16)!=0 or probe["ambient_kubernetes_token"]:
                        raise RuntimeError("Actor user/capability/ambient-credential check failed")
                    examples=argument_examples()
                    snapshot=store.call("/snapshot",dict(trial_id=trial_id))
                    examples["read_file"]={"file_path":"bill-december-2023.txt"}
                    examples["update_scheduled_transaction"]["id"]=snapshot["state"]["bank_account"]["scheduled_transactions"][0]["id"]
                    for name,args in examples.items():
                        row=control(store,actor_client,trial_id,name,args)
                        results.append(row)
                        if not row["passed"]:raise RuntimeError("A declared positive Actor control failed")
            except Exception as exc:
                mlflow.log_dict(dict(stage="actor-runtime-controls",error=type(exc).__name__),"error.json")
                raise
            finally:
                primary_failure = sys.exc_info()[0] is not None
                cleanup_errors = []
                mlflow.log_dict(public_view(results),"results.json")
                actor = actor or deployment.last_actor
                if actor is not None:
                    with mlflow.start_span(name="cleanup_actor",span_type="CHAIN") as span:
                        try:
                            store.call("/fence",dict(trial_id=trial_id))
                        except ContractError as exc:
                            if exc.code!="unknown_owned_trial":cleanup_errors.append(dict(stage="fence",error=exc.code))
                        except Exception as exc:
                            cleanup_errors.append(dict(stage="fence",error=type(exc).__name__))
                        # A store outage must not prevent the separate owned-UID
                        # lifecycle cleanup attempt or hide the original failure.
                        try:
                            deployment.delete_actor(actor["metadata"]["name"])
                            span.set_outputs(dict(deleted_actor=actor["metadata"]["name"],uid=actor["metadata"]["uid"]))
                        except Exception as exc:
                            cleanup_errors.append(dict(stage="actor_delete",error=type(exc).__name__,
                                actor_id=actor["metadata"]["name"],actor_uid=actor["metadata"]["uid"]))
                try:
                    exported=export_outbox(store,experiment.experiment_id)
                    mlflow.log_dict(exported,"audit/outbox-readback.json")
                except Exception as exc:
                    cleanup_errors.append(dict(stage="outbox_export",error=type(exc).__name__,pending=True))
                mlflow.log_dict(dict(errors=cleanup_errors,primary_failure_preserved=primary_failure),"audit/cleanup.json")
                if cleanup_errors and not primary_failure:raise RuntimeError("Cleanup/export incomplete; acceptance blocked")
        mlflow.log_dict(dict(run_id=run.info.run_id,cases=len(results),passed=len(results)==11 and all(r["passed"] for r in results),
            human_acceptance="pending",scope="positive-runtime-canary-only"),"summary.json")
        print(json.dumps(dict(run_id=run.info.run_id,cases=len(results),passed=all(r["passed"] for r in results))))


if __name__=="__main__":main()
