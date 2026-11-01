"""A health check, a shortened timer or a recovered failure cannot pass the soak."""
import json

import pytest

from src.infra.stability import monitor


def clock():
    value=[0.0]
    return value,lambda:value[0],lambda seconds:value.__setitem__(0,value[0]+seconds)


def test_two_hours_requires_full_continuity_and_durable_samples(tmp_path):
    value,now,wait=clock()
    result=monitor(lambda:dict(boot="same",ready=True),tmp_path/"samples.jsonl",clock=now,wall=now,wait=wait)
    assert result["passed"] is True and result["elapsed_seconds"]==7200
    assert result["samples"]==241 and result["automatic_restarts"]==0
    assert all(row["passed"] for row in map(json.loads,(tmp_path/"samples.jsonl").read_text().splitlines()))


def test_short_diagnostic_cannot_be_called_full_acceptance(tmp_path):
    _,now,wait=clock()
    result=monitor(lambda:dict(ready=True),tmp_path/"samples.jsonl",seconds=60,clock=now,wall=now,wait=wait)
    assert result["passed"] is False and result["full_window"] is False


def test_reboot_or_one_failed_sample_is_retained_without_retry(tmp_path):
    value,now,wait=clock()
    calls=[]
    def probe():
        calls.append(now())
        return dict(boot="old" if now()==0 else "new")
    with pytest.raises(RuntimeError,match="without_recovery"):
        monitor(probe,tmp_path/"samples.jsonl",clock=now,wall=now,wait=wait)
    assert calls==[0,30]
    assert json.loads((tmp_path/"samples.jsonl").read_text().splitlines()[-1])["passed"] is False


def test_sampling_gap_or_host_sleep_cannot_count_as_continuous_observation(tmp_path):
    value,now,wait=clock()
    def oversleep(_):value[0]+=120
    with pytest.raises(RuntimeError,match="without_recovery"):
        monitor(lambda:dict(ready=True),tmp_path/"samples.jsonl",clock=now,wall=now,wait=oversleep)


def test_existing_timeline_is_never_reset_for_preferred_results(tmp_path):
    path=tmp_path/"samples.jsonl";path.write_text("retained failure\n")
    with pytest.raises(FileExistsError):monitor(lambda:{},path)
    assert path.read_text()=="retained failure\n"
