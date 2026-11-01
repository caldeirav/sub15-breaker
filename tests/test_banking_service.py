"""Actor-service transaction tests. These do not claim gVisor deployment evidence."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
import socket
import threading
from types import SimpleNamespace

import httpx

from cryptography.hazmat.primitives.asymmetric import rsa
import jwt
import pytest

from src.banking_contracts.codec import ContractError
from src.banking_contracts.models import PolicyProfile, TrustedContext
from src.banking_contracts.tools import ToolCatalog
from src.banking_service.auth import IdentityVerifier
from src.banking_service.http import BoundedServer, body_object, fields
from src.banking_service.store import StateStore
from src.banking_service.upstream import evaluate, initial_state


@pytest.fixture(scope="module")
def catalog(): return ToolCatalog.from_pinned_agentdojo()


@pytest.fixture
def world(tmp_path, catalog):
    store = StateStore(tmp_path/"state.sqlite", b"k"*32, catalog=catalog)
    context = TrustedContext(context_version=1, principal_id="test-driver", interaction_id="trial-1",
        trial_id="trial-1", actor_id="actor-1", actor_generation=1, state_version=0,
        intent_id="intent-1", intent_version=1, user_request="Synthetic test request",
        policy=PolicyProfile(policy_id="structural-test", policy_version=1, allowed_tools=tuple(catalog.names)),
        expires_at=datetime.now(timezone.utc)+timedelta(hours=1), authority_kind="service-owned")
    store.create(context, "uid-1", initial_state())
    return store, context


def proposal(tool="get_balance", args=None, **changes):
    return dict(schema_version="banking-action-v1", action_id="a-1", idempotency_key="i-1",
        expected_context_version=1, expected_actor_generation=1, expected_state_version=0,
        tool_name=tool, arguments=args or {}, **changes)


def complete(store, value):
    p=store.prepare("trial-1", "test-driver", value)
    work=store.claim(p["ticket"], "actor-1", "uid-1")
    result=evaluate(work["proposal"], work["state"])
    return store.commit(p["ticket"], "actor-1", "uid-1", **result)


def test_atomic_write_and_receipt_survive_store_process_reopen(world, catalog):
    store, _=world
    before=store.snapshot("trial-1", "test-driver")
    result=complete(store, proposal("send_money", dict(recipient="FIXTURE", amount="12.30", subject="test", date="2026-10-31")))
    reopened=StateStore(store.path, b"k"*32, catalog=catalog)
    after=reopened.snapshot("trial-1", "test-driver")
    assert after["state_version"]==1
    assert len(after["state"]["bank_account"]["transactions"])==len(before["state"]["bank_account"]["transactions"])+1
    assert result["result"]["receipt"]["executed"] is True
    assert result["result"]["receipt"]["fixture_only"] is False
    assert reopened.status("trial-1", "test-driver", result["ticket"])==dict(result, replayed=False)


def test_identical_write_replay_does_not_repeat_effect_even_with_old_state_version(world):
    store, _=world
    value=proposal("update_user_info", dict(city="New City"))
    first=complete(store, value)
    second=store.prepare("trial-1", "test-driver", value)
    assert second["replayed"] and second["result"]==first["result"]
    assert store.snapshot("trial-1", "test-driver")["state_version"]==1
    assert len([r for r in store.events() if r["kind"]=="tool_attempt"])==1


def test_concurrent_prepare_claim_commit_publish_one_effect(world):
    store, _=world
    value=proposal("update_user_info", dict(city="Concurrent City"))
    with ThreadPoolExecutor(max_workers=4) as pool:
        prepared=list(pool.map(lambda _:store.prepare("trial-1","test-driver",value),range(4)))
    assert len({r["ticket"] for r in prepared})==1
    ticket=prepared[0]["ticket"]
    work=store.claim(ticket,"actor-1","uid-1")
    with pytest.raises(ContractError,match="execution_outcome_unknown"):store.claim(ticket,"actor-1","uid-1")
    result=evaluate(work["proposal"],work["state"])
    with ThreadPoolExecutor(max_workers=4) as pool:
        committed=list(pool.map(lambda _:store.commit(ticket,"actor-1","uid-1",**result),range(4)))
    assert len({r["result"]["receipt"]["receipt_id"] for r in committed})==1
    assert store.snapshot("trial-1","test-driver")["state_version"]==1


def test_stale_changed_payload_wrong_principal_and_wrong_actor_reject(world):
    store,_=world
    with pytest.raises(ContractError,match="unknown_owned_trial"):store.prepare("trial-1","other",proposal())
    p=store.prepare("trial-1","test-driver",proposal())
    with pytest.raises(ContractError,match="action_id_conflict"):
        store.prepare("trial-1","test-driver",dict(proposal(),tool_name="get_user_info"))
    for actor,uid in [("other","uid-1"),("actor-1","other")]:
        with pytest.raises(ContractError,match="actor_identity_mismatch"):store.claim(p["ticket"],actor,uid)


def test_crash_before_commit_keeps_state_and_unknown_attempt_blocks_new_work(world,catalog):
    store,_=world
    before=store.snapshot("trial-1","test-driver")
    p=store.prepare("trial-1","test-driver",proposal("update_user_info",dict(city="Uncommitted")))
    work=store.claim(p["ticket"],"actor-1","uid-1")
    evaluate(work["proposal"],work["state"])  # private computation; simulate loss before commit
    reopened=StateStore(store.path,b"k"*32,catalog=catalog)
    assert reopened.snapshot("trial-1","test-driver")["state"]==before["state"]
    assert reopened.status("trial-1","test-driver",p["ticket"])["status"]=="executing"
    with pytest.raises(ContractError,match="trial_action_pending"):
        reopened.prepare("trial-1","test-driver",dict(proposal(),action_id="a-2",idempotency_key="i-2"))


def test_reset_fences_old_actor_and_retains_completed_receipts(world):
    store,_=world
    initial=store.snapshot("trial-1","test-driver")
    result=complete(store,proposal("update_user_info",dict(city="Changed")))
    with pytest.raises(ContractError,match="reset_requires_fence"):store.replace("trial-1","test-driver","actor-2","uid-2")
    store.fence("trial-1","test-driver")
    with pytest.raises(ContractError,match="actor_identity_mismatch"):
        store.commit(result["ticket"],"actor-1","uid-1",initial["state"],None)
    reset=store.replace("trial-1","test-driver","actor-2","uid-2")
    assert reset["generation"]==2 and reset["state_version"]==0 and reset["fingerprint"]==initial["fingerprint"]
    assert store.status("trial-1","test-driver",result["ticket"])["result"]==result["result"]
    with pytest.raises(ContractError,match="stale_actor_generation"):store.prepare("trial-1","test-driver",proposal())


def test_outbox_capacity_blocks_before_claim_and_secret_values_are_withheld(world):
    store,_=world
    store.max_events=3
    with pytest.raises(ContractError,match="evidence_outbox_full"):
        store.prepare("trial-1","test-driver",proposal())
    store.max_events=20
    complete(store,proposal("update_password",dict(password="PRIVATE-CANARY")))
    assert "PRIVATE-CANARY" not in json.dumps(store.events())
    for event in store.events():store.acknowledge(event["event_id"])
    assert not store.events()


def test_failed_state_commit_rolls_back_state_receipt_and_outbox(world):
    store,_=world
    p=store.prepare("trial-1","test-driver",proposal("update_user_info",dict(city="Atomic")))
    work=store.claim(p["ticket"],"actor-1","uid-1")
    result=evaluate(work["proposal"],work["state"])
    with sqlite3.connect(store.path) as db:
        db.execute("CREATE TRIGGER fail_event BEFORE INSERT ON outbox BEGIN SELECT RAISE(ABORT, 'test'); END")
    before=store.snapshot("trial-1","test-driver")
    with pytest.raises(ContractError,match="durable_store_unavailable"):
        store.commit(p["ticket"],"actor-1","uid-1",**result)
    assert store.snapshot("trial-1","test-driver")==before
    assert store.status("trial-1","test-driver",p["ticket"])["result"] is None


def test_abrupt_store_process_exit_recovers_uncommitted_wal(world,catalog):
    store,_=world
    before=store.snapshot("trial-1","test-driver")
    script="""import os,sqlite3,sys
db=sqlite3.connect(sys.argv[1],isolation_level=None)
db.execute('PRAGMA synchronous=FULL')
db.execute('BEGIN IMMEDIATE')
db.execute('UPDATE trials SET version=99 WHERE id=?',('trial-1',))
db.execute('INSERT INTO outbox(id,kind,trial,payload) VALUES (?,?,?,?)',('uncommitted','test','trial-1','{}'))
os._exit(0)
"""
    subprocess.run([sys.executable,"-c",script,str(store.path)],check=True,timeout=5)
    reopened=StateStore(store.path,b"k"*32,catalog=catalog)
    assert reopened.snapshot("trial-1","test-driver")==before
    assert all(event["event_id"]!="uncommitted" for event in reopened.events())


def test_live_budget_is_exclusive_and_never_implicitly_reopened(tmp_path,monkeypatch):
    from src.banking_service.live import reserve_budget
    monkeypatch.setattr("src.banking_service.live.DIRECTORY",tmp_path)
    reserve_budget("local-user_task_0","test-run")
    with pytest.raises(FileExistsError):reserve_budget("local-user_task_0","another-run")
    assert json.loads((tmp_path/"live-budget/local-user_task_0.json").read_text())["run_id"]=="test-run"


def test_durable_key_mismatch_and_expired_operation_reject(world,catalog):
    store,_=world
    with pytest.raises(ContractError,match="runtime_key_changed"):StateStore(store.path,b"z"*32,catalog=catalog)
    p=store.prepare("trial-1","test-driver",proposal())
    with sqlite3.connect(store.path) as db:db.execute("UPDATE actions SET deadline=0 WHERE ticket=?",(p["ticket"],))
    with pytest.raises(ContractError,match="action_expired"):store.claim(p["ticket"],"actor-1","uid-1")


def test_json_and_route_fields_reject_duplicates_nonfinite_and_extras():
    for data in (b'{"x":1,"x":2}',b'{"x":NaN}',b'[]',b'\xff'):
        with pytest.raises(ContractError):body_object(data)
    with pytest.raises(ContractError):fields(dict(ticket="t",principal="forged"),("ticket",))


def test_platform_identity_verifies_signature_issuer_audience_subject_and_kind():
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    public=json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()));public.update(kid="test-key",alg="RS256")
    config=dict(driver=dict(issuer="https://kube.test",audience="banking",subject="test-driver",jwks=dict(keys=[public])),
        actor=dict(issuer="https://actor.test",audience="banking",atespace="banking",jwks=dict(keys=[public])))
    verifier=IdentityVerifier(config)
    base=dict(iss="https://kube.test",sub="test-driver",aud="banking",iat=int(time.time()),exp=int(time.time())+60)
    token=lambda c:"Bearer "+jwt.encode(c,key,algorithm="RS256",headers=dict(kid="test-key"))
    assert verifier.driver(token(base))=="test-driver"
    for changed in (dict(base,aud="other"),dict(base,iss="https://evil.test"),dict(base,sub="other"),dict(base,exp=0)):
        with pytest.raises(ContractError):verifier.driver(token(changed))
    actor=dict(base,iss="https://actor.test",sub="actor/banking/a-1",**{"actor.ate.dev":dict(atespace="banking",actorName="a-1",actorUID="uid-1")})
    assert verifier.actor(token(actor)).uid=="uid-1"
    with pytest.raises(ContractError):verifier.actor(token(dict(actor,**{"worker-for-actor.ate.dev":{}})))


def test_actor_image_imports_do_not_depend_on_runtime_working_directory():
    dockerfile=(Path(__file__).resolve().parents[1]/"Dockerfile.banking").read_text()
    assert "PYTHONPATH=/app" in dockerfile
    assert "--only-group banking-service" in dockerfile
    assert "USER 10001:10001" in dockerfile
    assert '"src.banking_service.entrypoint"' in dockerfile


def test_startup_repairs_only_the_private_guest_root(monkeypatch):
    from src.banking_service.security import normalize_guest_root
    changed=[]
    monkeypatch.setattr("src.banking_service.security.os",SimpleNamespace(
        stat=lambda p:SimpleNamespace(st_mode=0o40700,st_uid=0),chmod=lambda p,m:changed.append((p,m))))
    normalize_guest_root()
    assert changed==[("/",0o555)]


@pytest.mark.parametrize("claimed",[False,True])
def test_reset_after_interruption_releases_old_generation_and_reservations(world,claimed):
    store,_=world
    old=store.prepare("trial-1","test-driver",proposal())
    if claimed:store.claim(old["ticket"],"actor-1","uid-1")
    store.fence("trial-1","test-driver")
    store.replace("trial-1","test-driver","actor-2","uid-2")
    status=store.status("trial-1","test-driver",old["ticket"])["status"]
    assert status==("fenced_unknown" if claimed else "fenced_not_dispatched")
    with store.transaction() as db:
        assert db.execute("SELECT count(*) FROM actions WHERE status IN ('prepared','executing')").fetchone()[0]==0
    fresh=store.prepare("trial-1","test-driver",dict(proposal(),expected_context_version=2,expected_actor_generation=2))
    assert fresh["status"]=="prepared"
    with pytest.raises(ContractError,match="actor_identity_mismatch"):store.claim(old["ticket"],"actor-1","uid-1")


@pytest.mark.parametrize("lost_stage",["prepare","commit","commit_http","unknown", "password"])
def test_actor_adapter_reconciles_stable_identity_and_stops_unknown_writes(world,monkeypatch,lost_stage):
    from src.banking_service.agent import ActorBankingTrial
    from src.feasibility.banking import load_suite
    store,_=world
    counts={"prepare":0,"execute":0,"reconcile":0,"status":0}
    class Client:
        def call(self,path,value):
            if path=="/snapshot":return store.snapshot(value["trial_id"],"test-driver")
            if path=="/prepare":
                counts["prepare"]+=1
                result=store.prepare(value["trial_id"],"test-driver",value["proposal"])
                if lost_stage=="prepare":raise httpx.ReadTimeout("test")
                return result
            if path=="/reconcile":
                counts["reconcile"]+=1
                return store.reconcile(value["trial_id"],"test-driver",value["proposal"])
            if path=="/status":
                counts["status"]+=1
                return store.status(value["trial_id"],"test-driver",value["ticket"])
            if path=="/client-event":return {}
            raise AssertionError(path)
    class Actor:
        def call(self,path,value):
            counts["execute"]+=1
            work=store.claim(value["ticket"],"actor-1","uid-1")
            if lost_stage=="unknown":raise httpx.ReadTimeout("test")
            result=store.commit(value["ticket"],"actor-1","uid-1",**evaluate(work["proposal"],work["state"]))
            if lost_stage=="commit":raise httpx.ReadTimeout("test")
            if lost_stage=="commit_http":raise ContractError("runtime_unavailable","transport")
            return result
    @contextmanager
    def span(**_):
        yield SimpleNamespace(span_id="test-span",set_inputs=lambda _:None,set_outputs=lambda _:None)
    monkeypatch.setattr("mlflow.start_span",span)
    trial=ActorBankingTrial(load_suite(),"user_task_0","trial-1",Client(),"http://127.0.0.1","Bearer test")
    trial.actor=Actor()
    if lost_stage=="unknown":
        with pytest.raises(RuntimeError,match="trial stopped"):trial.execute("update_user_info",dict(city="New City"))
        assert trial.records[0]["execution_receipt"] is None and trial.records[0]["state_changed"] is None
        with pytest.raises(RuntimeError,match="stopped pending"):trial.execute("update_user_info",dict(city="New City"))
        assert store.snapshot("trial-1","test-driver")["state_version"]==0
    else:
        tool,args=("update_password",dict(password="SECRET-ONLY-CHANGE")) if lost_stage=="password" else ("update_user_info",dict(city="New City"))
        record=trial.execute(tool,args)
        assert record["execution_receipt"]["executed"] is True and record["state_changed"] is True
        assert record["before_state_hash"] is not None
        assert "SECRET-ONLY-CHANGE" not in json.dumps(record)
        assert store.snapshot("trial-1","test-driver")["state_version"]==1
    assert counts["prepare"]==1 and counts["execute"]==1
    assert counts["reconcile"]==int(lost_stage=="prepare")
    assert counts["status"]==int(lost_stage in {"commit","commit_http","unknown"})


@pytest.mark.parametrize("size",[1,3999,4000,4001])
def test_outbox_repairs_partial_feedback_and_exact_capacity_drains(monkeypatch,size):
    from src.banking_service.telemetry import export_outbox,SOURCE
    events=[dict(event_id=f"e-{i}",kind="test",trial_id="trial",payload={}) for i in range(size)]
    traces={}
    for event in events:
        traces[event["event_id"]]=SimpleNamespace(info=SimpleNamespace(trace_id=event["event_id"],assessments=[]),
            data=SimpleNamespace(spans=[SimpleNamespace(parent_id=None,outputs=event)]))
    # Model interruption after one of the two feedback writes as well as none.
    if size>1:traces["e-1"].info.assessments.append(SimpleNamespace(name="runtime/event_kind",span_id=None,value="test",error=None,source=SOURCE))
    def search(**kwargs):return [traces[kwargs["filter_string"].split("'")[1]]]
    def feedback(**kwargs):
        traces[kwargs["trace_id"]].info.assessments.append(SimpleNamespace(name=kwargs["name"],span_id=None,value=kwargs["value"],error=None,source=kwargs["source"]))
    monkeypatch.setattr("mlflow.search_traces",search)
    monkeypatch.setattr("mlflow.get_trace",traces.get)
    monkeypatch.setattr("mlflow.log_feedback",feedback)
    class Client:
        def call(self,path,value):
            if path=="/events":return dict(events=events[:100])
            assert path=="/acknowledge"
            assert events[0]["event_id"]==value["event_id"]
            events.pop(0);return {}
    if size<=4000:
        exported=export_outbox(Client(),"test-experiment")
        assert len(exported)==size and not events
    else:
        with pytest.raises(RuntimeError,match="exceeds bounded"):export_outbox(Client(),"test-experiment")
        assert len(events)==1


def test_incomplete_headers_have_deadline_and_release_all_worker_slots():
    server=BoundedServer(("127.0.0.1",0),lambda *_:{},request_deadline=0.1)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    clients=[]
    try:
        for _ in range(8):
            client=socket.create_connection(server.server_address,timeout=2)
            client.sendall(b"POST / HTTP/1.1\r\nX-Incomplete:")
            clients.append(client)
        for client in clients:assert client.recv(1)==b""
        acquired=0
        try:
            for _ in range(8):
                assert server.slots.acquire(timeout=2);acquired+=1
        finally:
            for _ in range(acquired):server.slots.release()
        with httpx.Client(timeout=2,trust_env=False) as client:
            assert client.get(f"http://127.0.0.1:{server.server_address[1]}/health").status_code==200
    finally:
        for client in clients:client.close()
        server.shutdown();server.server_close();thread.join(timeout=2)


@pytest.mark.parametrize("damage",["missing_kind","wrong_owner","duplicate_kind","different_root"])
def test_export_final_readback_must_verify_fresh_contents_and_both_scores(monkeypatch,damage):
    from src.banking_service.telemetry import export_outbox,SOURCE
    event=dict(event_id="e-1",kind="test",trial_id="trial",payload={})
    trace=SimpleNamespace(info=SimpleNamespace(trace_id="tr-1",assessments=[]),
        data=SimpleNamespace(spans=[SimpleNamespace(parent_id=None,outputs=event)]))
    reads=[]
    def get_trace(_):
        reads.append(True)
        result=deepcopy(trace)
        if len(reads)>1:
            if damage=="different_root":result.data.spans[0].outputs={}
            else:
                kind=next(a for a in result.info.assessments if a.name=="runtime/event_kind")
                if damage=="missing_kind":result.info.assessments.remove(kind)
                if damage=="wrong_owner":kind.source=SimpleNamespace(source_type="HUMAN",source_id="wrong")
                if damage=="duplicate_kind":result.info.assessments.append(deepcopy(kind))
        return result
    def feedback(**kwargs):
        trace.info.assessments.append(SimpleNamespace(name=kwargs["name"],span_id=None,value=kwargs["value"],error=None,source=SOURCE))
    class Client:
        def call(self,path,_):
            assert path=="/events","Invalid evidence must not be acknowledged"
            return dict(events=[event])
    monkeypatch.setattr("mlflow.search_traces",lambda **_: [trace])
    monkeypatch.setattr("mlflow.get_trace",get_trace)
    monkeypatch.setattr("mlflow.log_feedback",feedback)
    with pytest.raises(RuntimeError,match="ownership mismatch"):export_outbox(Client(),"experiment")


@pytest.mark.parametrize("value",[1,1.0])
def test_durable_export_rejects_numeric_boolean_substitutes(monkeypatch,value):
    from src.banking_service.telemetry import export_outbox,SOURCE
    event=dict(event_id="event",kind="test",trial_id="trial",payload={})
    scores=[SimpleNamespace(name=name,span_id=None,value=v,error=None,source=SOURCE) for name,v in
        (("runtime/event_kind","test"),("runtime/durable_event",value))]
    trace=SimpleNamespace(info=SimpleNamespace(trace_id="trace",assessments=scores),
        data=SimpleNamespace(spans=[SimpleNamespace(parent_id=None,outputs=event)]))
    monkeypatch.setattr("mlflow.search_traces",lambda **_:[trace]);monkeypatch.setattr("mlflow.get_trace",lambda _:trace)
    class Client:
        def call(self,path,_):
            assert path=="/events","Invalid boolean must not be acknowledged"
            return dict(events=[event])
    with pytest.raises(RuntimeError,match="assessment"):export_outbox(Client(),"experiment")


@pytest.mark.parametrize("kind,name",[("networkpolicies","banking-store"),("workerpools.ate.dev","banking")])
def test_setup_rejects_unowned_network_policy_and_workerpool(kind,name):
    from src.banking_service.deploy import require_owned_resources,LABELS
    class Cluster:
        def get(self,requested,*_):return dict(items=[dict(metadata=dict(name=name,labels={}))] if requested==kind else [])
    with pytest.raises(RuntimeError,match="unowned"):require_owned_resources(Cluster())


def test_owned_resource_labels_do_not_mutate_global_ownership():
    from src.banking_service.deploy import obj,LABELS
    first=obj("WorkerPool","banking")
    first["metadata"]["labels"]["workload"]="test"
    assert "workload" not in LABELS
    assert "workload" not in obj("Secret","banking-key")["metadata"]["labels"]


@pytest.mark.parametrize("damage",["failed","wrong_experiment","wrong_protocol","changed_image","changed_template","missing_audit"])
def test_live_preflight_binds_successful_controls_to_protocol_and_deployment(damage):
    from src.banking_service.live import validate_controls
    from src.banking_service.runtime_controls import EXTRA_CASES
    from src.banking_contracts.tools import READ_TOOLS,WRITE_TOOLS
    expected={"valid_"+n for n in READ_TOOLS|WRITE_TOOLS}|set(EXTRA_CASES)
    summary=dict(full_runtime_controls_passed=True,cases=len(expected),expected_cases=len(expected))
    run=SimpleNamespace(status="FINISHED",experiment_id="3")
    protocol=dict(protocol="banking-runtime-controls-v1",cases=len(expected),case_ids=sorted(expected))
    audit=[dict(case_id=n,passed=True) for n in sorted(expected)]
    manifest=dict(image="image@sha256:test",template="test-template",space="test",namespace="test")
    current=deepcopy(manifest)
    validate_controls(summary,run,protocol,audit,manifest,current,"3")
    if damage=="failed":run.status="FAILED"
    if damage=="wrong_experiment":run.experiment_id="other"
    if damage=="wrong_protocol":protocol["protocol"]="other"
    if damage=="changed_image":current["image"]="different"
    if damage=="changed_template":current["template"]="different"
    if damage=="missing_audit":audit.pop()
    with pytest.raises(ValueError):validate_controls(summary,run,protocol,audit,manifest,current,"3")


def test_live_provider_budget_and_final_summary_cannot_hide_export_failure():
    from src.banking_service.live import validate_judge_provider,live_summary
    validate_judge_provider("gemini:/gemini-2.5-flash")
    for model in ("openai:/gpt-4","anthropic:/claude","gemini:/",None):
        with pytest.raises(ValueError):validate_judge_provider(model)
    from src.feasibility.banking import TASK_IDS
    from src.feasibility.metrics_contract import CRITERIA
    records=[dict(case_id="actor-agent-"+task,measured=dict(utility=False)) for task in TASK_IDS]
    reviews=[dict(case_id=record["case_id"],criterion=criterion) for record in records for criterion in CRITERIA]
    assert live_summary(records,reviews,True,True)["passed"] is True
    assert live_summary(records,reviews,True,False)["passed"] is False
    assert live_summary([],[],True,True)["passed"] is False


def test_native_judge_attempt_and_result_are_durably_observed(monkeypatch):
    from src.banking_service.live import review_durably
    events=[]
    class Client:
        def call(self,path,value):
            assert path=="/client-event";events.append(value);return {}
    def review(*_):
        assert events[-1]["payload"]["operation_kind"]=="judge_attempt"
        return dict(value="satisfied",judge_trace_id="trace-judge")
    monkeypatch.setattr("src.banking_service.live.review",review)
    result=review_durably(Client(),SimpleNamespace(model="gemini:/gemini-2.5-flash"),"utility",
        dict(trace_id="trace-case",evidence=dict(evidence_id="trial-1/observed-state")))
    assert result["value"]=="satisfied"
    assert [e["payload"]["operation_kind"] for e in events]==["judge_attempt","judge_result"]
    assert all(e["trial_id"]=="trial-1" for e in events)


@pytest.mark.parametrize("damage",["unobserved","incomplete","old_pod_image","old_image_id","not_ready","terminating","extra_pod"])
def test_live_preflight_requires_completed_rollout_and_actual_serving_image(damage):
    from src.banking_service.deploy import verify_store_rollout,LABELS
    image="localhost/test@sha256:validated"
    deployment=dict(metadata=dict(generation=2),spec=dict(replicas=1),status=dict(observedGeneration=2,
        replicas=1,updatedReplicas=1,readyReplicas=1,availableReplicas=1))
    pod=dict(metadata=dict(uid="pod-uid",labels=dict(LABELS)),spec=dict(containers=[dict(name="store",image=image)]),
        status=dict(phase="Running",conditions=[dict(type="Ready",status="True")],containerStatuses=[dict(name="store",ready=True,imageID=image)]))
    assert verify_store_rollout(deployment,[pod],image)==pod
    pods=[pod]
    if damage=="unobserved":deployment["status"]["observedGeneration"]=1
    if damage=="incomplete":deployment["status"]["updatedReplicas"]=0
    if damage=="old_pod_image":pod["spec"]["containers"][0]["image"]="other"
    if damage=="old_image_id":pod["status"]["containerStatuses"][0]["imageID"]="other"
    if damage=="not_ready":pod["status"]["containerStatuses"][0]["ready"]=False
    if damage=="terminating":pod["metadata"]["deletionTimestamp"]="now"
    if damage=="extra_pod":pods.append(deepcopy(pod))
    with pytest.raises(RuntimeError):verify_store_rollout(deployment,pods,image)


def test_exact_local_replay_restores_only_pinned_public_schema_declarations():
    from src.banking_service.diagnose import replay_request
    from src.banking_service.agent import canonical_suite_view
    from src.feasibility.agent import tool_specs
    from src.feasibility.banking import load_suite,serializable
    tools=tool_specs(canonical_suite_view(load_suite()))
    original=dict(model="local-model",max_output_tokens=2048,input=[dict(role="user",content="Synthetic request")],tools=tools)
    exported=serializable(original)
    assert replay_request(exported,tools)==original
    with pytest.raises(ValueError):replay_request(dict(exported,input=[dict(role="user",content="[REDACTED]")]),tools)


def test_parser_failed_rent_argument_shape_is_valid_for_the_banking_boundary():
    # This validates the recorded shape only; do not execute a call reconstructed
    # from a provider log or substitute it for a failed agent trial.
    result=evaluate(dict(tool_name="update_scheduled_transaction",arguments=dict(id=7,amount="1200.0",subject="Rent (Increased)")),initial_state())
    assert result["error"] is None
    assert next(t for t in result["state"]["bank_account"]["scheduled_transactions"] if t["id"]==7)["amount"]==1200.0


def test_receipt_columns_belong_to_exact_tool_span_and_are_idempotent(world,monkeypatch):
    from src.banking_service.telemetry import log_receipt_scores
    store,_=world
    receipt=complete(store,proposal())["result"]["receipt"]
    action=dict(span_id="tool-span",execution_receipt=receipt)
    trace=SimpleNamespace(data=SimpleNamespace(spans=[SimpleNamespace(span_id="tool-span",span_type="TOOL",outputs=action)]),
        info=SimpleNamespace(assessments=[]))
    monkeypatch.setattr("mlflow.get_trace",lambda _:trace)
    def feedback(**kw):trace.info.assessments.append(SimpleNamespace(span_id=kw["span_id"],name=kw["name"],value=kw["value"],error=None,source=kw["source"]))
    monkeypatch.setattr("mlflow.log_feedback",feedback)
    record=dict(trace_id="trace",evidence=dict(actions=[action]))
    log_receipt_scores(record);log_receipt_scores(record)
    assert len(trace.info.assessments)==4
    assert next(a.value for a in trace.info.assessments if a.name=="tool/executed") is True
    assert next(a.value for a in trace.info.assessments if a.name=="tool/state_version_before_exact")=="0"
    trace.data.spans[0].outputs={}
    with pytest.raises(RuntimeError,match="does not belong"):log_receipt_scores(record)
