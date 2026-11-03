from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta,timezone
import json
import sqlite3

import pytest

from src.banking_contracts.codec import ContractError
from src.banking_contracts.models import PolicyProfile,TrustedContext
from src.banking_contracts.tools import ToolCatalog
from src.banking_service.app import StoreApplication
from src.banking_service.store import StateStore
from src.banking_service.upstream import initial_state


@pytest.fixture
def store(tmp_path):return StateStore(tmp_path/"state.sqlite",b"k"*32,max_trials=256)


def context(name):
    return TrustedContext(context_version=1,principal_id="driver",interaction_id=name,trial_id=name,actor_id="actor-"+name,
        actor_generation=1,state_version=0,intent_id=name,intent_version=1,user_request="synthetic",
        policy=PolicyProfile(policy_id="test",policy_version=1,allowed_tools=("get_balance",)),
        expires_at=datetime.now(timezone.utc)+timedelta(hours=1),authority_kind="service-owned")


def proposal():return dict(schema_version="banking-action-v1",action_id="a",idempotency_key="i",expected_context_version=1,
    expected_actor_generation=1,expected_state_version=0,tool_name="get_balance",arguments={})


def reserve(store,**overrides):
    return store.reserve_capacity("driver","campaign","a"*64,dict(dict(trials=3,actions=10,events=30),**overrides))


def test_capacity_is_read_only_authenticated_and_contains_no_bank_payload(store,monkeypatch):
    store.create(context("old"),"uid",initial_state());before=store.snapshot("old","driver")
    monkeypatch.setattr(store,"transaction",lambda:pytest.fail("readiness attempted a write transaction"))
    view=store.capacity();assert view["used"]["trials"]==1 and view["limits"]["trials"]==256
    assert "state" not in json.dumps(view) and "user_request" not in json.dumps(view)
    class Identity:
        def driver(self,auth):
            if auth!="driver":raise ContractError("unauthenticated","auth")
            return "driver"
    app=StoreApplication(store,Identity())
    assert app("/capacity",{},"driver")==view
    with pytest.raises(ContractError,match="unauthenticated"):app("/capacity",{},"wrong")


def test_default_and_bounded_trial_capacity_preserve_history(tmp_path):
    old=StateStore(tmp_path/"db",b"k"*32,max_trials=1);old.create(context("one"),"u1",initial_state())
    before=old.snapshot("one","driver")
    with pytest.raises(ContractError,match="trial_capacity"):old.create(context("two"),"u2",initial_state())
    new=StateStore(old.path,b"k"*32,max_trials=256)
    assert new.snapshot("one","driver")==before
    new.create(context("two"),"u2",initial_state());assert new.capacity()["used"]["trials"]==2
    assert StateStore(tmp_path/"legacy",b"k"*32).max_trials==100
    for invalid in (0,4097,True,"256"):
        with pytest.raises(ContractError,match="invalid_trial_capacity"):StateStore(tmp_path/"bad",b"k"*32,max_trials=invalid)


def test_campaign_blocks_competing_consumption_and_persists_usage(store):
    store.create(context("old"),"old",initial_state());reserve(store)
    with pytest.raises(ContractError,match="campaign_required"):store.create(context("outside"),"outside",initial_state())
    with pytest.raises(ContractError,match="campaign_required"):store.fence("old","driver")
    assert store.snapshot("old","driver")["status"]=="active"
    store.create(context("new"),"new",initial_state(),campaign_id="campaign")
    reopened=StateStore(store.path,b"k"*32,max_trials=256)
    assert reserve(reopened)["campaign"]["used"]==dict(trials=1,actions=0,events=1)
    with pytest.raises(ContractError,match="reservation_conflict"):reopened.reserve_capacity("driver","campaign","b"*64,dict(trials=3,actions=10,events=30))
    with pytest.raises(ContractError,match="unknown_capacity"):reopened.release_capacity("other","campaign")


def test_reservation_exhaustion_rolls_back_action_and_all_counters(store):
    reserve(store,events=1);store.create(context("new"),"new",initial_state(),campaign_id="campaign")
    before=store.capacity()
    with pytest.raises(ContractError,match="campaign_exhausted"):store.prepare("new","driver",proposal())
    assert store.capacity()==before
    with store.transaction() as db:assert db.execute("SELECT count(*) FROM actions").fetchone()[0]==0


def test_entire_campaign_headroom_and_concurrent_reservation_fail_closed(store):
    with pytest.raises(ContractError,match="insufficient"):reserve(store,trials=257)
    def attempt(i):
        try:store.reserve_capacity("driver","campaign-"+str(i),"a"*64,dict(trials=42,actions=192,events=1200));return "ok"
        except ContractError as exc:return exc.code
    with ThreadPoolExecutor(max_workers=2) as pool:values=list(pool.map(attempt,range(2)))
    assert values.count("ok")==1 and values.count("capacity_campaign_busy")==1


def test_capacity_reflects_action_outbox_and_pending_commit_headroom(store):
    reserve(store);store.create(context("new"),"new",initial_state(),campaign_id="campaign")
    store.prepare("new","driver",proposal());view=store.capacity()
    assert view["used"]==dict(trials=1,actions=1,events=2) and view["pending_event_slots"]==2
    assert view["available"]["events"]==3996
    store.release_capacity("driver","campaign")
    assert store.capacity()["campaign"] is None


def test_repeatable_demo_has_no_retained_trial_or_action_cap(tmp_path):
    store=StateStore(tmp_path/"demo",b"k"*32,max_trials=1,max_actions=1,repeatable_demo=True)
    for index in range(5):
        name="repeat-"+str(index)
        store.create(context(name),"uid-"+name,initial_state())
        store.prepare(name,"driver",proposal());store.fence(name,"driver")
    view=store.capacity()
    assert view["repeatable_demo"] and view["used"]["trials"]==view["used"]["actions"]==5
    assert view["limits"]["trials"] is view["limits"]["actions"] is None
    assert view["limits"]["events"]==4000  # Backpressure is not a spending budget.
    with pytest.raises(ContractError,match="demo_has_no_capacity_campaigns"):reserve(store)


def test_repeatable_mode_preserves_history_key_and_old_campaign_used_counts(store):
    reserve(store);store.create(context("prior"),"prior-uid",initial_state(),campaign_id="campaign")
    before=store.snapshot("prior","driver");used=store.capacity()["campaign"]["used"]
    demo=StateStore(store.path,b"k"*32,repeatable_demo=True)
    assert demo.snapshot("prior","driver")==before and demo.capacity()["campaign"] is None
    with demo.transaction() as db:
        row=db.execute("SELECT status,used FROM capacity_campaigns WHERE id='campaign'").fetchone()
        assert row["status"]=="released" and json.loads(row["used"])==used


def test_repeatable_mode_refuses_unresolved_actions_and_keeps_evidence_backpressure(store,tmp_path):
    store.create(context("pending"),"pending-uid",initial_state());store.prepare("pending","driver",proposal())
    with pytest.raises(ContractError,match="demo_actions_inflight"):
        StateStore(store.path,b"k"*32,repeatable_demo=True)
    demo=StateStore(tmp_path/"full",b"k"*32,max_events=1,repeatable_demo=True)
    demo.create(context("one"),"uid-one",initial_state())
    with pytest.raises(ContractError,match="evidence_outbox_full"):
        demo.create(context("two"),"uid-two",initial_state())
