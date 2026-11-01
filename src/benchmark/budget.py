"""Single durable local allowance; external Gemini reservations are separate."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import time

from src.infra.model_budget import atomic,encoded

PILOT=dict(version="benchmark-wiring-pilot-v1",local_total=80,
    cases=[dict(task_id=task,phase="native-control-live-wiring",actor_attempts=6,llm_guard_attempts=0)
        for task in ("user_task_0","user_task_2","user_task_13")],
    first_canary="user_task_0",initial_local_ceiling=18,unallocated_local=62,
    retries=0,fallback=False,guard="deterministic-native-allow",
    external_review="owner-authorized-necessary-Gemini-calls-2026-11-01")

# Owner subsequently requested more headroom and actual end-to-end completion.
# Carry the spent four canary + six rent requests forward, never reset them.
EXTENDED_PILOT=dict(version="benchmark-wiring-pilot-v2",local_total=160,
    cases=[dict(task_id="user_task_0",phase="reuse-completed-canary",actor_attempts=4,llm_guard_attempts=0),
        dict(task_id="user_task_2",phase="six-spent-plus-one-fresh-16-attempt-episode",actor_attempts=22,llm_guard_attempts=0),
        dict(task_id="user_task_13",phase="one-fresh-16-attempt-episode",actor_attempts=16,llm_guard_attempts=0)],
    first_canary="user_task_0",initial_local_ceiling=42,unallocated_local=118,
    episode_model_attempts=16,episode_tool_attempts=24,episode_seconds=480,
    retries=0,fallback=False,guard="deterministic-native-allow",
    supersedes="benchmark-wiring-pilot-v1",prior_policy_sha256=hashlib.sha256(encoded(PILOT)).hexdigest(),
    owner_direction="Extend the budget to ensure all use-cases can run end-to-end comfortably, and make sure everything completes",
    external_review=PILOT["external_review"])


class Budget:
    def __init__(self,directory,policy=PILOT):
        self.directory=Path(directory);self.policy=policy
        self.directory.mkdir(parents=True,exist_ok=True,mode=0o700)

    def reserve(self,*,role,case_id,trace_id,request=None,observed_after_dispatch=False,actual_started_at=None):
        if observed_after_dispatch and role not in {"gemini_task_judge","gemini_harness_judge"}:
            raise ValueError("late_reconciliation_is_external_only")
        fd=os.open(self.directory/".lock",os.O_CREAT|os.O_RDWR,0o600)
        with os.fdopen(fd,"w") as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            extended=self.policy.get("version")==EXTENDED_PILOT["version"]
            if extended:
                original=self.directory/"policy.json"
                if not original.is_file() or json.loads(original.read_text())!=PILOT:
                    raise RuntimeError("extended_budget_requires_unchanged_original_policy")
            elif (self.directory/"policy-v2.json").exists():raise RuntimeError("budget_policy_superseded")
            path=self.directory/("policy-v2.json" if extended else "policy.json")
            if not path.exists():
                if not extended and list(self.directory.glob("attempt-*.json")):raise RuntimeError("budget_policy_missing")
                atomic(path,self.policy)
            if json.loads(path.read_text())!=self.policy:raise RuntimeError("budget_policy_changed")
            entries=[json.loads(p.read_text()) for p in sorted(self.directory.glob("attempt-*.json"))]
            if [e["sequence"] for e in entries]!=list(range(1,len(entries)+1)):raise RuntimeError("budget_ledger_gap")
            local=[e for e in entries if e["role"] in {"actor","llm_guard"}]
            if role in {"actor","llm_guard"}:
                cases={case["task_id"]:case for case in self.policy["cases"]}
                if case_id not in cases:raise RuntimeError("undeclared_pilot_case")
                used=sum(e["case_id"]==case_id and e["role"]==role for e in local)
                limit=cases[case_id]["actor_attempts" if role=="actor" else "llm_guard_attempts"]
                if used>=limit or len(local)>=min(self.policy["local_total"],self.policy["initial_local_ceiling"]):
                    raise RuntimeError("combined_local_budget_exhausted")
            elif role not in {"gemini_task_judge","gemini_harness_judge"}:raise ValueError("unknown_budget_role")
            entry=dict(sequence=len(entries)+1,role=role,case_id=case_id,trace_id=trace_id,
                reserved_at=time.time(),request_sha256=hashlib.sha256(encoded(request)).hexdigest(),spent=True,
                policy_version=self.policy["version"])
            if observed_after_dispatch:
                entry.update(reserved_at=None,recorded_at=time.time(),observed_after_dispatch=True,
                    actual_started_at=actual_started_at,physical_http_attempt_count="unknown_historical_instrumentation_gap")
            target=self.directory/f"attempt-{len(entries)+1:04d}.json"
            out=os.open(target,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
            with os.fdopen(out,"wb") as stream:
                stream.write(encoded(entry));stream.flush();os.fsync(stream.fileno())
            return entry
