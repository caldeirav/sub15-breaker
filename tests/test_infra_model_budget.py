"""No refunds, hidden retries, resets or preferred-outcome replacement."""
from concurrent.futures import ThreadPoolExecutor
import json

import pytest

from src.infra.model_budget import record_outcome,reserve_probe


def reserve(path):
    return reserve_probe(path,case="fixture",run_id="run",trace_id="trace",request={"input":"synthetic"},profile_sha256="a"*64)


def test_probe_subcap_survives_concurrency_and_reopen(tmp_path):
    def attempt(_):
        try:return reserve(tmp_path)[0]
        except RuntimeError as exc:return str(exc)
    with ThreadPoolExecutor(max_workers=5) as pool:results=list(pool.map(attempt,range(12)))
    assert len([r for r in results if not isinstance(r,str)])==8
    assert results.count("local_probe_budget_exhausted")==4
    assert json.loads((tmp_path/"counter.json").read_text())=={"issued":8}
    with pytest.raises(RuntimeError,match="exhausted"):reserve(tmp_path)


def test_failed_or_unreturned_probe_stays_spent_and_outcome_is_immutable(tmp_path):
    path,entry=reserve(tmp_path)
    assert entry["reservation_spent"] is True
    record_outcome(path,{"status":"failed"})
    with pytest.raises(FileExistsError):record_outcome(path,{"status":"preferred-success"})
    second,_=reserve(tmp_path)
    assert second.name=="probe-0002.json"
    assert json.loads(path.with_suffix(".result.json").read_text())["outcome"]["status"]=="failed"


def test_deleted_or_partially_persisted_entries_block_new_dispatch(tmp_path):
    path,_=reserve(tmp_path)
    path.unlink()
    with pytest.raises(RuntimeError,match="differ"):reserve(tmp_path)


def test_changed_budget_policy_is_not_automatically_adopted(tmp_path):
    reserve(tmp_path)
    policy=tmp_path/"policy.json";value=json.loads(policy.read_text());value["probes"]=800
    policy.write_text(json.dumps(value))
    with pytest.raises(RuntimeError,match="policy_changed"):reserve(tmp_path)
