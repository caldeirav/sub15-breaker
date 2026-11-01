"""Configure and test the existing managed gateway without model generation.

This proves infrastructure transport using a bounded recorder and one harmless
MCP echo tool. It does not implement the banking MCP application or agent loop.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
from uuid import uuid4

from src.infra.common import STATE, VERSIONS
from src.infra.manage import Cluster, condition_is_current
from src.infra.protocol_resources import (FIXTURE_AUDIENCE, LABELS, MODEL_AUDIENCE,
    NAMESPACE, GATEWAY, manifests, resource)
from src.infra.protocol_client import LEGACY, MODERN, mcp_context

DIRECTORY = STATE/"target-stack"
EXPERIMENT = "breaker-banking-target-agent"
GATEWAY_REVISION = "26f5aebe99a36a037fe54f8080a608aca5547e15"


def require(condition, code):
    if not condition:raise RuntimeError(code)


def private(path, value):
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    path.write_text(json.dumps(value,indent=2)+"\n");path.chmod(0o600)
    return path


def redact(value, secrets):
    # Replace actual known values, not keys in public schema declarations.
    text=json.dumps(value,ensure_ascii=False)
    for secret in secrets:
        if secret:text=text.replace(secret,"[WITHHELD]")
    return json.loads(text)


def check_owned(cluster, objects):
    namespace=cluster.get("namespace",NAMESPACE)
    require(namespace["metadata"].get("labels",{}).get("app.kubernetes.io/part-of")=="sub15-breaker","foreign_gateway_namespace")
    for obj in objects:
        name,kind=obj["metadata"]["name"],obj["kind"]
        current=cluster.kubectl("get",kind,name,"-n",NAMESPACE,"--ignore-not-found","-o","json",capture=True).stdout
        if not current:continue
        value=json.loads(current)
        if kind=="Gateway" and name==GATEWAY:
            require(value["spec"]["gatewayClassName"]=="agentgateway","foreign_gateway_class")
            continue  # Only an extra listener is applied with its own field manager.
        require(all(value["metadata"].get("labels",{}).get(k)==v for k,v in LABELS.items()),"foreign_protocol_resource")


def configure(cluster, experiment_id):
    import mlflow
    from urllib.parse import urlsplit
    from src.banking_service.deploy import LABELS as BANKING_LABELS
    for key,default,port in [("MLFLOW_TRACKING_URI","http://localhost:5001",5001),("LM_STUDIO_BASE_URL","http://localhost:1234/v1",1234)]:
        url=urlsplit(os.getenv(key,default))
        require(url.scheme=="http" and url.hostname in {"localhost","127.0.0.1"} and url.port==port and
                not url.username and not url.password and not url.query and not url.fragment,"unexpected_local_service_profile")
    gateway=cluster.get("gateway",GATEWAY,"-n",NAMESPACE)
    if (DIRECTORY/"profile.json").exists():
        previous=json.loads((DIRECTORY/"profile.json").read_text())
        require(gateway["metadata"]["uid"]==previous["gateway_uid"],"managed_gateway_identity_changed_do_not_adopt")
    version=json.loads(cluster.kubectl("exec","-n",NAMESPACE,"deployment/"+GATEWAY,"--","/app/agentgateway","--version",capture=True).stdout)
    require(version["version"]==VERSIONS["agentgateway"].removeprefix("v") and version["git_revision"]==GATEWAY_REVISION,"gateway_runtime_drift")
    from src.infra.common import run
    host=run(["podman","exec","breaker-substrate-control-plane","getent","hosts","host.containers.internal"],capture=True).stdout.split()[0]
    model=os.environ["LM_STUDIO_MODEL"]
    issuer=json.loads(cluster.kubectl("get","--raw","/.well-known/openid-configuration",capture=True).stdout)["issuer"]
    jwks=json.loads(cluster.kubectl("get","--raw","/openid/v1/jwks",capture=True).stdout)
    bundle=manifests(host_ip=host,model=model,issuer=issuer,jwks=jwks,experiment_id=experiment_id)
    # Do not label the existing shared Gateway as exclusively owned by the probe.
    for item in bundle["items"]:
        if item["kind"]=="Gateway":item["metadata"].pop("labels",None)
    check_owned(cluster,bundle["items"])
    sa=next(i for i in bundle["items"] if i["kind"]=="ServiceAccount")
    cluster.kubectl("apply","--server-side","--field-manager=breaker-target-protocol","-f",private(DIRECTORY/"serviceaccount.json",sa))
    driver=cluster.get("serviceaccount","banking-driver","-n","breaker-banking")
    require(all(driver["metadata"].get("labels",{}).get(k)==v for k,v in BANKING_LABELS.items()),"foreign_banking_driver")
    tokens={}
    for key,name,namespace,audience in [("FIXTURE_TOKEN","target-protocol-client",NAMESPACE,FIXTURE_AUDIENCE),
            ("MODEL_TOKEN","banking-driver","breaker-banking",MODEL_AUDIENCE),
            ("WRONG_SUBJECT_TOKEN","banking-driver","breaker-banking",FIXTURE_AUDIENCE)]:
        tokens[key]=cluster.kubectl("create","token",name,"-n",namespace,"--audience="+audience,"--duration=3h",capture=True).stdout.strip()
        require(len(tokens[key].split("."))==3,"invalid_token_request_result")
    credentials=resource("v1","Secret","target-protocol-credentials",type="Opaque",stringData=tokens)
    check_owned(cluster,[credentials])
    cluster.kubectl("apply","--server-side","--field-manager=breaker-target-protocol","-f",private(DIRECTORY/"credentials.json",credentials))
    path=private(DIRECTORY/"resources.json",bundle)
    cluster.kubectl("apply","--server-side","--field-manager=breaker-target-protocol","--dry-run=server","--validate=strict","-f",path)
    cluster.kubectl("apply","--server-side","--field-manager=breaker-target-protocol","-f",path)
    cluster.kubectl("rollout","status","deployment/target-protocol-fixture","-n",NAMESPACE,"--timeout=180s")
    cluster.kubectl("wait","--for=condition=Ready","pod/target-protocol-client","-n",NAMESPACE,"--timeout=180s")
    cluster.kubectl("wait","--for=condition=Programmed","gateway/"+GATEWAY,"-n",NAMESPACE,"--timeout=180s")
    cluster.kubectl("rollout","status","deployment/"+GATEWAY,"-n",NAMESPACE,"--timeout=180s")
    source=next(item["data"] for item in bundle["items"] if item["kind"]=="ConfigMap")
    expected=dict(credentials={key:hashlib.sha256(value.encode()).hexdigest() for key,value in tokens.items()},
                  code={key:hashlib.sha256(value.encode()).hexdigest() for key,value in source.items()})
    code="import hashlib,json,pathlib; p=pathlib.Path('/credentials'); print(json.dumps({'credentials':{k:hashlib.sha256((p/k).read_bytes().strip()).hexdigest() if (p/k).is_file() else None for k in ['FIXTURE_TOKEN','MODEL_TOKEN','WRONG_SUBJECT_TOKEN']},'code':{f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in pathlib.Path('/probe').glob('*.py')}}))"
    deadline=time.monotonic()+90
    while True:
        observed=json.loads(cluster.kubectl("exec","-n",NAMESPACE,"target-protocol-client","--","python","-c",code,capture=True,timeout=20).stdout)
        if observed==expected:break
        require(time.monotonic()<deadline,"credential_projection_not_current")
        time.sleep(3)  # Wait for kubelet Secret projection, never retry inference.
    profile=dict(scope="managed-target-transport",gateway_uid=gateway["metadata"]["uid"],host_ip=host,model=model,
        experiment_id=str(experiment_id),experiment_name=EXPERIMENT,gateway_version=version,
        protocol_fixture_only=True,banking_mcp_application_implemented=False,
        profile_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),configured_at=time.time())
    private(DIRECTORY/"profile.json",profile)
    return profile,tokens


def current_bindings(cluster,profile):
    """Bind successful wire tests to current objects, generations and public specs."""
    desired=json.loads((DIRECTORY/"resources.json").read_text())["items"]
    snapshot={}
    for expected in desired:
        kind,name=expected["kind"],expected["metadata"]["name"]
        if kind not in {"Gateway","AgentgatewayBackend","HTTPRoute","AgentgatewayPolicy","ConfigMap"}:continue
        value=cluster.get(kind,name,"-n",NAMESPACE)
        metadata=value["metadata"]
        if kind=="Gateway":
            require(metadata["uid"]==profile["gateway_uid"],"qualified_gateway_replaced")
            require(all(condition_is_current(value,c) for c in ("Accepted","Programmed")),"gateway_status_not_current")
        elif kind=="AgentgatewayBackend":
            require(condition_is_current(value,"Accepted"),"backend_status_not_current")
        elif kind=="HTTPRoute":
            parents=value.get("status",{}).get("parents",[])
            require(any(p.get("controllerName")=="agentgateway.dev/agentgateway" and p.get("parentRef",{}).get("name")==GATEWAY and
                all(condition_is_current(dict(metadata=metadata,status=p),c) for c in ("Accepted","ResolvedRefs")) for p in parents),"route_status_not_current")
        elif kind=="AgentgatewayPolicy":
            ancestors=value.get("status",{}).get("ancestors",[])
            require(any(a.get("controllerName")=="agentgateway.dev/agentgateway" and a.get("ancestorRef",{}).get("name")==GATEWAY and
                all(condition_is_current(dict(metadata=metadata,status=a),c) for c in ("Accepted","Attached")) for a in ancestors),"policy_status_not_current")
        elif kind=="ConfigMap":
            require(value.get("data")==expected.get("data"),"protocol_code_differs_from_qualified_source")
        data=value.get("data") if kind=="ConfigMap" else value["spec"]
        snapshot[kind+"/"+name]=dict(uid=metadata["uid"],generation=metadata.get("generation"),
            spec_sha256=hashlib.sha256(json.dumps(data,sort_keys=True,separators=(",",":")).encode()).hexdigest())
    # NetworkPolicy is additive: a new allow rule can invalidate a previously
    # denied path even when every route and identity policy is unchanged.
    extra=cluster.get("networkpolicies","-n",NAMESPACE)["items"]
    extra += [cluster.get(kind,name,"-n",NAMESPACE) for kind,name in [
        ("agentgatewayparameters","internal"),("deployment",GATEWAY),("deployment","target-protocol-fixture"),
        ("service",GATEWAY),("service","target-protocol-fixture")]]
    for value in extra:
        metadata=value["metadata"]
        snapshot[value["kind"]+"/"+metadata["name"]]=dict(uid=metadata["uid"],generation=metadata.get("generation"),
            spec_sha256=hashlib.sha256(json.dumps(value["spec"],sort_keys=True,separators=(",",":")).encode()).hexdigest())
    namespace=cluster.get("namespace",NAMESPACE)
    snapshot["Namespace/"+NAMESPACE]=dict(uid=namespace["metadata"]["uid"],labels=namespace["metadata"].get("labels",{}))
    return snapshot


class Matrix:
    def __init__(self,cluster,profile,tokens,directory):
        self.cluster,self.profile,self.tokens,self.directory=cluster,profile,tokens,directory
        self.secrets=list(tokens.values())
        self.rows=[];self.client_spans=[];self.trace_id=None;self.cleanup_errors=[]
        service=cluster.get("service",GATEWAY,"-n",NAMESPACE)
        require({8080,8081}<={p["port"] for p in service["spec"]["ports"]},"managed_gateway_listener_not_serving")
        self.host=service["spec"]["clusterIP"]

    def wire(self,name,body=None,*,path="/v1/responses",method="POST",token="FIXTURE_TOKEN",port=8081,session=False,protocol=None):
        import mlflow
        from mlflow.tracing import get_tracing_context_headers_for_http_request
        kind="TOOL" if isinstance(body,dict) and body.get("method")=="tools/call" else "CHAIN"
        with mlflow.start_span(name="gateway_http_"+name,span_type=kind) as span:
            self.client_spans.append(span.span_id)
            request=dict(url=f"http://{self.host}:{port}{path}",method=method,token=token,session=session)
            if protocol:
                request["protocol"]=protocol
                if body is not None:body,_=mcp_context(body,protocol)
            if body is not None:request["body"]=body
            span.set_inputs(redact(request,self.secrets))
            request["traceparent"]=get_tracing_context_headers_for_http_request()["traceparent"]
            encoded=base64.b64encode(json.dumps(request).encode()).decode()
            try:
                raw=self.cluster.kubectl("exec","-n",NAMESPACE,"target-protocol-client","--","python","-B","/probe/protocol_client.py",encoded,capture=True,timeout=35).stdout
            except subprocess.CalledProcessError as exc:
                raw=exc.stdout or "{}"
                span.set_outputs(redact(json.loads(raw),self.secrets))
                raise RuntimeError("bounded_gateway_transport_failed") from None
            result=json.loads(raw)
            span.set_outputs(redact(result,self.secrets))
            payload=result.get("body")
            if (result.get("status",0)>=400 or isinstance(payload,dict) and
                ("error" in payload or payload.get("result",{}).get("isError") is True)):
                span.set_status("ERROR")
            require(result.get("physical_client_attempts")==1,"unexpected_client_attempt_count")
            return result

    def records(self):
        code="import json,urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8080/records',timeout=3).read().decode())"
        raw=self.cluster.kubectl("exec","-n",NAMESPACE,"deployment/target-protocol-fixture","--","python","-c",code,capture=True,timeout=15).stdout
        return json.loads(raw)["records"]

    def step(self,name,fn):
        import mlflow
        with mlflow.start_span(name=name,span_type="CHAIN") as span:
            span.set_inputs(dict(case_id=name,scope="non-executing-infrastructure-protocol"))
            try:
                result=fn();row=dict(case_id=name,passed=True,observations=redact(result,self.secrets),span_id=span.span_id)
                span.set_outputs(row);self.rows.append(row)
            except Exception as exc:
                row=dict(case_id=name,passed=False,error=type(exc).__name__,span_id=span.span_id)
                span.set_outputs(row);self.rows.append(row)
                raise

    def run(self):
        tool=dict(type="function",name="echo_decimal_fixture",description="Non-executing decimal/null wire fixture",parameters=dict(
            type="object",properties=dict(amount=dict(type="string"),note=dict(anyOf=[dict(type="string"),dict(type="null")],default=None),password=dict(type="string",writeOnly=True)),required=["amount"],additionalProperties=False))
        state={}
        def text():
            result=self.wire("text",dict(model="protocol-fixture",input="Synthetic protocol text only.",store=False))
            require(result["status"]==200 and result["body"]["status"]=="completed","fixture_text_response_failed")
            state["text"]=result["body"];return dict(status=200,response_status="completed")
        self.step("responses_text",text)
        def functions():
            start=self.wire("function",dict(model="protocol-fixture",input="Non-executing function fixture.",tools=[tool],store=False))
            require(start["status"]==200,"fixture_function_request_failed")
            calls=[i for i in start["body"]["output"] if i["type"]=="function_call"]
            require(len(calls)==1,"function_count_changed")
            call=calls[0]
            require(call["call_id"]=="fixture-call-1" and json.loads(call["arguments"])==dict(amount="123.40",note=None),"function_arguments_or_id_changed")
            history=[dict(role="user",content="Non-executing function fixture."),*start["body"]["output"],dict(type="function_call_output",call_id=call["call_id"],output='{"fixture_only":true}')]
            final=self.wire("function_result",dict(model="protocol-fixture",input=history,tools=[tool],store=False))
            require(final["status"]==200 and final["body"]["status"]=="completed","function_result_roundtrip_failed")
            records=[r for r in self.records() if r["path"]=="/v1/chat/completions"]
            upstream=records[-1]["body"]
            require(any(m.get("role")=="tool" and m.get("tool_call_id")==call["call_id"] for m in upstream["messages"]),"unpaired_upstream_tool_result")
            require(upstream["tools"][0]["function"]["parameters"]==tool["parameters"],"tool_schema_was_rewritten")
            require(all(not r["authorization_present"] for r in records),"caller_credential_forwarded_to_provider")
            require(start["body"].get("usage",{}).get("total_tokens")==44,"converted_usage_missing")
            return dict(call_id=call["call_id"],decimal="123.40",null_preserved=True,tool_results_paired=True,usage=44,provider_credentials_stripped=True)
        self.step("responses_function_roundtrip",functions)
        def failure():
            before=len([r for r in self.records() if r["path"]=="/v1/chat/completions"])
            result=self.wire("fault",dict(model="fixture-fail500",input="Deliberate provider fixture fault.",store=False))
            after=len([r for r in self.records() if r["path"]=="/v1/chat/completions"])
            require(result["status"]>=500 and after-before==1,"gateway_retried_or_concealed_provider_failure")
            return dict(status=result["status"],physical_upstream_attempts=1,expected_failure=True)
        self.step("provider_failure_without_retry",failure)
        for auth in ("none","invalid","MODEL_TOKEN","WRONG_SUBJECT_TOKEN"):
            def reject(auth=auth):
                before=len([r for r in self.records() if r["path"]=="/v1/chat/completions"])
                result=self.wire("reject_"+auth,dict(model="protocol-fixture",input="Must not reach recorder."),token=auth)
                after=len([r for r in self.records() if r["path"]=="/v1/chat/completions"])
                require(result["status"] in {401,403} and after==before,"identity_denial_failed")
                if auth=="WRONG_SUBJECT_TOKEN":require(result["status"]==403,"signed_wrong_subject_not_denied_by_authorization")
                return dict(status=result["status"],upstream_attempts=0)
            self.step("identity_"+auth,reject)
        def metadata():
            result=self.wire("metadata",path="/infra/model-metadata",method="GET")
            require(result["status"]==200 and self.profile["model"] in {m["id"] for m in result["body"]["data"]},"gateway_cannot_reach_model_server")
            return dict(status=200,model=self.profile["model"],generation_requests=0)
        self.step("managed_gateway_to_model_metadata",metadata)
        def modern_mcp():
            base=dict(path="/mcp",protocol=MODERN)
            discover=self.wire("mcp_discover",dict(jsonrpc="2.0",id=11,method="server/discover",params={}),**base)
            require(discover["status"]==200 and MODERN in discover["body"]["result"]["supportedVersions"],"modern_mcp_discovery_failed")
            require(discover["session_received"] is False,"modern_mcp_unexpected_session")
            listing=self.wire("mcp_modern_tools",dict(jsonrpc="2.0",id=12,method="tools/list",params={}),**base)
            tools=listing["body"]["result"]["tools"]
            require(len(tools)==1 and tools[0]["name"].endswith("echo_fixture"),"modern_mcp_tool_set_changed")
            needle="synthetic-private-"+uuid4().hex;self.secrets.append(needle)
            reply=self.wire("mcp_modern_echo",dict(jsonrpc="2.0",id=13,method="tools/call",params=dict(name=tools[0]["name"],arguments=dict(text=needle))),**base)
            require(reply["body"]["result"]["content"][0]["text"]==needle and reply["session_received"] is False,"modern_mcp_echo_failed")
            bad=self.wire("mcp_modern_unknown",dict(jsonrpc="2.0",id=14,method="tools/call",params=dict(name="execute_command",arguments={})),**base)
            require("error" in bad["body"] or bad["body"].get("result",{}).get("isError") is True,"modern_unknown_tool_not_denied")
            error=self.wire("mcp_modern_tool_error",dict(jsonrpc="2.0",id=15,method="tools/call",params=dict(name=tools[0]["name"],arguments=dict(text=123))),**base)
            require("error" in error["body"] or error["body"].get("result",{}).get("isError") is True,"modern_tool_error_concealed")
            denied=self.wire("mcp_modern_wrong_subject",dict(jsonrpc="2.0",id=16,method="tools/list",params={}),token="WRONG_SUBJECT_TOKEN",**base)
            require(denied["status"]==403,"modern_mcp_subject_authorization_failed")
            removed=self.wire("mcp_modern_removed_initialize",dict(jsonrpc="2.0",id=17,method="initialize",params=dict(protocolVersion=MODERN,capabilities={},clientInfo=dict(name="probe",version="1"))),**base)
            require(removed["status"]==404,"modern_removed_handshake_was_not_rejected")
            return dict(protocol=MODERN,server_discovery=True,sessionless=True,echo=True,unknown_tool_denied=True,tool_error_visible=True,removed_initialize_denied=True,banking_tools_executed=0)
        self.step("managed_mcp_2026_sessionless",modern_mcp)
        def mcp_flow():
            base=dict(path="/mcp",session=True,protocol=LEGACY)
            result=self.wire("mcp_initialize",dict(jsonrpc="2.0",id=1,method="initialize",params=dict(protocolVersion=LEGACY,capabilities={},clientInfo=dict(name="infra-probe",version="1"))),**base)
            require(result["status"]==200 and "result" in result["body"],"mcp_initialize_failed")
            primary=None
            try:
                notified=self.wire("mcp_initialized",dict(jsonrpc="2.0",method="notifications/initialized"),**base)
                require(notified["status"] in {200,202,204},"mcp_initialized_notification_failed")
                listing=self.wire("mcp_tools",dict(jsonrpc="2.0",id=2,method="tools/list",params={}),**base)
                tools=listing["body"]["result"]["tools"]
                require(len(tools)==1 and tools[0]["name"].endswith("echo_fixture"),"unexpected_mcp_tool_set")
                denied=self.wire("mcp_legacy_wrong_subject",dict(jsonrpc="2.0",id=5,method="tools/list",params={}),token="WRONG_SUBJECT_TOKEN",**base)
                require(denied["status"]==403,"session_id_bypassed_subject_authorization")
                needle="synthetic-private-"+uuid4().hex;self.secrets.append(needle)
                reply=self.wire("mcp_echo",dict(jsonrpc="2.0",id=3,method="tools/call",params=dict(name=tools[0]["name"],arguments=dict(text=needle))),**base)
                require(reply["body"]["result"]["content"][0]["text"]==needle,"mcp_result_changed")
            except BaseException as exc:
                primary=exc;raise
            finally:
                if result["session_received"]:
                    try:
                        closed=self.wire("mcp_close",method="DELETE",**base)
                        require(closed["status"] in {200,202,204},"mcp_session_cleanup_failed")
                    except Exception as exc:
                        self.cleanup_errors.append(type(exc).__name__)
                        if primary is None:raise
            return dict(advertised_tools=1,echo=True,wrong_subject_denied=True,
                session_mode="stateful" if result["session_received"] else "stateless",session_closed=True,banking_tools_executed=0)
        self.step("managed_mcp_2025_explicit_compatibility",mcp_flow)
        def bypass():
            destinations=[self.cluster.get("service","target-protocol-fixture","-n",NAMESPACE)["spec"]["clusterIP"],
                self.cluster.get("pods","-n",NAMESPACE,"-l","app=target-protocol-fixture")["items"][0]["status"]["podIP"]]
            for ip in destinations:
                raw=self.cluster.kubectl("exec","-n",NAMESPACE,"target-protocol-client","--","python","-B","/probe/probe_client.py",ip,"8080",capture=True,timeout=15).stdout
                result=json.loads(raw)
                require(result.get("reachable") is False and result.get("reason")=="connect-timeout","direct_backend_bypass_not_proven_denied")
            return dict(denied_service_and_pod=True,positive_controls_required=True)
        self.step("direct_backend_bypass_denied",bypass)
        self.step("post_negative_positive_control",text)


def main():
    from dotenv import load_dotenv
    import mlflow
    from mlflow.entities import AssessmentSource
    from src.infra.common import ROOT
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--configure",action="store_true")
    args=parser.parse_args()
    load_dotenv(ROOT/".env")
    os.environ["MLFLOW_ENABLE_ASYNC_TRACE_LOGGING"]="false"
    os.environ["MLFLOW_HTTP_REQUEST_TIMEOUT"]="5"
    os.environ["MLFLOW_HTTP_REQUEST_MAX_RETRIES"]="0"
    cluster=Cluster("breaker-substrate");cluster.ensure_owned()
    from src.infra.doctor import check_hypervisor,check_podman_versions
    check_hypervisor();check_podman_versions()
    experiment=mlflow.set_experiment(EXPERIMENT)
    if args.configure:profile,tokens=configure(cluster,experiment.experiment_id)
    else:
        profile=json.loads((DIRECTORY/"profile.json").read_text())
        tokens=json.loads((DIRECTORY/"credentials.json").read_text())["stringData"]
    require(profile["experiment_id"]==str(experiment.experiment_id),"gateway_export_experiment_mismatch")
    directory=DIRECTORY/"runs"/uuid4().hex;directory.mkdir(parents=True,mode=0o700)
    matrix=Matrix(cluster,profile,tokens,directory)
    source=AssessmentSource(source_type="CODE",source_id="managed-gateway-infrastructure-v1")
    run=mlflow.start_run(run_name="managed-gateway-protocol-matrix")
    mlflow.set_tags(dict(scope="non-executing-protocol-infrastructure",human_acceptance="pending",github_issue="38"))
    mlflow.log_dict(profile,"profile.json")
    for name in ["protocol_resources.py","protocol_fixture.py","protocol_client.py","target_stack.py"]:mlflow.log_artifact(str(ROOT/"src/infra"/name),"implementation")
    passed=False
    try:
        with mlflow.start_span(name="managed_gateway_protocol_matrix",span_type="CHAIN") as root:
            matrix.trace_id=root.trace_id
            mlflow.update_current_trace(metadata={"banking.scope":"infrastructure-protocol-fixture","banking.model_requests":"0","banking.utility_evaluated":"false"})
            root.set_inputs(dict(scope="non-executing-protocol-infrastructure",model_requests=0,gateway_profile_sha256=profile["profile_sha256"]))
            matrix.run();passed=True
            root.set_outputs(dict(passed=True,cases=len(matrix.rows),model_requests=0,banking_tools_executed=0))
    finally:
        summary=dict(passed=passed,cases=matrix.rows,model_requests=0,banking_tools_executed=0,
            run_id=run.info.run_id,trace_id=matrix.trace_id,profile_sha256=profile["profile_sha256"],human_acceptance="pending",cleanup_errors=matrix.cleanup_errors)
        private(directory/"summary.json",summary);mlflow.log_dict(summary,"summary.json")
        try:
            recorder=redact(matrix.records(),matrix.secrets)
            private(directory/"upstream-records.json",recorder);mlflow.log_dict(recorder,"upstream-records.json")
        except Exception as exc:
            mlflow.log_dict(dict(stage="upstream_recorder_readback",error=type(exc).__name__),"recorder-error.json")
        if matrix.trace_id:
            for row in matrix.rows:mlflow.log_feedback(trace_id=matrix.trace_id,span_id=row["span_id"],name="infra/protocol_passed",value=row["passed"],source=source)
        if not passed:mlflow.end_run(status="FAILED")
    try:
        mlflow.flush_trace_async_logging()
        deadline=time.monotonic()+20
        while True:
            trace=mlflow.get_trace(matrix.trace_id)
            if trace is not None:
                spans=trace.data.spans;ids={s.span_id for s in spans}
                native={r["span_id"] for r in matrix.rows}|set(matrix.client_spans)
                external=[s for s in spans if s.span_id not in native and s.parent_id is not None]
                if len(external)>=len(matrix.client_spans) and all(s.parent_id in ids for s in spans if s.parent_id):break
            require(time.monotonic()<deadline,"gateway_otlp_parentage_or_ingestion_incomplete")
            time.sleep(1)  # Read the same trace; do not reissue model/tool requests.
        roots=[s for s in spans if s.parent_id is None]
        require(len(roots)==1 and roots[0].name=="managed_gateway_protocol_matrix","distributed_trace_root_mismatch")
        rendered=json.dumps(trace.to_dict())
        require(not any(secret in rendered for secret in matrix.secrets),"gateway_trace_leaked_probe_credential_or_value")
        for row in matrix.rows:
            matches=[a for a in trace.info.assessments if a.span_id==row["span_id"] and a.name=="infra/protocol_passed"]
            require(len(matches)==1 and matches[0].value is True and matches[0].source.source_id==source.source_id,"protocol_assessment_readback_mismatch")
        audit=dict(passed=True,run_id=run.info.run_id,trace_id=matrix.trace_id,spans=len(spans),gateway_spans=len(external),
                   native_client_requests=len(matrix.client_spans),secret_values_absent=True,model_requests=0,
                   scope="protocol-infrastructure-only",human_acceptance="pending")
        bindings=current_bindings(cluster,profile)
        private(directory/"qualified-bindings.json",bindings);mlflow.log_dict(bindings,"qualified-bindings.json")
        private(DIRECTORY/"qualified-bindings.json",bindings)
        mlflow.log_dict(audit,"audit.json")
        private(directory/"audit.json",audit)
        private(DIRECTORY/"latest-protocol-audit.json",dict(audit,directory=str(directory),profile_sha256=profile["profile_sha256"]))
        mlflow.end_run(status="FINISHED")
        print(json.dumps(audit),flush=True)
    except BaseException as exc:
        failure=dict(passed=False,stage="persisted_gateway_trace_audit",error=type(exc).__name__,trace_id=matrix.trace_id)
        private(directory/"audit.json",failure);mlflow.log_dict(failure,"audit.json")
        mlflow.end_run(status="FAILED")
        raise


if __name__=="__main__":main()
