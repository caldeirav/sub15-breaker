import hashlib
import json

import pytest

from src.benchmark.guards import ReviewInput
from src.benchmark.review_decisions import apply_suite_review
from src.benchmark.review_form import SCHEMA,import_review
from src.integrations.agentdojo.inventory import digest


def fixture(tmp_path,*,duplicate=False,partial=False):
    rows=[]
    for index in range(2):
        value=ReviewInput(f"Goal {index}","unit-policy","Unit policy","get_balance",{})
        rows.append(dict(candidate_id=f"case-{index}",task_id="user_task_0",model_input=value.serialized(),input_digest=value.digest(),
            benchmark_label="permitted",unsafe_label=0,label_rule_version="unit-rule-v1",label_rule="unit-reference",
            projection_supported=True,projection_issues=[],training_eligible=False,training_blockers=["rule_spotcheck_and_group_split_required"]))
    spot=list(rows)
    if duplicate:rows.append(dict(rows[1],candidate_id="case-duplicate"))
    dataset=tmp_path/"dataset";dataset.mkdir();source_hash=digest(rows)
    (dataset/"report.json").write_text(json.dumps(dict(dataset_sha256=source_hash,candidates=len(rows),rule_version="unit-rule-v1",policy_id="unit-policy")))
    (dataset/"suite-labels.jsonl").write_text("".join(json.dumps(row)+"\n" for row in rows))
    directory=dataset/"rule-spot-review";directory.mkdir()
    report=dict(annotation_packet_sha256=digest(spot),candidates=2,policy_id="unit-policy",policy_text_sha256=digest("Unit policy"),
        source_inventory_sha256=source_hash,rule_version="unit-rule-v1")
    (directory/"report.json").write_text(json.dumps(report));(directory/"proposals.jsonl").write_text("".join(json.dumps(row)+"\n" for row in spot))
    approval=dict(status="approved",reviewer="unit-human",notes="",reviewed_at="2026-11-01T00:00:00Z")
    guide="unit guide"
    document=dict(schema_version=SCHEMA,packet_sha256=report["annotation_packet_sha256"],policy_id="unit-policy",policy_text_sha256=report["policy_text_sha256"],
        rubric_text=guide,rubric_sha256=hashlib.sha256(guide.encode()).hexdigest(),exported_at="2026-11-01T01:00:00Z",policy_review=approval,projection_review=approval,
        records=[dict(candidate_id=row["candidate_id"],input_digest=row["input_digest"],reviewed_label="permitted" if index==0 else "unknown",reviewer="unit-human",
            rationale="Granted read" if index==0 else "Prerequisite not established",reviewed_at="2026-11-01T00:30:00Z") for index,row in enumerate(spot[:1] if partial else spot)])
    path=tmp_path/"export.json";path.write_text(json.dumps(document))
    imported=tmp_path/"imported";import_review(directory,path,imported)
    return dataset,imported


def test_review_quarantines_unknown_without_rewriting_benchmark_or_claiming_training(tmp_path):
    dataset,review=fixture(tmp_path)
    original=(dataset/"suite-labels.jsonl").read_bytes()
    output=tmp_path/"decision"
    result=apply_suite_review(dataset,review,output)
    assert result["rule_spotcheck_complete"] is True and result["spotchecks_agree"]==1
    assert result["original_benchmark_labels"]=={"permitted":2}
    assert result["action_safety_labels"]=={"permitted":1,"unknown":1}
    assert result["supported_binary_candidates_after_split"]==1 and result["training_eligible"]==0
    rows=[json.loads(line) for line in (output/"labels.review-applied.jsonl").read_text().splitlines()]
    assert rows[1]["benchmark_label"]=="permitted" and rows[1]["original_unsafe_label"]==0
    assert rows[1]["unsafe_label"] is None and rows[1]["human_review"]["label"]=="unknown"
    assert all(row["training_eligible"] is False for row in rows)
    assert (dataset/"suite-labels.jsonl").read_bytes()==original
    with pytest.raises(FileExistsError):apply_suite_review(dataset,review,output)


def test_unknown_input_quarantine_cannot_be_bypassed_by_duplicate_candidate(tmp_path):
    dataset,review=fixture(tmp_path,duplicate=True)
    result=apply_suite_review(dataset,review,tmp_path/"decision")
    assert result["quarantined_candidates"]==["case-1","case-duplicate"]
    assert result["corpus_rows_individually_human_reviewed"]==2


def test_partial_review_does_not_clear_rule_gate(tmp_path):
    dataset,review=fixture(tmp_path,partial=True)
    result=apply_suite_review(dataset,review,tmp_path/"decision")
    assert result["rule_spotcheck_complete"] is False and result["supported_binary_candidates_after_split"]==0


def test_tampered_import_is_rejected_before_writing_decision(tmp_path):
    dataset,review=fixture(tmp_path)
    (review/"review.original.json").write_bytes((review/"review.original.json").read_bytes()+b" ")
    with pytest.raises(ValueError,match="bytes_changed"):apply_suite_review(dataset,review,tmp_path/"decision")
    assert not (tmp_path/"decision").exists()
