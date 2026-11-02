"""Serial banking MCP bridge to the existing store and real Actor HTTP service."""
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import threading
from time import perf_counter_ns
from uuid import uuid4

import httpx
import mlflow
from mlflow.tracing.fluent import with_active_span

from src.agent_runtime.contracts import ToolOutcome
from src.banking_contracts.codec import ContractError
from src.banking_service.http import body_object
from src.benchmark.guards import ReviewInput
from src.infra.protocol_client import MODERN,mcp_context


class Bridge:
    def __init__(self,catalog,registry,mask):
        self.catalog,self.registry,self.mask=catalog,registry,mask
        self.store=None;self.actor=None;self.trial_id=None;self.guard=None
        self.pending=None;self.lock=threading.Lock();self.actions=[]
        self.review_builder=None

    def configure(self,store,actor,trial_id,guard,review_builder=None):
        self.store,self.actor,self.trial_id,self.guard=store,actor,trial_id,guard
        self.pending=None;self.actions=[]
        self.review_builder=review_builder

    def tools(self):
        return [dict(name=name,description=f"Pinned synthetic banking tool: {name}.",
            inputSchema=schema["arguments"]) for name,schema in self.catalog.schemas().items()]

    def rpc(self,body):
        envelope=dict(jsonrpc="2.0",id=body.get("id"))
        method=body.get("method");params=body.get("params",{})
        if method=="server/discover":
            return dict(envelope,result=dict(resultType="complete",supportedVersions=[MODERN,"2025-11-25"],capabilities=dict(tools={}),
                _meta={"io.modelcontextprotocol/serverInfo":{"name":"banking-actor-bridge","version":"1"}},ttlMs=1000,cacheScope="private"))
        if method=="initialize":
            return dict(envelope,result=dict(protocolVersion=params["protocolVersion"],capabilities=dict(tools={}),
                serverInfo=dict(name="banking-actor-bridge",version="1")))
        complete={"resultType":"complete"} if params.get("_meta",{}).get("io.modelcontextprotocol/protocolVersion")==MODERN else {}
        if method=="tools/list":return dict(envelope,result=dict(**complete,tools=self.tools()))
        if method!="tools/call":return dict(envelope,error=dict(code=-32601,message="unsupported_banking_method"))
        if not self.lock.acquire(blocking=False):raise ValueError("serial_banking_bridge_busy")
        try:
            pending=self.pending
            if pending is None:raise ValueError("no_bound_agent_call")
            call,parent=pending
            if params.get("name")!=call.name or params.get("arguments",{})!=call.arguments:
                raise ValueError("gateway_call_binding_mismatch")
            self.pending=None  # No duplicate dispatch, including uncertain errors.
            outcome=self.dispatch(call,parent)
            return dict(envelope,result=dict(**complete,isError=outcome.status in {"error","unknown"},
                content=[dict(type="text",text=json.dumps(asdict(outcome),allow_nan=False))],structuredContent=asdict(outcome)))
        finally:self.lock.release()

    def dispatch(self,call,parent):
        span=mlflow.start_span_no_context(name="banking_actor_dispatch",span_type="TOOL",parent_span=parent)
        record=dict(call_id=call.call_id,tool=call.name,arguments=call.arguments,span_id=span.span_id,trial_id=self.trial_id)
        ticket=None
        try:
            with with_active_span(span):
                self.mask.learn(call.arguments)
                span.set_inputs(record)
                snapshot=self.store.call("/snapshot",dict(trial_id=self.trial_id))
                arguments=self.catalog.validate_arguments(call.name,call.arguments)
                proposal=dict(schema_version="banking-action-v1",action_id="action-"+uuid4().hex,idempotency_key="idem-"+uuid4().hex,
                    tool_name=call.name,arguments=arguments,expected_context_version=snapshot["context"]["context_version"],
                    expected_actor_generation=snapshot["generation"],expected_state_version=snapshot["state_version"])
                prepared=self.store.call("/prepare",dict(trial_id=self.trial_id,proposal=proposal))
                if prepared["status"]!="prepared":raise RuntimeError("unexpected_prepared_status")
                ticket=prepared["ticket"]
                # Context is caller/backend-owned, never model-supplied authority.
                materialize=perf_counter_ns();issues=()
                if self.review_builder:
                    projected=self.review_builder(snapshot,call.name,arguments,self.actions)
                    review=projected.value;issues=projected.issues
                else:
                    review=ReviewInput(snapshot["context"]["user_request"],"banking-wiring-v1",
                        "Synthetic banking wiring control; learned policy evaluation is not claimed.",call.name,arguments,
                        state={"state_version":snapshot["state_version"]})
                record["review_materialization_ns"]=perf_counter_ns()-materialize
                self.registry.register(ticket,review,self.guard,parent=span,input_issues=issues)
                started=perf_counter_ns()
                try:
                    result=self.actor.call("/execute",dict(ticket=ticket))
                except (ContractError,httpx.TransportError):
                    # Read status once, never repeat prepare or execution.
                    result=self.store.call("/status",dict(trial_id=self.trial_id,ticket=ticket))
                elapsed=perf_counter_ns()-started
                gate=self.registry.result(ticket)
                if result["status"]=="completed":
                    committed=result["result"]
                    status="error" if committed["error"] else "executed"
                    outcome=ToolOutcome(call.call_id,status,committed["output"],ticket,gate or {})
                    record.update(execution_receipt=committed["receipt"],state_changed=committed["state_changed"],
                        before_state_hash=committed["before_fingerprint"],error=committed["error"])
                    if gate is None or gate["decision"]!="allow":
                        raise RuntimeError("native_enforcement_bypassed")
                elif gate and gate["decision"] in {"block","error"} and result["status"]=="prepared":
                    outcome=ToolOutcome(call.call_id,"blocked" if gate["decision"]=="block" else "error",None,ticket,gate)
                else:outcome=ToolOutcome(call.call_id,"unknown",None,ticket,gate or {})
                record.update(status=outcome.status,output=outcome.output,ticket=ticket,guard=gate,
                    actor_roundtrip_ns=elapsed)
                span.set_outputs(record)
                self.actions.append(record)
                return outcome
        except Exception as exc:
            record.update(status="unknown",error=type(exc).__name__,ticket=ticket)
            span.set_outputs(record);self.actions.append(record)
            return ToolOutcome(call.call_id,"unknown",None,ticket,dict(error=type(exc).__name__))
        finally:span.end()


class BridgeServer(ThreadingHTTPServer):
    daemon_threads=True
    def __init__(self,address,bridge):self.bridge=bridge;super().__init__(address,Handler)


class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_GET(self):self.reply(200 if self.path=="/health" else 404,{"ready":self.path=="/health"})
    def reply(self,status,value):
        data=json.dumps(value,allow_nan=False).encode();self.send_response(status)
        self.send_header("content-type","application/json");self.send_header("content-length",str(len(data)));self.end_headers();self.wfile.write(data)
    def do_POST(self):
        try:
            self.connection.settimeout(45)
            sizes=self.headers.get_all("content-length",[])
            if self.path!="/mcp" or len(sizes)!=1 or self.headers.get("transfer-encoding"):raise ValueError("unsupported_request")
            size=int(sizes[0])
            if not 0<size<=131072:raise ValueError("body_limit")
            raw=self.rfile.read(size)
            if len(raw)!=size:raise ValueError("short_body")
            body=body_object(raw)
            if "id" not in body:self.reply(202,{})
            else:self.reply(200,self.server.bridge.rpc(body))
        except Exception:self.reply(400,{"error":"invalid_banking_bridge_request"})


class MCPClient:
    def __init__(self,base,token,bridge,*,timeout=50):
        self.base,self.token,self.bridge=base,token,bridge;self.names={};self.timeout=timeout

    def rpc(self,method,params):
        body,headers=mcp_context(dict(jsonrpc="2.0",id=uuid4().hex,method=method,params=params),MODERN)
        headers.update(authorization="Bearer "+self.token,accept="application/json, text/event-stream")
        from mlflow.tracing.distributed import get_tracing_context_headers_for_http_request
        headers.update(get_tracing_context_headers_for_http_request())
        with httpx.Client(timeout=self.timeout,trust_env=False,follow_redirects=False) as client:
            response=client.post(self.base+"/benchmark/mcp",json=body,headers=headers)
        response.raise_for_status()
        if "text/event-stream" in response.headers.get("content-type",""):
            values=[json.loads(line[5:].strip()) for line in response.text.splitlines() if line.startswith("data:")]
            payload=next(value for value in values if value.get("id")==body["id"])
        else:payload=response.json()
        if payload.get("error") or "result" not in payload:raise RuntimeError("gateway_mcp_rpc_error")
        return payload["result"]

    def discover(self):
        tools=self.rpc("tools/list",{})["tools"]
        canonical=set(self.bridge.catalog.names)
        for tool in tools:
            candidates=[name for name in canonical if tool["name"]==name or tool["name"].endswith("_"+name)]
            if len(candidates)!=1:raise RuntimeError("unrecognized_gateway_tool_name")
            name=candidates[0]
            if name in self.names or tool["inputSchema"]!=self.bridge.catalog.schemas()[name]["arguments"]:
                raise RuntimeError("gateway_tool_schema_or_name_mismatch")
            self.names[name]=tool["name"]
        if set(self.names)!=canonical:raise RuntimeError("gateway_tool_catalog_incomplete")
        return tools

    def execute(self,call):
        with mlflow.start_span(name="gateway_mcp_tool",span_type="TOOL") as span:
            span.set_inputs(dict(call_id=call.call_id,name=call.name,arguments=call.arguments,url=self.base+"/benchmark/mcp"))
            self.bridge.pending=(call,span)
            try:
                result=self.rpc("tools/call",dict(name=self.names[call.name],arguments=call.arguments))
                raw=result.get("structuredContent")
                if raw is None:raw=json.loads(result["content"][0]["text"])
                outcome=ToolOutcome(**raw)
                if outcome.call_id!=call.call_id:raise RuntimeError("mcp_call_id_mismatch")
                span.set_outputs(asdict(outcome));return outcome
            finally:self.bridge.pending=None
