from types import SimpleNamespace as S

import pytest

from src.benchmark.reconciliation import missing_operations,post_run_state,reconcile_record


class Clock:
    def __init__(self):self.now=0
    def read(self):return self.now
    def wait(self,seconds):self.now+=seconds


def span(id,parent,name,type="CHAIN",**kw):return S(span_id=id,parent_id=parent,name=name,span_type=type,**kw)


def trace(complete=True):
    spans=[span("http","client","managed_responses_http",outputs=dict(physical_attempts=1)),span("mcp","root","gateway_mcp_tool")]
    if complete:spans += [span("remote-model","http","POST /v1/responses","CHAT_MODEL"),span("remote-mcp","mcp","tools/call",None)]
    return S(data=S(spans=spans))


def audit(record,*,trace):return dict(span_count=len(trace.data.spans),managed_responses_dispatches=0,guard_managed_responses_dispatches=1)


def run(get_trace,provider_probe,**kw):
    clock=Clock()
    return reconcile_record(dict(trace_id="trace"),audit=audit,get_trace=get_trace,provider_probe=provider_probe,
        clock=clock.read,wait=clock.wait,timeout_seconds=4,quiet_seconds=1,poll_seconds=.5,**kw)


def test_delayed_gateway_export_cannot_pass_a_stable_incomplete_tree():
    reads=[]
    def get(id):reads.append(id);return trace(len(reads)>3)
    result=run(get,lambda **kw:dict(state="idle"))
    assert result["status"]=="complete" and result["attempts"]>=6 and result["audit"]["span_count"]==4
    assert result["model_requests_issued"]==0


def test_provider_tail_must_be_observed_idle_not_merely_a_cancelled_client():
    checks=[]
    def provider(**kw):checks.append(kw);return dict(state="busy" if len(checks)<4 else "idle")
    result=run(lambda id:trace(),provider)
    assert result["status"]=="complete" and result["attempts"]>=6
    assert result["immediate_provider_termination_claim"] is False


@pytest.mark.parametrize("provider",[None,lambda **kw:dict(state="unobserved"),lambda **kw:dict(state="busy")])
def test_missing_or_busy_provider_never_becomes_complete(provider):
    result=run(lambda id:trace(),provider)
    assert result["status"]=="incomplete" and result["elapsed_seconds"]==4
    assert result["pending"][0]["kind"]=="provider_idle"


def test_gateway_operation_required_for_each_parent_not_just_a_global_count():
    value=trace();value.data.spans.append(span("other-http","other-client","managed_responses_http",outputs=dict(physical_attempts=1)))
    assert missing_operations(value)==[dict(kind="gateway_model_span",parent_id="other-http",observed=0)]


def test_duplicate_gateway_operation_does_not_pass():
    value=trace();value.data.spans.append(span("duplicate","http","POST /v1/responses","CHAT_MODEL"))
    assert missing_operations(value)[0]["observed"]==2


def test_unissued_reservation_does_not_require_a_remote_model_span():
    value=S(data=S(spans=[span("http","client","managed_responses_http",outputs=dict(physical_attempts=0))]))
    assert missing_operations(value)==[]


def test_audit_ownership_failures_remain_incomplete_and_bounded():
    clock=Clock()
    def fail(*args,**kw):raise RuntimeError("ownership mismatch")
    result=reconcile_record(dict(trace_id="trace"),audit=fail,get_trace=lambda id:trace(),clock=clock.read,wait=clock.wait,
        timeout_seconds=2,quiet_seconds=.5)
    assert result["status"]=="incomplete" and result["elapsed_seconds"]==2
    assert result["observation_errors"] and result["audit"] is None


def test_fault_without_a_generative_request_needs_no_provider_observation():
    clock=Clock();value=S(data=S(spans=[]))
    result=reconcile_record(dict(trace_id="trace"),audit=lambda *a,**kw:dict(managed_responses_dispatches=0,guard_managed_responses_dispatches=0),
        get_trace=lambda id:value,clock=clock.read,wait=clock.wait,timeout_seconds=2,quiet_seconds=.5)
    assert result["status"]=="complete" and result["provider"]["state"]=="not_required"


@pytest.mark.parametrize("fingerprint,extra,expected",[("original",False,True),("changed",False,False),("original",True,False)])
def test_post_provider_state_is_read_only_and_detects_late_effects(fingerprint,extra,expected):
    calls=[]
    def call(path,body):
        calls.append((path,body))
        if path=="/snapshot":return dict(fingerprint=fingerprint)
        if path=="/trial-events":return dict(events=[dict(kind="tool_attempt",payload=dict(ticket="late"))] if extra else [])
        pytest.fail("effectful operation retried")
    result=post_run_state(dict(trial_id="trial",final_fingerprint="original",store_events=[]),S(call=call))
    assert all(result.values()) is expected
    assert [path for path,_ in calls]==["/snapshot","/trial-events"]


def test_backend_row_order_alone_does_not_prevent_quiet_readback():
    clock=Clock();reads=[]
    def ordered(*a,**kw):
        reads.append(True)
        return dict(managed_responses_dispatches=0,guard_managed_responses_dispatches=0,
            span_manifest=[dict(span_id=i) for i in (["a","b"] if len(reads)%2 else ["b","a"])])
    result=reconcile_record(dict(trace_id="trace"),audit=ordered,get_trace=lambda id:S(data=S(spans=[])),
        clock=clock.read,wait=clock.wait,timeout_seconds=2,quiet_seconds=.5,poll_seconds=.25)
    assert result["status"]=="complete"
