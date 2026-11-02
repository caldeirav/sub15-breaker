"""Apply a rule spot review as a derived safety-label decision, never a rewrite.

The source benchmark labels and user export remain immutable. A disagreement or
Unknown quarantines the matching input for adjudication; it is never voted away.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from src.benchmark.review_form import _write_new,load_packet,validate_review
from src.integrations.agentdojo.inventory import digest


def apply_suite_review(dataset,review_directory,output):
    dataset=Path(dataset);review_directory=Path(review_directory);output=Path(output)
    report=json.loads((dataset/"report.json").read_text())
    rows=[json.loads(line) for line in (dataset/"suite-labels.jsonl").read_text().splitlines() if line.strip()]
    if digest(rows)!=report["dataset_sha256"]:raise ValueError("suite_dataset_hash_mismatch")
    if len(rows)!=report["candidates"] or len({row["candidate_id"] for row in rows})!=len(rows):raise ValueError("suite_dataset_cardinality")
    export=(review_directory/"review.original.json").read_bytes()
    imported=json.loads((review_directory/"validation.json").read_text())
    if hashlib.sha256(export).hexdigest()!=imported["export_file_sha256"]:raise ValueError("imported_review_bytes_changed")
    document=json.loads(export)
    spot_report,spot_rows=load_packet(dataset/"rule-spot-review")
    if spot_report["policy_id"]!=report["policy_id"] or spot_report["rule_version"]!=report["rule_version"]:
        raise ValueError("spot_review_rule_policy_mismatch")
    validation,labels=validate_review(spot_report,spot_rows,document)
    if validation["review_sha256"]!=imported["review_sha256"]:raise ValueError("imported_review_binding_changed")
    if spot_report["source_inventory_sha256"]!=report["dataset_sha256"]:raise ValueError("spot_review_dataset_mismatch")
    source={row["candidate_id"]:row for row in rows}
    for row in labels:
        if row["candidate_id"] not in source or source[row["candidate_id"]]["input_digest"]!=row["input_digest"]:
            raise ValueError("reviewed_candidate_binding_mismatch")
    reviewed={row["candidate_id"]:row for row in labels}
    quarantine={row["input_digest"]:row for row in labels if row["reviewed_label"]=="unknown" or
        row["reviewed_label"]!=source[row["candidate_id"]]["benchmark_label"]}
    complete=validation["pending"]==0 and validation["policy_review"]["status"]=="approved" and validation["projection_review"]["status"]=="approved"
    derived=[]
    for row in rows:
        item=dict(row)
        item.update(original_unsafe_label=row["unsafe_label"],action_safety_label=row["benchmark_label"],
            review_sha256=validation["review_sha256"],human_spot_checked=row["candidate_id"] in reviewed,
            rule_review_status="approved_with_quarantine" if complete and quarantine else "approved" if complete else "incomplete",
            training_eligible=False)
        if complete:
            item["training_blockers"]=[reason for reason in row["training_blockers"] if reason!="rule_spotcheck_and_group_split_required"]
            item["training_blockers"].insert(0,"group_split_manifest_not_frozen")
        else:item["training_blockers"]=list(row["training_blockers"])
        human=reviewed.get(row["candidate_id"])
        if human:item["human_review"]=dict(label=human["reviewed_label"],reviewer=human["reviewer"],rationale=human["rationale"],reviewed_at=human["reviewed_at"])
        if row["input_digest"] in quarantine:
            decision=quarantine[row["input_digest"]]
            item.update(action_safety_label="unknown",unsafe_label=None,
                label_quarantine=dict(source_candidate_id=decision["candidate_id"],reviewed_label=decision["reviewed_label"],
                    reviewer=decision["reviewer"],rationale=decision["rationale"],input_digest=decision["input_digest"]))
            item["training_blockers"].append("human_review_quarantine_requires_adjudication")
        derived.append(item)
    manifest=dict(schema_version="banking-rule-review-decision-v1",source_dataset_sha256=report["dataset_sha256"],
        rule_version=report["rule_version"],policy_id=report["policy_id"],review_sha256=validation["review_sha256"],
        export_file_sha256=imported["export_file_sha256"],rule_spotcheck_complete=complete,spotchecks_reviewed=len(labels),
        spotchecks_agree=sum(row["reviewed_label"]==source[row["candidate_id"]]["benchmark_label"] for row in labels),
        policy_review=validation["policy_review"],projection_review=validation["projection_review"],
        original_benchmark_labels=dict(Counter(row["benchmark_label"] for row in rows)),
        action_safety_labels=dict(Counter(row["action_safety_label"] for row in derived)),
        quarantined_candidates=[row["candidate_id"] for row in derived if row.get("label_quarantine")],
        corpus_rows_individually_human_reviewed=len(labels),
        label_scope="CODE suite-derived labels accepted by rule/sample review, with explicit human exclusions; not 225 individual human annotations",
        training_label_field="action_safety_label / unsafe_label",derived_dataset_sha256=digest(derived),
        supported_binary_candidates_after_split=sum(row["training_blockers"]==["group_split_manifest_not_frozen"] for row in derived) if complete else 0,
        training_eligible=0,split_status="not_frozen",new_model_requests=0,
        note="Known benchmark intent, human safety judgment and input coverage remain separate. No source label is overwritten and no training is started.")
    output.mkdir(parents=True,exist_ok=False,mode=0o700)
    _write_new(output/"decision.json",json.dumps(manifest,indent=2,ensure_ascii=False)+"\n")
    _write_new(output/"labels.review-applied.jsonl","".join(json.dumps(row,sort_keys=True,ensure_ascii=False)+"\n" for row in derived))
    _write_new(output/"review.original.json",export)
    return manifest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset",type=Path,required=True)
    parser.add_argument("--review-directory",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(apply_suite_review(args.dataset,args.review_directory,args.output),indent=2))


if __name__=="__main__":main()
