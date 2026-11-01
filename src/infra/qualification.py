"""Fail-closed readback of the tested local target stack; never generates text."""
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

from src.infra.common import ROOT, STATE, VERSIONS
from src.infra.target_stack import DIRECTORY,current_bindings,private,require


def fresh_json(path):
    require(path.is_file(),"required_qualification_evidence_missing: "+path.name)
    age=time.time()-path.stat().st_mtime
    require(0<=age<=86400,"qualification_evidence_stale_or_future_dated: "+path.name)
    return json.loads(path.read_text())


def current_guest_os():
    status=json.loads(subprocess.check_output(["podman","machine","ssh","podman-machine-default","rpm-ostree status --json"],text=True,timeout=15))
    booted=[d for d in status.get("deployments",[]) if d.get("booted") is True]
    require(len(booted)==1,"cannot_identify_one_booted_guest_image")
    item=booted[0];reference=item.get("container-image-reference","")
    require(item.get("version")==VERSIONS["machine_os_version"] and reference=="ostree-unverified-image:docker://"+VERSIONS["machine_os_image"],"booted_guest_image_differs_from_reviewed_digest")
    return dict(version=item["version"],reference=reference,image_integrity="HTTPS-and-OCI-digest; no separate image signature attestation")


def verify_current(cluster, *, stability_directory, runtime_run_id):
    import mlflow
    from mlflow import MlflowClient
    from src.banking_service.deploy import Deployment,DIRECTORY as BANKING
    from src.banking_service.telemetry import SOURCE
    from src.banking_contracts.codec import public_view
    from src.infra.serving_probe import verify_evidence
    from src.infra.stability import FULL_WINDOW_SECONDS
    started=time.monotonic()
    client=MlflowClient()
    profile,loaded,protocol,stable=verify_evidence(cluster,stability_directory)
    serving=fresh_json(DIRECTORY/"latest-serving-audit.json")
    require(serving.get("passed") is True and serving["profile_sha256"]==profile["profile_sha256"],"local_serving_proof_missing_or_different_profile")
    require(client.get_run(serving["run_id"]).info.status=="FINISHED","serving_run_not_finished")
    expected_bindings=fresh_json(DIRECTORY/"qualified-bindings.json")
    require(current_bindings(cluster,profile)==expected_bindings,"gateway_objects_changed_since_qualification")
    require(hashlib.sha256((DIRECTORY/"resources.json").read_bytes()).hexdigest()==profile["profile_sha256"],"qualified_manifest_changed")
    for name,scope in [("readiness.json","infrastructure-readiness-only"),("network-check.json","network-policy-controls-only"),("enforcement-check.json","non-executing-gateway-fixture-only")]:
        value=fresh_json(cluster.directory/name)
        require(value.get("scope")==scope,"wrong_foundation_report_scope")
        if name=="readiness.json":
            require(value.get("skipped_checks")==[] and value["checks"].get("substrate") is True,"partial_foundation_cannot_qualify_target")
            require(value["configured_pins"]==VERSIONS,"foundation_pins_differ_from_current_profile")
        else:require(value.get("passed") is True,"foundation_control_matrix_failed")
    observed=Deployment()
    deployment=json.loads((BANKING/"deployment.json").read_text())
    observed.verify_deployment(deployment)
    run=client.get_run(runtime_run_id)
    require(run.info.status=="FINISHED","actual_actor_runtime_run_not_finished")
    stable_summary=fresh_json(stability_directory/"summary.json")
    node_start=datetime.fromisoformat(stable_summary["baseline"]["node_started_at"].replace("Z","+00:00")).timestamp()
    require(run.info.start_time/1000>=node_start,"actor_controls_predate_this_provider_boot")
    require(stable_summary["elapsed_seconds"]>=FULL_WINDOW_SECONDS,"provider_window_too_short")
    cache=DIRECTORY/"runtime-readback"/runtime_run_id;cache.mkdir(parents=True,exist_ok=True,mode=0o700)
    def artifact(name):
        path=client.download_artifacts(runtime_run_id,name,str(cache))
        return json.loads(Path(path).read_text())
    summary=artifact("summary.json");rows=artifact("results.json");cleanup=artifact("audit/cleanup.json")
    require(summary.get("full_runtime_controls_passed") is True and summary.get("cases")==23 and summary.get("expected_cases")==23 and
            summary.get("model_calls")==0 and summary.get("judge_calls")==0,"actual_actor_control_matrix_incomplete")
    require(cleanup.get("errors")==[],"actor_cleanup_incomplete")
    require(len(rows)==23 and len({row["case_id"] for row in rows})==23,"actor_case_ids_ambiguous")
    for row in rows:
        require(time.monotonic()-started<50,"qualification_readback_deadline")
        trace=mlflow.get_trace(row["trace_id"])
        require(trace is not None and trace.info.trace_metadata.get("mlflow.sourceRun")==runtime_run_id,"actor_trace_run_ownership_mismatch")
        roots=[s for s in trace.data.spans if s.parent_id is None]
        scores=[a for a in trace.info.assessments if a.name=="runtime/passed" and a.span_id is None]
        require(len(roots)==1 and roots[0].outputs==public_view({k:v for k,v in row.items() if k!="trace_id"}) and
            len(scores)==1 and scores[0].value is True and scores[0].error is None and scores[0].source is not None and
            scores[0].source.source_type=="CODE" and scores[0].source.source_id==SOURCE.source_id,"actor_case_evidence_or_score_readback_mismatch")
    versions=json.loads(subprocess.check_output(["podman","version","--format","json"],text=True,timeout=10))
    require(versions["Client"]["Version"]==versions["Server"]["Version"]==VERSIONS["podman"].removeprefix("v"),"current_podman_profile_mismatch")
    return dict(scope="local-target-stack-automated-qualification",automated_passed=True,human_acceptance="pending",
        checked_at=datetime.now().astimezone().isoformat(),profile_sha256=profile["profile_sha256"],configured_versions=VERSIONS,
        actor_controls_run=runtime_run_id,actor_cases=23,protocol_run=protocol["run_id"],protocol_trace=protocol["trace_id"],
        stability_run=stable["run_id"],stability_trace=stable["trace_id"],serving_run=serving["run_id"],serving_trace=serving["trace_id"],
        provider_baseline=stable_summary["baseline"],stability_directory=str(stability_directory),
        booted_guest=current_guest_os(),
        serving_completed_generations=serving["completed_generations"],serving_reserved_requests=serving["reserved_probe_attempts"],
        banking_mcp_application_implemented=False,banking_agent_graph_implemented=False,
        financial_authorization=False,production_transport_or_HA=False,loaded_model=loaded)


def require_current_cached(cluster):
    """Doctor gate: current observations plus complete persisted qualification."""
    from datetime import date
    from src.infra.stability import live_probe
    from src.infra.serving_probe import local_serving_software
    report=fresh_json(DIRECTORY/"qualification.json")
    require(report.get("scope")=="local-target-stack-automated-qualification" and report.get("automated_passed") is True,"full_target_qualification_not_recorded")
    require(report.get("configured_versions")==VERSIONS,"qualification_versions_changed")
    profile=fresh_json(DIRECTORY/"profile.json")
    require(report["profile_sha256"]==profile["profile_sha256"],"qualification_profile_changed")
    require(current_bindings(cluster,profile)==fresh_json(DIRECTORY/"qualified-bindings.json"),"qualified_gateway_configuration_changed")
    require(live_probe(cluster)==report["provider_baseline"],"provider_changed_after_qualification")
    require(current_guest_os()==report["booted_guest"],"booted_guest_image_changed")
    require(local_serving_software()==report["loaded_model"]["software"],"loaded_serving_software_changed")
    loaded=json.loads(subprocess.check_output(["lms","ps","--json"],text=True,timeout=15))
    selected=[m for m in loaded if m.get("identifier")==VERSIONS["local_model"]]
    require(len(selected)==1 and selected[0].get("contextLength")==VERSIONS["local_model_context"] and
            selected[0].get("architecture")=="qwen3_moe" and selected[0].get("quantization",{}).get("bits")==4,
            "qualified_model_unloaded_or_reconfigured")
    policy=json.loads((ROOT/"infra/version-policy.json").read_text())
    require(date.today()<=date.fromisoformat(policy["review_due"]),"component_release_review_overdue")
    return report


def main():
    from dotenv import load_dotenv
    import mlflow
    from mlflow.entities import AssessmentSource
    from src.infra.manage import Cluster
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stability-directory",type=Path,required=True)
    parser.add_argument("--runtime-controls-run",required=True)
    args=parser.parse_args()
    load_dotenv(ROOT/".env")
    os.environ["MLFLOW_ENABLE_ASYNC_TRACE_LOGGING"]="false"
    os.environ["MLFLOW_HTTP_REQUEST_TIMEOUT"]="5"
    os.environ["MLFLOW_HTTP_REQUEST_MAX_RETRIES"]="0"
    cluster=Cluster("breaker-substrate");cluster.verify()
    mlflow.set_experiment("breaker-infrastructure-reviews")
    with mlflow.start_run(run_name="target-stack-automated-qualification") as run:
        mlflow.set_tags(dict(scope="local-target-stack-automated-qualification",human_acceptance="pending",github_issue="38"))
        with mlflow.start_span(name="qualify_current_target_stack",span_type="CHAIN") as span:
            span.set_inputs(dict(runtime_run=args.runtime_controls_run,model_requests=0))
            report=verify_current(cluster,stability_directory=args.stability_directory,runtime_run_id=args.runtime_controls_run)
            span.set_outputs(report);trace_id=span.trace_id
        mlflow.log_feedback(trace_id=trace_id,name="infra/automated_qualified",value=True,
            source=AssessmentSource(source_type="CODE",source_id="target-stack-qualification-v1"))
        report.update(qualification_run=run.info.run_id,qualification_trace=trace_id)
        mlflow.log_dict(report,"qualification.json")
    mlflow.flush_trace_async_logging()
    require(mlflow.get_trace(trace_id) is not None,"qualification_trace_not_persisted")
    private(DIRECTORY/"qualification.json",report)
    print(json.dumps(report),flush=True)


if __name__=="__main__":main()
