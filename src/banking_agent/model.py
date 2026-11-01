"""Explicit, non-streaming LangChain Responses boundary for the banking graph.

This adapter does not prove gateway conversion, authenticate remote tools or
enable telemetry. Those are separate deployment gates; there is no default
provider URL, provider-hosted tool execution, retry or inference fallback here.
"""
from contextlib import contextmanager
from urllib.parse import urlsplit

import httpx
from langchain_openai import ChatOpenAI
from openai import APIError

from src.banking_contracts.codec import ContractError, parse_object


class _GuardedChatOpenAI(ChatOpenAI):
    """Do not let the async API silently construct an unguarded HTTP client."""

    def _generate(self, *args, **kwargs):
        try:
            return super()._generate(*args, **kwargs)
        except APIError as exc:
            # Native model callbacks see only a safe code, never an upstream
            # error body that might echo a credential or a tool argument.
            cause = exc.__cause__
            while cause is not None:
                if isinstance(cause, ContractError):
                    raise ContractError(cause.code, cause.stage) from None
                cause = cause.__cause__
            status = getattr(exc, "status_code", None)
            code = f"provider_http_{status}" if type(status) is int else "provider_transport_error"
            raise ContractError(code, "responses") from None

    async def _agenerate(self, *args, **kwargs):
        raise ContractError("async_responses_not_supported", "responses")


def banking_tools(catalog):
    """Preserve canonical optional/default/null/decimal schemas without strict rewriting."""
    return [dict(type="function", name=name, description=f"Simulated banking: {name}.",
                 parameters=value["arguments"])
            for name, value in catalog.schemas().items()]


def validate_response(value, catalog):
    """Check wire-only lifecycle fields before LangChain drops item status.

    Only the text/refusal/function subset is supported initially. Reject partial,
    ambiguous or provider-executed calls, even when final text is also present.
    Errors expose safe codes, not provider payloads or secret argument values.
    """
    def reject(code):
        raise ContractError(code, "responses")

    if not isinstance(value, dict) or value.get("object") != "response":
        reject("invalid_response_object")
    if value.get("error") is not None:
        reject("provider_response_error")
    if value.get("status") != "completed" or value.get("incomplete_details") is not None:
        reject("response_not_completed")
    if not isinstance(value.get("id"), str) or not value["id"]:
        reject("missing_response_id")
    output = value.get("output")
    if not isinstance(output, list) or not output:
        reject("empty_response_output")
    ids, call_ids, has_content = set(), set(), False
    for item in output:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"]:
            reject("missing_output_id")
        if item["id"] in ids:
            reject("duplicate_output_id")
        ids.add(item["id"])
        if item.get("status") != "completed":
            reject("output_not_completed")
        if item.get("type") == "message":
            if item.get("role") != "assistant" or not isinstance(item.get("content"), list):
                reject("invalid_assistant_message")
            for block in item["content"]:
                if not isinstance(block, dict):
                    reject("invalid_assistant_content")
                kind = block.get("type")
                if kind not in {"output_text", "refusal"}:
                    reject("unsupported_assistant_content")
                text = block.get("text" if kind == "output_text" else "refusal")
                if not isinstance(text, str):
                    reject("invalid_assistant_content")
                # Raw tool blocks are not successful assistant final content.
                if any(marker in text for marker in ("<tool_call>", "</tool_call>")):
                    reject("raw_tool_markup")
                has_content |= bool(text.strip())
        elif item.get("type") == "function_call":
            call_id = item.get("call_id")
            if not isinstance(call_id, str) or not call_id or call_id in call_ids:
                reject("invalid_function_call_id")
            call_ids.add(call_id)
            if item.get("namespace") is not None or item.get("caller") is not None:
                reject("unsupported_function_authority")
            arguments = item.get("arguments")
            if not isinstance(arguments, str):
                reject("invalid_function_arguments")
            # Unlike json.loads in the model adapter, this rejects duplicate keys,
            # non-finite numbers, non-object args and ambiguous decimal coercion.
            parsed = parse_object(arguments.encode("utf-8"))
            catalog.validate_arguments(item.get("name"), parsed)
        else:
            reject("unsupported_response_item")
    if not has_content and not call_ids:
        reject("empty_assistant_content")


def _base_url(url):
    parsed = urlsplit(url)
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname or
            parsed.username is not None or parsed.password is not None or
            parsed.query or parsed.fragment or parsed.path.rstrip("/") != "/v1"):
        raise ValueError("An explicit gateway http(s) /v1 URL without credentials is required")
    return url.rstrip("/")


@contextmanager
def gateway_model(*, base_url, model, api_key, catalog, max_output_tokens=1024,
                  timeout=30, transport=None):
    """Own the HTTP client's lifetime; only an explicit gateway endpoint is used.

    The HTTP wire guard is intentionally non-streaming. Streaming is not supported
    until item assembly/status validation has its own capability proof.
    """
    base_url = _base_url(base_url)
    if not isinstance(model, str) or not model.strip() or not isinstance(api_key, str) or not api_key:
        raise ValueError("An explicit model and gateway credential are required")
    if type(max_output_tokens) is not int or max_output_tokens < 1:
        raise ValueError("A positive output token limit is required")
    if type(timeout) not in {int, float} or not 0 < timeout <= 180:
        raise ValueError("A bounded positive timeout is required")

    def guard(response):
        if response.is_success:
            response.read()
            try:
                value = response.json()
                validate_response(value, catalog)
            except ContractError:
                raise
            except (ValueError, TypeError, UnicodeError, RecursionError):
                raise ContractError("invalid_response_json", "responses") from None

    with httpx.Client(transport=transport, timeout=timeout, trust_env=False,
                      follow_redirects=False, event_hooks={"response": [guard]}) as http:
        llm = _GuardedChatOpenAI(base_url=base_url, model=model, api_key=api_key,
                         http_client=http, use_responses_api=True,
                         use_previous_response_id=False, output_version="responses/v1",
                         disable_streaming=True,
                         store=False, truncation="disabled", max_retries=0,
                         timeout=timeout, max_tokens=max_output_tokens)
        yield llm.bind_tools(banking_tools(catalog), parallel_tool_calls=False)
