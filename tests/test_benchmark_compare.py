import json

import pytest

from src.benchmark.compare import claim_case,comparison_matrix
from src.benchmark.campaign_budget import CampaignBudget
from src.integrations.agentdojo.inventory import digest


def test_matrix_binds_artifact_calibration_and_live_only_replay(tmp_path,monkeypatch):
    model=dict(calibration={"temperature":0.5,"threshold":0.7})
    monkeypatch.setattr("src.benchmark.compare.encoder_manifest",lambda *args,**kw:model)
    rows=[dict(candidate_id="allowed",task_id="user_task_0",projection_supported=True,unsafe_label=0,input_digest="a"*64),
        dict(candidate_id="offline",task_id="user_task_14",projection_supported=True,unsafe_label=0,input_digest="b"*64),
        dict(candidate_id="unknown",task_id="user_task_2",projection_supported=True,unsafe_label=None,input_digest="c"*64)]
    (tmp_path/"rows.jsonl").write_text("\n".join(json.dumps(row) for row in rows))
    (tmp_path/"coverage.json").write_text(json.dumps(dict(dataset_sha256=digest(rows))))
    matrix=comparison_matrix("unused",tmp_path,reviewer_model="pinned-local")
    assert matrix["artifact_manifest_sha256"]==digest(model)
    assert matrix["calibration_sha256"]==digest(model["calibration"])
    replay=[case for case in matrix["cases"] if case["phase"]=="paired_replay"]
    assert len(replay)==1 and replay[0]["candidate_id"]=="allowed"
    assert len([case for case in matrix["cases"] if case["phase"]=="episodes"])==6
    assert matrix["quality_status"]=="failed_transfer_false_block_target"


def test_zero_request_cases_still_cannot_silently_repeat(tmp_path):
    budget=CampaignBudget(tmp_path)
    claim_case(budget,"canary-classifier",{})
    with pytest.raises(FileExistsError):claim_case(budget,"canary-classifier",{})


@pytest.mark.parametrize("backend_timeout",[None,62])
def test_mcp_backend_deadline_is_explicit_and_distinct_from_route(tmp_path,backend_timeout):
    from types import SimpleNamespace
    from src.benchmark.deployment import configure_bridge
    class Cluster:
        def kubectl(self,*args,**kwargs):
            if args[:2]==("get","--raw"):
                return SimpleNamespace(stdout=json.dumps({"issuer":"unit"} if args[2].endswith("openid-configuration") else {"keys":[]}))
            return SimpleNamespace(stdout="")
    configure_bridge(Cluster(),tmp_path,"127.0.0.1",8172,request_timeout=70,backend_timeout=backend_timeout)
    objects=json.loads((tmp_path/"gateway-bridge.json").read_text())["items"]
    assert objects[1]["spec"]["rules"][0]["timeouts"]["request"]=="70s"
    if backend_timeout is None:assert "backend" not in objects[2]["spec"]
    else:assert objects[2]["spec"]["backend"]["http"]["requestTimeout"]=="62s"
