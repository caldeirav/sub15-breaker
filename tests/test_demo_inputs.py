import json
from copy import deepcopy

from src.benchmark.admission import ReviewBuilder
from src.benchmark.projection import RECORD_FIELDS
from src.benchmark.wiring import fixture_messages
from src.banking_service.dataset_replay import canonical_calls
from src.banking_service.upstream import evaluate,environment_model
from src.integrations.agentdojo.banking import BankingAdapter,TASKS


def test_schema_order_matches_pinned_transaction_fields():
    a=BankingAdapter();state=a.suite.load_and_inject_default_environment({})
    assert tuple(type(state.bank_account.transactions[0]).model_fields)==RECORD_FIELDS


def test_all_reference_steps_match_after_actual_reads_and_store_roundtrip():
    adapter=BankingAdapter();builder=ReviewBuilder(lambda text,**kw:{"input_ids":list(text.split())})
    for task_id in TASKS:
        episode=adapter.episode(task_id,"fixture");state=episode.initial_state.model_dump(mode="json");actions=[]
        calls=canonical_calls(episode.task,episode.initial_state,adapter.catalog)
        messages=fixture_messages(calls)
        assert len({m.tool_calls[0]["id"] for m in messages[:-1]})==len(calls)
        for call in calls:
            snapshot=dict(context=dict(user_request=episode.public.prompt),state=state)
            memory=builder(snapshot,call["tool_name"],call["arguments"],actions)
            stored=builder(json.loads(json.dumps(snapshot,sort_keys=True)),call["tool_name"],call["arguments"],json.loads(json.dumps(actions,sort_keys=True)))
            assert memory.supported and stored.value.digest()==memory.value.digest()
            result=evaluate(call,deepcopy(state));assert result["error"] is None
            actions.append(dict(tool=call["tool_name"],arguments=call["arguments"],output=result["output"],status="executed"));state=result["state"]
        if task_id=="user_task_2":assert isinstance(calls[-1]["arguments"]["amount"],str)
