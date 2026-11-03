"""UI execution/auth/event regressions use only the explicit offline fixture."""
import json
from pathlib import Path
from types import SimpleNamespace as S
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.demo_ui.app import create_app
from src.demo_ui.state import Job,Controller
from validation.live_ui_fixture_server import FixtureController,FixtureRuntime,TOKEN,plan

ORIGIN="http://127.0.0.1:8091"


@pytest.fixture
def ui(tmp_path):
    runtime=FixtureRuntime()
    controller=FixtureController(plan(),tmp_path/"jobs",lambda *args:runtime)
    with TestClient(create_app(controller,TOKEN),base_url=ORIGIN) as client:
        yield client,controller,runtime


def login(client):
    response=client.post("/api/live/session",json=dict(token=TOKEN),headers={"Origin":ORIGIN})
    assert response.status_code==200
    assert "HttpOnly" in response.headers["set-cookie"] and "SameSite=strict" in response.headers["set-cookie"]
    return {"Origin":ORIGIN,"X-Demo-CSRF":response.json()["csrf"]}


def run(client,headers,card="D01",request_id=None):
    request_id=request_id or uuid4().hex
    return client.post("/api/live/runs",json=dict(card=card,request_id=request_id),headers=headers)


def finish(controller):controller.worker.submit(lambda:None).result(timeout=10)


def test_open_select_status_reconnect_are_read_only(ui):
    client,controller,runtime=ui
    for path in ("/","/assets/app.js","/assets/style.css"):
        response=client.get(path);assert response.status_code==200
        assert "no-store" in response.headers["cache-control"]
    headers=login(client)
    for _ in range(3):assert client.get("/api/live/status").status_code==200
    assert runtime.calls==[] and not runtime.opened
    assert not list(controller.jobs_directory.glob("*/public.json"))


def test_run_is_idempotent_and_arms_really_execute_sequentially(ui):
    client,controller,runtime=ui;headers=login(client);key=uuid4().hex
    response=run(client,headers,request_id=key);assert response.status_code==202
    again=run(client,headers,request_id=key);assert again.status_code==202 and again.json()["id"]==key
    finish(controller)
    result=client.get("/api/live/runs/"+key).json()
    assert result["phase"]=="completed" and runtime.calls==[("D01","classifier"),("D01","llm")]
    assert all(result["lanes"][arm]["summary"]["golden_pass"] for arm in ("classifier","llm"))
    second=run(client,headers,card="D01");assert second.status_code==202
    finish(controller)
    assert second.json()["id"]!=key
    assert runtime.calls[-2:]==[("D01","llm"),("D01","classifier")]
    assert len(list(controller.jobs_directory.glob("*/public.json")))==2
    events=controller.get(key).page(0)
    assert [e["sequence"] for e in events]==list(range(1,len(events)+1))
    assert max(i for i,e in enumerate(events) if e["lane"]=="classifier")<min(i for i,e in enumerate(events) if e["lane"]=="llm")


def test_other_card_cannot_start_while_pair_is_active(ui):
    client,controller,runtime=ui;headers=login(client)
    assert run(client,headers).status_code==202
    assert run(client,headers,card="D02").status_code==409
    finish(controller)
    assert run(client,headers,card="D02").status_code==202
    finish(controller)
    assert runtime.calls[-2:]==[("D02","llm"),("D02","classifier")]


@pytest.mark.parametrize("card",["D04","D05"])
def test_fault_cards_are_not_reported_as_model_latency_or_accuracy(ui,card):
    client,controller,runtime=ui;headers=login(client)
    response=run(client,headers,card=card);finish(controller)
    result=client.get("/api/live/runs/"+response.json()["id"]).json()
    assert all(lane["summary"]["fault_control"] and lane["summary"]["timing"]["guard_whole_review"] is None for lane in result["lanes"].values())


def test_session_origin_host_csrf_and_strict_body_gate_execution(ui):
    client,controller,runtime=ui
    assert run(client,{"Origin":ORIGIN}).status_code==401
    assert client.post("/api/live/session",json=dict(token=TOKEN)).status_code==403
    assert client.post("/api/live/session",json=dict(token=TOKEN),headers={"Origin":"http://evil.test"}).status_code==403
    assert client.post("/api/live/session",json=dict(token="é"*40),headers={"Origin":ORIGIN}).status_code==422
    assert client.get("/",headers={"Host":"evil.test"}).status_code==401
    headers=login(client)
    assert run(client,{"Origin":ORIGIN}).status_code==403
    assert client.post("/api/live/runs",json=dict(card="D01",request_id=uuid4().hex,path="/etc/passwd"),headers=headers).status_code==422
    assert client.post("/api/live/runs",json=dict(card="../../bad",request_id=uuid4().hex),headers=headers).status_code==422
    assert client.post("/api/live/runs",content="x"*5000,headers={**headers,"Content-Type":"application/json"}).status_code==413
    assert runtime.calls==[] and not runtime.opened


def test_sse_has_real_sequences_can_resume_and_does_not_repeat_execution(ui):
    client,controller,runtime=ui;headers=login(client)
    response=run(client,headers);key=response.json()["id"];finish(controller)
    before=list(runtime.calls)
    stream=client.get(f"/api/live/runs/{key}/events?after=2")
    assert stream.status_code==200 and "text/event-stream" in stream.headers["content-type"]
    assert "id: 1\n" not in stream.text and "id: 2\n" not in stream.text
    assert "event: complete" in stream.text and runtime.calls==before
    assert client.get(f"/api/live/runs/{key}/events?after=-1").status_code==400
    assert client.get(f"/api/live/runs/{key}/events",headers={"Last-Event-ID":"bad"}).status_code==400


def test_event_projection_never_exports_raw_credentials_arguments_or_state(tmp_path):
    job=Job(tmp_path/"job",dict(slot="unit",card="D01",order=["classifier","llm"]),uuid4().hex)
    job.emit("classifier",dict(stage="actor_dispatch",phase="finished",token="secret",arguments={"password":"secret"},
        state={"password":"secret"},actor_timings={"claim_roundtrip_ns":123,"password":"secret"}))
    text=(job.directory/"events.jsonl").read_text()
    assert "secret" not in text and "password" not in text and "arguments" not in text
    assert job.events[0]["actor_timings"]==dict(claim_roundtrip_ns=123)


def test_failure_halts_session_preserves_history_and_closes_runtime(tmp_path):
    runtime=FixtureRuntime()
    def fail(*args):raise RuntimeError("test failure")
    runtime.run_lane=fail
    controller=Controller(plan(),tmp_path/"jobs",lambda *args:runtime)
    try:
        job=controller.start("D01",uuid4().hex);finish(controller)
        assert job.snapshot()["phase"]=="failed" and controller.status()["halted"]
        assert job.snapshot()["lanes"]["classifier"]["phase"]=="failed"
        assert "test failure" not in json.dumps(job.snapshot())
        assert (job.directory/"failure.json").is_file()
        assert len(list(controller.jobs_directory.glob("*/public.json")))==1
        with pytest.raises(RuntimeError):controller.start("D02",uuid4().hex)
    finally:controller.close()
    assert runtime.closed


def test_static_ui_is_accessible_text_only_and_has_no_automatic_run_post():
    static=Path(__file__).resolve().parents[1]/"src/demo_ui/static"
    script=(static/"app.js").read_text();html=(static/"index.html").read_text();css=(static/"style.css").read_text()
    assert ".innerHTML" not in script and "eval(" not in script and "localStorage" not in script
    assert "aria-label=\"Demo scenarios\"" in html and "aria-live=\"polite\"" in html
    assert ":focus-visible" in css and "@media" in css
    assert '$("#run").addEventListener("click"' in script
    assert "Classifier decision core" in script and "Whole decision-guard review" in script
    assert "Waiting for its frozen turn" not in script
    assert "Startup in progress:" in script and "Latest startup observation:" in script
    assert 'closest("details").open=true' in script and "This route did not complete" in script


def test_repeated_runs_are_unlimited_and_do_not_modify_historical_allocations(tmp_path):
    history=tmp_path/"combined-budget";history.mkdir();original=b'{"spent":true}'
    (history/"live-demo-ui1.json").write_bytes(original)
    runtime=FixtureRuntime()
    # No delay: exercise many explicit runs without inference or budget files.
    original_lane=runtime.run_lane
    def quick_lane(*args):
        from unittest.mock import patch
        with patch("validation.live_ui_fixture_server.time.sleep"):
            return original_lane(*args)
    runtime.run_lane=quick_lane
    controller=Controller(plan(),tmp_path/"demo",lambda *args:runtime)
    try:
        for _ in range(12):
            job=controller.start("D01",uuid4().hex);finish(controller)
            assert job.snapshot()["phase"]=="completed"
        assert len(runtime.calls)==24
        assert controller.status()["repeatable"] and not controller.status()["budget_enforced"]
    finally:controller.close()
    assert (history/"live-demo-ui1.json").read_bytes()==original


def test_restart_keeps_old_results_and_idempotency_without_reexecuting(tmp_path):
    directory=tmp_path/"demo";first=FixtureRuntime()
    controller=Controller(plan(),directory,lambda *args:first)
    job=controller.start("D01",uuid4().hex);finish(controller);controller.close()
    second=FixtureRuntime();controller=Controller(plan(),directory,lambda *args:second)
    try:
        assert controller.get(job.data["id"]).snapshot()["phase"]=="completed"
        assert controller.start("D01",job.data["id"]).snapshot()["id"]==job.data["id"]
        assert not second.opened and second.calls==[]
        new=controller.start("D01",uuid4().hex);finish(controller)
        assert new.data["order"]==["llm","classifier"]
    finally:controller.close()


def test_source_failure_explains_restart_without_leaking_arbitrary_errors(tmp_path):
    runtime=FixtureRuntime()
    original_lane=runtime.run_lane
    def changed(job,arm,spec):
        if arm=="classifier":raise RuntimeError("demo_source_changed_restart_server")
        return original_lane(job,arm,spec)
    runtime.run_lane=changed
    controller=Controller(plan(),tmp_path/"demo",lambda *args:runtime)
    try:
        job=controller.start("D02",uuid4().hex);finish(controller)
        result=job.snapshot()
        assert result["error_code"]=="demo_source_changed_restart_server"
        assert "restart" in result["error_message"]
        assert result["lanes"]["llm"]["phase"]=="completed"
        assert result["lanes"]["classifier"]["phase"]=="failed"
    finally:controller.close()
