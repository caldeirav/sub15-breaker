"""Observe the locked MLflow/LiteLLM boundary, including malformed replies.

The native MLflow Judge still owns prompting, invocation, parsing and Feedback.
This serial post-run wrapper records raw responses/usage before the SDK's JSON
parser can discard them and forbids silent format/tool-loop retry attempts.
"""
from contextlib import contextmanager
import threading
from unittest.mock import patch

LOCK=threading.Lock()


@contextmanager
def observe_native_attempt(*,reserve,span,mask):
    from mlflow.genai.judges.adapters import litellm_adapter as adapter
    original=adapter._invoke_litellm
    observed={"physical_attempts":0}
    def invoke(**kwargs):
        if observed["physical_attempts"]:
            observed["automatic_retry_blocked"]=True
            raise RuntimeError("automatic_native_judge_retry_blocked")
        if not kwargs.get("litellm_model","").startswith("gemini/"):
            raise ValueError("unexpected_native_judge_provider")
        kwargs["num_retries"]=0
        kwargs["inference_params"]={**(kwargs.get("inference_params") or {}),"num_retries":0,"max_retries":0}
        reserve(role="gemini_harness_judge",trace_id=span.trace_id)
        observed["physical_attempts"]+=1
        response=original(**kwargs)
        choice=response.choices[0]
        observed.update(raw_response=mask(choice.message.content),finish_reason=choice.finish_reason,
            input_tokens=response.usage.prompt_tokens,output_tokens=response.usage.completion_tokens)
        cost=adapter._extract_response_cost(response)
        if cost is not None:observed["cost_usd"]=cost
        span.set_attribute("judge.physical_attempts",observed["physical_attempts"])
        span.set_attribute("judge.finish_reason",choice.finish_reason)
        span.set_attribute("mlflow.chat.tokenUsage",dict(input_tokens=observed["input_tokens"],output_tokens=observed["output_tokens"]))
        return response
    with LOCK,patch.object(adapter,"_invoke_litellm",invoke):
        yield observed
