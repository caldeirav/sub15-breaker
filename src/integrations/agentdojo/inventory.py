"""Offline candidate inventory, not execution, labels, training or a split claim."""
import argparse
import csv
import hashlib
import inspect
import json
from pathlib import Path

from src.banking_contracts.tools import AGENTDOJO_COMMIT,WRITE_TOOLS
from src.benchmark.privacy import Mask
from src.integrations.agentdojo.banking import BankingAdapter,TASKS,VERSION


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()


def components(rows,*,include_attacks):
    """Conservative automatic links; semantic-family adjudication is still needed."""
    parents={}
    def root(key):
        parents.setdefault(key,key)
        if parents[key]!=key:parents[key]=root(parents[key])
        return parents[key]
    for row in rows:
        keys=["task:"+row["task_id"],*["document:"+name for name in row["document_refs"]],
            *["task:"+name for name in row.get("inherited_task_refs",[])]]
        if include_attacks and row.get("attack_id"):keys.append("attack:"+row["attack_id"])
        for key in keys[1:]:parents[root(key)]=root(keys[0])
        root(keys[0])
    groups={}
    for key in sorted(parents):groups.setdefault(root(key),[]).append(key)
    return sorted(groups.values())


def inventory(adapter):
    suite=adapter.suite
    initial=suite.load_and_inject_default_environment({})
    raw_state=initial.model_dump(mode="json")
    mask=Mask();mask.learn(raw_state)
    references={};attacks={};errors=[]
    for kind,source,target in (("reference",suite.user_tasks,references),("attack",suite.injection_tasks,attacks)):
        for name,task in source.items():
            try:
                calls=[]
                for call in task.ground_truth(initial.model_copy(deep=True)):
                    args=dict(call.args)
                    # Upstream references use both integer and float amounts;
                    # translate those assets explicitly, not live model output.
                    if type(args.get("amount")) in {int,float}:args["amount"]=str(args["amount"])
                    args=adapter.catalog.validate_arguments(call.function,args)
                    mask.learn(args)
                    calls.append(dict(tool=call.function,arguments=args))
                target[name]=calls
            except Exception as exc:errors.append(dict(kind=kind,source_id=name,error=type(exc).__name__))
    type_to_id={type(task):name for name,task in suite.user_tasks.items()}
    tasks=[];rows=[];sources={}
    for task in [*suite.user_tasks.values(),*suite.injection_tasks.values()]:
        source=Path(inspect.getfile(type(task)))
        sources[type(task).__module__]=hashlib.sha256(source.read_bytes()).hexdigest()
    def add(task_id,kind,source_id,calls,documents,inherited):
        for index,action in enumerate(calls):
            prefix=calls[:index]
            state_known=not any(prior["tool"] in WRITE_TOOLS for prior in prefix)
            rows.append(mask(dict(candidate_id=f"{task_id}/{kind}/{source_id}/{index}",task_id=task_id,
                origin=kind,attack_id=source_id if kind=="attack" else None,source_id=source_id,
                legitimate_goal=suite.user_tasks[task_id].PROMPT,action=action,step_index=index,
                document_refs=documents,inherited_task_refs=inherited,
                prefix_actions=prefix,
                prefix_tools=[item["tool"] for item in prefix],
                state_reference="pinned-default-initial" if state_known else "requires-pinned-prefix-replay",
                observations_reference="requires-frozen-input-projection",
                label="pending_review",reviewer="",rationale="",
                training_eligible=False,live_task=task_id in TASKS)))
    for task_id,task in suite.user_tasks.items():
        calls=references.get(task_id,[])
        documents=sorted({call["arguments"]["file_path"] for call in calls if call["tool"]=="read_file"})
        inherited=[type_to_id[cls] for cls in type(task).__mro__[1:] if cls in type_to_id]
        tasks.append(mask(dict(task_id=task_id,legitimate_goal=task.PROMPT,reference_tools=[c["tool"] for c in calls],
            document_refs=documents,inherited_task_refs=inherited,live_task=task_id in TASKS)))
        source=Path(inspect.getfile(type(task)))
        sources[type(task).__module__]=hashlib.sha256(source.read_bytes()).hexdigest()
        add(task_id,"reference",task_id,calls,documents,inherited)
        for attack_id,candidates in attacks.items():add(task_id,"attack",attack_id,candidates,documents,inherited)
    task_groups=components(rows,include_attacks=False)
    all_groups=components(rows,include_attacks=True)
    heldout=sorted({key.removeprefix("task:") for group in task_groups
        if any("task:"+task in group for task in TASKS) for key in group if key.startswith("task:")})
    summary=dict(schema_version="banking-candidate-inventory-v1",agentdojo_commit=AGENTDOJO_COMMIT,benchmark_version=VERSION,
        live_task_ids=list(TASKS),offline_user_tasks=len(suite.user_tasks),attack_families=len(suite.injection_tasks),
        candidates=len(rows),reference_candidates=sum(r["origin"]=="reference" for r in rows),
        attack_origin_candidates=sum(r["origin"]=="attack" for r in rows),
        labels=dict(pending_review=len(rows)),training_eligible=0,
        requires_prefix_replay=sum(r["state_reference"]!="pinned-default-initial" for r in rows),
        automatic_task_document_groups=task_groups,all_cross_product_groups=all_groups,
        reserved_live_task_closure=heldout,source_file_sha256=sources,candidate_packet_sha256=digest(rows),errors=errors,
        split_status="not_frozen",warnings=[
            "Attack-origin is not an unsafe label; harmless reads can appear in attacker trajectories.",
            "The complete task/attack cross-product can connect all rows; do not random-split it.",
            "Review semantic/duplicate families and assign task/attack groups before selecting eligible pairs.",
            "Masked review exports are not final model inputs; never train on pending labels or guessed pre-action state."])
    return summary,tasks,rows,mask(raw_state)


def write_packet(directory,summary,tasks,rows,state):
    directory=Path(directory)
    directory.mkdir(parents=True,exist_ok=False,mode=0o700)
    def write(name,value):
        path=directory/name
        path.write_text(json.dumps(value,indent=2,ensure_ascii=False)+"\n");path.chmod(0o600)
    write("inventory.json",summary);write("tasks.json",tasks);write("initial-state.redacted.json",state)
    path=directory/"candidates.jsonl"
    path.write_text("".join(json.dumps(row,ensure_ascii=False,sort_keys=True)+"\n" for row in rows));path.chmod(0o600)
    fields=["candidate_id","task_id","origin","attack_id","legitimate_goal","tool","arguments","state_reference","label","reviewer","rationale"]
    path=directory/"annotation-review.csv"
    with path.open("w",newline="") as stream:
        writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader()
        for row in rows:
            writer.writerow({**{key:row[key] for key in fields if key in row},"tool":row["action"]["tool"],
                "arguments":json.dumps(row["action"]["arguments"],sort_keys=True)})
    path.chmod(0o600)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,required=True,help="New private review-packet directory; existing packets are never overwritten")
    args=parser.parse_args()
    summary,tasks,rows,state=inventory(BankingAdapter())
    write_packet(args.output,summary,tasks,rows,state)
    print(json.dumps({key:summary[key] for key in ("offline_user_tasks","attack_families","candidates","reference_candidates", 
        "attack_origin_candidates","requires_prefix_replay","training_eligible","split_status")},indent=2))


if __name__=="__main__":main()
