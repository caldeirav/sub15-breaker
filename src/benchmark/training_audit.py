"""Read-only v1 error/coverage audit. No model loading, calls or threshold fitting."""
import argparse
from collections import Counter,defaultdict
import hashlib
import json
from pathlib import Path

from src.banking_contracts.tools import READ_TOOLS
from src.benchmark.train_encoder import risks
from src.integrations.agentdojo.inventory import digest


def input_value(row):
    text=row["model_input"]
    if hashlib.sha256(text.encode()).hexdigest()!=row["input_digest"]:
        raise ValueError("audit_input_digest_mismatch")
    return json.loads(text)


def training_coverage(rows,documents):
    groups=defaultdict(list);parts=defaultdict(list)
    for row in rows:
        input_value(row)
        groups[row["scenario_group"]].append(row);parts[row["partition"]].append(row)
    changes=Counter()
    for pair in groups.values():
        if sorted(row["unsafe_label"] for row in pair)!=[0,1]:raise ValueError("audit_incomplete_pair")
        safe,unsafe=sorted(pair,key=lambda row:row["unsafe_label"])
        left=input_value(safe);right=input_value(unsafe)
        if left["goal"]!=right["goal"]:raise ValueError("audit_pair_goal_changed")
        a=left["action"]["arguments"];b=right["action"]["arguments"]
        changed=[key for key in sorted(set(a)|set(b)) if a.get(key)!=b.get(key)]
        if not changed and left["benchmark_state"].get("credential_facts")!=right["benchmark_state"].get("credential_facts"):
            changed=["credential_equality_fact"]
        changes["+".join(changed) or "no_visible_difference"]+=1
    partitions={}
    for part,values in parts.items():
        used=set()
        for row in values:
            for observation in input_value(row)["untrusted_observations"]:
                first=observation.split("\n",1)[0]
                if first.startswith("read_file "):used.add(first.removeprefix("read_file ").removesuffix(".txt"))
        available={doc["document_id"] for doc in documents[part]}
        if not used<=available:raise ValueError("audit_document_provenance_missing")
        partitions[part]=dict(rows=len(values),tool_counts=dict(Counter(row["tool"] for row in values)),
            label_counts=dict(Counter(str(row["unsafe_label"]) for row in values)),
            document_families_used=sorted({row["document_group"] for row in values}),
            generated_documents=len(available),used_documents=len(used),unused_documents=len(available-used),
            inputs_containing_partition_marker=sum(part.lower() in row["model_input"].lower() for row in values))
    return dict(rows=len(rows),scenarios=len(groups),read_examples=sum(row["tool"] in READ_TOOLS for row in rows),
        mutation_examples=sum(row["tool"] not in READ_TOOLS for row in rows),paired_changed_fields=dict(changes),partitions=partitions)


def transfer_errors(rows,predictions,calibration):
    sources={row["candidate_id"]:row for row in rows}
    if len(sources)!=len(rows):raise ValueError("audit_duplicate_source_candidate")
    ids=[row["candidate_id"] for row in predictions]
    if not predictions or len(ids)!=len(set(ids)):raise ValueError("audit_empty_or_duplicate_prediction")
    probabilities=risks([row["logits"] for row in predictions],calibration["temperature"])
    stats=defaultdict(Counter);errors=[]
    for prediction,risk in zip(predictions,probabilities,strict=True):
        row=sources[prediction["candidate_id"]];value=input_value(row)
        if prediction["input_digest"]!=row["input_digest"] or prediction["unsafe_label"]!=row["unsafe_label"]:
            raise ValueError("audit_prediction_binding_mismatch")
        label=row["unsafe_label"]
        if type(label) is not int or label not in {0,1} or not row["projection_supported"] or row.get("label_quarantine"):
            raise ValueError("audit_prediction_ineligible")
        tool=value["action"]["tool"];block=bool(risk>=calibration["threshold"])
        outcome="false_block" if block and label==0 else "false_allow" if not block and label==1 else "correct"
        for group in ("all","reads" if tool in READ_TOOLS else "mutations","tool/"+tool):
            count=stats[group];count["samples"]+=1;count["permitted" if label==0 else "prohibited"]+=1;count[outcome]+=1
        if outcome!="correct":errors.append(dict(candidate_id=row["candidate_id"],input_digest=row["input_digest"],
            tool=tool,outcome=outcome,unsafe_label=label,risk=float(risk),goal=value["goal"],action=value["action"],
            state_fields=sorted(value["benchmark_state"]),observation_count=len(value["untrusted_observations"])))
    return dict(scored=len(predictions),excluded=len(rows)-len(predictions),slices={key:dict(count) for key,count in stats.items()},errors=errors)


def load_rows(path):return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def audit(hybrid,original,training):
    hybrid,original,training=map(Path,(hybrid,original,training))
    rows=load_rows(hybrid/"rows.jsonl");source=json.loads((hybrid/"report.json").read_text())
    originals=load_rows(original/"rows.jsonl");coverage=json.loads((original/"coverage.json").read_text())
    if digest(rows)!=source["dataset_sha256"] or digest(originals)!=coverage["dataset_sha256"]:
        raise ValueError("audit_dataset_hash_mismatch")
    result=json.loads((training/"result.json").read_text());cal=json.loads((training/"calibration.json").read_text())
    if result["calibration"]!=cal:raise ValueError("audit_calibration_binding_mismatch")
    transfer=transfer_errors(originals,load_rows(training/"holdout-predictions.jsonl"),cal)
    expected=result["original_transfer_holdout"];actual=transfer["slices"]["all"]
    for key,field in (("samples","samples"),("false_block","false_blocks"),("false_allow","false_allows")):
        if actual.get(key,0)!=expected[field]:raise ValueError("audit_saved_result_mismatch")
    return dict(schema_version="banking-training-audit-v1",training_run_id=result["training_run_id"],
        source_hybrid_sha256=digest(source),source_coverage_sha256=digest(coverage),source_result_sha256=digest(result),
        training=training_coverage(rows,json.loads((hybrid/"documents.json").read_text())),transfer=transfer,
        new_model_requests=0,new_gemini_operations=0,threshold_changed=False,weights_changed=False,
        causal_attribution="Coverage/design gaps established; contribution of Gemini prose quality is not isolated by this audit.")


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hybrid",type=Path,required=True);parser.add_argument("--original",type=Path,required=True)
    parser.add_argument("--training",type=Path,required=True);parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    value=audit(args.hybrid,args.original,args.training)
    args.output.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    with args.output.open("x") as stream:stream.write(json.dumps(value,indent=2)+"\n")
    args.output.chmod(0o600)
    print(json.dumps(dict(output=str(args.output),training=value["training"],transfer_slices=value["transfer"]["slices"]),indent=2))


if __name__=="__main__":main()
