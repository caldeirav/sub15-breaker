"""Offline human-review form and immutable, packet-bound review import.

Rendering/importing never runs tools, models or training. A validated label is
not automatically a training row: final projection and group splits still gate it.
"""
import argparse
from collections import Counter,defaultdict
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path

from src.integrations.agentdojo.inventory import digest

SCHEMA="banking-human-review-v1"
LABELS={"permitted","prohibited","unknown"}
STATUSES={"pending","approved","needs_changes"}


def load_packet(directory):
    directory=Path(directory)
    report=json.loads((directory/"report.json").read_text())
    rows=[json.loads(line) for line in (directory/"proposals.jsonl").read_text().splitlines() if line.strip()]
    if report["annotation_packet_sha256"]!=digest(rows):raise ValueError("source_packet_hash_mismatch")
    if len(rows)!=report["candidates"] or len({r["candidate_id"] for r in rows})!=len(rows):raise ValueError("source_packet_cardinality")
    for row in rows:
        if hashlib.sha256(row["model_input"].encode()).hexdigest()!=row["input_digest"]:raise ValueError("source_input_digest_mismatch")
        features=json.loads(row["model_input"])
        if features["policy_id"]!=report["policy_id"] or digest(features["policy"])!=report["policy_text_sha256"]:
            raise ValueError("source_policy_mismatch")
    return report,rows


def _text(value):return isinstance(value,str) and bool(value.strip())


def _timestamp(value):
    if not isinstance(value,str):raise ValueError("review_timestamp_required")
    try:parsed=datetime.fromisoformat(value.replace("Z","+00:00"))
    except ValueError:raise ValueError("invalid_review_timestamp") from None
    if parsed.tzinfo is None:raise ValueError("review_timestamp_requires_timezone")


def validate_review(report,rows,review):
    if not isinstance(review,dict):raise ValueError("human_review_document_required")
    if review.get("schema_version")!=SCHEMA:raise ValueError("unsupported_human_review_schema")
    for key,expected in (("packet_sha256",report["annotation_packet_sha256"]),("policy_id",report["policy_id"]),
            ("policy_text_sha256",report["policy_text_sha256"])):
        if review.get(key)!=expected:raise ValueError("human_review_packet_binding_mismatch")
    rubric=review.get("rubric_text")
    if not _text(rubric) or hashlib.sha256(rubric.encode()).hexdigest()!=review.get("rubric_sha256"):
        raise ValueError("human_review_rubric_binding_mismatch")
    _timestamp(review.get("exported_at"))
    for name in ("policy_review","projection_review"):
        approval=review.get(name)
        if not isinstance(approval,dict) or not isinstance(approval.get("status"),str) or approval["status"] not in STATUSES:
            raise ValueError("review_approval_status_required")
        if not isinstance(approval.get("notes"),str):raise ValueError("review_notes_must_be_text")
        if approval["status"]!="pending":
            if not _text(approval.get("reviewer")):raise ValueError("approval_reviewer_required")
            _timestamp(approval.get("reviewed_at"))
        if approval["status"]=="needs_changes" and not _text(approval.get("notes")):raise ValueError("review_change_notes_required")
    source={r["candidate_id"]:r for r in rows}
    records=review.get("records")
    if not isinstance(records,list):raise ValueError("human_review_records_required")
    seen=set();by_digest=defaultdict(set)
    required={"candidate_id","input_digest","reviewed_label","reviewer","rationale","reviewed_at"}
    for item in records:
        if not isinstance(item,dict) or set(item)!=required:raise ValueError("human_review_record_fields")
        candidate=item["candidate_id"]
        if not isinstance(candidate,str) or candidate not in source:raise ValueError("unknown_review_candidate")
        if candidate in seen:raise ValueError("duplicate_review_candidate")
        seen.add(candidate)
        if item["input_digest"]!=source[candidate]["input_digest"]:raise ValueError("review_input_digest_mismatch")
        if not isinstance(item["reviewed_label"],str) or item["reviewed_label"] not in LABELS:raise ValueError("invalid_reviewed_label")
        if not _text(item["reviewer"]) or not _text(item["rationale"]):raise ValueError("reviewer_and_rationale_required")
        _timestamp(item["reviewed_at"])
        if item["reviewed_label"]!="unknown":by_digest[item["input_digest"]].add(item["reviewed_label"])
    conflicts={key for key,value in by_digest.items() if len(value)>1}
    validated=[];rule_disagreements=[]
    for item in records:
        original=source[item["candidate_id"]]
        blockers=["group_split_manifest_not_frozen"]
        if review["policy_review"]["status"]!="approved":blockers.append("policy_not_approved")
        if review["projection_review"]["status"]!="approved":blockers.append("projection_not_approved")
        if not original["projection_supported"]:blockers.append("projection_unsupported")
        if item["reviewed_label"]=="unknown":blockers.append("label_unknown")
        if item["input_digest"] in conflicts:blockers.append("conflicting_labels_for_same_input")
        grounded=original.get("benchmark_label") if original.get("label_rule_version") else None
        if grounded in LABELS and grounded!=item["reviewed_label"]:
            blockers.append("suite_grounding_disagreement_requires_adjudication")
            rule_disagreements.append(item["candidate_id"])
        validated.append(dict(candidate_id=item["candidate_id"],task_id=original["task_id"],input_digest=item["input_digest"],
            model_input=original["model_input"],reviewed_label=item["reviewed_label"],
            unsafe_label={"permitted":0,"prohibited":1,"unknown":None}[item["reviewed_label"]],
            reviewer=item["reviewer"],rationale=item["rationale"],reviewed_at=item["reviewed_at"],
            source_packet_sha256=report["annotation_packet_sha256"],annotation_source="self-reported-human-review",
            review_rubric_sha256=review["rubric_sha256"],
            original_benchmark_label=grounded,original_grounding_rule=original.get("label_rule"),
            projection_issues=original["projection_issues"],training_eligible=False,training_blockers=blockers))
    summary=dict(schema_version="banking-human-review-validation-v1",packet_sha256=report["annotation_packet_sha256"],
        policy_id=report["policy_id"],source_inventory_sha256=report["source_inventory_sha256"],
        review_rubric_sha256=review["rubric_sha256"],
        reviewed=len(records),pending=len(rows)-len(records),labels=dict(Counter(r["reviewed_label"] for r in records)),
        conflicting_input_digests=sorted(conflicts),
        suite_rule_disagreements=rule_disagreements,
        supported_reviewed_binary_candidates=sum(r["training_blockers"]==["group_split_manifest_not_frozen"] for r in validated),
        training_eligible=0,split_status="not_frozen",policy_review=review["policy_review"],projection_review=review["projection_review"],
        review_sha256=digest(review),note="Human labels are captured; no model training, split allocation or label repair occurs during import.")
    return summary,validated


def _write_new(path,text):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    with os.fdopen(fd,"wb") as stream:stream.write(text if isinstance(text,bytes) else text.encode("utf-8"))


def render_form(packet,output):
    from src.benchmark.review_ui import render
    report,rows=load_packet(packet)
    docs=Path(__file__).resolve().parents[2]/"docs"
    rubric=(docs/"banking-action-label-policy.md").read_text()
    if report.get("review_kind")=="suite_rule_spotcheck":
        rubric=(docs/"suite-grounded-labels.md").read_text()+"\n\n---\n\n"+rubric
    _write_new(output,render(report,rows,rubric))


def import_review(packet,review_path,output):
    report,rows=load_packet(packet)
    if Path(review_path).stat().st_size>5*1024*1024:raise ValueError("human_review_file_too_large")
    original=Path(review_path).read_bytes()
    review=json.loads(original)
    summary,validated=validate_review(report,rows,review)
    summary["export_file_sha256"]=hashlib.sha256(original).hexdigest()
    output=Path(output);output.mkdir(parents=True,exist_ok=False,mode=0o700)
    _write_new(output/"review.original.json",original)
    _write_new(output/"validation.json",json.dumps(summary,indent=2,ensure_ascii=False)+"\n")
    _write_new(output/"labels.validated.jsonl","".join(json.dumps(row,ensure_ascii=False,sort_keys=True)+"\n" for row in validated))
    return summary


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest="command",required=True)
    render=sub.add_parser("render");render.add_argument("--packet",type=Path,required=True);render.add_argument("--output",type=Path,required=True)
    load=sub.add_parser("import");load.add_argument("--packet",type=Path,required=True);load.add_argument("--review",type=Path,required=True);load.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    if args.command=="render":render_form(args.packet,args.output);print(f"Open {args.output} in your browser. No server or model calls are used.")
    else:print(json.dumps(import_review(args.packet,args.review,args.output),indent=2))


if __name__=="__main__":main()
