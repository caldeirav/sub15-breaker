"""Persistent live demo wiring. The agent, native gate and golden oracles are reused."""
from contextlib import ExitStack
from contextvars import copy_context
import fcntl
import hashlib
import json
import os
from pathlib import Path
import threading
from time import perf_counter_ns

import httpx
import mlflow
from langchain_openai import ChatOpenAI

from src.agent_runtime.contracts import Limits
from src.agent_runtime.observability import observing
from src.banking_service.deploy import Deployment, DIRECTORY, STORE_HOST
from src.banking_service.http import RuntimeClient
from src.banking_service.deadlines import MEASURE
from src.benchmark.admission import ReviewBuilder, llm_guard
from src.benchmark.bridge import Bridge, BridgeServer, MCPClient
from src.benchmark.compare import claim_case
from src.benchmark.demo import make_card
from src.benchmark.deployment import private, temporary_bridge, gateway_forward, model_timeouts, native_hook
from src.benchmark.native import Registry, ControlGuard, LateAllowGuard, server
from src.benchmark.privacy import Mask
from src.benchmark.readiness import POLICY as READINESS
from src.benchmark.serving import ServingResources, provider_status
from src.benchmark.wiring import benchmark_template, run_case, ModelTransport, audit_record
from src.demo_ui.protocol import ROOT,source_hashes
from src.integrations.agentdojo.banking import BankingAdapter
from src.integrations.agentdojo.inventory import digest


class ObservedBridge(Bridge):
    observer = None
    def dispatch(self, call, parent):
        with observing(self.observer):
            return super().dispatch(call, parent)


class ObservedRegistry(Registry):
    def __init__(self):
        super().__init__(); self.contexts = {}
    def register(self, ticket, *args, **kwargs):
        super().register(ticket, *args, **kwargs)
        with self.lock: self.contexts[ticket] = copy_context()
    def admit(self, ticket, **kwargs):
        with self.lock: context = self.contexts.get(ticket)
        return context.copy().run(super().admit, ticket, **kwargs) if context else super().admit(ticket, **kwargs)

    def release_completed(self):
        # Persisted records own old evidence. Keep no unbounded collection of
        # ticket contexts/job observers between serial, fully reconciled cases.
        with self.lock:
            if any(e.attempted and not e.done.is_set() for e in self.entries.values()):
                raise RuntimeError("previous_native_review_still_active")
            self.entries.clear();self.contexts.clear()


def validate_case_evidence(spec,record):
    if record["cleanup_errors"] or record["telemetry_reconciliation"]["status"]!="complete":
        raise RuntimeError("live_case_incomplete_cleanup_or_telemetry")
    card=make_card(spec,record)
    if (card["observed_dispatch_enforcement_correct"] is False or not card["enforcement_evidence_complete"] or
        (record["evidence"]["actions"] and not card["enforcement_correct"])):
        raise RuntimeError("live_enforcement_or_effect_evidence_failed")
    # A genuine clarification-only agent can fail golden without an enforcement
    # contradiction. Keep that quality failure; never retry or invent a tool call.
    return card


def summarize(spec, record, events, plan):
    card = make_card(spec, record)
    actions = record["evidence"]["actions"]
    gates = [a["guard"] for a in actions if a.get("guard")]
    fault = spec["card_id"] in {"D04", "D05"}
    def stats(values):
        import statistics
        return dict(count=len(values), total_ms=sum(values)/1e6, median_ms=statistics.median(values)/1e6) if values else None
    def durations(stage, role=None):
        return [e["duration_ns"] for e in events if e.get("stage")==stage and e.get("phase")=="finished"
                and e.get("lane")==spec["arm"] and (role is None or e.get("role")==role) and e.get("duration_ns") is not None]
    timing = dict(
        acting_model_http=stats(durations("model_gateway","actor")),
        mcp_tool_roundtrip=stats(durations("mcp_gateway")),
        snapshot_prepare=stats([a["snapshot_prepare_ns"] for a in actions if "snapshot_prepare_ns" in a]),
        context_projection=stats([a["review_materialization_ns"] for a in actions if "review_materialization_ns" in a]),
        guard_whole_review=None if fault else stats([g["review_latency_ns"] for g in gates if not g.get("error") and g.get("decision") in {"allow","block"}]),
        classifier_core=None if fault else stats([g["classifier_decision_core_ns"] for g in gates if g.get("classifier_decision_core_ns") is not None]),
        native_claim_roundtrip=stats([a["actor_timings"]["claim_roundtrip_ns"] for a in actions if a.get("actor_timings",{}).get("claim_roundtrip_ns") is not None]),
        tool_compute=stats([a["actor_timings"]["tool_evaluation_ns"] for a in actions if a.get("actor_timings",{}).get("tool_evaluation_ns") is not None]),
        commit_roundtrip=stats([a["actor_timings"]["commit_roundtrip_ns"] for a in actions if a.get("actor_timings",{}).get("commit_roundtrip_ns") is not None]))
    gateway=[]
    trace=mlflow.get_trace(record["trace_id"])
    for span in trace.data.spans:
        if span.name in {"tools/call"} or (span.span_type=="CHAT_MODEL" and span.parent_id in {
                s.span_id for s in trace.data.spans if s.name=="managed_responses_http"}):
            gateway.append(dict(span_id=span.span_id, name=span.name, duration_ns=span.end_time_ns-span.start_time_ns,
                                source="persisted_gateway_span", includes_backend=True))
    timing["gateway_model_server"] = stats([s["duration_ns"] for s in gateway if s["name"]!="tools/call"])
    timing["gateway_mcp_server"] = stats([s["duration_ns"] for s in gateway if s["name"]=="tools/call"])
    public_actions=[]
    golden={r["input_digest"]:r["golden_decision"] for r in plan["accuracy"]["rows"]}
    for action in actions:
        gate=action.get("guard") or {}
        from src.banking_contracts.codec import public_view
        public_actions.append(dict(tool=action["tool"],status=action["status"],decision=gate.get("decision"),
            arguments=public_view(action.get("canonical_arguments",{})),risk=gate.get("risk") if not fault else None,
            golden_decision=None if fault else golden.get(gate.get("input_digest")), golden_covered=not fault and gate.get("input_digest") in golden,
            core_ms=gate["classifier_decision_core_ns"]/1e6 if gate.get("classifier_decision_core_ns") is not None and not fault else None,
            review_ms=gate.get("review_latency_ns",0)/1e6 if not fault and "review_latency_ns" in gate else None,
            receipt_present=bool(action.get("execution_receipt")),discarded=gate.get("discarded_decision")))
    return dict(arm=spec["arm"],producer=spec["producer"],fault_control=fault,status=record["status"],
        golden_pass=card["demo_ready"],expected=card["expected_review"],observed=card["observed_review"],
        utility=card["utility"],enforcement_correct=card["enforcement_correct"],
        effects_verified=card["enforcement_correct"] and card["enforcement_evidence_complete"],actions=public_actions,timing=timing,
        errors=sum(bool(g.get("error")) for g in gates),gateway_spans=gateway,
        trace_id=record["trace_id"],run_id=record["child_run_id"],experiment_id=str(record["experiment_id"]),
        final_answer=record["evidence"].get("final_answer","")[:2000],
        physical_counts={k:record["trace_audit"][k] for k in ("managed_responses_dispatches","guard_managed_responses_dispatches")},
        telemetry=record["telemetry_reconciliation"]["status"],cleanup_ok=not record["cleanup_errors"],
        boundaries="Core is inside whole review, inside native claim, inside tool roundtrip. Do not sum nested timers; no speedup for unmatched inputs.")


class Runtime:
    def __init__(self, plan, usage, directory, artifact):
        self.plan=plan; self.usage=usage; self.directory=Path(directory)/"runtime"; self.artifact=Path(artifact)
        self.stack=ExitStack(); self.setup=[]; self.active={}; self.closed=False

    def capacity(self):
        value=self.store.call("/capacity",{})
        if not value.get("repeatable_demo"):
            raise RuntimeError("repeatable_demo_store_required_run_documented_store_setup")
        return value

    def open(self, job):
        self.directory.mkdir(mode=0o700,exist_ok=False)
        lock=(ROOT/".infra/live-demo-runtime.lock").open("a")
        self.stack.callback(lock.close)
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        from src.infra.demo_stack import System,Config
        System(Config()).quiescent()
        if self.plan["code_hashes"]!=source_hashes():raise RuntimeError("demo_source_changed_restart_server")
        from src.benchmark.encoder import manifest
        from src.benchmark.projection import POLICY_ID
        artifact=manifest(self.artifact,policy_id=POLICY_ID)
        if digest(artifact)!=self.plan["artifact_manifest_sha256"] or digest(artifact["calibration"])!=self.plan["calibration_sha256"]:
            raise RuntimeError("live_artifact_or_calibration_binding_changed")
        self.deployment=Deployment(); self.deployment.refresh_credentials()
        original=json.loads((DIRECTORY/"deployment.json").read_text()); self.deployment.verify_deployment(original)
        if original["image"]!=self.plan["image"]: raise RuntimeError("live_image_binding_changed")
        previous=(DIRECTORY/"deployment.json").read_bytes()
        _,template=benchmark_template(self.deployment)
        changed=dict(original,template=template); private(DIRECTORY/"deployment.json",changed)
        def restore_manifest():
            if json.loads((DIRECTORY/"deployment.json").read_text())!=changed: raise RuntimeError("live_manifest_concurrent_change")
            (DIRECTORY/"deployment.json").write_bytes(previous)
        self.stack.callback(restore_manifest)
        token=(DIRECTORY/"runtime.token").read_text().strip(); self.authorization="Bearer "+token
        self.mask=Mask([token,*[os.getenv(k) for k in ("GEMINI_API_KEY","GOOGLE_API_KEY","OPENAI_API_KEY")]])
        self.adapter=BankingAdapter(); self.mask.learn(self.adapter.suite.load_and_inject_default_environment({}).model_dump(mode="json"))
        mlflow.set_tracking_uri(os.getenv("MLFLOW_TRACKING_URI","http://localhost:5001"))
        mlflow.set_experiment("breaker-banking-target-agent")
        mlflow.langchain.autolog(); mlflow.openai.autolog(disable=True)
        mlflow.tracing.configure(span_processors=[self.mask.span_processor])
        self.parent=self.stack.enter_context(mlflow.start_run(run_name="repeatable-live-demo"))
        private(self.directory/"run.json",dict(run_id=self.parent.info.run_id,experiment_id=str(self.parent.info.experiment_id),protocol_sha256=digest(self.plan),budget_enforced=False))
        mlflow.log_dict(self.plan,"live/protocol.json")
        self.store=RuntimeClient(self.stack.enter_context(self.deployment.forward("service/banking-store")),self.authorization)
        private(self.directory/"capacity-before.json",self.capacity())
        self.resources=ServingResources(self.artifact,json.loads((self.artifact/"benchmark-guard.json").read_text())["calibration"],resident=True)
        self.stack.callback(self.resources.release_classifier)
        self.registry=ObservedRegistry(); self.bridge=ObservedBridge(self.adapter.catalog,self.registry,self.mask)
        grpc=server(self.registry,STORE_HOST,"0.0.0.0:8173"); self.stack.callback(lambda:grpc.stop(3).wait(5))
        http=BridgeServer(("0.0.0.0",8172),self.bridge)
        threading.Thread(target=http.serve_forever,daemon=True).start()
        self.stack.callback(lambda:private(self.directory/"bridge-transport.json",http.transport_snapshot()))
        self.stack.callback(http.server_close); self.stack.callback(http.shutdown)
        from src.infra.common import run as command
        host=command(["podman","exec","breaker-substrate-control-plane","getent","hosts","host.containers.internal"],capture=True).stdout.split()[0]
        self.stack.enter_context(temporary_bridge(self.deployment.cluster,self.directory,host,8172,request_timeout=470,backend_timeout=430,connect_timeout=30))
        self.stack.enter_context(model_timeouts(self.deployment.cluster,self.directory,request_timeout=330,backend_timeout=315))
        base=self.stack.enter_context(gateway_forward(self.deployment.cluster,self.directory)); self.base=base
        self.mcp=MCPClient(base,token,self.bridge,timeout=450); self.mcp.discover()
        def reserve_guard(request):
            span=mlflow.get_current_active_span()
            self.usage.reserve(role=self.active.get("role","llm_guard"),case_id=self.active["case_id"],trace_id=span.trace_id,request=request,model=self.plan["acting_model"])
            self.active["physical_attempts"]=self.active.get("physical_attempts",0)+1
        self.client=self.stack.enter_context(httpx.Client(transport=ModelTransport(base,on_request=reserve_guard,role="llm_guard"),timeout=300,trust_env=False,follow_redirects=False))
        common=dict(model=self.plan["acting_model"],base_url=base+"/v1",api_key=token,http_client=self.client,use_responses_api=True,
                    output_version="responses/v1",max_retries=0,timeout=300,temperature=0)
        self.model_common=common
        self.reviewer=llm_guard(ChatOpenAI(**common,max_tokens=256),guard_id="qwen-live-reviewer-v2",reserve_model=lambda:None,prompt_version="v2")
        definitions=[dict(type="function",function=dict(name=name,description=f"Pinned synthetic banking tool: {name}.",parameters=schema["arguments"])) for name,schema in self.adapter.catalog.schemas().items()]
        actor_client=self.stack.enter_context(httpx.Client(transport=ModelTransport(base,on_request=reserve_guard,role="actor"),timeout=300,trust_env=False,follow_redirects=False))
        actor_model=ChatOpenAI(**dict(common,http_client=actor_client),max_tokens=2048).bind_tools(definitions,parallel_tool_calls=False)
        observer=lambda event:job.emit("startup",event)
        from src.benchmark.startup import prepare
        # Controls use their original short fault timeout; no measured arm runs here.
        control_dir=self.directory/"controls";control_dir.mkdir()
        with native_hook(self.deployment.cluster,control_dir,host,8173,timeout_seconds=2):
            with observing(observer):
                observer(dict(stage="startup",phase="started"))
                self.startup=prepare(plan=self.plan,budget=self.usage,directory=self.directory,stage="native",resources=self.resources,
                    reviewer=self.reviewer,actor_model=actor_model,active=self.active,store=self.store,mcp=self.mcp,platform_check=self._platform_check)
                observer(dict(stage="startup",phase="finished"))
            for spec in [c for c in self.plan["cases"] if c["kind"]=="control" and not c.get("slot")]:
                claim_case(self.usage,spec["case_id"],self.plan)
                record,_=self._case(job,"setup",spec)
                if not make_card(spec,record)["demo_ready"]: raise RuntimeError("live_native_control_failed")
                self.setup.append(record)
        learned=self.directory/"learned";learned.mkdir()
        self.stack.enter_context(native_hook(self.deployment.cluster,learned,host,8173,timeout_seconds=330))
        for spec in [c for c in self.plan["cases"] if c["kind"]=="canary"]:
            claim_case(self.usage,spec["case_id"],self.plan)
            record,_=self._case(job,"setup",spec)
            if not make_card(spec,record)["demo_ready"]: raise RuntimeError("live_learned_canary_failed")
            self.setup.append(record)
        inputs=[[a["guard"]["input_digest"] for a in r["evidence"]["actions"]] for r in self.setup[-2:]]
        if inputs[0]!=inputs[1]: raise RuntimeError("live_canary_inputs_not_identical")
        private(self.directory/"startup-complete.json",dict(ready=True,priming=self.resources.snapshot(),controls=8))

    def _platform_check(self):
        from src.banking_service.validation import runtime_proof
        from src.benchmark.readiness import check
        actor=None
        try:
            actor=self.deployment.create_actor();runtime_proof(self.deployment,actor)
            with self.deployment.forward(actor["metadata"]["name"],actor=True) as base:
                client=RuntimeClient(base,self.authorization,timeout=15,boundary="driver_to_actor")
                probe=client.call("/probe",{})
                if (probe["uid"],probe["gid"],probe["effective_capabilities"],probe["no_new_privs"],probe["ambient_kubernetes_token"])!=(10001,10001,"0000000000000000","1",False):
                    raise RuntimeError("live_startup_sandbox_profile_mismatch")
                result=check(client,actor_id=actor["metadata"]["name"],actor_uid=actor["metadata"]["uid"],ticket_lifetime=900,policy=READINESS)
                return dict(ready=True,readiness=result,trial_created=False,tools_executed=0)
        finally:
            actor=actor or self.deployment.last_actor
            if actor:self.deployment.delete_actor(actor["metadata"]["name"])

    def _case(self, job, arm, spec):
        self.registry.release_completed()
        observer=lambda event:job.emit(arm,event)
        self.bridge.observer=observer
        mode=spec.get("mode")
        if spec["kind"]=="control":
            guard=LateAllowGuard() if mode in {"cancel","timeout"} else ControlGuard("allow" if mode=="unsupported" else mode)
            builder=ReviewBuilder(self.resources.projection_tokenizer(),maximum=1) if mode=="unsupported" else None
        else:
            guard=self.resources.select("classifier") if spec["arm"]=="classifier" else self.reviewer
            builder=ReviewBuilder(self.resources.projection_tokenizer())
        calls=self.plan["fixtures"]["user_task_0"] if spec["kind"]=="canary" else (
            self.plan["fixtures"]["user_task_0"]+self.plan["fixtures"]["injection_task_0"] if spec.get("card_id")=="D02" else None)
        self.active.update(case_id=spec["case_id"],role="llm_guard",physical_attempts=0)
        try:
            with observing(observer):
                record=run_case(deployment=self.deployment,store=self.store,authorization=self.authorization,adapter=self.adapter,
                    bridge=self.bridge,mcp=self.mcp,budget=self.usage,mask=self.mask,task_id=spec["task_id"],
                    control=mode if spec["kind"]=="control" else None,selected_guard=guard,review_builder=builder,
                    scripted_calls=calls,case_name=spec["case_id"],deadline_profile=MEASURE.name,request_model_id=self.plan["acting_model"],
                    cancel_on_review_start=mode=="cancel",limits=Limits(**self.plan["native_limits"]),
                    reconcile_telemetry=True,provider_probe=lambda **kw:provider_status(self.plan["acting_model"],**kw),verify_admission_readiness=True,
                    readiness_policy=READINESS,
                    reconciliation_options=dict(timeout_seconds=120,quiet_seconds=2,poll_seconds=1))
        except Exception as exc:
            partial=getattr(exc,"partial_record",None)
            private(self.directory/(spec["case_id"]+".partial.json"),self.mask(partial or dict(case_id=spec["case_id"],error=type(exc).__name__)))
            raise
        record["services_ready_before_case"]=True;record["serving_resources"]=self.resources.snapshot()
        path=self.directory/(spec["case_id"]+".json");private(path,record)
        record["source_record_path"]=str(path.resolve());record["source_record_sha256"]=hashlib.sha256(path.read_bytes()).hexdigest()
        validate_case_evidence(spec,record)
        with self.usage.locked(): entries=self.usage.entries()
        for role,key in (("actor","managed_responses_dispatches"),("llm_guard","guard_managed_responses_dispatches")):
            if sum(e["case_id"]==spec["case_id"] and e["role"]==role for e in entries)!=record["trace_audit"][key]:
                raise RuntimeError("live_request_ledger_mismatch")
        return record,path

    def run_lane(self, job, arm, spec):
        if self.plan["code_hashes"]!=source_hashes():raise RuntimeError("demo_source_changed_restart_server")
        self.renew_authority()
        job.emit(arm,dict(stage="credentials",phase="renewed"))
        self.capacity()
        job.emit(arm,dict(stage="lane",phase="started"))
        record,path=self._case(job,arm,spec)
        result=summarize(spec,record,job.events,self.plan)
        for span in result["gateway_spans"]:
            job.emit(arm,dict(stage="gateway_export",phase="observed",span_id=span["span_id"],duration_ns=span["duration_ns"]))
        job.emit(arm,dict(stage="lane",phase="finished",status=record["status"]))
        private(job.directory/(arm+"-source.json"),dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
        return record,result

    def renew_authority(self):
        # A presentation may pause for an hour between cards. Renew credentials,
        # never a model, and do not replay any inference or banking operation.
        self.deployment.refresh_credentials()
        token=(DIRECTORY/"runtime.token").read_text().strip()
        self.mask.secrets.add(token)
        self.authorization="Bearer "+token
        self.store.authorization=self.authorization;self.mcp.token=token
        self.model_common.update(api_key=token)
        self.reviewer=llm_guard(ChatOpenAI(**self.model_common,max_tokens=256),
            guard_id="qwen-live-reviewer-v2",reserve_model=lambda:None,prompt_version="v2")

    def review(self, job, slot, records):
        from src.feasibility.judges import build_judges, review
        from src.benchmark.judge_transport import observe_native_attempt
        from src.benchmark.review import review_harness,compact_observations
        from src.demo_ui.review import build,VERSION,INSTRUCTIONS
        model="gemini:/gemini-2.5-flash";results=[]
        def settle(entries,result):
            for entry in entries:self.usage.settle(entry["sequence"],accounted_cost_usd=result.get("cost_usd"),usage_verified=False)
        with observing(lambda e:job.emit("review",e)):
            for record in records:
                spec=next(c for c in slot["cases"] if c["case_id"]==record["case_id"])
                if not spec.get("gemini_task_judge"):continue
                for criterion,judge in build_judges(model).items():
                    entries=[]
                    def invocation(span):
                        def reserve(**kw):entries.append(self.usage.reserve(role="gemini_task_judge",case_id=spec["case_id"],trace_id=kw["trace_id"],request=dict(criterion=criterion),model=model))
                        return observe_native_attempt(span=span,mask=self.mask,model_uri=model,reserve=reserve)
                    job.emit("review",dict(stage="gemini",phase="started"))
                    result=review(judge,criterion,record,invocation_context=invocation)
                    settle(entries,result);results.append(result)
                    private(job.directory/"reviews.json",results)
                    job.emit("review",dict(stage="gemini",phase="finished",error=result.get("error")))
            case_id=slot["slot"]+"-review";claim_case(self.usage,case_id,self.plan)
            scoped=dict(self.plan,cases=[c for c in self.plan["cases"]+slot["cases"] if c["case_id"] in {r["case_id"] for r in self.setup+records}])
            with mlflow.start_span(name="live_pair_persisted_evidence",span_type="CHAIN") as suite:
                observations=compact_observations(scoped,self.setup+records)
                observations["live_ui"]=dict(card=slot["card"],arm_order=slot["order"],execution="sequential",
                    event_source="observed_host_boundaries_and_persisted_gateway_readback",events=job.events,
                    startup_probes=self.startup["model_probes"],startup_unscored=True,
                    classifier_priming_forwards=len(self.startup["classifier"]["startup_priming"]),
                    rubric_version=VERSION,rubric_sha256=hashlib.sha256(INSTRUCTIONS.encode()).hexdigest())
                suite.set_outputs(observations)
            persisted=mlflow.get_trace(suite.trace_id)
            if persisted is None:raise RuntimeError("live_review_target_not_persisted")
            entries=[]
            def reserve(**kw):entries.append(self.usage.reserve(role="gemini_harness_judge",case_id=case_id,trace_id=kw["trace_id"],request=dict(slot=slot["slot"]),model=model))
            result=review_harness(build(model),observations=observations,target_trace_id=suite.trace_id,
                reserve=reserve,scope="sequential-live-five-card-demo-pair",required_cases=[r["case_id"] for r in self.setup+records],rubric_version=VERSION)
            settle(entries,result);results.append(result);private(job.directory/"reviews.json",results)
        return dict(verdict=result.get("value"),error=result.get("error"),operations=len(results),
            task_agreements=sum(r.get("agrees") is True for r in results[:-1]),task_errors=sum(bool(r.get("error")) for r in results[:-1]),
            judge_trace_id=result.get("judge_trace_id"),scope="Post-run external review, not guard timing or human acceptance")

    def close(self):
        if self.closed:return
        self.closed=True
        try:
            if hasattr(self,"store"):
                if hasattr(self,"deployment"):
                    self.deployment.refresh_credentials()
                    self.store.authorization="Bearer "+(DIRECTORY/"runtime.token").read_text().strip()
                private(self.directory/"capacity-final.json",self.store.call("/capacity",{}))
        finally:self.stack.close()
