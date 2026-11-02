"""Shared explicit service startup, separate from golden scoring and latency samples."""
from pathlib import Path
from time import perf_counter_ns

import httpx
import mlflow
from langchain_core.messages import HumanMessage,SystemMessage

from src.benchmark.accuracy import review_input
from src.benchmark.compare import claim_case
from src.benchmark.deployment import private
from src.benchmark.guards import ReviewInput,timed_review
from src.benchmark.projection import POLICY_ID,POLICY_TEXT
from src.benchmark.serving import provider_status

PROFILE=dict(schema_version="services-ready-v1",classifier_lifetime="resident-for-run",classifier_thread="single-owner-worker",
    classifier_priming_passes=2,priming_scored=False,model_startup_calls_per_process=2,model_action_retries=0,
    shared_model_reloaded=False,global_settings_changed=False)


def priming_values(plan):return {r["candidate_id"]:review_input(r["model_input"]) for r in plan["startup_inputs"]}


def validate(value,plan,stage,entries):
    if not value.get("ready") or value.get("stage")!=stage or value.get("profile")!=plan["startup_profile"]:raise ValueError("startup_report_binding")
    classifier=value.get("classifier") or {};samples=classifier.get("startup_priming",[])
    expected={(r["input_digest"],index) for r in plan["startup_inputs"] for index in range(2)}
    observed={(r.get("input_digest"),r.get("pass_index")) for r in samples}
    if not classifier.get("classifier_primed") or not classifier.get("classifier_weights_loaded") or len(samples)!=len(expected) or observed!=expected or any(r.get("error") for r in samples):raise ValueError("startup_priming_evidence")
    probes=value.get("model_probes",[])
    cases={c["case_id"]:c for c in plan["cases"] if c["kind"]=="startup" and c["stage"]==stage}
    if len(probes)!=2 or {r["case_id"] for r in probes}!=set(cases):raise ValueError("startup_probe_evidence")
    for row in probes:
        if row["status"]!="completed" or row["physical_attempts"]!=1 or row["reconciliation"]["status"]!="complete" or cases[row["case_id"]].get(row["role"])!=1:
            raise ValueError("startup_probe_not_ready")
        if sum(e["case_id"]==row["case_id"] and e["role"]==row["role"] for e in entries)!=1:raise ValueError("startup_reservation_count")
    return value


def prepare(*,plan,budget,directory,stage,resources,reviewer,actor_model,active,store=None,mcp=None,platform_check=None):
    from src.benchmark.measurement import transport_audit
    from src.benchmark.reconciliation import reconcile_record
    started=perf_counter_ns();report=dict(schema_version="services-ready-report-v1",stage=stage,ready=False,profile=PROFILE,checks={},model_probes=[])
    path=Path(directory)/"services-startup.json"
    def save():private(path,report)
    try:
        status=provider_status(plan["acting_model"])
        if status.get("state")!="idle":raise RuntimeError("startup_provider_not_idle_or_loaded")
        if status.get("context_length")!=plan["serving"]["shared_context"]:raise RuntimeError("startup_provider_context_mismatch")
        report["checks"]["provider"]=status
        uri=mlflow.get_tracking_uri()
        if not uri.startswith(("http://","https://")) or httpx.get(uri.rstrip("/")+"/health",timeout=5,trust_env=False).status_code!=200:
            raise RuntimeError("startup_tracking_not_ready")
        report["checks"]["tracking"]=dict(ready=True)
        if store:report["checks"]["store"]=store.call("/capacity",{})
        if mcp:report["checks"]["mcp"]=dict(catalog_verified=True,tool_count=len(mcp.discover()),tools_executed=0)
        if platform_check:report["checks"]["actor_native_path"]=platform_check()
        values=priming_values(plan)
        resources.select("classifier")  # Verify functional Qwen probes with encoder weights ALSO resident.
        # Startup probes are newly reserved real requests; they never execute a proposal.
        for role in ("actor","llm_guard"):
            spec=next(c for c in plan["cases"] if c["kind"]=="startup" and c["stage"]==stage and c.get(role)==1)
            claim_case(budget,spec["case_id"],plan);active.update(case_id=spec["case_id"],role=role,physical_attempts=0)
            row=dict(case_id=spec["case_id"],role=role,phase="startup_not_scored",physical_attempts=0)
            with mlflow.start_span(name="service_startup_"+role,span_type="CHAIN") as span:
                row["trace_id"]=span.trace_id;span.set_inputs(dict(phase="startup_not_scored",role=role,tools_executed=0))
                try:
                    if role=="actor":
                        response=actor_model.invoke([SystemMessage(content="Service startup check only. Propose exactly one get_balance tool call with empty arguments. No tool will be executed."),HumanMessage(content="Check tool-calling protocol readiness.")])
                        calls=response.tool_calls
                        if response.invalid_tool_calls or len(calls)!=1 or calls[0].get("name")!="get_balance" or calls[0].get("args")!={}:raise RuntimeError("startup_actor_protocol_invalid")
                        metadata=response.response_metadata
                        if metadata.get("status","completed")!="completed" or metadata.get("finish_reason") not in {None,"stop","tool_calls"}:raise RuntimeError("startup_actor_response_incomplete")
                        row.update(status="completed",proposal_validated=True,proposal_executed=False)
                    else:
                        sentinel=ReviewInput("Synthetic service startup readiness only.",POLICY_ID,POLICY_TEXT,"get_balance",{})
                        review=timed_review(reviewer,sentinel)
                        if review.get("decision") not in {"allow","block"} or review.get("error"):raise RuntimeError("startup_reviewer_protocol_invalid")
                        row.update(status="completed",protocol_validated=True,scored=False,input_digest=sentinel.digest())
                except Exception as exc:row.update(status="error",error=type(exc).__name__)
                row["physical_attempts"]=active["physical_attempts"];span.set_outputs(row)
            row["reconciliation"]=reconcile_record(row,audit=transport_audit,provider_probe=lambda **kw:provider_status(plan["acting_model"],**kw),timeout_seconds=120,quiet_seconds=2,poll_seconds=1)
            report["model_probes"].append(row);save()
            if row["status"]!="completed" or row["physical_attempts"]!=1 or row["reconciliation"]["status"]!="complete":raise RuntimeError("startup_model_probe_failed")
        # Last startup step: initialize the same resident worker used for ALL measured forwards.
        with mlflow.start_span(name="classifier_startup_priming",span_type="CHAIN") as span:
            span.set_inputs(dict(phase="startup_not_scored",input_digests=[v.digest() for v in values.values()],passes=2))
            resources.prepare(values,passes=plan["startup_profile"]["classifier_priming_passes"])
            span.set_outputs(resources.snapshot());report["classifier_priming_trace_id"]=span.trace_id
        after=provider_status(plan["acting_model"])
        if after.get("state")!="idle" or after.get("context_length")!=plan["serving"]["shared_context"]:raise RuntimeError("startup_provider_changed_after_priming")
        report["checks"]["provider_after_priming"]=after
        report["classifier"]=resources.snapshot();report.update(ready=True,elapsed_ns=perf_counter_ns()-started,measured_requests_started_after_ready=True)
        save();mlflow.log_dict(report,"startup/"+stage+".json");return report
    except Exception as exc:
        report.update(error=type(exc).__name__,elapsed_ns=perf_counter_ns()-started,classifier=resources.snapshot());save();raise
