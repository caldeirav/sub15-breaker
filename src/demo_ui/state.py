"""Bounded durable UI jobs and observed events, not reconstructed live traces."""
from concurrent.futures import ThreadPoolExecutor
import json
import fcntl
import os
from pathlib import Path
import re
import threading
from time import perf_counter_ns
from uuid import uuid4

from src.benchmark.deployment import private
from src.integrations.agentdojo.inventory import digest
from src.demo_ui.protocol import CARDS,UsageLog,make_pair

TERMINAL = {"completed", "failed", "interrupted"}
ERROR_MESSAGES = {
    "demo_source_changed_restart_server": "Execution code changed after this server started. Stop the UI with Ctrl-C, wait for cleanup, then restart it before a new run.",
    "repeatable_demo_store_required_run_documented_store_setup": "The installed banking store needs the documented repeatable-demo image upgrade before running this UI.",
}
EVENT_FIELDS = {"stage", "phase", "tool", "tools", "role", "attempt", "status", "utility", "decision", "discarded",
                "duration_ns", "core_ns", "trace_id", "span_id", "run_id", "deleted", "errors", "actor_timings", "error"}


class Job:
    def __init__(self, directory, slot, request_id):
        self.directory = Path(directory); self.directory.mkdir(mode=0o700, parents=True, exist_ok=False)
        self.lock = threading.RLock(); self.origin = perf_counter_ns(); self.events = []
        self.data = dict(id=request_id, slot=slot["slot"], card=slot["card"], order=slot["order"], phase="queued",
            lanes={arm:dict(phase="waiting", summary=None) for arm in ("classifier", "llm")}, external_review=None,
            mode="live_sequential", metrics_note="Nested boundaries are not additive. Arms run sequentially on shared hardware.")
        self.save()

    def save(self):
        with self.lock: private(self.directory/"public.json", self.data)

    def emit(self, lane, event):
        with self.lock:
            if len(self.events) >= 10000: raise RuntimeError("live_event_capacity_exhausted")
            # No arguments, prompts, state, ticket capabilities, tokens or exception payloads.
            facts = {k:v for k,v in event.items() if k in EVENT_FIELDS}
            if "actor_timings" in facts:
                facts["actor_timings"]={k:v for k,v in facts["actor_timings"].items()
                    if k.endswith("_ns") and type(v) is int and 0<=v<=4_000_000_000_000}
            if any(isinstance(v,str) and len(v)>256 for v in facts.values()): raise ValueError("oversized_public_event")
            row = dict(sequence=len(self.events)+1, lane=lane, observed_ms=(perf_counter_ns()-self.origin)/1e6,
                time_basis="observed_host_clock", **facts)
            text = json.dumps(row, allow_nan=False)
            if len(text)>4096: raise ValueError("oversized_public_event")
            fd = os.open(self.directory/"events.jsonl", os.O_CREAT|os.O_APPEND|os.O_WRONLY, 0o600)
            with os.fdopen(fd,"a") as stream: stream.write(text+"\n")
            self.events.append(row)

    def snapshot(self):
        with self.lock: return json.loads(json.dumps(self.data))

    def update(self, **values):
        with self.lock:
            self.data.update(values);self.save()

    def lane(self, arm, **values):
        with self.lock:
            self.data["lanes"][arm].update(values);self.save()

    def page(self, after):
        with self.lock: return list(self.events[after:after+200])

    @classmethod
    def load(cls,directory):
        job=cls.__new__(cls);job.directory=Path(directory);job.lock=threading.RLock()
        job.data=json.loads((job.directory/"public.json").read_text());job.origin=perf_counter_ns()
        path=job.directory/"events.jsonl"
        job.events=[json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
        return job


class Controller:
    """One worker owns global hook/bridge configuration. Each arm runs in order."""
    def __init__(self, plan, directory, runtime_factory, *, owner_lock=None, context_factory=None):
        self.plan=plan
        self.directory=Path(directory); self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.owner_lock=owner_lock or (self.directory/"operator.lock").open("a")
        try:fcntl.flock(self.owner_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            self.owner_lock.close();raise RuntimeError("demo_already_open_in_another_ui") from None
        self.jobs_directory=self.directory/"runs";self.jobs_directory.mkdir(exist_ok=True,mode=0o700)
        self.session_directory=self.directory/"sessions"/uuid4().hex
        self.usage=UsageLog(self.session_directory/"usage")
        self.runtime_factory=runtime_factory; self.runtime=None
        self.context_factory=context_factory; self._cards=None
        self.lock=threading.RLock(); self.worker=ThreadPoolExecutor(max_workers=1,thread_name_prefix="live-demo")
        self.jobs={}; self.active=None; self.halted=False; self.closing=False; self.close_error=None
        self.prepared=False;self.preparation_phase="not_started";self.preparation_job=None;self.preparation_future=None
        self.repeats=dict.fromkeys(CARDS,0)
        # Old jobs remain readable; a restart NEVER reissues their work. Runtime
        # quiescence/readiness checks must pass before a new explicit click runs.
        for path in self.jobs_directory.glob("*/public.json"):
            data=json.loads(path.read_text())
            self.repeats[data["card"]]+=1
            if data["phase"] not in TERMINAL:
                job=Job.load(path.parent);job.update(phase="interrupted",error="server_interrupted_no_automatic_rerun")

    def status(self):
        with self.lock:
            return dict(mode="live_sequential",active=self.active,halted=self.halted,
                cards=list(CARDS),opening_page_runs_models=False,budget_enforced=False,repeatable=True,
                ready=self.prepared and not self.halted and not self.closing,
                preparation=dict(phase=self.preparation_phase))

    def cards(self):
        """Read-only presentation context; cached and digest-recorded.

        Never dispatches work. A failing pinned derivation falls back to the
        curated metadata (labelled as such) instead of blocking the UI; the
        failure is recorded privately for operator inspection. The build runs
        outside the controller lock so a slow pinned load cannot stall status
        polling; concurrent first requests deterministically rebuild the same
        value.
        """
        with self.lock:
            if self._cards is not None:
                return self._cards
            factory=self.context_factory
        value=None
        if factory is not None:
            try:
                from src.demo_ui.context import bounded
                value=bounded(factory(self.plan))
                private(self.session_directory/"card-context.json",
                    dict(source=value.get("source"),context_sha256=value.get("context_sha256")))
            except Exception as exc:
                private(self.session_directory/"card-context-failure.json",dict(error=type(exc).__name__))
        if value is None:
            from src.demo_ui.context import fallback
            value=fallback(self.plan)
        with self.lock:
            if self._cards is None:
                self._cards=value
            return self._cards

    def prepare(self):
        """Operator opt-in; no presentation card, pair, counter or external review."""
        with self.lock:
            if self.closing or self.halted or self.active:raise RuntimeError("live_session_busy_halted_or_closing")
            if self.preparation_future is None:
                if not self.prepared:self.preparation_phase="queued"
                self.preparation_future=self.worker.submit(self._prepare)
            return self.preparation_future

    def _prepare(self, job=None):
        # Called only on the same worker that owns every later measured lane.
        if self.prepared:return
        standalone=job is None
        if standalone:
            job=Job(self.session_directory/"preparation",dict(slot="preparation",card=None,order=[]),uuid4().hex)
            job.update(kind="preparation",lanes={},metrics_note="Startup checks only; outside presentation-card timing.")
        self.preparation_job=job
        with self.lock:self.preparation_phase="preparing"
        job.update(phase="startup")
        try:
            self.runtime=self.runtime_factory(self.plan,self.usage,self.session_directory)
            self.runtime.open(job)
            with self.lock:
                self.prepared=True;self.preparation_phase="ready"
            if standalone:job.update(phase="completed")
        except Exception as exc:
            with self.lock:self.preparation_phase="failed";self.halted=True
            if standalone:self._fail(job,exc,stage="preparation")
            raise

    def start(self, card, request_id):
        if card not in CARDS or not re.fullmatch(r"[0-9a-f]{32}",request_id): raise ValueError("invalid_card_or_request_id")
        with self.lock:
            existing=self.jobs.get(request_id)
            if existing:
                if existing.data["card"]!=card: raise ValueError("idempotency_key_conflict")
                return existing
            saved=self.jobs_directory/request_id/"public.json"
            if saved.exists():
                existing=Job.load(saved.parent)
                if existing.data["card"]!=card:raise ValueError("idempotency_key_conflict")
                return existing
            if self.closing or self.halted or self.active: raise RuntimeError("live_session_busy_halted_or_closing")
            if self.preparation_future is not None and not self.preparation_future.done():
                raise RuntimeError("demo_preparation_in_progress")
            slot=make_pair(card,request_id,self.repeats[card]);self.repeats[card]+=1
            job=Job(self.jobs_directory/request_id,slot,request_id)
            private(job.directory/"protocol.json",dict(protocol_sha256=digest(self.plan),pair=slot,budget_enforced=False))
            self.jobs[request_id]=job; self.active=request_id
            self.worker.submit(self._execute,job,slot)
            return job

    def _execute(self,job,slot):
        try:
            if not self.prepared:self._prepare(job)
            job.update(phase="running")
            records=[]
            for arm in slot["order"]:
                job.lane(arm,phase="running")
                spec=next(c for c in slot["cases"] if c.get("arm")==arm)
                record,summary=self.runtime.run_lane(job,arm,spec)
                records.append(record)
                job.lane(arm,phase="completed",summary=summary)
            job.update(phase="external_review")
            job.update(external_review=self.runtime.review(job,slot,records),phase="completed")
        except Exception as exc:
            self._fail(job,exc)
        finally:
            with self.lock:
                self.active=None
                self.jobs.pop(job.data["id"],None)  # Completed history is read from disk, not held forever.

    def _fail(self,job,exc,*,stage="run"):
        with self.lock:self.halted=True
        code=str(exc) if str(exc) in ERROR_MESSAGES else None
        message=ERROR_MESSAGES.get(code,"The run stopped after a runtime error. Inspect server logs and retained evidence before restarting.")
        for arm,data in job.snapshot()["lanes"].items():
            if data["phase"]=="running":job.lane(arm,phase="failed")
        private(job.directory/"failure.json",dict(error=type(exc).__name__,error_code=code,
            error_message=message,partial_lanes=job.snapshot()["lanes"]))
        job.update(phase="failed",error=type(exc).__name__,error_code=code,error_message=message)
        job.emit("system",dict(stage=stage,phase="failed",error=type(exc).__name__))

    def get(self, request_id):
        if not re.fullmatch(r"[0-9a-f]{32}",request_id): raise KeyError("unknown_run")
        if request_id in self.jobs:return self.jobs[request_id]
        path=self.jobs_directory/request_id
        if not (path/"public.json").exists():raise KeyError("unknown_run")
        return Job.load(path)

    def close(self):
        with self.lock:
            if self.closing:
                if self.close_error:raise RuntimeError("live_cleanup_failed_inspect_private_evidence")
                return
            self.closing=True
        # Do not kill effectful work because a browser disconnects/server closes.
        def cleanup():
            if self.runtime is not None: self.runtime.close()
        try:self.worker.submit(cleanup).result()
        except Exception as exc:
            self.close_error=type(exc).__name__
            private(self.session_directory/"cleanup-failure.json",dict(error=self.close_error,
                message="Cleanup failed; inspect retained evidence before restarting. No automatic work replay."))
            raise RuntimeError("live_cleanup_failed_inspect_private_evidence") from None
        finally:
            self.worker.shutdown(wait=True)
            self.owner_lock.close()
            self.preparation_phase="closed"
