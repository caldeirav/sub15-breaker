"""Offline flow tests; no local model generation or platform enforcement claim."""
import ast
from pathlib import Path

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
import pytest

from src.agent_runtime.contracts import Limits,TaskInput,ToolOutcome
from src.agent_runtime.runner import run


def call(id="call-1",name="echo",args=None):
    return AIMessage(content="",tool_calls=[dict(id=id,name=name,args=args or {})])


def test_one_graph_flow_pairs_remote_results_then_uses_genuine_final_content():
    model=FakeMessagesListChatModel(responses=[call(),AIMessage(content="Finished.")])
    reserved=[];executed=[]
    def execute(value):
        executed.append(value)
        return ToolOutcome(value.call_id,"executed",{"value":"123.40"},"unit-fixture")
    result=run(TaskInput("episode","Unit transport fixture",("echo",)),model=model,execute=execute,reserve_model=lambda:reserved.append(1))
    assert result.status=="completed" and result.answer=="Finished."
    assert result.model_attempts==len(reserved)==2 and result.tool_attempts==len(executed)==1


@pytest.mark.parametrize("status",["blocked","unknown","error"])
def test_boundary_outcome_stops_without_fabricating_completion(status):
    model=FakeMessagesListChatModel(responses=[call(),AIMessage(content="Must not be used.")])
    result=run(TaskInput("episode","Unit fixture",("echo",)),model=model,
        execute=lambda value:ToolOutcome(value.call_id,status),reserve_model=lambda:None)
    assert result.status==status and result.answer=="" and result.model_attempts==1


def test_model_budget_exhaustion_does_not_make_a_final_apology_success():
    result=run(TaskInput("episode","Unit fixture",("echo",)),model=FakeMessagesListChatModel(responses=[call()]),
        execute=lambda value:ToolOutcome(value.call_id,"executed",True),reserve_model=lambda:None,limits=Limits(model_attempts=1))
    assert result.status=="budget_exhausted" and result.answer=="" and result.model_attempts==1


def test_transport_failure_is_unknown_not_proven_blocked():
    def broken(_):raise TimeoutError("Do not export this raw provider message")
    result=run(TaskInput("episode","Unit fixture",("echo",)),model=FakeMessagesListChatModel(responses=[call()]),
        execute=broken,reserve_model=lambda:None)
    assert result.status=="unknown" and result.error=="TimeoutError" and result.answer==""
    assert result.outcomes==(ToolOutcome("call-1","unknown"),)


@pytest.mark.parametrize("metadata",[{"finish_reason":"length"},{"finish_reason":"content_filter"},{"status":"incomplete"}])
def test_partial_model_content_is_not_normal_completion(metadata):
    result=run(TaskInput("episode","Unit fixture",()),
        model=FakeMessagesListChatModel(responses=[AIMessage(content="Partial answer",response_metadata=metadata)]),
        execute=lambda _:pytest.fail("unexpected dispatch"),reserve_model=lambda:None)
    assert result.status=="protocol_error" and result.answer=="" and result.model_attempts==1


def test_reused_or_unknown_model_call_cannot_dispatch():
    invoked=[]
    result=run(TaskInput("episode","Unit fixture",("echo",)),model=FakeMessagesListChatModel(responses=[call(),call()]),
        execute=lambda value:(invoked.append(value) or ToolOutcome(value.call_id,"executed",True)),reserve_model=lambda:None)
    assert result.status=="protocol_error" and len(invoked)==1
    result=run(TaskInput("episode","Unit fixture",("echo",)),model=FakeMessagesListChatModel(responses=[call(name="execute_command")]),
        execute=lambda _:pytest.fail("unknown tool dispatched"),reserve_model=lambda:None)
    assert result.status=="protocol_error" and result.tool_attempts==0


def test_runner_has_no_agentdojo_or_banking_runtime_import_dependency():
    root=Path(__file__).resolve().parents[1]/"src/agent_runtime"
    for path in root.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            names=[]
            if isinstance(node,ast.Import):names=[a.name for a in node.names]
            elif isinstance(node,ast.ImportFrom) and node.module:names=[node.module]
            assert not any(n.startswith(("agentdojo","src.feasibility","src.banking_service","src.banking_contracts")) for n in names)


def test_pinned_agentdojo_reference_fixture_runs_through_same_generic_graph():
    # This deterministic reference model is a unit control, never the live acting
    # model. FunctionsRuntime exists only in this test's in-memory backend.
    from agentdojo.functions_runtime import FunctionsRuntime
    from src.integrations.agentdojo.banking import BankingAdapter
    adapter=BankingAdapter();episode=adapter.episode("user_task_0","reference-fixture")
    initial=episode.initial_state.model_copy(deep=True);state=initial.model_copy(deep=True)
    runtime=FunctionsRuntime(adapter.suite.tools)
    scripted=[]
    for index,reference in enumerate(episode.task.ground_truth(initial)):
        args=dict(reference.args)
        if isinstance(args.get("amount"),float):args["amount"]=str(args["amount"])
        scripted.append(call(id=f"reference-{index}",name=reference.function,args=args))
    scripted.append(AIMessage(content="Reference fixture finished."))
    def execute(value):
        args=adapter.catalog.to_upstream_arguments(value.name,value.arguments)
        output,error=runtime.run_function(state,value.name,args,raise_on_error=False)
        assert error is None
        return ToolOutcome(value.call_id,"executed",output,"in-memory-reference-fixture")
    result=run(episode.public,model=FakeMessagesListChatModel(responses=scripted),execute=execute,reserve_model=lambda:None)
    measured=adapter.evaluate(episode,result,state)
    assert result.status=="completed" and measured["utility"] is True
    assert measured["selected_attack_goal_reached"] is False
    assert episode.initial_state==initial


def test_native_graph_model_tool_and_guard_spans_persist_together(tmp_path,monkeypatch):
    import mlflow
    from mlflow.tracking import fluent
    previous=mlflow.get_tracking_uri()
    monkeypatch.setattr(fluent,"_active_experiment_id",fluent._active_experiment_id)
    monkeypatch.setenv("MLFLOW_ENABLE_ASYNC_TRACE_LOGGING","false")
    monkeypatch.delenv("MLFLOW_EXPERIMENT_ID",raising=False)
    monkeypatch.delenv("MLFLOW_EXPERIMENT_NAME",raising=False)
    mlflow.set_tracking_uri(f"sqlite:///{tmp_path/'traces.db'}")
    try:
        experiment=mlflow.set_experiment("offline-benchmark-flow")
        mlflow.langchain.autolog()
        def execute(value):
            with mlflow.start_span(name="unit_remote_tool",span_type="TOOL") as tool:
                tool.set_inputs({"name":value.name,"arguments":value.arguments})
                with mlflow.start_span(name="unit_guard",span_type="GUARDRAIL") as guard:
                    guard.set_inputs({"fixture_only":True});guard.set_outputs({"decision":"block"})
                result=ToolOutcome(value.call_id,"blocked",None,"unit-only")
                tool.set_outputs({"status":result.status,"executed":False})
                return result
        result=run(TaskInput("episode","Unit fixture",("echo",)),model=FakeMessagesListChatModel(responses=[call()]),
                   execute=execute,reserve_model=lambda:None)
        assert result.status=="blocked" and result.answer==""
        mlflow.flush_trace_async_logging()
        traces=mlflow.search_traces(locations=[experiment.experiment_id],return_type="list")
        assert len(traces)==1
        trace=mlflow.get_trace(traces[0].info.trace_id);spans=trace.data.spans
        assert len([s for s in spans if s.parent_id is None])==1
        assert {"CHAT_MODEL","TOOL","GUARDRAIL"}<={s.span_type for s in spans}
        ids={s.span_id for s in spans}
        assert all(s.parent_id in ids for s in spans if s.parent_id is not None)
    finally:
        mlflow.langchain.autolog(disable=True)
        mlflow.set_tracking_uri(previous)


def test_trace_privacy_masks_exceptions_without_destroying_schema(tmp_path,monkeypatch):
    import json
    import mlflow
    from mlflow.tracking import fluent
    from src.benchmark.privacy import Mask
    previous=mlflow.get_tracking_uri()
    monkeypatch.setattr(fluent,"_active_experiment_id",fluent._active_experiment_id)
    monkeypatch.setenv("MLFLOW_ENABLE_ASYNC_TRACE_LOGGING","false")
    monkeypatch.delenv("MLFLOW_EXPERIMENT_ID",raising=False)
    monkeypatch.delenv("MLFLOW_EXPERIMENT_NAME",raising=False)
    mlflow.set_tracking_uri(f"sqlite:///{tmp_path/'privacy.db'}")
    try:
        mlflow.set_experiment("offline-privacy")
        with mlflow.tracing.configure(span_processors=[Mask(["private-sentinel"]).span_processor]):
            with mlflow.start_span(name="privacy-fixture") as span:
                trace_id=span.trace_id
                span.set_inputs({"properties":{"password":{"type":"string"}},"password":"private-sentinel"})
                span.record_exception(ValueError("private-sentinel"))
                span.set_outputs({"result":"private-sentinel"})
        trace=mlflow.get_trace(trace_id)
        root=trace.data.spans[0]
        assert root.inputs["properties"]["password"]=={"type":"string"}
        assert "private-sentinel" not in json.dumps(root.to_dict())
        assert root.events[0].attributes["exception.stacktrace"]=="[WITHHELD]"
    finally:mlflow.set_tracking_uri(previous)
