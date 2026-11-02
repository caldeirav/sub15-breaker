"""Pinned ModernBERT acquisition and explicit Apple-MPS compatibility control.

The bootstrap classification head is intentionally untrained. It is never
exported as a banking guard and its logits are not safety verdicts.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
from time import perf_counter

MODEL_ID="answerdotai/ModernBERT-base"
REVISION="8949b909ec900327062f0ebf497f51aef5e6f0c8"
FILES=["config.json","model.safetensors","tokenizer.json","tokenizer_config.json","special_tokens_map.json","README.md"]


def base_snapshot(*,download=False):
    from huggingface_hub import snapshot_download
    return Path(snapshot_download(MODEL_ID,revision=REVISION,allow_patterns=FILES,
        local_files_only=not download,token=False,max_workers=2))


def file_hashes(directory):
    result={}
    for name in FILES:
        path=Path(directory)/name
        if not path.is_file():raise ValueError("pinned_base_file_missing")
        with path.open("rb") as stream:result[name]=hashlib.file_digest(stream,"sha256").hexdigest()
    return result


def tokenizer(directory):
    from transformers import AutoTokenizer
    return AutoTokenizer.from_pretrained(directory,local_files_only=True,trust_remote_code=False)


def load_bootstrap(directory,*,device="cpu"):
    import torch
    from transformers import AutoModelForSequenceClassification
    torch.manual_seed(17)
    # New classification keys/unused MLM keys are valid only during bootstrap.
    model,info=AutoModelForSequenceClassification.from_pretrained(directory,num_labels=2,
        local_files_only=True,trust_remote_code=False,use_safetensors=True,output_loading_info=True,
        reference_compile=False,attn_implementation="sdpa",dtype=torch.float32)
    return model.to(device),info


def retokenize(rows,directory,*,maximum=2048):
    tok=tokenizer(directory)
    output=[]
    for row in rows:
        value=dict(row)
        count=len(tok(row["model_input"],truncation=False)["input_ids"])
        issues=[issue for issue in row["projection_issues"] if issue!="encoder_context_overflow"]
        if count>maximum:issues.append("encoder_context_overflow")
        value.update(input_tokens=count,maximum_tokens=maximum,projection_issues=issues,projection_supported=not issues,
            tokenizer_model_id=MODEL_ID,tokenizer_revision=REVISION,training_eligible=False)
        value["training_blockers"]=[reason for reason in row["training_blockers"] if reason!="input_unsupported"]
        if issues:value["training_blockers"].append("input_unsupported")
        output.append(value)
    return output


def compatibility(directory,text,*,maximum=2048):
    import torch
    if not torch.backends.mps.is_available():raise RuntimeError("mps_not_available")
    if os.getenv("PYTORCH_ENABLE_MPS_FALLBACK") not in {None,"0"}:raise RuntimeError("implicit_mps_cpu_fallback_not_allowed")
    tok=tokenizer(directory)
    inputs=tok(text,return_tensors="pt",truncation=False)
    if inputs["input_ids"].shape[1]>maximum:raise ValueError("compatibility_input_over_limit")
    model,loading=load_bootstrap(directory)
    model.eval()
    with torch.inference_mode():cpu=model(**inputs).logits.detach().clone()
    model.to("mps");gpu={key:value.to("mps") for key,value in inputs.items()}
    torch.mps.synchronize();started=perf_counter()
    with torch.inference_mode():mps=model(**gpu).logits.detach().cpu()
    torch.mps.synchronize();forward_seconds=perf_counter()-started
    delta=(cpu-mps).abs().max().item()
    if not torch.isfinite(mps).all() or not torch.allclose(cpu,mps,atol=2e-3,rtol=2e-3):raise RuntimeError("mps_cpu_forward_mismatch")
    model.train();optimizer=torch.optim.AdamW(model.parameters(),lr=1e-6)
    loss=model(**gpu,labels=torch.tensor([0],device="mps")).loss
    loss.backward()
    norm=torch.nn.utils.clip_grad_norm_(model.parameters(),1.0)
    if not torch.isfinite(loss) or not torch.isfinite(norm):raise RuntimeError("mps_backward_nonfinite")
    optimizer.step();torch.mps.synchronize()
    return dict(model_id=MODEL_ID,revision=REVISION,device="mps",dtype="float32",attention="sdpa",reference_compile=False,
        tokens=inputs["input_ids"].shape[1],cpu_mps_max_absolute_difference=delta,
        backward_loss=float(loss.detach().cpu()),gradient_norm=float(norm.detach().cpu()),
        mps_current_allocated_bytes=torch.mps.current_allocated_memory(),mps_driver_allocated_bytes=torch.mps.driver_allocated_memory(),
        first_forward_seconds=forward_seconds,latency_benchmark=False,
        untrained_head=True,banking_guard=False,exported_model=False,loading_info=loading)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download",action="store_true",help="Explicitly acquire the one pinned base checkpoint, no alternate model")
    parser.add_argument("--dataset",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--mps-smoke",action="store_true")
    args=parser.parse_args()
    if args.output.exists():raise FileExistsError(args.output)
    directory=base_snapshot(download=args.download)
    source=json.loads((args.dataset/"decision.json").read_text())
    rows=[json.loads(line) for line in (args.dataset/"labels.review-applied.jsonl").read_text().splitlines()]
    from src.integrations.agentdojo.inventory import digest
    if digest(rows)!=source["derived_dataset_sha256"]:raise ValueError("review_applied_dataset_changed")
    converted=retokenize(rows,directory)
    report=dict(schema_version="modernbert-coverage-v1",model_id=MODEL_ID,revision=REVISION,base_directory=str(directory),
        files_sha256=file_hashes(directory),source_decision_sha256=digest(source),source_dataset_sha256=digest(rows),
        dataset_sha256=digest(converted),maximum_tokens=2048,candidates=len(rows),
        supported=sum(row["projection_supported"] for row in converted),
        known_binary_supported=sum(row["projection_supported"] and row["unsafe_label"] is not None for row in converted),
        min_tokens=min(row["input_tokens"] for row in converted),max_tokens=max(row["input_tokens"] for row in converted),
        pretrained_banking_guard=False,model_requests=0,quarantined=[r["candidate_id"] for r in converted if r.get("label_quarantine")])
    if args.mps_smoke:
        report["compatibility"]=compatibility(directory,max(converted,key=lambda row:row["input_tokens"])["model_input"])
    args.output.mkdir(parents=True,mode=0o700)
    for name,text in (("coverage.json",json.dumps(report,indent=2)+"\n"),("rows.jsonl","".join(json.dumps(row,sort_keys=True)+"\n" for row in converted))):
        path=args.output/name;path.write_text(text);path.chmod(0o600)
    print(json.dumps(report,indent=2))


if __name__=="__main__":main()
