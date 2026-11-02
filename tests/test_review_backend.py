from copy import deepcopy
import hashlib
from http.client import HTTPConnection
import json
import threading

import httpx
import pytest

from src.benchmark.review_backend import build_bundle,ReviewStore,ReviewServer,VERSION


def fixture(tmp_path):
    native=tmp_path/"native";native.mkdir()
    plan=dict(namespace="nd7",code_sha256="a"*64,cases=[dict(case_id="nd7-ok",kind="card",card_id="D03",arm="classifier"),dict(case_id="nd7-not-run",kind="card",card_id="D01",arm="llm")])
    card=dict(case_id="nd7-ok",card_id="D03",demo_ready=True,expected_review="allow",observed_review="allow")
    record=dict(status="completed",producer="acting_model",tool_attempts=1,measured=dict(utility=True),cleanup_errors=[],trace_id="tr-"+"a"*32,child_run_id="b"*32,
        telemetry_reconciliation=dict(status="complete"),trace_audit=dict(managed_responses_dispatches=2,guard_managed_responses_dispatches=0),
        evidence=dict(initial_state=dict(city="PRIVATE_BEFORE",balance=10),actual_state=dict(city="PRIVATE_AFTER",balance=10),
            actions=[dict(tool="update_user_info",status="executed",arguments=dict(api_key="SECRET"),native_admission_attempted=True,
                guard=dict(decision="allow",review_latency_ns=30000000,classifier_decision_core_ns=20000000),execution_receipt=dict(executed=True,signature="PRIVATE_SIGNATURE"))]))
    report=dict(curated_accuracy=dict(classifier=dict(total=4,note="SECRET",api_key="SECRET")),external_harness_verdict="supported")
    for name,value in (("plan.json",plan),("cards.json",[card]),("nd7-ok.json",record),("report.json",report)):(native/name).write_text(json.dumps(value))
    return dict(id="nd7",directory=str(native),report=str(native/"report.json"))


def test_replay_contract_orders_events_redacts_payloads_and_preserves_missing_cases(tmp_path):
    entry=fixture(tmp_path);output=tmp_path/"bundle";payload=build_bundle([entry],output)
    assert payload["mode"]=="saved_replay" and not payload["live_dispatch_supported"]
    text=json.dumps(payload)
    assert not any(x in text for x in ("PRIVATE_BEFORE","PRIVATE_AFTER","PRIVATE_SIGNATURE","SECRET"))
    store=ReviewStore(output);run=store.get("/api/v1/runs/nd7/results")
    assert not run["complete"] and not run["all_ready"] and run["cases"][1]["status"]=="not_run"
    first=store.get("/api/v1/runs/nd7/events?limit=2");second=store.get("/api/v1/runs/nd7/events?after=2&limit=2")
    assert [e["sequence"] for e in first["events"]+second["events"]]==[1,2,3,4]
    assert all(e["timestamp"] is None and e["time_basis"]=="logical_order_not_wall_clock" for e in first["events"])
    assert store.get("/api/v1/cases")["schema_version"]==VERSION
    assert store.get("/api/v1/accounting")["accounting"]=={}
    with pytest.raises((KeyError,ValueError)):store.get("/api/v1/runs/../../etc/passwd")
    with pytest.raises(ValueError):store.get("/api/v1/runs/nd7/events?limit=201")


def test_partial_dispatch_cannot_be_promoted_by_original_green_card(tmp_path):
    entry=fixture(tmp_path);path=tmp_path/"native/nd7-ok.json";record=json.loads(path.read_text());record["tool_attempts"]=2;path.write_text(json.dumps(record))
    payload=build_bundle([entry],tmp_path/"bundle");case=payload["runs"][0]["cases"][0]
    assert case["original_recorded_ready"] is True and case["ready"] is False and case["enforcement_coverage"]=="partial_unverified"


def test_readiness_recovery_remains_visible_separate_from_model_calls(tmp_path):
    entry=fixture(tmp_path);path=tmp_path/"native/nd7-ok.json";record=json.loads(path.read_text())
    record["readiness"]=dict(ready=True,recovered=True,retry_count=1,attempts=[dict(attempt=1,status="transient_failure",retryable=True,elapsed_ns=100),dict(attempt=2,status="ready",retryable=False,elapsed_ns=100)])
    path.write_text(json.dumps(record));run=build_bundle([entry],tmp_path/"bundle")["runs"][0]
    assert run["cases"][0]["readiness"]["recovered"] is True and run["cases"][0]["physical_actor"]==2
    assert len([e for e in run["events"] if e["stage"]=="readiness_observation"])==2


def test_new_projection_exposes_golden_verdicts_and_startup_not_threshold_counts(tmp_path):
    entry=fixture(tmp_path);path=tmp_path/"native/report.json";value=json.loads(path.read_text())
    value.update(golden_accuracy=dict(unique_inputs=1,results=[dict(candidate_id="read",task_id="user_task_0",input_digest="a"*64,golden="allow",use_cases=["D01"],
        backends={arm:dict(observed="allow",correct=True) for arm in ("classifier","llm")})],overall={},by_use_case={}),
        decision_core=dict(read=dict(below15=6,core=dict(median_ms=12))),native_core_below15=10,
        service_startup=dict(native=dict(ready=True,classifier=dict(classifier_primed=True,startup_priming=[]),model_probes=[])))
    path.write_text(json.dumps(value));payload=build_bundle([entry],tmp_path/"bundle");run=payload["runs"][0]
    assert run["golden_accuracy"]["results"][0]["golden"]=="allow" and run["golden_accuracy"]["results"][0]["backends"]["llm"]["correct"]
    assert run["service_startup"]["native"]["ready"] and "below15" not in json.dumps(payload)


def test_bundle_and_sources_are_hash_checked(tmp_path):
    entry=fixture(tmp_path);output=tmp_path/"bundle";build_bundle([entry],output)
    (tmp_path/"native/nd7-ok.json").write_text("tampered")
    with pytest.raises(ValueError,match="source_changed"):ReviewStore(output)


def test_first_case_setup_failure_without_cards_is_retained_not_hidden(tmp_path):
    entry=fixture(tmp_path);native=tmp_path/"native";(native/"cards.json").unlink();(native/"nd7-ok.json").unlink()
    (native/"failure.json").write_text(json.dumps(dict(error="ContractError",message="invalid_runtime_json",completed_cases=[])))
    (native/"nd7-ok.partial.json").write_text(json.dumps(dict(case_id="nd7-ok",status="setup_failed",error_code="invalid_runtime_json",trial_created=True,actor_deleted=True,cleanup_errors=[])))
    run=build_bundle([entry],tmp_path/"bundle")["runs"][0]
    assert not run["complete"] and not run["all_ready"]
    assert run["cases"][0]["status"]=="setup_failed" and run["cases"][0]["actor_deleted"] is True
    assert run["cases"][1]["status"]=="not_run"


def test_report_transitive_sources_are_rechecked_by_replay_server(tmp_path):
    entry=fixture(tmp_path);proof=tmp_path/"proof.json";proof.write_text("proof")
    report=tmp_path/"native/report.json";value=json.loads(report.read_text());value["source_hashes"]={str(proof):hashlib.sha256(proof.read_bytes()).hexdigest()};report.write_text(json.dumps(value))
    output=tmp_path/"bundle";build_bundle([entry],output);proof.write_text("changed")
    with pytest.raises(ValueError,match="source_changed"):ReviewStore(output)


def test_read_only_http_auth_host_and_method_gates_without_inference(tmp_path):
    entry=fixture(tmp_path);output=tmp_path/"bundle";build_bundle([entry],output)
    store=ReviewStore(output);server=ReviewServer(("127.0.0.1",0),store,"x"*40)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{server.server_port}",trust_env=False) as client:
            assert client.get("/api/v1/runs").status_code==401
            headers=dict(Authorization="Bearer "+"x"*40)
            response=client.get("/api/v1/runs",headers=headers)
            assert response.status_code==200 and response.json()["runs"][0]["mode"]=="saved_replay"
            assert response.headers["cache-control"]=="no-store"
            assert client.post("/api/v1/runs",headers=headers,json={}).status_code==405
            assert client.get("/api/v1/runs",headers=dict(headers,Host="evil.invalid")).status_code==401
        malformed=HTTPConnection("127.0.0.1",server.server_port,timeout=2)
        malformed.request("GET","/api/v1/runs",headers={"Authorization":"Bearer \xff"})
        response=malformed.getresponse();assert response.status==401;response.read();malformed.close()
    finally:server.shutdown();server.server_close();thread.join(2)
    with pytest.raises(ValueError):ReviewServer(("0.0.0.0",0),store,"x"*40)
