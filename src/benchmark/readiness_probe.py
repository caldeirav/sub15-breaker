"""Frozen non-effectful Actor readiness observations; never run models or banking tools."""
import argparse
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import re
from time import perf_counter_ns

from src.banking_service.deploy import Deployment,DIRECTORY
from src.banking_service.http import RuntimeClient
from src.banking_service.diagnostics import RuntimeCallError
from src.banking_service.validation import runtime_proof
from src.benchmark.capacity import history_snapshot
from src.benchmark.deployment import native_hook,private
from src.benchmark.native import Registry,server
from src.benchmark.privacy import Mask
from src.infra.common import ROOT,STATE,run
from src.integrations.agentdojo.inventory import digest

FILES=["src/banking_service/http.py","src/banking_service/diagnostics.py","src/banking_service/app.py","src/banking_service/auth.py",
    "src/banking_service/deploy.py","src/benchmark/readiness_probe.py","src/benchmark/native.py","src/benchmark/deployment.py"]


def hashes():return {name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in FILES}


def exclusive(path,value):
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,"w") as stream:stream.write(json.dumps(value,indent=2)+"\n")


def freeze(directory):
    config=json.loads((DIRECTORY/"deployment.json").read_text())
    plan=dict(schema_version="actor-readiness-probes-v1",source_hashes=hashes(),image=config["image"],deployment_sha256=digest(config),
        actors=4,readiness_observations_per_actor=2,driver_timeout_seconds=15,actor_store_timeout_seconds=5,
        native_hook_timeout_seconds=2,model_requests=0,trial_creates=0,tools_called=0,automatic_retries=0,
        note="Fixed first/subsequent non-effectful observations, not hidden model warmups or retry-until-green.")
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=False)
    exclusive(directory/"plan.json",plan);return plan


def capture_logs(deployment,directory,mask,actor=None):
    targets=[("ate-system","deployment/atenet-egress"),("breaker-banking","deployment/banking-store")]
    if actor:
        assignment=actor.get("status",{}).get("workerAssignment",{})
        if assignment.get("workerPod"):targets.append((assignment["workerNamespace"],assignment["workerPod"]))
    records=[]
    for namespace,target in targets:
        try:
            text=deployment.cluster.kubectl("logs",target,"-n",namespace,"--all-containers","--since=10m","--tail=2000",capture=True).stdout
            text=mask(re.sub(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+","[WITHHELD_JWT]",text))
            path=Path(directory)/(namespace+"-"+target.replace("/","-")+".log");path.write_text(text);path.chmod(0o600)
            records.append(dict(namespace=namespace,target=target,path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
        except Exception as exc:records.append(dict(namespace=namespace,target=target,error=type(exc).__name__))
    private(Path(directory)/"log-capture.json",records)


def execute(directory):
    directory=Path(directory);plan=json.loads((directory/"plan.json").read_text());config=json.loads((DIRECTORY/"deployment.json").read_text())
    if plan["source_hashes"]!=hashes() or plan["deployment_sha256"]!=digest(config):raise RuntimeError("readiness_probe_binding_changed")
    exclusive(directory/"started.json",dict(plan_sha256=digest(plan),automatic_retries=0))
    d=Deployment();d.verify_deployment(config);d.refresh_credentials()
    token=(DIRECTORY/"runtime.token").read_text().strip();mask=Mask([token,(DIRECTORY/"platform.token").read_text().strip()])
    ledger=STATE/"benchmark-guard-harness/combined-budget"
    def entries():return [json.loads(p.read_text()) for p in sorted(ledger.glob("attempt-*.json"))]
    before_entries=entries();before_history=history_snapshot(d)
    host=run(["podman","exec","breaker-substrate-control-plane","getent","hosts","host.containers.internal"],capture=True).stdout.split()[0]
    registry=Registry();observations=[];cleanups=[]
    try:
        with ExitStack() as stack:
            store=RuntimeClient(stack.enter_context(d.forward("service/banking-store")),"Bearer "+token,boundary="driver_to_store")
            before_capacity=store.call("/capacity",{});private(directory/"capacity-before.json",before_capacity)
            actors=json.loads(d.ate("get","actors","-a","breaker-banking","-o","json").stdout)
            if actors.get("actors",actors.get("items",[])):raise RuntimeError("readiness_probe_requires_no_existing_actors")
            grpc=server(registry,"banking-store.breaker-banking.svc.cluster.local","0.0.0.0:8173");stack.callback(lambda:grpc.stop(3).wait(5))
            with native_hook(d.cluster,directory,host,8173,timeout_seconds=plan["native_hook_timeout_seconds"]):
                try:
                    for index in range(plan["actors"]):
                        case=f"readiness-actor-{index+1:02d}";exclusive(directory/(case+"-started.json"),dict(case_id=case))
                        actor=None;deleted=False
                        try:
                            actor=d.create_actor();runtime=runtime_proof(d,actor)
                            private(directory/(case+"-runtime.json"),dict(actor_id=actor["metadata"]["name"],actor_uid=actor["metadata"]["uid"],sandbox_class=runtime["status"]["workerAssignment"]["sandboxRuntime"]["sandboxClass"]))
                            with d.forward(actor["metadata"]["name"],actor=True) as base:
                                client=RuntimeClient(base,"Bearer "+token,timeout=plan["driver_timeout_seconds"],boundary="driver_to_actor")
                                probe=client.call("/probe",{})
                                if (probe["uid"],probe["gid"],probe["effective_capabilities"],probe["no_new_privs"],probe["ambient_kubernetes_token"])!=(10001,10001,"0000000000000000","1",False):raise RuntimeError("readiness_sandbox_probe_differs")
                                for sample in range(plan["readiness_observations_per_actor"]):
                                    started=perf_counter_ns();row=dict(case_id=case,sample=sample,first_actor_store_observation=sample==0)
                                    try:
                                        value=client.call("/admission-readiness",{})
                                        correct=(value.get("actor_id"),value.get("actor_uid"),value.get("ticket_lifetime_seconds"))==(actor["metadata"]["name"],actor["metadata"]["uid"],900)
                                        row.update(status="ready" if correct else "identity_or_profile_mismatch",identity_verified=correct,
                                            driver_transport=client.last_diagnostics,actor_transport=value.get("readiness_transport"))
                                    except RuntimeCallError as exc:row.update(status="transport_failure",error_code=exc.code,transport=exc.transport)
                                    except Exception as exc:row.update(status="error",error=type(exc).__name__)
                                    row["elapsed_ns"]=perf_counter_ns()-started;observations.append(row)
                                    private(directory/"observations.json",observations)
                                    print(json.dumps(dict(case_id=case,sample=sample,status=row["status"])),flush=True)
                                    if row["status"]!="ready":
                                        failure_dir=directory/(case+f"-sample-{sample}-pre-restoration");failure_dir.mkdir()
                                        capture_logs(d,failure_dir,mask,actor)
                        finally:
                            actor=actor or d.last_actor
                            if actor:
                                d.delete_actor(actor["metadata"]["name"]);deleted=True
                            cleanups.append(dict(case_id=case,actor_deleted=deleted));private(directory/"cleanup.json",cleanups)
                finally:
                    logs=directory/"pre-restoration";logs.mkdir();capture_logs(d,logs,mask)
            after_capacity=store.call("/capacity",{});private(directory/"capacity-after.json",after_capacity)
            if before_capacity!=after_capacity:raise RuntimeError("readiness_probe_mutated_store_capacity")
        after_entries=entries();after_history=history_snapshot(d)
        if before_entries!=after_entries or before_history!=after_history or registry.entries:raise RuntimeError("readiness_probe_unexpected_effect")
        actors=json.loads(d.ate("get","actors","-a","breaker-banking","-o","json").stdout)
        if actors.get("actors",actors.get("items",[])):raise RuntimeError("readiness_probe_actor_cleanup_incomplete")
        cm=d.cluster.get("configmap","atenet-egress","-n","ate-system")
        if cm["data"]!=json.loads((directory/"native-original-configmap.json").read_text())["data"]:raise RuntimeError("readiness_probe_hook_restore_differs")
        result=dict(schema_version="actor-readiness-probe-result-v1",plan_sha256=digest(plan),observations=len(observations),
            ready=sum(o["status"]=="ready" for o in observations),failures=sum(o["status"]!="ready" for o in observations),
            fixed_batch_complete=len(observations)==8,model_tool_judge_requests=0,trial_creates=0,history_ledger_capacity_unchanged=True,
            no_actors_remaining=True,hook_restored=True,historical_cause_established=False,demo_rehearsal_complete=False,
            source_hashes={str(p.resolve()):hashlib.sha256(p.read_bytes()).hexdigest() for p in directory.rglob("*.json")})
        private(directory/"result.json",result);return result
    except Exception as exc:
        private(directory/"failure.json",dict(error=type(exc).__name__,observations=len(observations),readiness_probe_only=True))
        raise


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("directory",type=Path)
    action=p.add_mutually_exclusive_group(required=True);action.add_argument("--freeze",action="store_true");action.add_argument("--execute",action="store_true")
    args=p.parse_args();value=freeze(args.directory) if args.freeze else execute(args.directory);print(json.dumps(value,indent=2))


if __name__=="__main__":main()
