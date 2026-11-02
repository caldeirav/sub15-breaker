"""Explicit owner-approved style-coverage amendment; no generation or repair.

The source generation run remains failed. Existing rejected/incomplete responses
stay excluded; this stage only assembles existing structurally valid notes.
"""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path

import mlflow

from src.benchmark.bulk_v2 import STYLES,materialize,load_review
from src.benchmark.modernbert import base_snapshot,tokenizer
from src.benchmark.training_v2 import PARTITIONS
from src.integrations.agentdojo.inventory import digest


def sha(path):
    with Path(path).open("rb") as stream:return hashlib.file_digest(stream,"sha256").hexdigest()


def quality_banks(notes,plan):
    banks={part:[] for part in PARTITIONS};seen=set();duplicates=[];cases={case["case_id"]:case for case in plan["cases"]}
    for row in notes:
        source=cases[row["case_id"]]
        if row["issues"] or row["partition"]!=source["partition"] or row["style"]!=source["style"]:raise ValueError("v2_assembly_note_provenance")
        shell=" ".join(row["text"].lower().split())
        if shell in seen:duplicates.append(dict(row,issues=["duplicate_note_shell"]));continue
        seen.add(shell);banks[row["partition"]].append(row)
    for part,rows in banks.items():
        counts=Counter(row["style"] for row in rows)
        if len(rows)<48 or sum(row["adversarial_requested"] for row in rows)<24:raise ValueError("v2_amended_population_coverage")
        if any(counts[style]<16 for style in STYLES[part]):raise ValueError("v2_amended_style_coverage")
    return banks,duplicates


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source",type=Path,required=True);parser.add_argument("--review",type=Path,required=True)
    parser.add_argument("--review-packet",type=Path,required=True);parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--source-run-id",required=True);parser.add_argument("--owner-approved-style-amendment",action="store_true",required=True)
    args=parser.parse_args();approved,review=load_review(args.review,args.review_packet)
    source=args.source;scenario=json.loads((source/"scenario-manifest.json").read_text());plan=json.loads((source/"generation-plan.json").read_text())
    if digest(scenario)!=plan["scenario_manifest_sha256"] or digest(review)!=plan["review_sha256"]:raise ValueError("v2_assembly_source_binding")
    from src.benchmark import scenarios_v2,training_documents,bulk_v2
    if (sha(scenarios_v2.__file__)!=scenario["scenario_code_sha256"] or sha(training_documents.__file__)!=scenario["document_code_sha256"] or
            sha(bulk_v2.__file__)!=plan["generator_code_sha256"]):raise ValueError("v2_assembly_frozen_code_changed")
    notes=json.loads((source/"notes.json").read_text());original_rejected=json.loads((source/"note-rejections.original.json").read_text())
    receipts=json.loads((source/"generation-receipts.json").read_text())
    if len(receipts)!=len(plan["cases"]) or sum(r["physical_attempts"] for r in receipts)!=len(plan["cases"]):raise ValueError("v2_assembly_dispatch_accounting")
    banks,duplicates=quality_banks(notes,plan)
    amendment=dict(schema_version="banking-v2-style-coverage-amendment-v1",owner_approved=True,source_run_id=args.source_run_id,
        original_generation_plan_sha256=digest(plan),scenario_manifest_sha256=digest(scenario),review_sha256=digest(review),
        source_files={name:sha(source/name) for name in ["notes.json","note-rejections.original.json","generation-receipts.json"]},
        source_generation_errors=sum(r["error"] is not None for r in receipts),minimum_notes_per_population=48,
        minimum_adversarial_per_population=24,minimum_notes_per_reserved_style=16,per_call_minimum_superseded=True,
        failed_or_rejected_responses_repaired=False,new_provider_calls=0,predictor_loaded=False,
        note_counts={part:dict(total=len(rows),adversarial=sum(r["adversarial_requested"] for r in rows),styles=dict(Counter(r["style"] for r in rows))) for part,rows in banks.items()},
        source_code_sha256=sha(__file__))
    args.output.mkdir(parents=True,exist_ok=False,mode=0o700)
    (args.output/"assembly-amendment.json").write_text(json.dumps(amendment,indent=2)+"\n")
    for name in ("scenario-manifest.json","generation-plan.json"):(args.output/name).write_bytes((source/name).read_bytes())
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[2]/".env")
    os.environ["MLFLOW_ENABLE_ASYNC_TRACE_LOGGING"]="false";os.environ["MLFLOW_HTTP_REQUEST_MAX_RETRIES"]="0"
    mlflow.set_tracking_uri(os.getenv("MLFLOW_TRACKING_URI","http://localhost:5001"));mlflow.set_experiment("breaker-banking-guard-development")
    with mlflow.start_run(run_name="v2-approved-style-coverage-assembly-no-new-generation") as run:
        mlflow.log_dict(amendment,"protocol/assembly-amendment.json")
        tok=tokenizer(base_snapshot());rows=materialize(scenario,banks,token_count=lambda text:len(tok(text,truncation=False)["input_ids"]))
        rejected=original_rejected+duplicates
        report=dict(schema_version="banking-v2-dataset-v1",run_id=run.info.run_id,dataset_sha256=digest(rows),scenario_manifest_sha256=digest(scenario),
            generation_plan_sha256=digest(plan),assembly_amendment_sha256=digest(amendment),review_sha256=digest(review),rows=len(rows),
            by_partition=dict(Counter(row["partition"] for row in rows)),per_partition_class_counts={part:dict(Counter(str(row["unsafe_label"]) for row in rows if row["partition"]==part)) for part in PARTITIONS},
            maximum_tokens=max(row["input_tokens"] for row in rows),original_fit=False,retained_notes=sum(map(len,banks.values())),rejected_notes=len(rejected),
            source_generation_errors=sum(r["error"] is not None for r in receipts),source_provider_attempts=sum(r["physical_attempts"] for r in receipts),
            new_provider_calls=0,new_local_requests=0,challenge_scope=scenario["independence_scope"],source_failed_run_preserved=True)
        for part in PARTITIONS:
            path=args.output/(part+".jsonl");path.write_text("".join(json.dumps(row,sort_keys=True)+"\n" for row in rows if row["partition"]==part));path.chmod(0o600)
        for name,value in (("report.json",report),("note-banks.json",banks),("note-rejections.json",rejected)):
            path=args.output/name;path.write_text(json.dumps(value,indent=2)+"\n");path.chmod(0o600);mlflow.log_artifact(str(path),"dataset")
        print(json.dumps(report,indent=2))


if __name__=="__main__":main()
