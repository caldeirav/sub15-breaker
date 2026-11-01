"""Offline LangChain/wire tests; these do NOT prove installed gateway conversion."""
import asyncio
import json
from types import SimpleNamespace

import httpx
from langchain.messages import HumanMessage, SystemMessage, ToolMessage
import pytest

from src.banking_agent.capabilities import GATEWAY_REVISION, gateway_capability
from src.banking_agent.model import banking_tools, gateway_model, validate_response
from src.banking_contracts.codec import ContractError
from src.banking_contracts.tools import ToolCatalog


@pytest.fixture(scope="module")
def catalog():
    return ToolCatalog.from_pinned_agentdojo()


def message(text="Done.", **changes):
    return dict(id="msg-1", type="message", role="assistant", status="completed",
                content=[dict(type="output_text", text=text, annotations=[])], **changes)


def function_call(name="get_balance", arguments="{}", call_id="call-1", id="fc-1"):
    return dict(id=id, type="function_call", name=name, arguments=arguments,
                call_id=call_id, status="completed")


def response(*items, **changes):
    value = dict(id="resp-1", object="response", created_at=1, status="completed",
                 error=None, incomplete_details=None, model="test-local",
                 output=list(items), parallel_tool_calls=False, tools=[], tool_choice="auto",
                 usage=dict(input_tokens=17, output_tokens=3, total_tokens=20,
                            input_tokens_details=dict(cached_tokens=0),
                            output_tokens_details=dict(reasoning_tokens=0)))
    return dict(value, **changes)


def invoke(catalog, wire, *, status=200):
    seen = []
    def upstream(request):
        seen.append(request)
        return httpx.Response(status, json=wire)
    with gateway_model(base_url="http://gateway.invalid/v1", model="test-local", api_key="test-only",
                       catalog=catalog, transport=httpx.MockTransport(upstream)) as model:
        result = model.invoke([HumanMessage(content="Synthetic request")])
    return result, seen


def test_langchain_really_uses_responses_and_preserves_usage(catalog):
    result, seen = invoke(catalog, response(message()))
    assert len(seen) == 1 and str(seen[0].url) == "http://gateway.invalid/v1/responses"
    assert result.text == "Done."
    assert result.response_metadata["status"] == "completed"
    assert result.usage_metadata == dict(input_tokens=17, output_tokens=3, total_tokens=20,
                                         input_token_details=dict(cache_read=0),
                                         output_token_details=dict(reasoning=0))
    body = json.loads(seen[0].content)
    assert body["store"] is False and body["truncation"] == "disabled"
    assert body["parallel_tool_calls"] is False and body["max_output_tokens"] == 1024
    assert "previous_response_id" not in body and body.get("stream", False) is False
    assert body["tools"] == banking_tools(catalog)


def test_full_tool_history_call_id_content_and_decimal_roundtrip(catalog):
    seen = []
    call = function_call("update_scheduled_transaction",
                         '{"id":7,"amount":"1200.0","subject":"Rent (Increased)"}')
    replies = [response(message("Checking."), call), response(message("Finished."), id="resp-2")]
    def upstream(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json=replies[len(seen)-1])
    with gateway_model(base_url="http://gateway.invalid/v1", model="test-local", api_key="test-only",
                       catalog=catalog, transport=httpx.MockTransport(upstream)) as model:
        history = [SystemMessage(content="Only synthetic banking."), HumanMessage(content="Review the notice.")]
        first = model.invoke(history)
        assert first.text == "Checking."
        assert first.tool_calls[0]["id"] == "call-1"
        assert first.tool_calls[0]["args"]["amount"] == "1200.0"
        history += [first, ToolMessage(content='{"ok":true}', tool_call_id="call-1")]
        assert model.invoke(history).text == "Finished."
    items = seen[1]["input"]
    assert next(item for item in items if item["type"] == "function_call") == call
    assert next(item for item in items if item["type"] == "function_call_output") == dict(
        type="function_call_output", call_id="call-1", output='{"ok":true}')
    assert "previous_response_id" not in seen[1]


def test_schemas_keep_optional_null_defaults_sensitive_declarations(catalog):
    wire = {tool["name"]: tool for tool in banking_tools(catalog)}
    assert set(wire) == set(catalog.names)
    for name in catalog.names:
        assert wire[name]["parameters"] == catalog.schemas()[name]["arguments"]
        assert "strict" not in wire[name]
    assert wire["update_password"]["parameters"]["properties"]["password"]["x-sensitive"] is True
    amount = wire["update_scheduled_transaction"]["parameters"]["properties"]["amount"]
    assert {part["type"] for part in amount["anyOf"]} == {"string", "null"}
    assert amount["default"] is None


@pytest.mark.parametrize("wire,code", [
    (response(message(), status="incomplete", incomplete_details={"reason":"max_output_tokens"}), "response_not_completed"),
    (response(message(), status="failed"), "response_not_completed"),
    (response(message(), status="cancelled"), "response_not_completed"),
    (response(message(), error={"message":"DO-NOT-ECHO"}), "provider_response_error"),
    (response(message(), object="chat.completion"), "invalid_response_object"),
    (response(message(), id=""), "missing_response_id"),
    (response(), "empty_response_output"),
    (response(message("  ")), "empty_assistant_content"),
    (response(message("<tool_call>raw</tool_call>")), "raw_tool_markup"),
    (response(dict(function_call(), status="in_progress")), "output_not_completed"),
    (response(dict(message(), status="incomplete")), "output_not_completed"),
    (response(function_call(), function_call(id="fc-2")), "invalid_function_call_id"),
    (response(function_call(), function_call(call_id="call-2")), "duplicate_output_id"),
    (response(dict(function_call(), caller="provider")), "unsupported_function_authority"),
    (response(dict(function_call(), type="mcp_call")), "unsupported_response_item"),
    (response(function_call(arguments='{"x":1,"x":2}')), "duplicate_json_key"),
    (response(function_call(arguments='{"x":NaN}')), "nonfinite_json_number"),
    (response(function_call(arguments='[]')), "expected_json_object"),
    (response(function_call(arguments='{"x":')), "invalid_json"),
    (response(function_call(name="execute_command")), "unknown_tool"),
    (response(function_call(name="update_scheduled_transaction", arguments='{"id":7,"amount":1200.0}')), "invalid_tool_arguments"),
    (response(function_call(arguments='{"principal":"attacker"}')), "invalid_tool_arguments"),
])
def test_rejects_partial_ambiguous_or_unsupported_wire_before_dispatch(catalog, wire, code):
    with pytest.raises(Exception) as error:
        invoke(catalog, wire)
    # The SDK wraps hook failures; the adapter recovers the safe contract code.
    causes = []
    exc = error.value
    while exc is not None:
        causes.append(exc)
        exc = exc.__cause__
    assert any(isinstance(exc, ContractError) and exc.code == code for exc in causes)
    assert "DO-NOT-ECHO" not in str(error.value)


def test_structured_refusal_is_preserved(catalog):
    item = dict(message(), content=[dict(type="refusal", refusal="I need clarification.")])
    result, _ = invoke(catalog, response(item))
    assert result.content[0]["type"] == "refusal"
    assert result.content[0]["refusal"] == "I need clarification."


def test_provider_http_error_is_not_retried_or_fallback(catalog):
    seen = []
    def upstream(request):
        seen.append(request)
        return httpx.Response(500, json={"error":{"message":"DO-NOT-ECHO"}})
    with gateway_model(base_url="http://gateway.invalid/v1", model="test-local", api_key="test-only",
                       catalog=catalog, transport=httpx.MockTransport(upstream)) as model:
        with pytest.raises(ContractError, match="^provider_http_500$") as error:
            model.invoke("Synthetic request")
    assert "DO-NOT-ECHO" not in str(error.value)
    assert len(seen) == 1


def test_async_does_not_bypass_the_wire_guard(catalog):
    seen = []
    def upstream(request):
        seen.append(request)
        return httpx.Response(200, json=response(message()))
    with gateway_model(base_url="http://gateway.invalid/v1", model="test-local", api_key="test-only",
                       catalog=catalog, transport=httpx.MockTransport(upstream)) as model:
        with pytest.raises(ContractError, match="async_responses_not_supported"):
            asyncio.run(model.ainvoke("Synthetic request"))
    assert seen == []


def test_stream_uses_guarded_nonstreaming_invocation(catalog):
    seen = []
    def upstream(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json=response(message()))
    with gateway_model(base_url="http://gateway.invalid/v1", model="test-local", api_key="test-only",
                       catalog=catalog, transport=httpx.MockTransport(upstream)) as model:
        assert list(model.stream("Synthetic request"))[0].text == "Done."
    assert len(seen) == 1 and seen[0].get("stream", False) is False


@pytest.mark.parametrize("url", ["", "http://localhost:1234", "http://user:key@gateway/v1",
                               "https://gateway/v1?token=secret", "https://gateway/v1#secret"])
def test_gateway_url_is_explicit_and_credentials_are_not_in_url(catalog, url):
    with pytest.raises(ValueError):
        with gateway_model(base_url=url, model="test", api_key="test", catalog=catalog):
            pytest.fail("invalid configuration accepted")


def test_version_gate_does_not_accept_host_version_or_wrong_revision(tmp_path, monkeypatch):
    versions = tmp_path/"versions.json"
    versions.write_text('{"agentgateway":"v1.7.0"}')
    observed = dict(version="1.4.1", git_revision="wrong")
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(stdout=json.dumps(observed))
    monkeypatch.setattr("src.banking_agent.capabilities.subprocess.run", run)
    assert gateway_capability("agentgateway", versions)["compatible"] is False
    observed["version"] = "1.7.0"
    assert gateway_capability("agentgateway", versions)["compatible"] is False
    observed["git_revision"] = GATEWAY_REVISION
    assert gateway_capability("agentgateway", versions)["compatible"] is True
    assert calls == [["agentgateway", "--version"]] * 3


@pytest.mark.parametrize("partial", [False, True])
def test_native_langgraph_checkpoint_and_mlflow_wire_capability(catalog, tmp_path, monkeypatch, partial):
    """A one-node capability fixture, NOT the final banking orchestration."""
    import mlflow
    from langgraph.checkpoint.sqlite import SqliteSaver
    from langgraph.graph import END, START, MessagesState, StateGraph
    from mlflow.tracking import fluent

    previous_uri = mlflow.get_tracking_uri()
    monkeypatch.setattr(fluent, "_active_experiment_id", fluent._active_experiment_id)
    monkeypatch.setenv("MLFLOW_ENABLE_ASYNC_TRACE_LOGGING", "false")
    monkeypatch.delenv("MLFLOW_EXPERIMENT_ID", raising=False)
    monkeypatch.delenv("MLFLOW_EXPERIMENT_NAME", raising=False)
    mlflow.set_tracking_uri(f"sqlite:///{tmp_path/'mlflow.db'}")
    try:
        experiment = mlflow.set_experiment("offline-protocol-capability")
        # Before graph construction, as prescribed by MLflow's LangGraph docs.
        mlflow.langchain.autolog(run_tracer_inline=True)
        wire = response(message(), status="incomplete" if partial else "completed")
        transport = httpx.MockTransport(lambda _: httpx.Response(200, json=wire))
        with gateway_model(base_url="http://gateway.invalid/v1", model="test-local", api_key="test-only",
                           catalog=catalog, transport=transport) as model:
            with SqliteSaver.from_conn_string(str(tmp_path/"checkpoints.db")) as saver:
                builder = StateGraph(MessagesState)
                builder.add_node("model", lambda state: {"messages": [model.invoke(state["messages"])]})
                builder.add_edge(START, "model")
                builder.add_edge("model", END)
                graph = builder.compile(checkpointer=saver)
                config = {"configurable": {"thread_id": "offline-fixture"}}
                if partial:
                    with pytest.raises(Exception):
                        graph.invoke({"messages": [HumanMessage(content="Synthetic fixture.")]}, config)
                else:
                    result = graph.invoke({"messages": [HumanMessage(content="Synthetic fixture.")]}, config)
                    assert result["messages"][-1].text == "Done."
                    assert graph.get_state(config).next == ()
            if not partial:
                with SqliteSaver.from_conn_string(str(tmp_path/"checkpoints.db")) as reopened:
                    restored = builder.compile(checkpointer=reopened).get_state(config)
                    assert restored.values["messages"][-1].text == "Done."
                    assert restored.next == ()
        mlflow.flush_trace_async_logging()
        traces = mlflow.search_traces(locations=[experiment.experiment_id], return_type="list")
        assert len(traces) == 1
        trace = mlflow.get_trace(traces[0].info.trace_id)
        spans = trace.data.spans
        roots = [span for span in spans if span.parent_id is None]
        assert len(roots) == 1
        ids = {span.span_id for span in spans}
        assert all(span.parent_id in ids for span in spans if span.parent_id is not None)
        model_spans = [span for span in spans if span.span_type == "CHAT_MODEL"]
        assert len(model_spans) == 1
        expected_status = "ERROR" if partial else "OK"
        assert roots[0].status.status_code.value == expected_status
        assert model_spans[0].status.status_code.value == expected_status
    finally:
        mlflow.langchain.autolog(disable=True)
        mlflow.set_tracking_uri(previous_uri)
