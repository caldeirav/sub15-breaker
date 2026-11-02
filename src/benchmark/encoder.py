"""Local-only compact neural encoder loader for a reviewed benchmark artifact.

No model or weights are downloaded. Loading a base/relevance/command head is not
evidence of a trained banking guard; the adapter requires the matching manifest
and rejects a partially/randomly initialized sequence-classification head.
"""
import hashlib
import json
import math
import gc
from time import perf_counter_ns
from pathlib import Path

from src.benchmark.guards import INPUT_VERSION


def manifest(directory,*,policy_id):
    directory=Path(directory)
    value=json.loads((directory/"benchmark-guard.json").read_text())
    if (value.get("input_version")!=INPUT_VERSION or value.get("policy_id")!=policy_id or
        value.get("trained_for")!="banking-action-guard" or value.get("unsafe_class_id")!=1 or
        not value.get("model_id") or not isinstance(value.get("files"),dict) or not value["files"]):
        raise ValueError("incompatible_banking_encoder_manifest")
    # Bind every local file the loaders could consume, not just a convenient
    # subset of weights. This deliberately supports a small, flat export only.
    actual_files={path.name for path in directory.iterdir() if path.name!="benchmark-guard.json"}
    if (actual_files!=set(value["files"]) or
            not {"config.json","tokenizer_config.json","tokenizer.json","model.safetensors"}<=actual_files):
        raise ValueError("encoder_manifest_incomplete_export")
    for name,expected in value["files"].items():
        path=(directory/name).resolve()
        if not path.is_relative_to(directory.resolve()) or not path.is_file():
            raise ValueError("encoder_manifest_file_missing_or_outside_artifact")
        with path.open("rb") as stream:actual=hashlib.file_digest(stream,"sha256").hexdigest()
        if actual!=expected:raise ValueError("encoder_artifact_hash_mismatch")
    return value


def tokenizer(directory,*,policy_id):
    """Verified projection tokenizer only: no classification weights/device."""
    manifest(directory,policy_id=policy_id)
    from transformers import AutoTokenizer
    return AutoTokenizer.from_pretrained(directory,local_files_only=True,trust_remote_code=False)


class EncoderLogit:
    def __init__(self,directory,*,policy_id,device="cpu"):
        self.manifest=manifest(directory,policy_id=policy_id)
        self.model_id=self.manifest["model_id"]
        import torch
        from transformers import AutoModelForSequenceClassification,AutoTokenizer
        self.torch=torch
        self.tokenizer=AutoTokenizer.from_pretrained(directory,local_files_only=True,trust_remote_code=False)
        self.model,info=AutoModelForSequenceClassification.from_pretrained(directory,local_files_only=True,
            trust_remote_code=False,use_safetensors=True,output_loading_info=True)
        if self.model.config.num_labels!=2 or any(info.get(key) for key in ("missing_keys","unexpected_keys","mismatched_keys","error_msgs")):
            raise ValueError("encoder_head_not_fully_loaded")
        self.model=self.model.to(device).eval()

    def close(self):
        if self.model is None:return
        device=self.model.device.type
        self.model=None
        gc.collect()
        if device=="mps":self.torch.mps.empty_cache()

    def __call__(self,text):
        if self.model is None:raise RuntimeError("encoder_resource_closed")
        self.last_timings_ns={};started=perf_counter_ns()
        inputs=self.tokenizer(text,return_tensors="pt",truncation=False)
        self.last_input_tokens=inputs["input_ids"].shape[1]
        tokenized=perf_counter_ns()
        maximum=min(self.tokenizer.model_max_length,self.model.config.max_position_embeddings)
        if inputs["input_ids"].shape[1]>maximum:raise ValueError("encoder_input_requires_truncation")
        inputs={key:value.to(self.model.device) for key,value in inputs.items()}
        enqueued=perf_counter_ns()
        with self.torch.inference_mode():logits=self.model(**inputs).logits[0].float().cpu().tolist()
        completed=perf_counter_ns()
        if len(logits)!=2 or not all(math.isfinite(value) for value in logits):raise ValueError("invalid_encoder_logits")
        self.last_timings_ns=dict(tokenization_ns=tokenized-started,device_enqueue_ns=enqueued-tokenized,
            forward_and_host_result_ns=completed-enqueued,encoder_total_ns=completed-started)
        return logits[1]-logits[0]
