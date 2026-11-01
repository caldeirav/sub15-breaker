"""Conservative operator-owned ledger for the sprint's eight local probes.

Reservations are spent before dispatch and never refunded. This is process/crash
accounting on private host storage, not protection from a malicious operator or
loss/rollback of the disk. The separate final campaign retains its 72-call cap.
"""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time

POLICY = dict(owner="langgraph-agentgateway-sprint-2026-11-01",total=80,probes=8,final_trials=9,attempts_per_trial=8,
              local_only=True,paid_judges=0,automatic_fallback=False)


def encoded(value):
    return json.dumps(value,sort_keys=True,separators=(",",":"),allow_nan=False).encode()


def atomic(path,value):
    with tempfile.NamedTemporaryFile(dir=path.parent,delete=False) as stream:
        pending=Path(stream.name)
        try:
            stream.write(encoded(value));stream.flush();os.fsync(stream.fileno())
            pending.replace(path)
        finally:pending.unlink(missing_ok=True)


def reserve_probe(directory, *, case, run_id, trace_id, request, profile_sha256):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True,mode=0o700)
    descriptor=os.open(directory/".lock",os.O_CREAT|os.O_RDWR,0o600)
    with os.fdopen(descriptor,"a") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        policy=directory/"policy.json";counter=directory/"counter.json"
        if not policy.exists():
            if counter.exists() or list(directory.glob("probe-*.json")):
                raise RuntimeError("probe_budget_missing_policy_with_retained_attempts")
            atomic(policy,POLICY);atomic(counter,dict(issued=0))
        if json.loads(policy.read_text())!=POLICY:
            raise RuntimeError("probe_budget_policy_changed")
        issued=json.loads(counter.read_text())["issued"]
        if type(issued) is not int or not 0<=issued<=POLICY["probes"]:
            raise RuntimeError("invalid_probe_budget_counter")
        expected={f"probe-{i:04d}.json" for i in range(1,issued+1)}
        observed={p.name for p in directory.glob("probe-[0-9][0-9][0-9][0-9].json")}
        if observed!=expected:raise RuntimeError("probe_budget_entries_and_counter_differ")
        if issued>=POLICY["probes"]:raise RuntimeError("local_probe_budget_exhausted")
        entry=dict(sequence=issued+1,case=case,run_id=run_id,trace_id=trace_id,phase="compatibility-probe",reserved_at=time.time(),
            request=request,request_sha256=hashlib.sha256(encoded(request)).hexdigest(),profile_sha256=profile_sha256,
            retries=0,reservation_spent=True,provider="local-Qwen-via-managed-agentgateway")
        path=directory/f"probe-{issued+1:04d}.json"
        fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        with os.fdopen(fd,"wb") as output:
            output.write(encoded(entry));output.flush();os.fsync(output.fileno())
        # A crash between these writes fails closed on the next reservation.
        atomic(counter,dict(issued=issued+1))
        return path,entry


def record_outcome(reservation, value):
    path=Path(reservation)
    if not path.is_file():raise RuntimeError("unknown_probe_reservation")
    result=path.with_suffix(".result.json")
    fd=os.open(result,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    with os.fdopen(fd,"wb") as output:
        output.write(encoded(dict(finished_at=time.time(),reservation=path.name,outcome=value)))
        output.flush();os.fsync(output.fileno())
    return result
