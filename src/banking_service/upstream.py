"""Pinned simulated environment and tool evaluation, without model/checker calls."""
import json
import multiprocessing
import resource

from agentdojo.functions_runtime import FunctionsRuntime
from agentdojo.task_suite import get_suite

from src.banking_contracts.codec import ContractError
from src.banking_contracts.tools import ToolCatalog
from src.banking_service.store import MAX_RESULT_BYTES, MAX_STATE_BYTES, packed


def environment_model():
    return type(get_suite("v1.2.2", "banking").load_and_inject_default_environment({}))


def initial_state():
    return get_suite("v1.2.2", "banking").load_and_inject_default_environment({}).model_dump(mode="json")


def evaluate(proposal, state):
    """Only the Actor server calls this in deployment. Unit tests are not runtime proof."""
    catalog = ToolCatalog.from_pinned_agentdojo()
    arguments = catalog.to_upstream_arguments(proposal["tool_name"], proposal["arguments"])
    env = environment_model().model_validate(state)
    suite = get_suite("v1.2.2", "banking")
    runtime = FunctionsRuntime(suite.tools)
    output, error = runtime.run_function(env, proposal["tool_name"], arguments, raise_on_error=False)
    if error:
        return dict(state=state, output=None, error="upstream_tool_error")
    if hasattr(output, "model_dump"): output = output.model_dump(mode="json")
    # Convert upstream nested Pydantic values without a repr/default=str fallback.
    from pydantic import TypeAdapter
    output = TypeAdapter(object).dump_python(output, mode="json")
    packed(output, MAX_RESULT_BYTES)
    after = env.model_dump(mode="json")
    packed(after, MAX_STATE_BYTES)
    return dict(state=after, output=output, error=None)


def _child(connection, proposal, state):
    try:
        resource.setrlimit(resource.RLIMIT_CPU, (8, 8))
        resource.setrlimit(resource.RLIMIT_NOFILE, (128, 128))
        result = evaluate(proposal, state)
        connection.send_bytes(packed(result, MAX_STATE_BYTES+MAX_RESULT_BYTES+1024).encode())
    except Exception as exc:
        connection.send_bytes(json.dumps(dict(failure="tool_worker_failed",failure_type=type(exc).__name__,
            contract_code=exc.code if isinstance(exc,ContractError) else None)).encode())
    finally:
        connection.close()


def bounded_evaluate(proposal, state, timeout=15):
    context = multiprocessing.get_context("spawn")
    reader, writer = context.Pipe(duplex=False)
    process = context.Process(target=_child, args=(writer, proposal, state))
    process.start()
    writer.close()
    try:
        if not reader.poll(timeout): raise ContractError("tool_deadline", "runtime")
        value = json.loads(reader.recv_bytes(MAX_STATE_BYTES+MAX_RESULT_BYTES+1024))
        if "failure" in value:
            code=value.get("contract_code") or value["failure"]+"_"+value.get("failure_type","unknown")
            raise ContractError(code,"runtime")
        return value
    except EOFError:
        process.join(timeout=1)
        raise ContractError("tool_worker_exit_"+str(process.exitcode), "runtime") from None
    finally:
        if process.is_alive(): process.terminate()
        process.join(timeout=2)
        if process.is_alive():
            process.kill()
            process.join(timeout=2)
        reader.close()
