"""One fixed v2 fit; fresh challenge and original transfer open after export only."""
import argparse
from collections import Counter,defaultdict
import gc
import hashlib
import json
import math
import os
from pathlib import Path
import random
from time import perf_counter

import mlflow
import numpy as np

from src.benchmark.encoder import EncoderLogit
from src.benchmark.guards import INPUT_VERSION
from src.benchmark.modernbert import MODEL_ID,REVISION,base_snapshot,file_hashes,load_bootstrap,tokenizer
from src.benchmark.projection import POLICY_ID
from src.benchmark.train_encoder import predict,metrics,risks
from src.benchmark.training_v2 import PROTOCOL,PARTITIONS,choose_stratified_threshold
from src.banking_contracts.tools import READ_TOOLS
from src.eval.calibrate import fit_temperature
from src.integrations.agentdojo.inventory import digest


def load_rows(path):return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def file_sha(path):
    with Path(path).open("rb") as stream:return hashlib.file_digest(stream,"sha256").hexdigest()


def seal_dataset(dataset):
    dataset=Path(dataset);report=json.loads((dataset/"report.json").read_text());scenario=json.loads((dataset/"scenario-manifest.json").read_text())
    if report["scenario_manifest_sha256"]!=digest(scenario):raise ValueError("v2_scenario_manifest_changed")
    seal=dict(schema_version="banking-v2-sealed-dataset-v1",report_sha256=digest(report),scenario_sha256=digest(scenario),
        protocol=PROTOCOL,partition_files={part:dict(sha256=file_sha(dataset/(part+".jsonl")),rows=report["by_partition"][part]) for part in PARTITIONS},
        challenge_rows_parsed=False,challenge_labels_used_for_selection=False)
    path=dataset/"dataset-seal.json"
    with path.open("x") as stream:stream.write(json.dumps(seal,indent=2)+"\n")
    path.chmod(0o600);return seal


def validate_seal(dataset):
    dataset=Path(dataset);seal=json.loads((dataset/"dataset-seal.json").read_text());report=json.loads((dataset/"report.json").read_text())
    if seal["protocol"]!=PROTOCOL or seal["report_sha256"]!=digest(report):raise ValueError("v2_sealed_protocol_or_report_changed")
    scenario=json.loads((dataset/"scenario-manifest.json").read_text())
    if seal["scenario_sha256"]!=digest(scenario):raise ValueError("v2_sealed_scenario_changed")
    for part in PARTITIONS:
        if file_sha(dataset/(part+".jsonl"))!=seal["partition_files"][part]["sha256"]:raise ValueError("v2_sealed_partition_changed")
    return seal,report,scenario


def validate_fit_rows(groups,scenario):
    cases={case["case_id"]:case for case in scenario["cases"]};seen={};digests=set()
    for part,rows in groups.items():
        if part=="fresh_challenge":raise ValueError("v2_challenge_must_not_enter_fitting")
        if len(rows)!=scenario["rows"][part]:raise ValueError("v2_fit_cardinality")
        for row in rows:
            case=cases[row["scenario_group"]]
            if row["partition"]!=part or case["partition"]!=part or row["goal_template_id"]!=case["goal"]["goal_template_id"]:
                raise ValueError("v2_fit_source_binding")
            if hashlib.sha256(row["model_input"].encode()).hexdigest()!=row["input_digest"]:raise ValueError("v2_fit_input_changed")
            if row["input_digest"] in digests:raise ValueError("v2_fit_duplicate_input")
            digests.add(row["input_digest"])
            if row.get("original_benchmark_case") or row.get("execution_error") or not row["projection_supported"] or row.get("label_quarantine"):
                raise ValueError("v2_fit_ineligible_row")
            if row["goal_origin"]=="gemini" and (row["goal_review_status"]!="approved" or not row.get("goal_review_sha256")):
                raise ValueError("v2_fit_unreviewed_goal")
            if row["label_source"]!="CODE/closed-banking-authorization-v2" or type(row["unsafe_label"]) is not int or row["unsafe_label"] not in {0,1}:
                raise ValueError("v2_fit_label_provenance")
            if row["tool"] in READ_TOOLS and row["unsafe_label"]!=0:raise ValueError("v2_fit_read_label_conflict")
            for key in ("scenario_group","entity_group","document_group","source_template_group","goal_template_id","note_id","note_style"):
                group=(key,row[key])
                if group in seen and seen[group]!=part:raise ValueError("v2_fit_source_overlap")
                seen[group]=part


def population_metrics(logits,rows,calibration):
    value=metrics(logits,[row["unsafe_label"] for row in rows],temperature=calibration["temperature"],threshold=calibration["threshold"])
    value["accuracy"]=1-(value["false_allows"]+value["false_blocks"])/value["samples"]
    value["balanced_accuracy"]=(2-value["false_allow_rate"]-value["false_block_rate"])/2 if value["false_allow_rate"] is not None and value["false_block_rate"] is not None else None
    slices={}
    for name,select in (("reads",lambda row:row["tool"] in READ_TOOLS),("mutations",lambda row:row["tool"] not in READ_TOOLS)):
        indices=[index for index,row in enumerate(rows) if select(row)]
        if indices:slices[name]=metrics([logits[i] for i in indices],[rows[i]["unsafe_label"] for i in indices],temperature=calibration["temperature"],threshold=calibration["threshold"])
    value["strata"]=slices
    value["per_tool"]={tool:metrics([logits[i] for i,row in enumerate(rows) if row["tool"]==tool],
        [row["unsafe_label"] for row in rows if row["tool"]==tool],temperature=calibration["temperature"],threshold=calibration["threshold"]) for tool in sorted({row["tool"] for row in rows})}
    for field in ("family","task_id"):
        names=sorted({row[field] for row in rows if row.get(field) is not None})
        value["per_"+field]={name:metrics([logits[i] for i,row in enumerate(rows) if row.get(field)==name],
            [row["unsafe_label"] for row in rows if row.get(field)==name],temperature=calibration["temperature"],threshold=calibration["threshold"]) for name in names}
    value["false_block_constraints_met"]=all(v["false_block_rate"] is not None and v["false_block_rate"]<=0.10 for v in [value,*slices.values()])
    value["sample_intervals_do_not_assert_independent_cases"]=True
    return value


def paired_bootstrap(rows,baseline_logits,baseline_cal,new_logits,new_cal,*,replicates=2000):
    old=risks(baseline_logits,baseline_cal["temperature"])>=baseline_cal["threshold"]
    new=risks(new_logits,new_cal["temperature"])>=new_cal["threshold"]
    groups=defaultdict(list)
    for index,row in enumerate(rows):groups[row["scenario_group"]].append(index)
    values=[]
    for indices in groups.values():
        labels=np.array([rows[i]["unsafe_label"] for i in indices]);read=np.array([rows[i]["tool"] in READ_TOOLS for i in indices])
        a=old[indices];b=new[indices]
        def means(pred):return np.array([np.mean(pred==labels),np.mean(pred[labels==0]),np.mean(~pred[labels==1]),np.mean(pred[(labels==0)&~read])])
        values.append(means(b)-means(a))
    values=np.array(values);rng=np.random.default_rng(17);draws=values[rng.integers(0,len(values),size=(replicates,len(values)))].mean(axis=1)
    return dict(method="paired-scenario-cluster-bootstrap",seed=17,replicates=replicates,clusters=len(values),
        scope="scenario-instance uncertainty conditional on fixed template/note banks, not independent-template uncertainty",
        differences_v2_minus_v1={name:dict(estimate=float(values[:,i].mean()),percentile95=[float(v) for v in np.quantile(draws[:,i],[0.025,0.975])])
            for i,name in enumerate(("accuracy","false_block_rate","false_allow_rate","permitted_mutation_false_block_rate"))})


def train(model,tok,groups):
    import torch
    optimizer=torch.optim.AdamW(model.parameters(),lr=PROTOCOL["learning_rate"],weight_decay=PROTOCOL["weight_decay"])
    history=[];best=None;best_nll=float("inf");best_epoch=None
    for epoch in range(PROTOCOL["epochs"]):
        ordered=list(groups["train"]);random.Random(PROTOCOL["seed"]+epoch).shuffle(ordered)
        batches=[ordered[i:i+PROTOCOL["batch_size"]] for i in range(0,len(ordered),PROTOCOL["batch_size"])]
        model.train();optimizer.zero_grad(set_to_none=True);losses=[];started=perf_counter()
        with mlflow.start_span(name="v2_encoder_training_epoch",span_type="CHAIN") as epoch_span:
            epoch_span.set_inputs(dict(epoch=epoch+1,samples=len(ordered),configuration=PROTOCOL))
            for step,batch in enumerate(batches):
                inputs=tok([row["model_input"] for row in batch],return_tensors="pt",padding=True,truncation=False)
                if inputs["input_ids"].shape[1]>PROTOCOL["maximum_tokens"]:raise ValueError("v2_training_input_overflow")
                with mlflow.start_span(name="v2_encoder_forward_backward",span_type="CHAIN") as span:
                    span.set_inputs(dict(candidate_ids=[r["candidate_id"] for r in batch],tokens=inputs["input_ids"].shape[1]))
                    loss=model(**{key:value.to("mps") for key,value in inputs.items()},labels=torch.tensor([r["unsafe_label"] for r in batch],device="mps")).loss
                    if not torch.isfinite(loss):raise RuntimeError("v2_training_loss_nonfinite")
                    (loss/PROTOCOL["gradient_accumulation"]).backward();value=float(loss.detach().cpu());losses.append(value)
                    if (step+1)%PROTOCOL["gradient_accumulation"]==0 or step==len(batches)-1:
                        norm=torch.nn.utils.clip_grad_norm_(model.parameters(),1.0)
                        if not torch.isfinite(norm):raise RuntimeError("v2_training_gradient_nonfinite")
                        optimizer.step();optimizer.zero_grad(set_to_none=True)
                    span.set_outputs(dict(loss=value))
            epoch_span.set_outputs(dict(mean_loss=float(np.mean(losses)),seconds=perf_counter()-started))
        logits=predict(model,tok,groups["checkpoint_validation"],device="mps")
        score=metrics(logits,[row["unsafe_label"] for row in groups["checkpoint_validation"]])
        history.append(dict(epoch=epoch+1,training_nll=float(np.mean(losses)),checkpoint_validation_nll=score["nll"]))
        mlflow.log_metrics(dict(training_nll=float(np.mean(losses)),checkpoint_validation_nll=score["nll"]),step=epoch+1)
        if score["nll"]<best_nll:
            best_nll=score["nll"];best_epoch=epoch+1;best={key:value.detach().cpu().clone() for key,value in model.state_dict().items()}
        print(json.dumps(history[-1]),flush=True)
    model.load_state_dict(best);model.eval()
    del optimizer,best;gc.collect();torch.mps.empty_cache()
    return history,best_epoch


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset",type=Path,required=True);parser.add_argument("--original",type=Path)
    parser.add_argument("--baseline",type=Path);parser.add_argument("--output",type=Path);parser.add_argument("--seal-only",action="store_true")
    args=parser.parse_args()
    if args.seal_only:print(json.dumps(seal_dataset(args.dataset),indent=2));return
    if not args.output or not args.original or not args.baseline:parser.error("--output, --original and --baseline are required for fitting")
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[2]/".env")
    os.environ["MLFLOW_ENABLE_ASYNC_TRACE_LOGGING"]="false";os.environ["MLFLOW_HTTP_REQUEST_MAX_RETRIES"]="0";os.environ["MLFLOW_HTTP_REQUEST_TIMEOUT"]="10"
    mlflow.set_tracking_uri(os.getenv("MLFLOW_TRACKING_URI","http://localhost:5001"));mlflow.set_experiment("breaker-banking-guard-development")
    import torch
    if not torch.backends.mps.is_available() or os.getenv("PYTORCH_ENABLE_MPS_FALLBACK") not in {None,"0"}:raise RuntimeError("explicit_mps_required")
    seal,report,scenario=validate_seal(args.dataset)
    groups={part:load_rows(args.dataset/(part+".jsonl")) for part in PARTITIONS if part!="fresh_challenge"}
    validate_fit_rows(groups,scenario)
    original_coverage=json.loads((args.original/"coverage.json").read_text())
    base_files=file_hashes(base_snapshot())
    if base_files!=original_coverage["files_sha256"]:raise ValueError("v2_pinned_base_files_changed")
    protocol=dict(configuration=PROTOCOL,dataset_seal_sha256=digest(seal),dataset_report_sha256=digest(report),
        scenario_manifest_sha256=digest(scenario),baseline_artifact_sha256=digest(json.loads((args.baseline/"benchmark-guard.json").read_text())),
        original_coverage_sha256=digest(original_coverage),base_files_sha256=base_files,fresh_challenge_opened=False,
        compare_frozen_v1_on_same_fresh_challenge=True,hyperparameter_runs=1,source_code_sha256=file_sha(__file__))
    args.output.mkdir(parents=True,exist_ok=False,mode=0o700)
    (args.output/"training-protocol.json").write_text(json.dumps(protocol,indent=2)+"\n")
    random.seed(PROTOCOL["seed"]);np.random.seed(PROTOCOL["seed"]);torch.manual_seed(PROTOCOL["seed"])
    tok=tokenizer(base_snapshot());tok.model_max_length=PROTOCOL["maximum_tokens"]
    model,loading=load_bootstrap(base_snapshot(),device="mps")
    with mlflow.start_run(run_name="modernbert-v2-one-fixed-fit-and-frozen-fresh-challenge") as run:
        mlflow.log_dict(protocol,"protocol/training.json");mlflow.log_dict(loading,"protocol/bootstrap-loading.json")
        history,best_epoch=train(model,tok,groups)
        cal_logits=predict(model,tok,groups["calibration"],device="mps")
        temperature=fit_temperature([dict(logits=logits,label=row["unsafe_label"]) for row,logits in zip(groups["calibration"],cal_logits,strict=True)])
        threshold_logits=predict(model,tok,groups["threshold_validation"],device="mps")
        threshold=choose_stratified_threshold(threshold_logits,groups["threshold_validation"],temperature)
        calibration=dict(model_id="modernbert-banking-code-grounded-v2",policy_id=POLICY_ID,input_version=INPUT_VERSION,
            temperature=temperature,threshold=threshold,calibration_set_id=digest(groups["calibration"]),threshold_set_sha256=digest(groups["threshold_validation"]),
            training_protocol_sha256=digest(protocol),temperature_boundary_warning=temperature<=math.exp(-4.9) or temperature>=math.exp(4.9))
        artifact=args.output/"model";model.config.id2label={0:"permitted",1:"prohibited"};model.config.label2id={"permitted":0,"prohibited":1}
        model.save_pretrained(artifact,safe_serialization=True);tok.save_pretrained(artifact)
        files={path.name:file_sha(path) for path in artifact.iterdir() if path.is_file()}
        exported=dict(model_id=calibration["model_id"],policy_id=POLICY_ID,input_version=INPUT_VERSION,trained_for="banking-action-guard",unsafe_class_id=1,
            files=files,base_model=MODEL_ID,base_revision=REVISION,calibration=calibration,training_run_id=run.info.run_id,training_protocol_sha256=digest(protocol))
        (artifact/"benchmark-guard.json").write_text(json.dumps(exported,indent=2)+"\n")
        (args.output/"calibration.json").write_text(json.dumps(calibration,indent=2)+"\n")
        reloaded=EncoderLogit(artifact,policy_id=POLICY_ID,device="mps")
        delta=abs(reloaded(groups["threshold_validation"][0]["model_input"])-(threshold_logits[0][1]-threshold_logits[0][0]))
        if delta>2e-3:raise RuntimeError("v2_export_reload_mismatch")
        del reloaded;gc.collect();torch.mps.empty_cache()
        # The model/temperature/threshold/export are frozen before this first parse.
        validate_seal(args.dataset)
        fresh=load_rows(args.dataset/"fresh_challenge.jsonl")
        fresh_logits=predict(model,tok,fresh,device="mps")
        originals=load_rows(args.original/"rows.jsonl");coverage=json.loads((args.original/"coverage.json").read_text())
        if digest(originals)!=coverage["dataset_sha256"] or digest(coverage)!=protocol["original_coverage_sha256"]:raise ValueError("v2_original_dataset_changed")
        transfer=[dict(row,tool=json.loads(row["model_input"])["action"]["tool"]) for row in originals if row["projection_supported"] and row["unsafe_label"] is not None and not row.get("label_quarantine")]
        transfer_logits=predict(model,tok,transfer,device="mps")
        fresh_score=population_metrics(fresh_logits,fresh,calibration);transfer_score=population_metrics(transfer_logits,transfer,calibration)
        del model;gc.collect();torch.mps.empty_cache()
        baseline=EncoderLogit(args.baseline,policy_id=POLICY_ID,device="mps");baseline_cal=baseline.manifest["calibration"]
        if digest(baseline.manifest)!=protocol["baseline_artifact_sha256"]:raise ValueError("v1_baseline_artifact_changed")
        baseline_logits=predict(baseline.model,baseline.tokenizer,fresh,device="mps")
        old_predictions={row["candidate_id"]:row for row in load_rows(args.baseline.parent/"holdout-predictions.jsonl")}
        if set(old_predictions)!={row["candidate_id"] for row in transfer}:raise ValueError("v1_transfer_population_mismatch")
        old_transfer_logits=[]
        for row in transfer:
            old=old_predictions[row["candidate_id"]]
            if old["input_digest"]!=row["input_digest"] or old["unsafe_label"]!=row["unsafe_label"]:raise ValueError("v1_transfer_binding_mismatch")
            old_transfer_logits.append(old["logits"])
        eligible_ids={row["candidate_id"] for row in transfer}
        result=dict(training_run_id=run.info.run_id,model_id=calibration["model_id"],history=history,selected_epoch=best_epoch,calibration=calibration,
            threshold_validation=population_metrics(threshold_logits,groups["threshold_validation"],calibration),
            calibration_before=metrics(cal_logits,[r["unsafe_label"] for r in groups["calibration"]]),
            calibration_after=metrics(cal_logits,[r["unsafe_label"] for r in groups["calibration"]],temperature=temperature,threshold=threshold),
            fresh_challenge=fresh_score,frozen_v1_on_fresh_challenge=population_metrics(baseline_logits,fresh,baseline_cal),
            fresh_paired_group_bootstrap=paired_bootstrap(fresh,baseline_logits,baseline_cal,fresh_logits,calibration),
            original_development_transfer=transfer_score,original_total=len(originals),original_excluded=len(originals)-len(transfer),
            frozen_v1_original_transfer=population_metrics(old_transfer_logits,transfer,baseline_cal),
            exclusions=[dict(candidate_id=r["candidate_id"],issues=r["projection_issues"],quarantined=bool(r.get("label_quarantine"))) for r in originals if r["candidate_id"] not in eligible_ids],
            export_reload_logit_delta=delta,independence_scope=scenario["independence_scope"],native_agent_episodes=0,
            coverage_limitations=["partial multi-field updates covered; mixed-tool multi-intent workflows are not a synthetic fitting family"],
            agent_task_success_rate_measured=False,latency_claim=False,original_corpus_fit=False,repeated_training_for_preferred_result=False)
        for name,values,logits in (("fresh-predictions.jsonl",fresh,fresh_logits),("v1-fresh-predictions.jsonl",fresh,baseline_logits),("transfer-predictions.jsonl",transfer,transfer_logits)):
            path=args.output/name;path.write_text("".join(json.dumps(dict(candidate_id=row["candidate_id"],input_digest=row["input_digest"],unsafe_label=row["unsafe_label"],logits=logit))+"\n" for row,logit in zip(values,logits,strict=True)))
            mlflow.log_artifact(str(path),"predictions")
        (args.output/"result.json").write_text(json.dumps(result,indent=2)+"\n")
        mlflow.log_dict(result,"quality/result.json");mlflow.log_dict(exported,"artifact/benchmark-guard.json")
        print(json.dumps(result,indent=2))


if __name__=="__main__":main()
