"""Observe the locked native MLflow provider boundary, including malformed replies.

The native MLflow Judge still owns prompting, invocation, parsing and Feedback.
This serial post-run wrapper covers the installed native Gateway adapter and
LiteLLM adapter, records raw responses/usage before JSON parsing, and forbids
silent format/tool-loop retry attempts. It is not the deployed agentgateway.
"""
from contextlib import contextmanager
import threading
from unittest.mock import patch

LOCK=threading.Lock()


@contextmanager
def observe_native_attempt(*,reserve,span,mask,model_uri="gemini:/gemini-2.5-flash"):
    from mlflow.genai.judges.adapters import litellm_adapter as adapter
    from mlflow.genai.judges.adapters import gateway_adapter as gateway
    original=adapter._invoke_litellm
    original_gateway=gateway.send_chat_request
    observed={"physical_attempts":0}
    def before():
        if observed["physical_attempts"]:
            observed["automatic_retry_blocked"]=True
            raise RuntimeError("automatic_native_judge_retry_blocked")
        reserve(role="gemini_harness_judge",trace_id=span.trace_id)
        observed["physical_attempts"]+=1
    def invoke(**kwargs):
        if not kwargs.get("litellm_model","").startswith("gemini/"):
            raise ValueError("unexpected_native_judge_provider")
        kwargs["num_retries"]=0
        kwargs["inference_params"]={**(kwargs.get("inference_params") or {}),"num_retries":0,"max_retries":0}
        before()
        response=original(**kwargs)
        choice=response.choices[0]
        observed.update(raw_response=mask(choice.message.content),finish_reason=choice.finish_reason,
            input_tokens=response.usage.prompt_tokens,output_tokens=response.usage.completion_tokens)
        cost=adapter._extract_response_cost(response)
        if cost is not None:observed["cost_usd"]=cost
        span.set_attribute("judge.physical_attempts",observed["physical_attempts"])
        span.set_attribute("judge.finish_reason",choice.finish_reason)
        span.set_attribute("judge.raw_response",observed["raw_response"])
        span.set_attribute("mlflow.chat.tokenUsage",dict(input_tokens=observed["input_tokens"],output_tokens=observed["output_tokens"]))
        return response
    def invoke_gateway(**kwargs):
        if not model_uri.startswith("gemini:/"):raise ValueError("unexpected_native_judge_provider")
        kwargs["num_retries"]=0
        before()
        response=original_gateway(**kwargs)
        # Direct Gemini's native wire response, before MLflow normalizes/parses.
        usage=response.get("usageMetadata",{})
        candidates=response.get("candidates",[])
        observed.update(adapter="mlflow-native-gateway",raw_response=mask(response),
            finish_reason=candidates[0].get("finishReason") if candidates else None)
        if "promptTokenCount" in usage:observed["input_tokens"]=usage["promptTokenCount"]
        if "candidatesTokenCount" in usage:observed["output_tokens"]=usage["candidatesTokenCount"]
        if "input_tokens" in observed and "output_tokens" in observed:
            cost=gateway._lookup_model_cost(model_uri,observed["input_tokens"],observed["output_tokens"])
            if cost is not None:observed["cost_usd"]=cost
        span.set_attribute("judge.physical_attempts",observed["physical_attempts"])
        span.set_attribute("judge.finish_reason",observed["finish_reason"])
        span.set_attribute("judge.raw_response",observed["raw_response"])
        if "input_tokens" in observed and "output_tokens" in observed:
            span.set_attribute("mlflow.chat.tokenUsage",dict(input_tokens=observed["input_tokens"],output_tokens=observed["output_tokens"]))
        return response
    with LOCK,patch.object(adapter,"_invoke_litellm",invoke),patch.object(gateway,"send_chat_request",invoke_gateway):
        yield observed
