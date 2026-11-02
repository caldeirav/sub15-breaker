from types import SimpleNamespace as S
import json

import pytest

from src.benchmark.readiness_probe import freeze,exclusive,main


def test_probe_protocol_is_fixed_non_effectful_and_cannot_be_refrozen(monkeypatch,tmp_path):
    monkeypatch.setattr("src.benchmark.readiness_probe.DIRECTORY",tmp_path)
    (tmp_path/"deployment.json").write_text(json.dumps(dict(image="pinned",store_limits=dict(trials=256))))
    directory=tmp_path/"probes";plan=freeze(directory)
    assert plan["actors"]==4 and plan["readiness_observations_per_actor"]==2
    assert plan["native_hook_timeout_seconds"]==2 and plan["actor_store_timeout_seconds"]==5
    assert all(plan[key]==0 for key in ("model_requests","trial_creates","tools_called","automatic_retries"))
    with pytest.raises(FileExistsError):freeze(directory)
    exclusive(directory/"started.json",dict(started=True))
    with pytest.raises(FileExistsError):exclusive(directory/"started.json",dict(started=True))


def test_readiness_cli_cannot_return_success_for_failed_or_incomplete_batch(monkeypatch,tmp_path):
    monkeypatch.setattr("sys.argv",["readiness_probe",str(tmp_path),"--execute"])
    for result in (dict(fixed_batch_complete=True,failures=1),dict(fixed_batch_complete=False,failures=0)):
        monkeypatch.setattr("src.benchmark.readiness_probe.execute",lambda directory:result)
        with pytest.raises(SystemExit) as caught:main()
        assert caught.value.code==1
