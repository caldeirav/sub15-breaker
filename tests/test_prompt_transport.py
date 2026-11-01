from contextlib import nullcontext
import json

import httpx
import pytest

from src.benchmark.prompt_pilot import GOALS,generate


@pytest.mark.parametrize("status",[200,400])
def test_real_sdk_hooks_preserve_native_errors_and_total_tokens_offline(tmp_path,monkeypatch,status):
    from google import genai
    original=genai.Client;calls=[];reservations=[];settlements=[]
    def respond(request):
        calls.append(json.loads(request.content))
        if status==400:return httpx.Response(400,json={"error":{"code":400,"status":"INVALID_ARGUMENT","message":"offline schema rejection"}})
        return httpx.Response(200,json=dict(candidates=[dict(content=dict(parts=[dict(text=json.dumps(dict(goals=[GOALS["refund"]]*8)))],role="model"),finishReason="STOP")],
            usageMetadata=dict(promptTokenCount=10,candidatesTokenCount=50,totalTokenCount=110,thoughtsTokenCount=50)))
    def client(**kwargs):
        kwargs["http_options"].client_args["transport"]=httpx.MockTransport(respond)
        return original(**kwargs)
    class Span:
        trace_id="offline"
        def set_inputs(self,value):pass
        def set_outputs(self,value):pass
    class Budget:
        def reserve(self,**kwargs):reservations.append(kwargs);return dict(sequence=len(reservations))
        def settle(self,sequence,**kwargs):settlements.append(kwargs)
    monkeypatch.setattr(genai,"Client",client)
    monkeypatch.setenv("GEMINI_API_KEY","offline-placeholder-not-a-real-key")
    monkeypatch.setattr("src.benchmark.prompt_pilot.mlflow.start_span",lambda **kwargs:nullcontext(Span()))
    monkeypatch.setattr("src.benchmark.prompt_pilot.mlflow.log_dict",lambda *args,**kwargs:None)
    count=2 if status==400 else 1
    cases=[dict(case_id=f"offline-{i}",kind="goal",family="refund",variant="goal") for i in range(count)]
    receipts,accepted,rejected=generate(Budget(),dict(cases=cases,protocol_sha256="a"*64),tmp_path)
    assert len(calls)==len(receipts)==len(reservations)==1
    assert receipts[0]["http_status"]==status and receipts[0]["physical_attempts"]==1
    if status==400:
        assert "offline schema rejection" in receipts[0]["error_detail"]
        assert "INVALID_ARGUMENT" in receipts[0]["raw_http_response"]
        assert settlements[0]["usage_verified"] is False and not accepted and not rejected
    else:
        assert len(accepted)==1 and len(rejected)==7
        assert str(settlements[0]["accounted_cost_usd"])=="0.000253"
        assert settlements[0]["usage_verified"] is True
        assert not accepted[0]["training_eligible"] and accepted[0]["review_status"]=="pending"
