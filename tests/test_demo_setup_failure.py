from contextlib import nullcontext
from types import SimpleNamespace as S

import pytest

from src.banking_contracts.codec import ContractError
from src.benchmark.wiring import run_case


def contexts(monkeypatch):
    spans=[]
    class Span:
        trace_id="trace"
        def set_inputs(self,value):pass
        def set_outputs(self,value):self.outputs=value
    def span(**kwargs):
        value=Span();value.name=kwargs["name"];spans.append(value);return nullcontext(value)
    monkeypatch.setattr("src.benchmark.wiring.mlflow.start_run",lambda **k:nullcontext(S(info=S(run_id="child",experiment_id="5"))))
    monkeypatch.setattr("src.benchmark.wiring.mlflow.start_span",span)
    monkeypatch.setattr("src.benchmark.wiring.runtime_proof",lambda *a:{})
    return spans


def test_failed_trial_creation_still_deletes_actor_and_preserves_partial_evidence(monkeypatch):
    spans=contexts(monkeypatch);deleted=[]
    actor=dict(metadata=dict(name="actor",uid="uid"))
    d=S(create_actor=lambda:actor,last_actor=None,delete_actor=lambda name:deleted.append(name))
    def call(path,body):
        assert path=="/create";raise ContractError("trial_capacity","runtime")
    with pytest.raises(ContractError) as caught:
        run_case(deployment=d,store=S(call=call),authorization="not-used",adapter=S(episode=lambda *a:S(public=S(prompt="synthetic"))),bridge=S(wait_idle=lambda t:True),mcp=None,budget=None,mask=None,task_id="user_task_0")
    assert deleted==["actor"] and caught.value.partial_record["actor_deleted"] is True
    assert caught.value.partial_record["trial_created"] is False and caught.value.partial_record["status"]=="setup_failed"
    cleanup=next(s.outputs for s in spans if s.name=="cleanup_substrate_actor")
    assert cleanup==dict(errors=[],deleted=True,trial_created=False,fence_required=False)


def test_capacity_gate_stops_before_actor_allocation(monkeypatch):
    contexts(monkeypatch)
    def create():pytest.fail("Actor allocated before capacity check")
    with pytest.raises(RuntimeError,match="capacity_not_ready"):
        run_case(deployment=S(create_actor=create,last_actor=None),store=S(call=lambda *a:dict(campaign=None)),authorization="not-used",
            adapter=None,bridge=None,mcp=None,budget=None,mask=None,task_id="user_task_0",capacity_campaign="campaign")
