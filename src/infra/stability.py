"""Measure owned-provider continuity without retries, recovery or inference."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from src.infra.common import ROOT, environment

FULL_WINDOW_SECONDS = 7200


def monitor(probe, path, *, seconds=FULL_WINDOW_SECONDS, interval=30,
            clock=time.monotonic, wall=time.time, wait=time.sleep):
    """A short diagnostic can never satisfy the full two-hour protocol."""
    if seconds <= 0 or interval <= 0 or interval > 60:
        raise ValueError("Invalid stability window or interval")
    start, started_at = clock(), wall()
    baseline, samples, last_wall, max_gap = None, 0, started_at, 0
    descriptor = os.open(path, os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600)
    with os.fdopen(descriptor,"w") as output:
        while True:
            now = wall()
            gap = now-last_wall
            max_gap = max(max_gap,gap)
            row = dict(at=now, elapsed_seconds=clock()-start)
            try:
                observed = probe()
                if baseline is None:baseline = observed
                if observed != baseline:
                    raise RuntimeError("provider_or_node_identity_readiness_or_version_changed")
                if gap > 2*interval+15:
                    raise RuntimeError("stability_sampling_gap")
                row.update(observed=observed,passed=True)
            except Exception as exc:
                row.update(passed=False,error=type(exc).__name__)
                output.write(json.dumps(row)+"\n");output.flush();os.fsync(output.fileno())
                raise RuntimeError("stability_probe_failed_without_recovery") from None
            output.write(json.dumps(row)+"\n");output.flush();os.fsync(output.fileno())
            samples += 1
            last_wall = now
            elapsed = clock()-start
            if elapsed >= seconds:
                return dict(scope="provider-continuity-only-not-full-stack-acceptance",
                            started_at=started_at,ended_at=wall(),elapsed_seconds=elapsed,
                            requested_seconds=seconds,samples=samples,max_sampling_gap_seconds=max_gap,
                            full_window=seconds>=FULL_WINDOW_SECONDS,passed=seconds>=FULL_WINDOW_SECONDS,
                            baseline=baseline,automatic_restarts=0,model_requests=0)
            wait(min(interval,seconds-elapsed))


def live_probe(cluster):
    def command(args):
        return subprocess.run(list(map(str,args)),capture_output=True,text=True,
                              check=True,timeout=15,env=environment()).stdout.strip()
    boot = command(["podman","machine","ssh","podman-machine-default","cat","/proc/sys/kernel/random/boot_id"])
    node_name = "breaker-substrate-control-plane"
    node = json.loads(command(["podman","inspect",node_name]))[0]
    if not node["State"].get("Running"):
        raise RuntimeError("owned_node_stopped")
    base = ["kubectl","--kubeconfig",cluster.kubeconfig,"--context",cluster.context,"--request-timeout=8s"]
    if command([*base,"get","--raw","/readyz"]) != "ok":
        raise RuntimeError("kubernetes_api_not_ready")
    nodes = json.loads(command([*base,"get","nodes","-o","json"]))["items"]
    if (len(nodes)!=1 or nodes[0]["metadata"]["name"]!=node_name or
        not any(c.get("type")=="Ready" and c.get("status")=="True" for c in nodes[0]["status"].get("conditions",[]))):
        raise RuntimeError("owned_node_not_ready")
    versions=json.loads(command(["podman","version","--format","json"]))
    client,server=versions["Client"]["Version"],versions["Server"]["Version"]
    if client!=server:
        raise RuntimeError("host_guest_podman_version_mismatch")
    return dict(guest_boot_id=boot,node_id=node["Id"],node_started_at=node["State"]["StartedAt"],
                kubernetes_node_uid=nodes[0]["metadata"]["uid"],api_ready=True,node_ready=True,
                podman_client=client,podman_server=server)


def main():
    from dotenv import load_dotenv
    import mlflow
    from mlflow.entities import AssessmentSource
    from src.infra.doctor import check_hypervisor
    from src.infra.manage import Cluster
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory",type=Path,required=True)
    parser.add_argument("--seconds",type=int,default=FULL_WINDOW_SECONDS)
    args=parser.parse_args()
    load_dotenv(ROOT/".env")
    os.environ["MLFLOW_ENABLE_ASYNC_TRACE_LOGGING"]="false"
    os.environ["MLFLOW_HTTP_REQUEST_TIMEOUT"]="5"
    os.environ["MLFLOW_HTTP_REQUEST_MAX_RETRIES"]="0"
    cluster=Cluster("breaker-substrate");cluster.ensure_owned();check_hypervisor()
    args.directory.mkdir(parents=True,exist_ok=False,mode=0o700)
    mlflow.set_experiment("breaker-infrastructure-reviews")
    run=mlflow.start_run(run_name="provider-two-hour-continuity")
    mlflow.set_tags(dict(scope="provider-continuity-only",human_acceptance="pending",github_issue="38"))
    mlflow.log_dict(dict(seconds=args.seconds,interval=30,automatic_recovery=False,model_requests=0,
                         implementation_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()),"protocol.json")
    mlflow.log_artifact(__file__,"implementation")
    trace_id=None
    summary=dict(passed=False,scope="provider-continuity-only",human_acceptance="pending")
    try:
        with mlflow.start_span(name="owned_provider_continuity",span_type="CHAIN") as span:
            span.set_inputs(dict(seconds=args.seconds,model_requests=0,automatic_restarts=0))
            trace_id=span.trace_id
            (args.directory/"started.json").write_text(json.dumps(dict(
                run_id=run.info.run_id,trace_id=trace_id,started_at=datetime.now(timezone.utc).isoformat(),seconds=args.seconds))+"\n")
            summary=monitor(lambda:live_probe(cluster),args.directory/"samples.jsonl",seconds=args.seconds)
            span.set_outputs(summary)
            if not summary["passed"]:raise RuntimeError("diagnostic_window_is_not_full_acceptance")
    except BaseException as exc:
        summary.update(passed=False,error=type(exc).__name__)
    finally:
        (args.directory/"summary.json").write_text(json.dumps(summary,indent=2)+"\n")
        mlflow.log_dict(summary,"summary.json")
        if (args.directory/"samples.jsonl").exists():mlflow.log_artifact(str(args.directory/"samples.jsonl"),"observations")
        if trace_id:
            mlflow.log_feedback(trace_id=trace_id,name="infra/provider_stable",value=summary["passed"],
                source=AssessmentSource(source_type="CODE",source_id="owned-provider-stability-v1"))
        mlflow.end_run(status="FINISHED" if summary["passed"] else "FAILED")
    mlflow.flush_trace_async_logging()
    trace=mlflow.get_trace(trace_id) if trace_id else None
    if trace is None:raise RuntimeError("stability_trace_readback_missing")
    if not any(a.name=="infra/provider_stable" and a.value is summary["passed"] for a in trace.info.assessments):
        raise RuntimeError("stability_assessment_readback_missing")
    audit=dict(run_id=run.info.run_id,trace_id=trace_id,trace_readback=True,passed=summary["passed"],scope="provider-continuity-only")
    (args.directory/"audit.json").write_text(json.dumps(audit,indent=2)+"\n")
    print(json.dumps(audit),flush=True)
    return 0 if summary["passed"] else 1


if __name__=="__main__":
    sys.exit(main())
