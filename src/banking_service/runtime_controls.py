"""Declared actual-Actor controls, including crash/restart and evidence recovery."""
from contextlib import ExitStack
from copy import deepcopy
import json
import os
import socket
from uuid import uuid4

from dotenv import load_dotenv
import httpx
import mlflow

from src.banking_contracts.codec import ContractError,public_view
from src.banking_contracts.fixtures import argument_examples
from src.banking_service.deploy import Deployment,DIRECTORY,ROOT,LABELS
from src.banking_service.http import RuntimeClient
from src.banking_service.telemetry import SOURCE,export_outbox
from src.banking_service.validation import control,proposal,runtime_proof

EXTRA_CASES=("idempotent_replay","changed_payload","stale_state","spoofed_authority","unauthenticated_driver",
    "cross_trial_binding","fresh_actor_reset","stale_generation","store_pod_restart","mlflow_outage_outbox",
    "crash_before_commit","crash_after_commit")


def main():
    load_dotenv(ROOT/".env")
    os.environ["MLFLOW_ENABLE_ASYNC_TRACE_LOGGING"]="false"
    os.environ["MLFLOW_HTTP_REQUEST_TIMEOUT"]="5"
    os.environ["MLFLOW_HTTP_REQUEST_MAX_RETRIES"]="0"
    mlflow.set_tracking_uri(os.getenv("MLFLOW_TRACKING_URI","http://localhost:5001"))
    experiment=mlflow.set_experiment("breaker-banking-actor-service-03b")
    deployment=Deployment();authorization="Bearer "+(DIRECTORY/"runtime.token").read_text().strip()
    expected={"valid_"+name for name in argument_examples()}|set(EXTRA_CASES)
    results=[];owned={};all_trials=set()
    with mlflow.start_run(run_name="actor-service-full-runtime-controls") as run,ExitStack() as stack:
        mlflow.log_dict(dict(case_ids=sorted(expected),cases=len(expected),protocol="banking-runtime-controls-v1",
            actual_gvisor_required=True,driver="controlled-validation-only",model_calls=0,judge_calls=0,
            tool_cpu_seconds=8,tool_wall_seconds=15,financial_authorization=False,
            crash_injection="Immutable dedicated templates exit after claim or after commit; never request-controlled",
            durability="Single-writer SQLite on local PVC; no node/disk-loss or HA claim"),"protocol.json")
        for path in sorted((ROOT/"src/banking_service").glob("*.py")):mlflow.log_artifact(str(path),"implementation")
        mlflow.log_artifact(str(DIRECTORY/"deployment.json"),"runtime")
        base=stack.enter_context(deployment.forward("service/banking-store"))
        store=RuntimeClient(base,authorization)

        def step(name,fn):
            with mlflow.start_span(name=name,span_type="CHAIN") as span:
                span.set_inputs(dict(case_id=name,financial_authorization=False))
                observations=fn()
                row=dict(case_id=name,passed=True,observations=observations)
                span.set_outputs(public_view(row));trace_id=span.trace_id
            mlflow.log_feedback(trace_id=trace_id,name="runtime/passed",value=True,source=SOURCE)
            results.append(dict(row,trace_id=trace_id))

        def allocate(trial_id,fault=None):
            all_trials.add(trial_id)
            with mlflow.start_span(name="allocate_actor",span_type="CHAIN") as span:
                try:actor=deployment.create_actor(fault_stage=fault)
                finally:
                    if deployment.last_actor is not None:
                        owned[deployment.last_actor["metadata"]["name"]]=(deployment.last_actor,trial_id)
                span.set_outputs(public_view(actor))
            mlflow.log_dict(runtime_proof(deployment,actor),f"runtime/{actor['metadata']['name']}-assignment.json")
            return actor

        def actor_client(actor):
            url=stack.enter_context(deployment.forward(actor["metadata"]["name"],actor=True))
            client=RuntimeClient(url,authorization,timeout=25)
            probe=client.call("/probe",{})
            if (probe["uid"],probe["gid"],probe["effective_capabilities"],probe["no_new_privs"],probe["ambient_kubernetes_token"])!=(10001,10001,"0000000000000000","1",False):
                raise RuntimeError("Observed Actor security profile differs")
            mlflow.log_dict(probe,f"runtime/{actor['metadata']['name']}-probe.json")
            return client

        def create_trial(actor,trial_id):
            return store.call("/create",dict(trial_id=trial_id,actor_id=actor["metadata"]["name"],
                actor_uid=actor["metadata"]["uid"],user_request="Controlled synthetic runtime validation only"))

        def dispose(actor,trial_id):
            with mlflow.start_span(name="fence_delete_owned_actor",span_type="CHAIN") as span:
                fence_error=None
                try:store.call("/fence",dict(trial_id=trial_id))
                except ContractError as exc:
                    if exc.code!="unknown_owned_trial":fence_error=exc.code
                except Exception as exc:fence_error=type(exc).__name__
                deployment.delete_actor(actor["metadata"]["name"])
                owned.pop(actor["metadata"]["name"],None)
                span.set_outputs(dict(deleted_actor=actor["metadata"]["name"],uid=actor["metadata"]["uid"],fence_error=fence_error))
                if fence_error:raise RuntimeError("Owned Actor deleted but durable fencing remains incomplete")

        def reject(fn,code):
            try:fn()
            except ContractError as exc:
                if exc.code!=code:raise
                return dict(rejection=code)
            raise RuntimeError("Expected rejection did not occur")

        def invoke(client,ticket,name):
            with mlflow.start_span(name=name,span_type="TOOL") as span:
                span.set_inputs(dict(ticket=ticket,tool=name,execution_backend="substrate-gvisor"))
                result=client.call("/execute",dict(ticket=ticket))
                span.set_outputs(public_view(result))
                if result["status"]=="completed":
                    values={"execution_error":bool(result["result"]["error"]),
                        "state_changed":result["result"]["state_changed"],"executed":result["result"]["receipt"]["executed"]}
                    for field,value in values.items():
                        mlflow.log_feedback(trace_id=span.trace_id,span_id=span.span_id,name="tool/"+field,value=value,source=SOURCE)
                return result

        trial_id="trial-"+uuid4().hex
        actor=None;failed=False
        try:
            actor=allocate(trial_id);initial=create_trial(actor,trial_id);client=actor_client(actor)
            examples=argument_examples();examples["read_file"]={"file_path":"bill-december-2023.txt"}
            examples["update_scheduled_transaction"]["id"]=initial["state"]["bank_account"]["scheduled_transactions"][0]["id"]
            for name,args in examples.items():
                row=control(store,client,trial_id,name,args)
                results.append(row)
                if not row["passed"]:raise RuntimeError("Positive tool control failed")
            last=results[-1]
            before=store.call("/snapshot",dict(trial_id=trial_id))
            def replay():
                same=store.call("/prepare",dict(trial_id=trial_id,proposal=last["proposal"]))
                after=store.call("/snapshot",dict(trial_id=trial_id))
                if not same["replayed"] or same["result"]!=last["result"]["result"] or after!=before:
                    raise RuntimeError("Idempotent replay repeated or changed a committed effect")
                return dict(receipt_id=same["result"]["receipt"]["receipt_id"],state_version=after["state_version"])
            step("idempotent_replay",replay)
            changed=deepcopy(last["proposal"]);changed["arguments"]["city"]="Changed payload"
            step("changed_payload",lambda:reject(lambda:store.call("/prepare",dict(trial_id=trial_id,proposal=changed)),"action_id_conflict"))
            stale=proposal(before,"get_balance",{});stale["expected_state_version"]-=1
            step("stale_state",lambda:reject(lambda:store.call("/prepare",dict(trial_id=trial_id,proposal=stale)),"stale_state"))
            spoof=proposal(before,"get_balance",{});spoof["principal_id"]="forged"
            step("spoofed_authority",lambda:reject(lambda:store.call("/prepare",dict(trial_id=trial_id,proposal=spoof)),"invalid_runtime_request"))
            step("unauthenticated_driver",lambda:reject(lambda:RuntimeClient(base,"Bearer invalid").call("/snapshot",dict(trial_id=trial_id)),"unauthenticated"))
            trial2="trial-"+uuid4().hex;other=allocate(trial2);other_initial=create_trial(other,trial2);other_client=actor_client(other)
            def cross_trial():
                if other_initial["fingerprint"]!=initial["fingerprint"] or other_initial["fingerprint"]==before["fingerprint"]:
                    raise RuntimeError("Trials did not retain independent initial state")
                pending=store.call("/prepare",dict(trial_id=trial2,proposal=proposal(other_initial,"get_balance",{})))
                denied=reject(lambda:invoke(client,pending["ticket"],"get_balance"),"actor_identity_mismatch")
                allowed=invoke(other_client,pending["ticket"],"get_balance")
                if allowed["status"]!="completed":raise RuntimeError("Cross-trial negative lacked a healthy positive")
                return dict(**denied,positive_receipt=allowed["result"]["receipt"]["receipt_id"],isolated=True)
            step("cross_trial_binding",cross_trial)
            dispose(other,trial2)
            old_actor=actor
            def reset():
                nonlocal actor,client
                dispose(old_actor,trial_id)
                actor=allocate(trial_id);client=actor_client(actor)
                restored=store.call("/replace",dict(trial_id=trial_id,actor_id=actor["metadata"]["name"],actor_uid=actor["metadata"]["uid"]))
                if restored["fingerprint"]!=initial["fingerprint"] or restored["generation"]!=2 or restored["state_version"]!=0:
                    raise RuntimeError("Fresh-Actor reset did not restore initial state/generation")
                retained=store.call("/status",dict(trial_id=trial_id,ticket=last["ticket"]))
                if retained["result"]!=last["result"]["result"]:raise RuntimeError("Reset lost completed receipt history")
                return dict(generation=2,old_actor_uid=old_actor["metadata"]["uid"],new_actor_uid=actor["metadata"]["uid"],fingerprint=restored["fingerprint"])
            step("fresh_actor_reset",reset)
            step("stale_generation",lambda:reject(lambda:invoke(client,last["ticket"],"update_user_info"),"actor_identity_mismatch"))
            def restart_store():
                nonlocal store
                snapshot=store.call("/snapshot",dict(trial_id=trial_id))
                pod=next(p for p in deployment.cluster.get("pods","-n","breaker-banking")["items"] if p["metadata"].get("labels",{}).get("app")=="banking-store")
                if any(pod["metadata"].get("labels",{}).get(k)!=v for k,v in LABELS.items()):
                    raise RuntimeError("Refusing to restart an unowned store pod")
                deployment.cluster.kubectl("delete","pod",pod["metadata"]["name"],"-n","breaker-banking","--wait=true")
                deployment.cluster.kubectl("rollout","status","deployment/banking-store","-n","breaker-banking","--timeout=180s")
                store=RuntimeClient(stack.enter_context(deployment.forward("service/banking-store")),authorization)
                restored=store.call("/snapshot",dict(trial_id=trial_id))
                history=store.call("/status",dict(trial_id=trial_id,ticket=last["ticket"]))
                if restored!=snapshot or history["result"]!=last["result"]["result"]:raise RuntimeError("Store restart lost durable data")
                return dict(restarted_store_pod_uid=pod["metadata"]["uid"],state_preserved=True,receipt_preserved=True)
            step("store_pod_restart",restart_store)
            def mlflow_outage():
                events=store.call("/events",{})["events"]
                if not events:raise RuntimeError("No durable evidence to test outage recovery")
                uri=mlflow.get_tracking_uri();observed=False
                with socket.socket() as unavailable:
                    unavailable.bind(("127.0.0.1",0))
                    try:
                        mlflow.set_tracking_uri(f"http://127.0.0.1:{unavailable.getsockname()[1]}")
                        try:export_outbox(store,experiment.experiment_id)
                        except Exception:observed=True
                    finally:mlflow.set_tracking_uri(uri)
                if not observed or store.call("/events",{})["events"]!=events:
                    raise RuntimeError("MLflow outage lost or acknowledged durable evidence")
                return dict(export_unavailable=True,pending_events=len(events),evidence_preserved=True)
            step("mlflow_outage_outbox",mlflow_outage)
            dispose(actor,trial_id)
            for stage,case in (("after_claim","crash_before_commit"),("after_commit","crash_after_commit")):
                tid="trial-"+uuid4().hex
                fault_actor=allocate(tid,fault=stage);start=create_trial(fault_actor,tid);fault_client=actor_client(fault_actor)
                def crash(stage=stage,tid=tid,start=start,fault_client=fault_client):
                    value=proposal(start,"update_user_info",dict(city="Crash-boundary change"))
                    pending=store.call("/prepare",dict(trial_id=tid,proposal=value))
                    try:invoke(fault_client,pending["ticket"],"update_user_info")
                    except (ContractError,httpx.TransportError):pass
                    else:raise RuntimeError("Fault template did not interrupt its response")
                    result=store.call("/status",dict(trial_id=tid,ticket=pending["ticket"]))
                    actual=store.call("/snapshot",dict(trial_id=tid))
                    if stage=="after_claim":
                        if result["status"]!="executing" or result["result"] is not None or actual!=start:
                            raise RuntimeError("Uncommitted crash published an effect or fabricated a result")
                        return dict(status="unknown_execution",state_committed=False,ticket=pending["ticket"])
                    if result["status"]!="completed" or actual["state_version"]!=1 or not result["result"]["state_changed"]:
                        raise RuntimeError("Committed lost response could not be reconciled")
                    replayed=store.call("/prepare",dict(trial_id=tid,proposal=value))
                    if not replayed["replayed"] or replayed["result"]!=result["result"]:raise RuntimeError("Reconciliation repeated a write")
                    return dict(status="committed_reconciled",receipt_id=result["result"]["receipt"]["receipt_id"],state_version=1)
                step(case,crash)
                dispose(fault_actor,tid)
            if {r["case_id"] for r in results}!=expected or len(results)!=len(expected):raise RuntimeError("Runtime case matrix differs")
        except BaseException:
            failed=True
            raise
        finally:
            primary_failure=failed
            cleanup=[]
            for name,(active,tid) in list(owned.items()):
                try:dispose(active,tid)
                except Exception as exc:cleanup.append(dict(actor=name,error=type(exc).__name__))
            mlflow.log_dict(dict(errors=cleanup),"audit/cleanup.json")
            mlflow.log_dict(public_view(results),"results.json")
            try:
                exported=export_outbox(store,experiment.experiment_id)
                mlflow.log_dict(exported,"audit/outbox-readback.json")
                actual=[row for row in exported if row["trial_id"] in all_trials]
                if sum(row["kind"]=="tool_attempt" for row in actual)!=14 or sum(row["kind"]=="tool_result" for row in actual)!=13:
                    raise RuntimeError("Actual claimed/completed tool evidence differs from declared fault matrix")
            except Exception:
                failed=True
                mlflow.log_dict(dict(pending=True),"audit/outbox-incomplete.json")
            if cleanup:failed=True
            audit=[]
            for row in results:
                trace=mlflow.get_trace(row["trace_id"])
                roots=[s for s in trace.data.spans if s.parent_id is None] if trace else []
                scores=[a for a in trace.info.assessments if a.name=="runtime/passed" and a.span_id is None] if trace else []
                wanted=public_view({k:v for k,v in row.items() if k!="trace_id"})
                valid=(len(roots)==1 and roots[0].outputs==wanted and len(scores)==1 and scores[0].value is True and
                    scores[0].error is None and scores[0].source is not None and scores[0].source.source_type=="CODE" and
                    scores[0].source.source_id=="banking-actor-service-v1" and trace.info.trace_metadata.get("mlflow.sourceRun")==run.info.run_id)
                audit.append(dict(case_id=row["case_id"],trace_id=row["trace_id"],passed=valid))
            mlflow.log_dict(audit,"audit/case-trace-score-readback.json")
            if not all(row["passed"] for row in audit):failed=True
            summary=dict(run_id=run.info.run_id,cases=len(results),expected_cases=len(expected),
                full_runtime_controls_passed=not failed and len(results)==len(expected) and all(r["passed"] for r in results),
                human_acceptance="pending",model_calls=0,judge_calls=0)
            mlflow.log_dict(summary,"summary.json")
            print(json.dumps(summary),flush=True)
            if not summary["full_runtime_controls_passed"] and not primary_failure:raise RuntimeError("Incomplete runtime evidence")


if __name__=="__main__":main()
