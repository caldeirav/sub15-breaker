"""Bounded durable UI jobs and observed events, not reconstructed live traces."""
from concurrent.futures import ThreadPoolExecutor
import json
import fcntl
import os
from pathlib import Path
import re
import threading
from time import perf_counter_ns

from src.benchmark.campaign_budget import LOCAL, EXTERNAL
from src.benchmark.deployment import private
from src.integrations.agentdojo.inventory import digest
from src.demo_ui.allocation import CARDS

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


class Controller:
    """One worker owns global hook/bridge configuration. Each arm runs in order."""
    def __init__(self, budget, directory, runtime_factory):
        self.budget=budget; self.plan=budget.plan(current_source=True)
        self.directory=Path(directory); self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.owner_lock=(self.directory/"operator.lock").open("a")
        try:fcntl.flock(self.owner_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            self.owner_lock.close();raise RuntimeError("campaign_already_open_in_another_ui") from None
        self.runtime_factory=runtime_factory; self.runtime=None
        self.lock=threading.RLock(); self.worker=ThreadPoolExecutor(max_workers=1,thread_name_prefix="live-demo")
        self.jobs={}; self.active=None; self.halted=False; self.closing=False
        # An old interrupted campaign must never silently reissue its startup/model calls.
        for path in self.directory.glob("*/public.json"):
            data=json.loads(path.read_text())
            if data["phase"] not in TERMINAL: self.halted=True
        if (self.budget.directory/("live-session-"+self.plan["namespace"]+".json")).exists():self.halted=True

    def status(self):
        with self.lock:
            remaining={card:sum(s["card"]==card and not (self.budget.directory/("live-slot-"+s["slot"]+".json")).exists()
                                for s in self.plan["slots"]) for card in CARDS}
            return dict(mode="live_sequential", campaign=self.plan["namespace"], active=self.active, halted=self.halted,
                remaining=remaining, cards=list(CARDS), opening_page_runs_models=False,
                setup_local_cap=sum(c.get(r,0) for c in self.plan["cases"] if c["kind"] in {"startup","canary"} for r in LOCAL),
                priming_forwards=2*len(self.plan.get("startup_inputs",[])),
                per_click_caps={card:dict(local=sum(c.get(r,0) for c in self.plan["cases"] if c.get("slot")==next(s["slot"] for s in self.plan["slots"] if s["card"]==card) for r in LOCAL),
                    external=sum(c.get(r,0) for c in self.plan["cases"] if c.get("slot")==next(s["slot"] for s in self.plan["slots"] if s["card"]==card) for r in EXTERNAL)) for card in CARDS},
                local_cap=sum(c.get(r,0) for c in self.plan["cases"] for r in LOCAL),
                external_cap=sum(c.get(r,0) for c in self.plan["cases"] for r in EXTERNAL))

    def start(self, card, request_id):
        if card not in CARDS or not re.fullmatch(r"[0-9a-f]{32}",request_id): raise ValueError("invalid_card_or_request_id")
        with self.lock:
            existing=self.jobs.get(request_id)
            if existing:
                if existing.data["card"]!=card: raise ValueError("idempotency_key_conflict")
                return existing
            saved=self.directory/request_id/"public.json"
            if saved.exists(): raise RuntimeError("request_already_recorded_reconnect_without_rerunning")
            if self.closing or self.halted or self.active: raise RuntimeError("live_session_busy_halted_or_closing")
            self.budget.plan(current_source=True)
            with self.budget.locked():
                slot=next((s for s in self.plan["slots"] if s["card"]==card and not (self.budget.directory/("live-slot-"+s["slot"]+".json")).exists()),None)
                if slot is None: raise RuntimeError("no_fresh_allocation_for_card")
                self.budget._exclusive(self.budget.directory/("live-slot-"+slot["slot"]+".json"),dict(slot=slot,request_id=request_id,matrix_sha256=digest(self.plan)))
                # Both lanes spend their slot even if setup later fails; no retry-until-green.
                for case in self.plan["cases"]:
                    if case.get("slot")==slot["slot"] and case["kind"]!="external_review":
                        self.budget._exclusive(self.budget.directory/("native-case-"+case["case_id"]+".json"),dict(case_id=case["case_id"],matrix_sha256=digest(self.plan),state="started",automatic_rerun=False))
            job=Job(self.directory/request_id,slot,request_id)
            self.jobs[request_id]=job; self.active=request_id
            self.worker.submit(self._execute,job,slot)
            return job

    def _execute(self,job,slot):
        try:
            if self.runtime is None:
                job.update(phase="startup")
                self.runtime=self.runtime_factory(self.plan,self.budget,self.directory)
                self.runtime.open(job)
            job.update(phase="running")
            records=[]
            for arm in slot["order"]:
                job.lane(arm,phase="running")
                spec=next(c for c in self.plan["cases"] if c.get("slot")==slot["slot"] and c.get("arm")==arm)
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
            with self.lock: self.active=None

    def get(self, request_id):
        if not re.fullmatch(r"[0-9a-f]{32}",request_id): raise KeyError("unknown_run")
        if request_id not in self.jobs: raise KeyError("unknown_run")
        return self.jobs[request_id]

    def close(self):
        with self.lock: self.closing=True
        # Do not kill effectful work because a browser disconnects/server closes.
        def cleanup():
            if self.runtime is not None: self.runtime.close()
        try:self.worker.submit(cleanup).result()
        finally:
            self.worker.shutdown(wait=True)
            self.owner_lock.close()
