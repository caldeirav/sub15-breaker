"""Bounded retries for ONE authenticated, read-only readiness operation only."""
from copy import deepcopy
from time import perf_counter_ns,sleep

from src.banking_contracts.codec import ContractError
from src.banking_service.diagnostics import RuntimeCallError

POLICY=dict(schema_version="actor-readiness-retry-v1",max_attempts=3,attempt_timeout_seconds=15,
    backoff_seconds=[0.25,0.5],retryable_http_statuses=[502,503,504],operation="/admission-readiness",
    model_action_retries=0)
TRANSIENT={"ConnectTimeout","ReadTimeout","WriteTimeout","PoolTimeout","ConnectError","ReadError","WriteError","CloseError","RemoteProtocolError"}


def retryable(error):
    if not isinstance(error,RuntimeCallError):return False
    if error.code not in {"runtime_unavailable","runtime_transport_error","invalid_runtime_json"}:return False
    if error.code in {"unauthenticated","driver_not_allowed","actor_identity_required","actor_identity_mismatch","actor_store_identity_or_profile_not_ready"}:return False
    hops=error.transport.get("hops",[])
    if any(h.get("status") in {401,403} for h in hops):return False
    failures=[h for h in hops if h.get("failure") not in {None,"success"}]
    if not failures:return False
    deepest=failures[-1]
    if deepest.get("failure")=="transport_error":return deepest.get("exception_type") in TRANSIENT
    return deepest.get("status") in POLICY["retryable_http_statuses"] and deepest.get("failure") in {"invalid_json","http_error"}


class ReadinessError(ContractError):
    def __init__(self,code,report,transport=None):
        super().__init__(code,"transport");self.readiness=deepcopy(report)
        if transport:self.transport=deepcopy(transport)


def check(client,*,actor_id,actor_uid,ticket_lifetime,policy,on_observation=lambda value:None,wait=sleep):
    if policy!=POLICY or client.timeout!=policy["attempt_timeout_seconds"]:raise ValueError("readiness_retry_policy_binding")
    report=dict(schema_version="actor-readiness-check-v1",policy=deepcopy(policy),ready=False,attempts=[],retry_count=0,recovered=False)
    for index in range(policy["max_attempts"]):
        started=perf_counter_ns();row=dict(attempt=index+1)
        try:
            value=client.call("/admission-readiness",{})
            if (value.get("actor_id"),value.get("actor_uid"),value.get("ticket_lifetime_seconds"))!=(actor_id,actor_uid,ticket_lifetime):
                raise ContractError("actor_store_identity_or_profile_not_ready","authentication")
            row.update(status="ready",driver_transport=getattr(client,"last_diagnostics",None),actor_transport=value.get("readiness_transport"),retryable=False)
            report.update(ready=True,identity=dict(actor_id=actor_id,actor_uid=actor_uid,ticket_lifetime_seconds=ticket_lifetime))
            error=None
        except Exception as exc:
            error=exc;transient=retryable(exc)
            row.update(status="transient_failure" if transient else "non_retryable_failure",error_type=type(exc).__name__,error_code=getattr(exc,"code","readiness_check_error"),retryable=transient)
            if getattr(exc,"transport",None):row["transport"]=deepcopy(exc.transport)
        row["elapsed_ns"]=perf_counter_ns()-started;report["attempts"].append(row)
        report.update(retry_count=index,recovered=bool(report["ready"] and index))
        on_observation(deepcopy(report))  # Persist failed observations before any wait/retry.
        if report["ready"]:return report
        if not row["retryable"] or index+1==policy["max_attempts"]:
            raise ReadinessError("actor_readiness_unavailable" if row["retryable"] else row["error_code"],report,getattr(error,"transport",None)) from None
        wait(policy["backoff_seconds"][index])
    raise AssertionError("unreachable_readiness_policy")
