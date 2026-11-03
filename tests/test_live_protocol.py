"""Repeatable demo has no allocations, ledger prerequisites or spending gates."""
from copy import deepcopy
from uuid import uuid4

from src.demo_ui import protocol
from src.demo_ui.protocol import UsageLog,make_pair


def test_protocol_reuses_inputs_but_removes_benchmark_allocations(tmp_path,monkeypatch):
    base=dict(namespace="nd13",policy_sha256="old",capacity={"campaign_id":"old"},
        measurement_protocol={},rehearsal_of=None,fixtures={},startup_inputs=[])
    monkeypatch.setattr("src.benchmark.demo.make_plan",lambda *a,**kw:deepcopy(base))
    monkeypatch.setattr(protocol,"source_hashes",lambda:{"unit.py":"a"*64})
    value=protocol.make_plan(tmp_path/"artifact")
    assert not value["budget_enforced"]
    assert not any(k in value for k in ("namespace","capacity","policy_sha256","slots"))
    assert len(value["cases"])==10
    assert {c["kind"] for c in value["cases"]}=={"control","canary","startup"}


def test_every_click_has_new_cases_and_repeated_cards_alternate_first_arm():
    first=make_pair("D01",uuid4().hex,0);second=make_pair("D01",uuid4().hex,1)
    assert first["order"]==["classifier","llm"] and second["order"]==["llm","classifier"]
    assert not {c["case_id"] for c in first["cases"]}&{c["case_id"] for c in second["cases"]}
    for card in ("D04","D05"):
        assert all(c["producer"]=="fault_control" for c in make_pair(card,uuid4().hex,0)["cases"][:2])


def test_usage_journal_observes_without_any_call_or_cost_cap(tmp_path):
    journal=UsageLog(tmp_path/"usage")
    for _ in range(70):
        entry=journal.reserve(role="actor",case_id="same-case",trace_id="trace",model="local",request={})
        assert not entry["budget_enforced"] and "cost_hold_usd" not in entry
    entry=journal.reserve(role="gemini_harness_judge",case_id="review",trace_id="trace",model="external")
    journal.settle(entry["sequence"],accounted_cost_usd="1000",usage_verified=False)
    assert len(journal.entries())==71
    assert not list(tmp_path.glob("live-demo-*.json"))
