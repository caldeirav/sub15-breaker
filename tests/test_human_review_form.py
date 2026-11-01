from copy import deepcopy
import hashlib
import json

import pytest

from src.benchmark.guards import ReviewInput
from src.benchmark.review_form import SCHEMA,import_review,load_packet,validate_review
from src.benchmark.review_ui import SCRIPT,render
from src.integrations.agentdojo.inventory import digest


def packet(*,identical=False):
    rows=[]
    for index in range(2):
        value=ReviewInput("Review goal" if identical else f"Review goal {index}","unit-policy","Unit policy","get_balance",{})
        rows.append(dict(candidate_id=f"unit-{index}",task_id="user_task_0",model_input=value.serialized(),input_digest=value.digest(),
            projection_supported=index==0,projection_issues=[] if index==0 else ["encoder_context_overflow"],
            proposed_label="permitted",proposal_rationale="Draft only",draft_intent="read_only",intent_rationale="Unit intent",input_tokens=10,maximum_tokens=512))
    report=dict(annotation_packet_sha256=digest(rows),candidates=2,policy_id="unit-policy",policy_text_sha256=digest("Unit policy"),source_inventory_sha256="a"*64)
    return report,rows


def review(report,rows):
    approval=dict(status="approved",reviewer="unit-human",reviewed_at="2026-11-01T00:00:00Z",notes="")
    rubric="# Unit review guide"
    return dict(schema_version=SCHEMA,packet_sha256=report["annotation_packet_sha256"],policy_id=report["policy_id"],
        policy_text_sha256=report["policy_text_sha256"],exported_at="2026-11-01T01:00:00Z",
        rubric_text=rubric,rubric_sha256=hashlib.sha256(rubric.encode()).hexdigest(),
        policy_review=deepcopy(approval),projection_review=deepcopy(approval),records=[dict(candidate_id=row["candidate_id"],
            input_digest=row["input_digest"],reviewed_label="permitted" if index==0 else "unknown",reviewer="unit-human",
            rationale="Policy grants read access." if index==0 else "Missing facts require further review.",reviewed_at="2026-11-01T00:30:00Z") for index,row in enumerate(rows)])


def test_partial_human_review_preserves_unknowns_and_does_not_unlock_training():
    report,rows=packet();value=review(report,rows)
    summary,accepted=validate_review(report,rows,value)
    assert summary["reviewed"]==2 and summary["pending"]==0
    assert summary["supported_reviewed_binary_candidates"]==1 and summary["training_eligible"]==0
    assert accepted[0]["unsafe_label"]==0 and accepted[1]["unsafe_label"] is None
    assert "projection_unsupported" in accepted[1]["training_blockers"]
    assert all(row["training_eligible"] is False for row in accepted)
    value["records"].pop()
    assert validate_review(report,rows,value)[0]["pending"]==1


@pytest.mark.parametrize("kind",["packet","input","anonymous","rationale","timestamp","duplicate","label","rubric"])
def test_changed_or_incomplete_review_is_rejected(kind):
    report,rows=packet();value=review(report,rows)
    if kind=="packet":value["packet_sha256"]="wrong"
    elif kind=="input":value["records"][0]["input_digest"]="wrong"
    elif kind=="anonymous":value["records"][0]["reviewer"]=""
    elif kind=="rationale":value["records"][0]["rationale"]=" "
    elif kind=="timestamp":value["records"][0]["reviewed_at"]="2026-11-01T00:00:00"
    elif kind=="duplicate":value["records"].append(deepcopy(value["records"][0]))
    elif kind=="label":value["records"][0]["reviewed_label"]="pending_review"
    elif kind=="rubric":value["rubric_text"]="different guide"
    with pytest.raises(ValueError):validate_review(report,rows,value)


def test_conflicting_binary_labels_are_retained_and_blocked_not_voted_away():
    report,rows=packet(identical=True);value=review(report,rows)
    value["records"][1]["reviewed_label"]="prohibited"
    summary,accepted=validate_review(report,rows,value)
    assert summary["conflicting_input_digests"]==[rows[0]["input_digest"]]
    assert summary["supported_reviewed_binary_candidates"]==0
    assert all("conflicting_labels_for_same_input" in row["training_blockers"] for row in accepted)


def test_requested_policy_changes_are_not_treated_as_approval():
    report,rows=packet();value=review(report,rows)
    value["policy_review"].update(status="needs_changes",notes="Read policy needs narrowing.")
    summary,accepted=validate_review(report,rows,value)
    assert summary["supported_reviewed_binary_candidates"]==0
    assert all("policy_not_approved" in row["training_blockers"] for row in accepted)


def test_rule_spotcheck_disagreement_is_preserved_for_adjudication_not_repaired():
    report,rows=packet()
    rows[0].update(benchmark_label="permitted",label_rule_version="unit-rule-v1",label_rule="unit-source-intent")
    report["annotation_packet_sha256"]=digest(rows)
    value=review(report,rows);value["records"][0]["reviewed_label"]="prohibited"
    summary,accepted=validate_review(report,rows,value)
    assert summary["suite_rule_disagreements"]==[rows[0]["candidate_id"]]
    assert accepted[0]["unsafe_label"]==1 and accepted[0]["original_benchmark_label"]=="permitted"
    assert "suite_grounding_disagreement_requires_adjudication" in accepted[0]["training_blockers"]


def test_import_is_packet_bound_private_and_never_overwrites(tmp_path):
    report,rows=packet();source=tmp_path/"packet";source.mkdir()
    (source/"report.json").write_text(json.dumps(report))
    (source/"proposals.jsonl").write_text("".join(json.dumps(row)+"\n" for row in rows))
    path=tmp_path/"review.json";path.write_text(json.dumps(review(report,rows)))
    output=tmp_path/"validated"
    result=import_review(source,path,output)
    assert result["reviewed"]==2 and (output/"labels.validated.jsonl").is_file()
    assert (output/"review.original.json").read_bytes()==path.read_bytes()
    assert ((output/"review.original.json").stat().st_mode&0o777)==0o600
    assert (output.stat().st_mode&0o777)==0o700
    with pytest.raises(FileExistsError):import_review(source,path,output)
    altered=deepcopy(rows);altered[0]["model_input"]="changed"
    (source/"proposals.jsonl").write_text("".join(json.dumps(row)+"\n" for row in altered))
    with pytest.raises(ValueError,match="hash_mismatch"):load_packet(source)


def test_form_embeds_data_as_text_and_blocks_network_and_active_document_content():
    report,rows=packet()
    value=json.loads(rows[0]["model_input"]);value["goal"]='</script><img src="https://invalid.test" onerror="alert(1)">'
    rows[0]["model_input"]=json.dumps(value)
    page=render(report,rows,"# Review guide")
    assert "connect-src 'none'" in page and "img-src 'none'" in page
    assert "script-src 'sha256-" in page
    assert '</script><img src="https://invalid.test"' not in page
    assert "\\u003c/script>" in page
    assert ".innerHTML" not in SCRIPT and "fetch(" not in SCRIPT
