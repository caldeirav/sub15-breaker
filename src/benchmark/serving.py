"""Arm-local encoder lifetime; never changes the shared acting-model service."""
import json
import subprocess
from time import perf_counter_ns

from src.benchmark.admission import classifier_guard
from src.benchmark.encoder import tokenizer
from src.benchmark.projection import POLICY_ID


class ServingResources:
    def __init__(self,artifact,calibration,*,classifier_device="mps"):
        if classifier_device not in {"cpu","mps"}:raise ValueError("unsupported_classifier_device")
        self.artifact,self.calibration,self.device=artifact,calibration,classifier_device
        self.classifier=None;self.tokenizer=None;self.events=[]

    def projection_tokenizer(self):
        if self.tokenizer is None:
            started=perf_counter_ns();self.tokenizer=tokenizer(self.artifact,policy_id=POLICY_ID)
            self.events.append(dict(operation="load_tokenizer_only",elapsed_ns=perf_counter_ns()-started))
        return self.tokenizer

    def select(self,arm):
        if arm not in {"classifier","llm","control"}:raise ValueError("unknown_serving_arm")
        if arm!="classifier":
            self.release_classifier();return None
        if self.classifier is None:
            started=perf_counter_ns()
            self.classifier,self.tokenizer=classifier_guard(self.artifact,self.calibration,device=self.device)
            self.events.append(dict(operation="load_classifier",device=self.device,elapsed_ns=perf_counter_ns()-started))
        return self.classifier

    def release_classifier(self):
        if self.classifier is not None:
            self.classifier.close();self.classifier=None
            self.events.append(dict(operation="release_local_classifier",device=self.device))

    def snapshot(self):
        return dict(classifier_weights_loaded=self.classifier is not None,tokenizer_loaded=self.tokenizer is not None,
            classifier_device=self.device,events=list(self.events),explicit_warmup_requests=0,
            shared_model_reloaded=False,global_settings_changed=False,
            isolation="local encoder lifetime only; not dedicated hardware or unified-memory isolation")


def provider_status(model_id,*,timeout_seconds=5):
    """Read-only loaded-model status, not a model request or termination proof."""
    try:
        rows=json.loads(subprocess.check_output(["lms","ps","--json"],text=True,timeout=timeout_seconds))
        matches=[m for m in rows if m.get("identifier")==model_id]
        if len(matches)!=1:return dict(state="unobserved",reason="loaded_model_identity_not_unique")
        model=matches[0];status=model.get("status");queued=model.get("queued")
        if status=="idle" and queued==0:return dict(state="idle",model_id=model_id,queued=0)
        return dict(state="busy" if status is not None else "unobserved",model_id=model_id,status=status,queued=queued)
    except (OSError,ValueError,subprocess.SubprocessError) as exc:
        return dict(state="unobserved",error=type(exc).__name__)
