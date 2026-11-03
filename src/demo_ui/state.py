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
    def __init__(self, plan, directory, runtime_factory):
        self.plan=plan
        self.directory=Path(directory); self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.owner_lock=(self.directory/"operator.lock").open("a")
        try:fcntl.flock(self.owner_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            self.owner_lock.close();raise RuntimeError("demo_already_open_in_another_ui") from None
        self.jobs_directory=self.directory/"runs";self.jobs_directory.mkdir(exist_ok=True,mode=0o700)
        self.session_directory=self.directory/"sessions"/uuid4().hex
        self.usage=UsageLog(self.session_directory/"usage")
        self.runtime_factory=runtime_factory; self.runtime=None
        self.lock=threading.RLock(); self.worker=ThreadPoolExecutor(max_workers=1,thread_name_prefix="live-demo")
        self.jobs={}; self.active=None; self.halted=False; self.closing=False
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
                cards=list(CARDS),opening_page_runs_models=False,budget_enforced=False,repeatable=True)

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
            slot=make_pair(card,request_id,self.repeats[card]);self.repeats[card]+=1
            job=Job(self.jobs_directory/request_id,slot,request_id)
            private(job.directory/"protocol.json",dict(protocol_sha256=digest(self.plan),pair=slot,budget_enforced=False))
            self.jobs[request_id]=job; self.active=request_id
            self.worker.submit(self._execute,job,slot)
            return job

    def _execute(self,job,slot):
        try:
            if self.runtime is None:
                job.update(phase="startup")
                self.runtime=self.runtime_factory(self.plan,self.usage,self.session_directory)
                self.runtime.open(job)
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
            self.halted=True
            private(job.directory/"failure.json",dict(error=type(exc).__name__,partial_lanes=job.snapshot()["lanes"]))
            job.update(phase="failed",error=type(exc).__name__)
            job.emit("system",dict(stage="run",phase="failed",error=type(exc).__name__))
        finally:
            with self.lock:
                self.active=None
                self.jobs.pop(job.data["id"],None)  # Completed history is read from disk, not held forever.

    def get(self, request_id):
        if not re.fullmatch(r"[0-9a-f]{32}",request_id): raise KeyError("unknown_run")
        if request_id in self.jobs:return self.jobs[request_id]
        path=self.jobs_directory/request_id
        if not (path/"public.json").exists():raise KeyError("unknown_run")
        return Job.load(path)

    def close(self):
        with self.lock: self.closing=True
        # Do not kill effectful work because a browser disconnects/server closes.
        def cleanup():
            if self.runtime is not None: self.runtime.close()
        try:self.worker.submit(cleanup).result()
        finally:
            self.worker.shutdown(wait=True)
            self.owner_lock.close()
