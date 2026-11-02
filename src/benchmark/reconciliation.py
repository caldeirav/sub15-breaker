"""Bounded read-only reconciliation of exported operations, not model retries."""
import hashlib
import json
import math
from time import monotonic,sleep

import mlflow


def missing_operations(trace):
    """Require remote evidence per attempted model/MCP operation, not just totals."""
    missing=[];spans=trace.data.spans
    for span in spans:
        if span.name=="managed_responses_http" and (getattr(span,"outputs",None) or {}).get("physical_attempts",1)==1:
            children=[s for s in spans if s.parent_id==span.span_id and s.span_type=="CHAT_MODEL"]
            if len(children)!=1:missing.append(dict(kind="gateway_model_span",parent_id=span.span_id,observed=len(children)))
        if span.name=="gateway_mcp_tool":
            children=[s for s in spans if s.parent_id==span.span_id and s.name=="tools/call"]
            if len(children)!=1:missing.append(dict(kind="gateway_mcp_span",parent_id=span.span_id,observed=len(children)))
    return missing


def post_run_state(record,store):
    """Late read-only effect check; never repeat prepare, claim or execution."""
    snapshot=store.call("/snapshot",dict(trial_id=record["trial_id"]))
    events=store.call("/trial-events",dict(trial_id=record["trial_id"]))["events"]
    def attempts(rows):return [event["payload"].get("ticket") for event in rows if event["kind"]=="tool_attempt"]
    return dict(fingerprint_matches_final=snapshot["fingerprint"]==record["final_fingerprint"],
        tool_attempts_match_final=attempts(events)==attempts(record["store_events"]))


def reconcile_record(record,*,audit,provider_probe=None,timeout_seconds=30,quiet_seconds=1,poll_seconds=.5,
        get_trace=None,clock=monotonic,wait=sleep):
    """Observe expected remote spans, audited scores and provider idle before ready.

    Idle is a point-in-time provider observation, not per-request usage or proof
    that cancellation immediately stopped compute. MLflow reads also retain the
    caller's configured per-request I/O timeout; no generator is invoked here.
    """
    if (any(not math.isfinite(v) for v in (timeout_seconds,quiet_seconds,poll_seconds)) or
            not 0<quiet_seconds<timeout_seconds or poll_seconds<=0):raise ValueError("invalid_reconciliation_deadlines")
    get_trace=get_trace or mlflow.get_trace
    started=clock();deadline=started+timeout_seconds;stable_since=None;last_signature=None
    attempts=0;last_audit=None;pending=[];provider=dict(state="not_required");errors=[]
    while clock()<deadline:
        attempts+=1;pending=[]
        try:
            trace=get_trace(record["trace_id"])
            if trace is None:raise RuntimeError("trace_not_persisted")
            last_audit=audit(record,trace=trace)
            pending=missing_operations(trace)
            physical=last_audit["managed_responses_dispatches"]+last_audit["guard_managed_responses_dispatches"]
            if physical:
                provider=provider_probe(timeout_seconds=max(.01,min(5,deadline-clock()))) if provider_probe else dict(state="unobserved",reason="provider_probe_missing")
                if provider.get("state")!="idle":pending.append(dict(kind="provider_idle",observation=provider))
            else:provider=dict(state="not_required")
            # Backend row order is not a new observation. Actual ownership,
            # outputs, provenance and operation counts still change the digest.
            canonical=dict(last_audit)
            for field in ("span_manifest","score_provenance","span_names"):
                if field in canonical:canonical[field]=sorted(canonical[field],key=lambda value:json.dumps(value,sort_keys=True,default=str))
            signature=hashlib.sha256(json.dumps(dict(audit=canonical,provider=provider),sort_keys=True,default=str).encode()).hexdigest()
            now=clock()
            if pending or signature!=last_signature:stable_since=now if not pending else None
            last_signature=signature
            if not pending and stable_since is not None and now-stable_since>=quiet_seconds and now<=deadline:
                return dict(status="complete",scope="expected gateway operations, audited ownership/scores, observed provider idle and quiet readback",
                    attempts=attempts,elapsed_seconds=now-started,quiet_seconds=quiet_seconds,audit=last_audit,provider=provider,
                    pending=[],observation_errors=errors,model_requests_issued=0,immediate_provider_termination_claim=False)
        except Exception as exc:
            errors.append(dict(attempt=attempts,error=type(exc).__name__,detail=str(exc)[:512]))
            pending=[dict(kind="trace_or_provider_readback",error=type(exc).__name__)]
            stable_since=None;last_signature=None
        remaining=deadline-clock()
        if remaining>0:wait(min(poll_seconds,remaining))
    return dict(status="incomplete",attempts=attempts,elapsed_seconds=clock()-started,audit=last_audit,provider=provider,
        pending=pending or [dict(kind="quiet_readback_deadline")],observation_errors=errors,model_requests_issued=0,
        immediate_provider_termination_claim=False)
