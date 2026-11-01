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


class Budget:
    def __init__(self,directory,policy=PILOT):
        self.directory=Path(directory);self.policy=policy
        self.directory.mkdir(parents=True,exist_ok=True,mode=0o700)

    def reserve(self,*,role,case_id,trace_id,request=None):
        fd=os.open(self.directory/".lock",os.O_CREAT|os.O_RDWR,0o600)
        with os.fdopen(fd,"w") as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            path=self.directory/"policy.json"
            if not path.exists():
                if list(self.directory.glob("attempt-*.json")):raise RuntimeError("budget_policy_missing")
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
                reserved_at=time.time(),request_sha256=hashlib.sha256(encoded(request)).hexdigest(),spent=True)
            target=self.directory/f"attempt-{len(entries)+1:04d}.json"
            out=os.open(target,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
            with os.fdopen(out,"wb") as stream:
                stream.write(encoded(entry));stream.flush();os.fsync(stream.fileno())
            return entry
