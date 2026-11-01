"""Bounded offline replay of pinned synthetic banking fixtures for label evidence.

This is data preparation, not a live agent executor or native-enforcement proof.
Only the same released banking implementations used by the Actor are called.
No network/model calls or generic commands are available in the worker.
"""
from contextlib import redirect_stderr,redirect_stdout
from copy import deepcopy
import io
import multiprocessing
import resource
import socket

from src.banking_contracts.tools import READ_TOOLS,WRITE_TOOLS,ToolCatalog
from src.banking_service.upstream import evaluate


def canonical_calls(task,state,catalog):
    calls=[]
    for call in task.ground_truth(state.model_copy(deep=True)):
        args=dict(call.args)
        if type(args.get("amount")) in {int,float}:args["amount"]=str(args["amount"])
        calls.append(dict(tool_name=call.function,arguments=catalog.validate_arguments(call.function,args)))
    return calls


def changed_paths(before,after,prefix=""):
    if before==after:return []
    if isinstance(before,dict) and isinstance(after,dict):
        paths=[]
        for key in sorted(set(before)|set(after)):
            name=f"{prefix}.{key}" if prefix else key
            if key not in before or key not in after:paths.append(name)
            else:paths.extend(changed_paths(before[key],after[key],name))
        return paths
    return [prefix]


def execute_calls(calls,state):
    steps=[];current=deepcopy(state)
    for call in calls:
        if call["tool_name"] not in READ_TOOLS|WRITE_TOOLS:raise ValueError("offline_tool_not_allowed")
        before=deepcopy(current)
        result=evaluate(call,current)
        current=deepcopy(result["state"])
        steps.append(dict(action=deepcopy(call),before=before,after=deepcopy(current),output=result["output"],error=result["error"],
            changed_paths=changed_paths(before,current)))
    return steps,current


def _check(predicate,initial,state):
    try:return dict(value=bool(predicate("",initial.model_copy(deep=True),type(initial).model_validate(deepcopy(state)))),error=None)
    except Exception as exc:return dict(value=None,error=type(exc).__name__)


def replay_suite():
    """Worker/test entry point; no results are exported without privacy projection."""
    from agentdojo.task_suite import get_suite
    catalog=ToolCatalog.from_pinned_agentdojo()  # revision and 11-tool fence
    suite=get_suite("v1.2.2","banking")
    initial=suite.load_and_inject_default_environment({})
    original=initial.model_dump(mode="json")
    references={};combined=[]
    for task_id,task in suite.user_tasks.items():
        calls=canonical_calls(task,initial,catalog)
        steps,final=execute_calls(calls,original)
        omit={};omit_errors={}
        for index,call in enumerate(calls):
            if call["tool_name"] in WRITE_TOOLS:
                counter_steps,without=execute_calls(calls[:index]+calls[index+1:],original)
                omit[str(index)]=_check(lambda answer,before,after:task.utility(answer,before,after,strict=True),initial,without)
                omit_errors[str(index)]=[step["error"] for step in counter_steps if step["error"]]
        reference=dict(task_id=task_id,goal=task.PROMPT,calls=calls,steps=steps,final=final,
            utility=_check(lambda answer,before,after:task.utility(answer,before,after,strict=True),initial,final),
            no_op_utility=_check(lambda answer,before,after:task.utility(answer,before,after,strict=True),initial,original),
            omitted_write_utility=omit,omitted_write_errors=omit_errors,
            attack_checks={name:dict(initial=_check(attack.security,initial,original),final=_check(attack.security,initial,final))
                for name,attack in suite.injection_tasks.items()})
        references[task_id]=reference
        for attack_id,attack in suite.injection_tasks.items():
            attack_calls=canonical_calls(attack,initial,catalog)
            attack_steps,after=execute_calls(attack_calls,final)
            checks=[]
            for index,step in enumerate(attack_steps):
                # Leave-one-write-out controls establish contribution to an
                # aggregate attacker goal, not just origin in an attack file.
                counter_steps,without=execute_calls(attack_calls[:index]+attack_calls[index+1:],final)
                checks.append(dict(before=_check(attack.security,initial,step["before"]),
                    after=_check(attack.security,initial,step["after"]),
                    omitted_step_final=_check(attack.security,initial,without),
                    omitted_step_errors=[item["error"] for item in counter_steps if item["error"]]))
            combined.append(dict(task_id=task_id,attack_id=attack_id,calls=attack_calls,steps=attack_steps,
                baseline_attack=_check(attack.security,initial,final),final_attack=_check(attack.security,initial,after),
                step_checks=checks,final_utility=_check(lambda answer,before,post:task.utility(answer,before,post,strict=True),initial,after)))
    return dict(scope="offline-pinned-banking-fixture-replay",references=references,combined=combined,
        model_calls=0,network_calls_allowed=False,native_enforcement_proof=False)


def _worker(connection):
    try:
        resource.setrlimit(resource.RLIMIT_CPU,(90,90))
        resource.setrlimit(resource.RLIMIT_NOFILE,(128,128))
        def no_network(*args,**kwargs):raise RuntimeError("offline_dataset_network_forbidden")
        socket.socket=no_network;socket.create_connection=no_network
        with redirect_stdout(io.StringIO()),redirect_stderr(io.StringIO()):result=replay_suite()
        connection.send(dict(result=result))
    except Exception as exc:
        connection.send(dict(error=type(exc).__name__))
    finally:connection.close()


def bounded_replay(timeout=120):
    context=multiprocessing.get_context("spawn")
    reader,writer=context.Pipe(duplex=False)
    process=context.Process(target=_worker,args=(writer,));process.start();writer.close()
    try:
        if not reader.poll(timeout):raise RuntimeError("offline_dataset_replay_timeout")
        result=reader.recv()
        if "error" in result:raise RuntimeError("offline_dataset_replay_"+result["error"])
        return result["result"]
    finally:
        reader.close()
        if process.is_alive():process.terminate()
        process.join(timeout=3)
        if process.is_alive():process.kill();process.join(timeout=3)
