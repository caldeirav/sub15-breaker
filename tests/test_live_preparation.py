"""Operator preparation uses only offline fixtures: no models, cluster or judges."""
import json
import threading
from uuid import uuid4

import pytest

from src.demo_ui.state import Controller
from validation.live_ui_fixture_server import FixtureRuntime,plan


def test_prepare_is_once_only_without_card_review_or_run_ids(tmp_path):
    runtime=FixtureRuntime();opens=[];owner=[]
    original=runtime.open
    def opened(job):
        opens.append(job);owner.append(threading.get_ident());original(job)
    runtime.open=opened
    controller=Controller(plan(),tmp_path,lambda *args:runtime)
    try:
        future=controller.prepare();future.result(timeout=5)
        assert controller.prepare() is future
        assert controller.status()["ready"] and controller.status()["preparation"]["phase"]=="ready"
        assert len(opens)==1 and runtime.calls==[] and not list(controller.jobs_directory.iterdir())
        assert controller.repeats==dict.fromkeys(controller.repeats,0)
        saved=json.loads((controller.session_directory/"preparation/public.json").read_text())
        assert saved["kind"]=="preparation" and saved["card"] is None and saved["lanes"]=={}
        assert saved["phase"]=="completed" and saved["external_review"] is None
        assert owner[0]!=threading.get_ident()
    finally:controller.close()
    assert runtime.closed and not controller.status()["ready"]


def test_first_card_reuses_prepared_worker_without_startup(tmp_path):
    runtime=FixtureRuntime();threads=[];original=runtime.run_lane
    def lane(*args):
        threads.append(threading.get_ident());return original(*args)
    runtime.run_lane=lane
    controller=Controller(plan(),tmp_path,lambda *args:runtime)
    try:
        controller.prepare().result(timeout=5)
        worker=controller.worker.submit(threading.get_ident).result(timeout=5)
        job=controller.start("D02",uuid4().hex)
        controller.worker.submit(lambda:None).result(timeout=5)
        assert job.data["phase"]=="completed"
        assert runtime.calls==[("D02","llm"),("D02","classifier")]
        assert threads==[worker,worker]
        assert not any(e["lane"] in {"startup","setup"} for e in job.events)
    finally:controller.close()


def test_prepare_failure_is_not_ready_retains_evidence_and_never_retries(tmp_path):
    runtime=FixtureRuntime();attempts=[]
    def failed(job):
        attempts.append(True);raise RuntimeError("private provider detail")
    runtime.open=failed
    controller=Controller(plan(),tmp_path,lambda *args:runtime)
    try:
        with pytest.raises(RuntimeError):controller.prepare().result(timeout=5)
        assert controller.status()["halted"] and not controller.status()["ready"]
        assert controller.status()["preparation"]["phase"]=="failed"
        assert (controller.session_directory/"preparation/failure.json").exists()
        saved=(controller.session_directory/"preparation/public.json").read_text()
        assert "private provider detail" not in saved and json.loads(saved)["phase"]=="failed"
        with pytest.raises(RuntimeError):controller.start("D01",uuid4().hex)
        with pytest.raises(RuntimeError):controller.prepare()
        assert attempts==[True] and runtime.calls==[]
    finally:controller.close()
    assert runtime.closed


def test_pending_prepare_blocks_new_runs_and_shutdown_drains_it(tmp_path):
    runtime=FixtureRuntime();started=threading.Event();release=threading.Event();closed=threading.Event()
    def prepare(job):
        started.set();assert release.wait(5)
    runtime.open=prepare
    controller=Controller(plan(),tmp_path,lambda *args:runtime)
    closer=None
    try:
        future=controller.prepare();assert started.wait(3)
        assert controller.prepare() is future
        with pytest.raises(RuntimeError,match="preparation_in_progress"):
            controller.start("D01",uuid4().hex)
        assert not list(controller.jobs_directory.iterdir()) and not controller.status()["ready"]
        def close():controller.close();closed.set()
        closer=threading.Thread(target=close);closer.start()
        assert not closed.wait(.05)
    finally:
        release.set()
        if closer:closer.join(5)
        else:controller.close()
    assert closed.is_set() and runtime.closed


@pytest.mark.parametrize("prepare",[False,True])
def test_cli_serves_only_after_requested_preparation_and_always_closes(tmp_path,monkeypatch,capsys,prepare):
    from src.demo_ui import __main__ as cli
    runtime=FixtureRuntime();controllers=[]
    def controller(*args):
        value=Controller(*args);controllers.append(value);return value
    monkeypatch.setattr(cli,"ROOT",tmp_path)
    monkeypatch.setattr(cli,"make_plan",lambda artifact:plan())
    monkeypatch.setattr(cli,"Controller",controller)
    monkeypatch.setattr(cli,"Runtime",lambda *args:runtime)
    def serve(app,**kwargs):
        assert runtime.opened==prepare and controllers[0].status()["ready"]==prepare
        assert runtime.calls==[]
    monkeypatch.setattr(cli.uvicorn,"run",serve)
    monkeypatch.setattr("sys.argv",["demo",*(["--prepare"] if prepare else [])])
    cli.main()
    output=capsys.readouterr().out
    assert ("Demo ready —" in output)==prepare
    assert runtime.closed==prepare and controllers[0].closing


def test_cli_does_not_serve_after_failed_preparation(tmp_path,monkeypatch,capsys):
    from src.demo_ui import __main__ as cli
    runtime=FixtureRuntime()
    def fail(job):raise RuntimeError("deliberate offline failure")
    runtime.open=fail
    monkeypatch.setattr(cli,"ROOT",tmp_path)
    monkeypatch.setattr(cli,"make_plan",lambda artifact:plan())
    monkeypatch.setattr(cli,"Runtime",lambda *args:runtime)
    monkeypatch.setattr(cli.uvicorn,"run",lambda *a,**kw:pytest.fail("Failed preparation served the UI"))
    monkeypatch.setattr("sys.argv",["demo","--prepare"])
    with pytest.raises(SystemExit) as error:cli.main()
    assert error.value.code==1 and runtime.closed
    output=capsys.readouterr()
    assert "Demo ready —" not in output.out and "preparation failed" in output.err
def test_cleanup_failure_is_retained_and_not_swallowed_by_second_close(tmp_path):
    runtime=FixtureRuntime()
    def fail():raise RuntimeError("private upstream details must not be exposed")
    runtime.close=fail
    controller=Controller(plan(),tmp_path,lambda *args:runtime)
    controller.prepare().result()
    with pytest.raises(RuntimeError,match="live_cleanup_failed_inspect_private_evidence"):
        controller.close()
    with pytest.raises(RuntimeError,match="live_cleanup_failed_inspect_private_evidence"):
        controller.close()
    evidence=(controller.session_directory/"cleanup-failure.json").read_text()
    assert "RuntimeError" in evidence and "upstream details" not in evidence
