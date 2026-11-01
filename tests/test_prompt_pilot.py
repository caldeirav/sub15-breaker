from copy import deepcopy
import json

import pytest

from src.benchmark.prompt_pilot import GOALS,Goals,Documents,code_facts_review_packet,corrected_plan,import_review,plan,prompt_for,provider_schema,review_html,template_issues,validate_reply
from src.integrations.agentdojo.inventory import digest


def packet():
    value=dict(schema_version="banking-v2-goal-packet-v1",candidates=[dict(candidate_id="goal-0",issues=[],source_goal=GOALS["refund"],proposed_goal=GOALS["refund"],training_eligible=False)])
    value["packet_sha256"]=digest(value);return value


def review(value):return dict(schema_version="banking-v2-goal-review-v1",packet_sha256=value["packet_sha256"],reviewer="owner",
    reviewed_at="2026-11-01T23:00:00Z",decisions=[dict(candidate_id="goal-0",decision="approved",rationale="All constraints preserved")])


def test_goal_paraphrases_are_pending_even_if_structurally_valid():
    accepted,rejected=validate_reply(dict(kind="goal",family="refund",case_id="pilot"),json.dumps(dict(goals=[GOALS["refund"]]*8)))
    assert len(accepted)==1 and len(rejected)==7
    assert accepted[0]["review_status"]=="pending" and accepted[0]["training_eligible"] is False


def test_placeholder_checks_do_not_claim_semantic_fidelity():
    changed=GOALS["refund"].replace("refund exactly that amount","refund twice that amount")
    assert not template_issues(changed,{"PAYEE":1},minimum=8,maximum=100)
    # Structural checks deliberately cannot approve this changed authorization.
    assert "placeholder_multiset_mismatch" in template_issues("Transfer {{UNKNOWN}}",{"PAYEE":1},minimum=1,maximum=100)


def test_human_approval_is_bound_to_packet_and_does_not_start_training():
    value=packet();accepted=import_review(value,review(value))
    assert len(accepted)==1 and accepted[0]["review_status"]=="approved" and not accepted[0]["training_eligible"]
    modified=deepcopy(value);modified["candidates"][0]["proposed_goal"]="Altered request"
    with pytest.raises(ValueError,match="packet_changed"):import_review(modified,review(value))
    bad=review(value);bad["decisions"]*=2
    with pytest.raises(ValueError,match="cardinality"):import_review(value,bad)


def test_structural_rejections_and_unknown_reviews_cannot_be_promoted():
    value=packet();value["candidates"][0]["issues"]=["missing_placeholder"]
    value["packet_sha256"]=digest({k:v for k,v in value.items() if k!="packet_sha256"})
    with pytest.raises(ValueError,match="cannot_be_approved"):import_review(value,review(value))
    decision=review(value);decision["decisions"][0]["decision"]="unknown"
    assert import_review(value,decision)==[]


def test_pilot_scope_and_untrusted_html_are_explicit():
    definition=plan({},{});assert len(definition["cases"])==12
    assert sum(case["kind"]=="goal" for case in definition["cases"])==4
    value=packet();value["candidates"][0]["proposed_goal"]="</script><script>untrusted</script>"
    html=review_html(value)
    assert "</script><script>untrusted" not in html and "textContent" in html


def test_provider_schema_fix_preserves_strict_local_parser():
    for schema in (Goals,Documents):
        assert "additionalProperties" in json.dumps(schema.model_json_schema())
        assert "additionalProperties" not in json.dumps(provider_schema(schema.model_json_schema()))
    with pytest.raises(ValueError):
        Goals.model_validate_json(json.dumps(dict(goals=[GOALS["refund"]]*8,extra_label="permitted")))


def test_corrected_pilot_changes_wire_and_ids_without_resampling_prompt_design():
    original=plan({},{});fixed=corrected_plan({},{},original)
    assert original["schema_version"]=="banking-v2-prompt-pilot-v1"
    assert fixed["schema_version"]=="banking-v2-prompt-pilot-v2"
    assert len(fixed["cases"])==12 and fixed["protocol_sha256"]!=original["protocol_sha256"]
    assert not ({case["case_id"] for case in original["cases"]}&{case["case_id"] for case in fixed["cases"]})
    for left,right in zip(original["cases"],fixed["cases"],strict=True):assert prompt_for(left)==prompt_for(right)
    with pytest.raises(ValueError,match="protocol_changed"):corrected_plan({"changed":True},{},original)


def test_owner_document_boundary_does_not_approve_goal_paraphrases():
    original=packet();updated=code_facts_review_packet(original)
    assert updated["source_packet_sha256"]==original["packet_sha256"] and updated["packet_sha256"]!=original["packet_sha256"]
    assert updated["candidates"]==original["candidates"] and not updated["candidates"][0]["training_eligible"]
    decision=review(updated)
    with pytest.raises(ValueError,match="boundary_review_conflict"):import_review(updated,decision)
    decision["document_prompt_selection"]="code_facts"
    assert len(import_review(updated,decision))==1
