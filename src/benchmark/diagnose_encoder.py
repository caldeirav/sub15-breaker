"""Frozen development-only representation diagnosis, never threshold/model selection.

No facts, requests or actions are removed or invented. Changed observation
containers/whitespace are diagnostic encodings, not a new native input contract.
"""
import argparse
from collections import defaultdict
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path

import mlflow
import numpy as np

from src.banking_contracts.tools import READ_TOOLS
from src.benchmark.encoder import EncoderLogit,manifest
from src.benchmark.projection import POLICY_ID
from src.benchmark.projection import expand_table
from src.benchmark.train_encoder import predict,risks
from src.benchmark.train_v2 import load_rows,validate_seal
from src.integrations.agentdojo.inventory import digest

VARIANTS=("canonical","pad_empty_observations_four","pack_observations_one","pretty_json","canonical_table_columns","row_object_tables")


def table_view(value,mode):
    if isinstance(value,dict):
        if value.get("encoding")=="columnar-v1":
            if mode=="rows":return [table_view(row,mode) for row in expand_table(value)]
            columns=value["columns"];ordered=sorted(columns);indices=[columns.index(key) for key in ordered]
            return dict(value,columns=ordered,rows=[[table_view(row[index],mode) for index in indices] for row in value["rows"]],
                constant=table_view(value["constant"],mode))
        return {key:table_view(item,mode) for key,item in value.items()}
    if isinstance(value,list):return [table_view(item,mode) for item in value]
    return value


def transform(text,variant):
    original=json.loads(text);value=deepcopy(original);observations=original["untrusted_observations"]
    if variant=="pad_empty_observations_four":
        value["untrusted_observations"]=observations+[""]*max(0,4-len(observations))
    elif variant=="pack_observations_one":
        value["untrusted_observations"]=[json.dumps(observations,ensure_ascii=False,separators=(",",":"))] if observations else []
    elif variant in {"canonical_table_columns","row_object_tables"}:
        value=table_view(value,"columns" if variant=="canonical_table_columns" else "rows")
    elif variant not in {"canonical","pretty_json"}:raise ValueError("unknown_representation_diagnostic")
    rendered=json.dumps(value,ensure_ascii=False,sort_keys=True,allow_nan=False,**({"indent":2} if variant=="pretty_json" else {"separators":(",",":")}))
    recovered=json.loads(rendered)
    if variant=="pad_empty_observations_four":
        if any(recovered["untrusted_observations"][len(observations):]):raise ValueError("nonempty_diagnostic_padding")
        recovered["untrusted_observations"]=recovered["untrusted_observations"][:len(observations)]
    elif variant=="pack_observations_one" and observations:
        recovered["untrusted_observations"]=json.loads(recovered["untrusted_observations"][0])
    if table_view(recovered,"rows")!=table_view(original,"rows"):raise ValueError("diagnostic_lost_or_changed_information")
    return rendered


def auc(labels,scores):
    positive=np.asarray([score for label,score in zip(labels,scores,strict=True) if label==1])
    negative=np.asarray([score for label,score in zip(labels,scores,strict=True) if label==0])
    if not len(positive) or not len(negative):return None
    return float(np.mean((positive[:,None]>negative[None,:])+0.5*(positive[:,None]==negative[None,:])))


def saved_ranking(rows,predictions):
    by_id={row["candidate_id"]:row for row in predictions};indices=[row for row in rows if row["candidate_id"] in by_id]
    def score(values):
        labels=[];scores=[]
        for row in values:
            value=by_id[row["candidate_id"]]
            if value["input_digest"]!=row["input_digest"] or value["unsafe_label"]!=row["unsafe_label"]:raise ValueError("diagnostic_score_binding_mismatch")
            labels.append(row["unsafe_label"]);scores.append(value["logits"][1]-value["logits"][0])
        return dict(samples=len(values),roc_auc=auc(labels,scores))
    writes=[row for row in indices if json.loads(row["model_input"])["action"]["tool"] not in READ_TOOLS]
    return dict(all=score(indices),mutations_only=score(writes))


def select_fresh(rows):
    groups=defaultdict(dict)
    for row in rows:groups[row["family"]].setdefault(row["scenario_group"],[]).append(row)
    selected=[]
    for family in sorted(groups):
        for case in sorted(groups[family])[:2]:selected.extend(groups[family][case])
    return selected


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact",type=Path,required=True);parser.add_argument("--training",type=Path,required=True)
    parser.add_argument("--original",type=Path,required=True);parser.add_argument("--dataset",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True);parser.add_argument("--execute-frozen-diagnostic",action="store_true")
    args=parser.parse_args();model_manifest=manifest(args.artifact,policy_id=POLICY_ID)
    validate_seal(args.dataset)
    original_all=load_rows(args.original/"rows.jsonl");coverage=json.loads((args.original/"coverage.json").read_text())
    if digest(original_all)!=coverage["dataset_sha256"]:raise ValueError("diagnostic_original_changed")
    original=[row for row in original_all if row["projection_supported"] and row["unsafe_label"] is not None and not row.get("label_quarantine")]
    fresh=load_rows(args.dataset/"fresh_challenge.jsonl");selected=select_fresh(fresh)
    scores={"original":load_rows(args.training/"transfer-predictions.jsonl"),"fresh":load_rows(args.training/"fresh-predictions.jsonl")}
    populations={"original":original,"fresh":selected}
    plan=dict(schema_version="frozen-encoder-representation-diagnostic-v1",artifact_manifest_sha256=digest(model_manifest),
        model_id=model_manifest["model_id"],calibration=model_manifest["calibration"],variants=list(VARIANTS),
        populations={key:[dict(candidate_id=row["candidate_id"],input_digest=row["input_digest"]) for row in values] for key,values in populations.items()},
        selection="all original supported; two smallest scenario-group IDs per fresh family; no score-based selection",
        maximum_tokens=2048,batch_size=2,counterbalance="rotate variant order by case index",model_fitting=False,
        threshold_selection=False,native_execution=False,provider_requests=0,
        source_code_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    if not args.execute_frozen_diagnostic:print(json.dumps(plan,indent=2));return
    args.output.mkdir(parents=True,exist_ok=False,mode=0o700)
    (args.output/"plan.json").write_text(json.dumps(plan,indent=2)+"\n")
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[2]/".env")
    os.environ["MLFLOW_ENABLE_ASYNC_TRACE_LOGGING"]="false";os.environ["MLFLOW_HTTP_REQUEST_MAX_RETRIES"]="0"
    import torch
    if not torch.backends.mps.is_available() or os.getenv("PYTORCH_ENABLE_MPS_FALLBACK") not in {None,"0"}:raise RuntimeError("explicit_mps_required")
    encoder=EncoderLogit(args.artifact,policy_id=POLICY_ID,device="mps");cal=model_manifest["calibration"]
    materialized=[];unique={};unsupported=[]
    for population,rows in populations.items():
        for index,row in enumerate(rows):
            offset=index%len(VARIANTS)
            for variant in VARIANTS[offset:]+VARIANTS[:offset]:
                text=transform(row["model_input"],variant);key=hashlib.sha256(text.encode()).hexdigest()
                tokens=len(encoder.tokenizer(text,truncation=False)["input_ids"])
                record=dict(population=population,candidate_id=row["candidate_id"],variant=variant,unsafe_label=row["unsafe_label"],
                    original_input_digest=row["input_digest"],diagnostic_input_digest=key,tokens=tokens)
                if tokens>plan["maximum_tokens"]:unsupported.append(dict(record,error="diagnostic_context_overflow"));continue
                unique.setdefault(key,dict(candidate_id=key,model_input=text));materialized.append(record)
    mlflow.set_tracking_uri(os.getenv("MLFLOW_TRACKING_URI","http://localhost:5001"));mlflow.set_experiment("breaker-banking-guard-development")
    with mlflow.start_run(run_name="v2-frozen-information-preserving-representation-diagnosis") as run:
        mlflow.log_dict(plan,"protocol/diagnostic.json")
        values=list(unique.values());logits=predict(encoder.model,encoder.tokenizer,values,device="mps",batch_size=2)
        measured={value["candidate_id"]:logit for value,logit in zip(values,logits,strict=True)}
        summaries={};baseline={};parity=[];predictions=[]
        saved={key:{row["candidate_id"]:row for row in values} for key,values in scores.items()}
        for row in materialized:
            logit=measured[row["diagnostic_input_digest"]];risk=float(risks([logit],cal["temperature"])[0]);blocked=risk>=cal["threshold"]
            value=dict(row,logits=logit,risk=risk,decision="block" if blocked else "allow");predictions.append(value)
            if row["variant"]=="canonical":
                prior=saved[row["population"]][row["candidate_id"]]
                if prior["input_digest"]!=row["original_input_digest"]:raise ValueError("diagnostic_baseline_binding")
                parity.append(max(abs(a-b) for a,b in zip(logit,prior["logits"],strict=True)))
                baseline[(row["population"],row["candidate_id"])]=value
        if max(parity)>2e-3:raise RuntimeError("diagnostic_frozen_reload_score_mismatch")
        for population in populations:
            summaries[population]={}
            for variant in VARIANTS:
                values=[row for row in predictions if row["population"]==population and row["variant"]==variant]
                if not values:
                    summaries[population][variant]=dict(samples=0,error="no_supported_diagnostic_inputs")
                    continue
                false_allow=sum(row["decision"]=="allow" and row["unsafe_label"]==1 for row in values)
                false_block=sum(row["decision"]=="block" and row["unsafe_label"]==0 for row in values)
                summaries[population][variant]=dict(samples=len(values),false_allows=false_allow,false_blocks=false_block,
                    accuracy=1-(false_allow+false_block)/len(values),blocked=sum(row["decision"]=="block" for row in values),
                    decision_flips=sum(row["decision"]!=baseline[(population,row["candidate_id"])]["decision"] for row in values),
                    mean_absolute_risk_change=float(np.mean([abs(row["risk"]-baseline[(population,row["candidate_id"])]["risk"]) for row in values])))
        result=dict(run_id=run.info.run_id,plan_sha256=digest(plan),model_id=model_manifest["model_id"],summaries=summaries,
            saved_logits_max_delta=max(parity),unique_encoder_inputs=len(unique),unsupported=unsupported,
            full_saved_score_ranking={"original":saved_ranking(original,scores["original"]),"fresh":saved_ranking(fresh,scores["fresh"])},
            no_native_contract_changed=True,no_threshold_or_weights_changed=True,provider_requests=0,
            caution="Observed development-only sensitivity, not a newly selected input format or independent quality test.")
        for name,value in (("result.json",result),("predictions.json",predictions)):
            path=args.output/name;path.write_text(json.dumps(value,indent=2)+"\n");path.chmod(0o600);mlflow.log_artifact(str(path),"diagnosis")
        print(json.dumps(result,indent=2))


if __name__=="__main__":main()
