import pytest

from src.benchmark.review import RUBRIC,build_harness_judge


def test_external_review_is_explicitly_gemini_and_no_retries():
    judge=build_harness_judge("gemini:/gemini-2.5-flash")
    assert judge.model=="gemini:/gemini-2.5-flash"
    assert judge.inference_params["num_retries"]==0
    assert judge.inference_params["max_tokens"]==8192
    with pytest.raises(ValueError):build_harness_judge("openai:/other-model")


def test_harness_rubric_is_not_an_agent_utility_or_safety_certificate():
    assert "A well-recorded utility failure is not a harness failure" in RUBRIC
    assert "unit-only or application-only denials are insufficient" in RUBRIC
    assert "A deterministic guard is not a trained classifier" in RUBRIC
    assert "insufficient_evidence" in RUBRIC


def test_failed_feedback_attachment_retains_native_verdict_without_retry(monkeypatch):
    import mlflow
    from src.benchmark.review import review_harness
    class Span:
        trace_id="review"
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def set_inputs(self,value):pass
        def set_outputs(self,value):pass
    class Judge:
        model="gemini:/unit-fixture"
        calls=0
        def __call__(self,**kw):
            self.calls+=1
            return mlflow.entities.Feedback(name="unit-review",value="supported",rationale="unit fixture")
    judge=Judge();reservations=[]
    monkeypatch.setattr(mlflow,"start_span",lambda **kw:Span())
    monkeypatch.setattr(mlflow,"log_assessment",lambda **kw:(_ for _ in ()).throw(mlflow.MlflowException("attachment fixture failure")))
    monkeypatch.setattr(mlflow,"log_feedback",lambda **kw:None)
    result=review_harness(judge,observations={},target_trace_id="target",reserve=lambda **kw:reservations.append(kw))
    assert result["error_stage"]=="attach_native_feedback"
    assert result["native_feedback"]["feedback"]["value"]=="supported"
    assert result["value"] is None and judge.calls==len(reservations)==1


def test_native_transport_records_raw_reply_and_blocks_implicit_retry(monkeypatch):
    from types import SimpleNamespace as S
    from mlflow.genai.judges.adapters import litellm_adapter as adapter
    from src.benchmark.judge_transport import observe_native_attempt
    from src.benchmark.privacy import Mask
    calls=[];reservations=[];attributes={}
    def invoke(**kw):
        calls.append(kw)
        return S(choices=[S(message=S(content='{"result":"supported"'),finish_reason="length")],usage=S(prompt_tokens=10,completion_tokens=20))
    monkeypatch.setattr(adapter,"_invoke_litellm",invoke)
    monkeypatch.setattr(adapter,"_extract_response_cost",lambda response:0.001)
    span=S(trace_id="trace",set_attribute=lambda key,value:attributes.update({key:value}))
    with observe_native_attempt(reserve=lambda **kw:reservations.append(kw),span=span,mask=Mask()) as observed:
        adapter._invoke_litellm(litellm_model="gemini/unit",num_retries=3)
        with pytest.raises(RuntimeError,match="retry_blocked"):adapter._invoke_litellm(litellm_model="gemini/unit")
    assert len(calls)==len(reservations)==1 and calls[0]["num_retries"]==0
    assert observed["finish_reason"]=="length" and observed["raw_response"]=='{"result":"supported"'
    assert observed["input_tokens"]==10 and observed["cost_usd"]==0.001
    assert observed["automatic_retry_blocked"] is True
