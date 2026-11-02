"""Read-only report integrity checks with synthetic evidence; never run a campaign."""
import hashlib
import json

import pytest

from validation.live_ui_report import render


@pytest.fixture
def evidence(tmp_path):
    results=[]
    for i in range(1,6):
        summary=dict(golden_pass=i!=1,expected="allow",observed="block" if i==1 else "allow",
            timing=dict(classifier_core=None,guard_whole_review=None),run_id="fixture",trace_id="fixture")
        results.append(dict(id=str(i),card=f"D0{i}",phase="completed",order=["classifier","llm"],
            lanes={arm:dict(summary=summary) for arm in ("classifier","llm")},
            external_review=dict(verdict="not_supported" if i==1 else "supported")))
    proof=dict(passed=True,mode="live",runIds=[r["id"] for r in results])
    (tmp_path/"proof.json").write_text(json.dumps(proof))
    (tmp_path/"results.json").write_text(json.dumps(results))
    final=dict(campaign="ui1",date="fixture",runtime_source="fixture",preservation_verified=True,
        resources_restored=True,no_actors_remaining=True,measured_classifier_core_raw_ms={"D02":[1025.966]},
        priming_forwards=10,startup_model_requests=2,startup_metrics=dict(load_ms=1,first_priming_core_ms=2,elapsed_ms=3),
        campaign_local=26,campaign_external=21,accounting=dict(local=358,external=223,accounted_with_holds_usd="79.0755570"),
        allocation_sha256="fixture",parent_run_id="fixture",image="fixture")
    for name in ("proof","results"):
        final[f"browser_{name}_sha256"]=hashlib.sha256((tmp_path/f"{name}.json").read_bytes()).hexdigest()
    return tmp_path,final


def test_renderer_preserves_negative_golden_and_review_outcomes(evidence):
    browser,final=evidence
    text=render(browser,final)
    assert "| D01 | classifier → llm | FAIL; expected allow, observed block" in text
    assert "not_supported" in text and "1025.966" in text
    assert text==render(browser,final)


@pytest.mark.parametrize("name",["proof","results"])
def test_renderer_rejects_changed_browser_evidence(evidence,name):
    browser,final=evidence
    path=browser/f"{name}.json"
    path.write_text(path.read_text()+"\n")
    with pytest.raises(ValueError,match="hash_binding_changed"):render(browser,final)


def test_renderer_requires_final_restoration_and_preservation(evidence):
    browser,final=evidence
    final["resources_restored"]=False
    with pytest.raises(ValueError,match="cleanup_proof_required"):render(browser,final)
