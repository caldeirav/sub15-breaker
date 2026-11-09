"""Arm-local encoder lifetime; never changes the shared acting-model service."""
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from threading import Lock
from time import perf_counter_ns

from src.benchmark.admission import classifier_guard
from src.benchmark.encoder import tokenizer
from src.benchmark.projection import POLICY_ID
from src.benchmark.guards import timed_review


class ResidentClassifier:
    """Load, prime and serve on the SAME owned thread; preserve MLflow context."""
    def __init__(self,artifact,calibration,device):
        self.executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix="banking-classifier")
        self.lock=Lock();self.closed=False
        try:self.inner,self.tokenizer=self.executor.submit(copy_context().run,classifier_guard,artifact,calibration,device=device).result()
        except BaseException:self.executor.shutdown(wait=True);raise
        self.guard_id=self.inner.guard_id;self.stage_timings_ns={}
        # timed_review reads frozen calibration context off the selected guard.
        self.calibration=getattr(self.inner,"calibration",None)

    def review(self,value):
        def forward():
            verdict=self.inner.review(value)
            meta={name:getattr(self.inner,name,None) for name in ("decision_core_ns","calibration_threshold_ns","input_tokens")}
            meta["stage_timings_ns"]=dict(getattr(self.inner,"stage_timings_ns",{}))
            return verdict,meta
        with self.lock:
            if self.closed:raise RuntimeError("classifier_resource_closed")
            verdict,meta=self.executor.submit(copy_context().run,forward).result()
            for name,value in meta.items():setattr(self,name,value)
            return verdict

    def close(self):
        with self.lock:
            if self.closed:return
            try:self.executor.submit(copy_context().run,self.inner.close).result()
            finally:self.closed=True;self.executor.shutdown(wait=True)


class ServingResources:
    def __init__(self,artifact,calibration,*,classifier_device="mps",resident=False):
        if classifier_device not in {"cpu","mps"}:raise ValueError("unsupported_classifier_device")
        self.artifact,self.calibration,self.device=artifact,calibration,classifier_device
        self.classifier=None;self.tokenizer=None;self.events=[]
        self.resident=resident;self.primed=False;self.priming_samples=[];self.primed_inputs=None

    def projection_tokenizer(self):
        if self.tokenizer is None:
            started=perf_counter_ns();self.tokenizer=tokenizer(self.artifact,policy_id=POLICY_ID)
            self.events.append(dict(operation="load_tokenizer_only",elapsed_ns=perf_counter_ns()-started))
        return self.tokenizer

    def select(self,arm):
        if arm not in {"classifier","llm","control"}:raise ValueError("unknown_serving_arm")
        if arm!="classifier":
            if not self.resident:self.release_classifier()
            return None
        if self.classifier is None:
            started=perf_counter_ns()
            if self.resident:
                self.classifier=ResidentClassifier(self.artifact,self.calibration,self.device);self.tokenizer=self.classifier.tokenizer
            else:self.classifier,self.tokenizer=classifier_guard(self.artifact,self.calibration,device=self.device)
            self.events.append(dict(operation="load_classifier",device=self.device,elapsed_ns=perf_counter_ns()-started))
        return self.classifier

    def prepare(self,values,*,passes=2):
        if not self.resident or passes!=2:raise ValueError("explicit_resident_priming_policy_required")
        inputs=[(name,value.digest()) for name,value in values.items()]
        if not inputs:raise ValueError("classifier_priming_inputs_required")
        if self.primed:
            if inputs!=self.primed_inputs:raise ValueError("classifier_priming_inputs_changed")
            return self.snapshot()
        guard=self.select("classifier")
        for index in range(passes):
            for name,value in values.items():
                review=timed_review(guard,value)
                sample=dict(phase="startup_priming_not_scored",input=name,input_digest=value.digest(),pass_index=index,
                    elapsed_ns=review["review_latency_ns"],classifier_core_ns=review.get("classifier_decision_core_ns"),error=review.get("error"))
                self.priming_samples.append(sample)
                # Availability/finite inference only: never gate startup on a preferred decision.
                if review.get("decision") not in {"allow","block"} or review.get("error"):raise RuntimeError("classifier_priming_failed")
        self.primed=True;self.primed_inputs=inputs;self.events.append(dict(operation="classifier_priming_complete",forwards=len(self.priming_samples)))
        return self.snapshot()

    def release_classifier(self):
        if self.classifier is not None:
            self.classifier.close();self.classifier=None
            self.primed=False;self.primed_inputs=None
            self.events.append(dict(operation="release_local_classifier",device=self.device))

    def snapshot(self):
        return dict(classifier_weights_loaded=self.classifier is not None,tokenizer_loaded=self.tokenizer is not None,
            classifier_device=self.device,events=list(self.events),explicit_warmup_requests=len(self.priming_samples),
            serving_profile="resident-primed-v1" if self.resident else "historical-arm-local",classifier_primed=self.primed,
            startup_priming=list(self.priming_samples),priming_scored_as_accuracy=False,
            shared_model_reloaded=False,global_settings_changed=False,
            isolation="local encoder lifetime only; not dedicated hardware or unified-memory isolation")


def provider_status(model_id,*,timeout_seconds=5):
    """Read-only loaded-model status, not a model request or termination proof."""
    try:
        rows=json.loads(subprocess.check_output(["lms","ps","--json"],text=True,timeout=timeout_seconds))
        matches=[m for m in rows if m.get("identifier")==model_id]
        if len(matches)!=1:return dict(state="unobserved",reason="loaded_model_identity_not_unique")
        model=matches[0];status=model.get("status");queued=model.get("queued")
        if status=="idle" and queued==0:return dict(state="idle",model_id=model_id,queued=0,context_length=model.get("contextLength"))
        return dict(state="busy" if status is not None else "unobserved",model_id=model_id,status=status,queued=queued)
    except (OSError,ValueError,subprocess.SubprocessError) as exc:
        return dict(state="unobserved",error=type(exc).__name__)
