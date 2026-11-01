import json

import pytest

from src.integrations.agentdojo.banking import BankingAdapter,TASKS
from src.integrations.agentdojo.inventory import components,inventory,write_packet


def test_pinned_inventory_is_unlabeled_offline_and_does_not_expand_live_tasks(monkeypatch):
    from agentdojo.functions_runtime import FunctionsRuntime
    monkeypatch.setattr(FunctionsRuntime,"run_function",lambda *args,**kw:pytest.fail("inventory executed a tool"))
    summary,tasks,rows,state=inventory(BankingAdapter())
    assert summary["offline_user_tasks"]==16 and summary["attack_families"]==9
    assert summary["errors"]==[]
    assert summary["reference_candidates"]==33 and summary["attack_origin_candidates"]==192
    assert summary["candidates"]==225 and summary["requires_prefix_replay"]==36
    assert summary["training_eligible"]==0 and summary["split_status"]=="not_frozen"
    assert all(row["label"]=="pending_review" and not row["training_eligible"] for row in rows)
    assert len(summary["all_cross_product_groups"])==1
    assert summary["live_task_ids"]==list(TASKS)
    assert state["user_account"]["password"]=="[WITHHELD]"
    assert any(row["task_id"]=="user_task_2" and row["action"]["arguments"].get("amount")=="1200" for row in rows)


def test_packet_is_private_and_never_overwrites(tmp_path):
    summary,tasks,rows,state=inventory(BankingAdapter())
    path=tmp_path/"packet"
    write_packet(path,summary,tasks,rows,state)
    assert (path.stat().st_mode&0o777)==0o700
    assert ((path/"annotation-review.csv").stat().st_mode&0o777)==0o600
    assert len((path/"candidates.jsonl").read_text().splitlines())==225
    with pytest.raises(FileExistsError):write_packet(path,summary,tasks,rows,state)


def test_shared_document_and_attack_families_are_not_random_row_splits():
    rows=[dict(task_id="one",document_refs=["shared"],attack_id="attack-a"),
        dict(task_id="two",document_refs=["shared"],attack_id="attack-b"),
        dict(task_id="three",document_refs=[],attack_id="attack-a")]
    assert len(components(rows,include_attacks=False))==2
    assert len(components(rows,include_attacks=True))==1
