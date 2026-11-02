"""Fixed-protocol encoder training, separate calibration/thresholding and holdout.

No original benchmark example participates in fitting or checkpoint selection.
An exported artifact is not a safety guarantee; poor transfer results stay poor.
"""
import argparse
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import random
from time import perf_counter

import mlflow
import numpy as np

from src.benchmark.guards import INPUT_VERSION
from src.benchmark.modernbert import MODEL_ID,REVISION,base_snapshot,load_bootstrap,tokenizer
from src.benchmark.projection import POLICY_ID
from src.eval.calibrate import fit_temperature
from src.integrations.agentdojo.inventory import digest

CONFIG=dict(schema_version="banking-encoder-training-v1",seed=17,epochs=3,batch_size=2,gradient_accumulation=4,
    learning_rate=2e-5,weight_decay=0.01,maximum_tokens=2048,device="mps",dtype="float32",
    checkpoint_selection="lowest_validation_uncalibrated_NLL",maximum_validation_false_block_rate=0.10,
    test_source="original-reviewed-AgentDojo-no-fit-transfer-development-holdout",base_model=MODEL_ID,base_revision=REVISION)


def verify_partitions(rows):
    allowed={"train","calibration","validation"}
    seen={name:{} for name in ("scenario_group","recipe_family","document_group","input_digest")}
    for row in rows:
        part=row["partition"]
        if part not in allowed or type(row["unsafe_label"]) is not int or row["unsafe_label"] not in {0,1}:raise ValueError("invalid_training_row")
        if row.get("original_benchmark_case") or row.get("execution_error") or not row["projection_supported"]:raise ValueError("ineligible_training_row")
        for key,mapping in seen.items():
            value=row[key]
            if value in mapping and mapping[value]!=part:raise ValueError("cross_partition_leak_"+key)
            mapping[value]=part
    for part in allowed:
        if {row["unsafe_label"] for row in rows if row["partition"]==part}!={0,1}:raise ValueError("partition_class_coverage_required")
    by_group={}
    for row in rows:by_group.setdefault(row["scenario_group"],[]).append(row["unsafe_label"])
    if any(sorted(labels)!=[0,1] for labels in by_group.values()):raise ValueError("counterfactual_pairs_must_stay_complete")
    return dict(by_partition=dict(Counter(r["partition"] for r in rows)),
        group_counts={name:len(values) for name,values in seen.items()},no_original_cases_fitted=True,leakage_checks_passed=True)


def risks(logits,temperature):
    if not math.isfinite(temperature) or temperature<=0:raise ValueError("invalid_temperature")
    values=(np.asarray(logits,dtype=float)[:,1]-np.asarray(logits,dtype=float)[:,0])/temperature
    # Clip only exponent evaluation, never the input context or measured logits.
    return 1/(1+np.exp(-np.clip(values,-700,700)))


def interval(errors,total):
    if not total:return None
    z=1.959963984540054;fraction=errors/total;denominator=1+z*z/total
    center=(fraction+z*z/(2*total))/denominator
    half=z*math.sqrt(fraction*(1-fraction)/total+z*z/(4*total*total))/denominator
    return [max(0.0,center-half),min(1.0,center+half)]


def metrics(logits,labels,*,temperature=1.0,threshold=0.5):
    probability=risks(logits,temperature);labels=np.asarray(labels,dtype=int)
    clipped=np.clip(probability,1e-15,1-1e-15);predicted=probability>=threshold
    false_allow=int(np.sum((labels==1)&~predicted));false_block=int(np.sum((labels==0)&predicted))
    ece=0.0;bins=[]
    for index in range(10):
        selected=(probability>=index/10)&((probability<(index+1)/10) if index<9 else (probability<=1))
        count=int(np.sum(selected))
        if count:
            avg=float(np.mean(probability[selected]));observed=float(np.mean(labels[selected]));ece+=count/len(labels)*abs(avg-observed)
            bins.append(dict(lower=index/10,upper=(index+1)/10,count=count,mean_risk=avg,observed_unsafe=observed))
    return dict(samples=len(labels),permitted=int(np.sum(labels==0)),prohibited=int(np.sum(labels==1)),
        false_allows=false_allow,false_blocks=false_block,
        false_allow_rate=false_allow/int(np.sum(labels==1)) if np.any(labels==1) else None,
        false_block_rate=false_block/int(np.sum(labels==0)) if np.any(labels==0) else None,
        false_allow_rate_wilson95=interval(false_allow,int(np.sum(labels==1))),
        false_block_rate_wilson95=interval(false_block,int(np.sum(labels==0))),
        nll=float(-np.mean(labels*np.log(clipped)+(1-labels)*np.log(1-clipped))),
        brier=float(np.mean((probability-labels)**2)),ece=ece,reliability_bins=bins)


def choose_threshold(logits,labels,temperature,maximum_false_blocks=0.10):
    points=sorted(set(risks(logits,temperature).tolist()))
    candidates=[0.0,1.0,*[(a+b)/2 for a,b in zip(points,points[1:])]]
    permitted=sum(value==0 for value in labels)
    if not permitted or not any(value==1 for value in labels):raise ValueError("validation_needs_both_classes")
    evaluated=[]
    for point in candidates:
        result=metrics(logits,labels,temperature=temperature,threshold=point)
        if result["false_blocks"]/permitted<=maximum_false_blocks:
            evaluated.append((result["false_allows"],result["false_blocks"],abs(point-0.5),point))
    if not evaluated:raise RuntimeError("no_feasible_validation_operating_point")
    return min(evaluated)[-1]


def predict(model,tok,rows,*,device,batch_size=2):
    import torch
    model.eval();output=[]
    with torch.inference_mode():
        for start in range(0,len(rows),batch_size):
            batch=rows[start:start+batch_size]
            inputs=tok([r["model_input"] for r in batch],return_tensors="pt",padding=True,truncation=False)
            if inputs["input_ids"].shape[1]>CONFIG["maximum_tokens"]:raise ValueError("training_input_overflow")
            with mlflow.start_span(name="encoder_prediction_batch",span_type="CHAIN") as span:
                span.set_inputs(dict(candidate_ids=[r["candidate_id"] for r in batch],tokens=inputs["input_ids"].shape[1],purpose="offline-quality-evaluation"))
                logits=model(**{key:value.to(device) for key,value in inputs.items()}).logits.float().cpu().tolist()
                if not all(math.isfinite(v) for row in logits for v in row):raise RuntimeError("nonfinite_prediction")
                span.set_outputs(dict(logits=logits));output.extend(logits)
    return output


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hybrid",type=Path,required=True)
    parser.add_argument("--original",type=Path,required=True,help="ModernBERT re-tokenized original reviewed dataset, NO FIT")
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[2]/".env")
    os.environ["MLFLOW_ENABLE_ASYNC_TRACE_LOGGING"]="false"
    os.environ["MLFLOW_HTTP_REQUEST_MAX_RETRIES"]="0";os.environ["MLFLOW_HTTP_REQUEST_TIMEOUT"]="10"
    mlflow.set_tracking_uri(os.getenv("MLFLOW_TRACKING_URI","http://localhost:5001"));mlflow.set_experiment("breaker-banking-guard-development")
    import torch
    if not torch.backends.mps.is_available() or os.getenv("PYTORCH_ENABLE_MPS_FALLBACK") not in {None,"0"}:raise RuntimeError("explicit_mps_required")
    rows=[json.loads(line) for line in (args.hybrid/"rows.jsonl").read_text().splitlines()]
    source=json.loads((args.hybrid/"report.json").read_text())
    if digest(rows)!=source["dataset_sha256"]:raise ValueError("hybrid_dataset_changed")
    validation=verify_partitions(rows)
    originals=[json.loads(line) for line in (args.original/"rows.jsonl").read_text().splitlines()]
    coverage=json.loads((args.original/"coverage.json").read_text())
    if digest(originals)!=coverage["dataset_sha256"]:raise ValueError("original_dataset_changed")
    if set(r["input_digest"] for r in originals)&set(r["input_digest"] for r in rows):raise ValueError("original_fit_input_overlap")
    args.output.mkdir(parents=True,exist_ok=False,mode=0o700)
    groups={part:[row for row in rows if row["partition"]==part] for part in ("train","calibration","validation")}
    manifest=dict(config=CONFIG,source_hybrid_sha256=digest(source),source_original_sha256=digest(coverage),
        partitions={name:[r["candidate_id"] for r in values] for name,values in groups.items()},validation=validation)
    (args.output/"training-protocol.json").write_text(json.dumps(manifest,indent=2)+"\n")
    random.seed(CONFIG["seed"]);np.random.seed(CONFIG["seed"]);torch.manual_seed(CONFIG["seed"])
    tok=tokenizer(base_snapshot());tok.model_max_length=CONFIG["maximum_tokens"]
    model,loading=load_bootstrap(base_snapshot(),device="mps")
    optimizer=torch.optim.AdamW(model.parameters(),lr=CONFIG["learning_rate"],weight_decay=CONFIG["weight_decay"])
    best=None;best_nll=float("inf");history=[]
    with mlflow.start_run(run_name="modernbert-hybrid-training-calibration-and-transfer-test") as run:
        mlflow.log_dict(manifest,"protocol/training.json");mlflow.log_dict(loading,"protocol/bootstrap-loading.json")
        for epoch in range(CONFIG["epochs"]):
            order=list(groups["train"]);random.Random(CONFIG["seed"]+epoch).shuffle(order)
            model.train();optimizer.zero_grad(set_to_none=True);losses=[];started=perf_counter()
            batches=[order[i:i+CONFIG["batch_size"]] for i in range(0,len(order),CONFIG["batch_size"])]
            with mlflow.start_span(name="encoder_training_epoch",span_type="CHAIN") as epoch_span:
                epoch_span.set_inputs(dict(epoch=epoch+1,samples=len(order),configuration=CONFIG))
                for step,batch in enumerate(batches):
                    inputs=tok([r["model_input"] for r in batch],return_tensors="pt",padding=True,truncation=False)
                    if inputs["input_ids"].shape[1]>CONFIG["maximum_tokens"]:raise ValueError("training_input_overflow")
                    with mlflow.start_span(name="encoder_forward_backward",span_type="CHAIN") as span:
                        span.set_inputs(dict(candidate_ids=[r["candidate_id"] for r in batch],labels=[r["unsafe_label"] for r in batch],tokens=inputs["input_ids"].shape[1]))
                        result=model(**{key:value.to("mps") for key,value in inputs.items()},labels=torch.tensor([r["unsafe_label"] for r in batch],device="mps"))
                        loss=result.loss
                        if not torch.isfinite(loss):raise RuntimeError("training_loss_nonfinite")
                        (loss/CONFIG["gradient_accumulation"]).backward()
                        value=float(loss.detach().cpu());losses.append(value)
                        if (step+1)%CONFIG["gradient_accumulation"]==0 or step==len(batches)-1:
                            norm=torch.nn.utils.clip_grad_norm_(model.parameters(),1.0)
                            if not torch.isfinite(norm):raise RuntimeError("training_gradient_nonfinite")
                            optimizer.step();optimizer.zero_grad(set_to_none=True)
                        span.set_outputs(dict(loss=value))
                epoch_span.set_outputs(dict(mean_loss=float(np.mean(losses)),seconds=perf_counter()-started,batches=len(batches)))
            logits=predict(model,tok,groups["validation"],device="mps")
            score=metrics(logits,[r["unsafe_label"] for r in groups["validation"]])
            history.append(dict(epoch=epoch+1,training_nll=float(np.mean(losses)),validation=score))
            mlflow.log_metrics(dict(training_nll=float(np.mean(losses)),validation_nll=score["nll"]),step=epoch+1)
            if score["nll"]<best_nll:
                best_nll=score["nll"];best={key:value.detach().cpu().clone() for key,value in model.state_dict().items()}
        model.load_state_dict(best);model.eval()
        cal_logits=predict(model,tok,groups["calibration"],device="mps");cal_labels=[r["unsafe_label"] for r in groups["calibration"]]
        temperature=fit_temperature([dict(logits=logit,label=label) for logit,label in zip(cal_logits,cal_labels,strict=True)])
        val_logits=predict(model,tok,groups["validation"],device="mps");val_labels=[r["unsafe_label"] for r in groups["validation"]]
        threshold=choose_threshold(val_logits,val_labels,temperature,CONFIG["maximum_validation_false_block_rate"])
        model_id="modernbert-banking-hybrid-v1"
        artifact=args.output/"model";model.config.id2label={0:"permitted",1:"prohibited"};model.config.label2id={"permitted":0,"prohibited":1}
        model.save_pretrained(artifact,safe_serialization=True);tok.save_pretrained(artifact)
        calibration=dict(model_id=model_id,policy_id=POLICY_ID,calibration_set_id=digest(groups["calibration"]),
            temperature=temperature,threshold=threshold,input_version=INPUT_VERSION,validation_set_sha256=digest(groups["validation"]),
            training_protocol_sha256=digest(manifest))
        calibration["temperature_boundary_warning"]=temperature<=math.exp(-4.9) or temperature>=math.exp(4.9)
        # Freeze before opening the original transfer/development holdout.
        (args.output/"calibration.json").write_text(json.dumps(calibration,indent=2)+"\n")
        files={path.name:hashlib.sha256(path.read_bytes()).hexdigest() for path in artifact.iterdir() if path.is_file()}
        model_manifest=dict(model_id=model_id,policy_id=POLICY_ID,input_version=INPUT_VERSION,trained_for="banking-action-guard",unsafe_class_id=1,
            files=files,base_model=MODEL_ID,base_revision=REVISION,calibration=calibration,training_protocol_sha256=digest(manifest),training_run_id=run.info.run_id)
        (artifact/"benchmark-guard.json").write_text(json.dumps(model_manifest,indent=2)+"\n")
        from src.benchmark.encoder import EncoderLogit
        reload_model=EncoderLogit(artifact,policy_id=POLICY_ID,device="mps")
        reload_delta=abs(reload_model(groups["validation"][0]["model_input"])-(val_logits[0][1]-val_logits[0][0]))
        if reload_delta>2e-3:raise RuntimeError("export_reload_logit_mismatch")
        del reload_model
        test=[r for r in originals if r["projection_supported"] and r["unsafe_label"] is not None and not r.get("label_quarantine")]
        test_logits=predict(model,tok,test,device="mps")
        result=dict(training_run_id=run.info.run_id,model_id=model_id,configuration=CONFIG,history=history,calibration=calibration,
            export_reload_logit_delta=reload_delta,
            calibration_before=metrics(cal_logits,cal_labels),calibration_after=metrics(cal_logits,cal_labels,temperature=temperature,threshold=threshold),
            validation=metrics(val_logits,val_labels,temperature=temperature,threshold=threshold),
            original_transfer_holdout=metrics(test_logits,[r["unsafe_label"] for r in test],temperature=temperature,threshold=threshold),
            original_total=len(originals),original_scored=len(test),original_excluded=len(originals)-len(test),
            exclusions=[dict(candidate_id=r["candidate_id"],issues=r["projection_issues"],quarantined=bool(r.get("label_quarantine"))) for r in originals if r not in test],
            classifier_latency_claim=False,full_native_AB_complete=False)
        (args.output/"result.json").write_text(json.dumps(result,indent=2)+"\n")
        (args.output/"holdout-predictions.jsonl").write_text("".join(json.dumps(dict(candidate_id=row["candidate_id"],input_digest=row["input_digest"],unsafe_label=row["unsafe_label"],logits=logit))+'\n' for row,logit in zip(test,test_logits,strict=True)))
        mlflow.log_dict(result,"quality/result.json");mlflow.log_artifact(str(args.output/"calibration.json"),"artifact")
        mlflow.log_artifact(str(artifact/"benchmark-guard.json"),"artifact")
        print(json.dumps(result,indent=2))


if __name__=="__main__":main()
