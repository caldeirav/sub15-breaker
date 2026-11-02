"""Temporary additive benchmark routes and the native Substrate egress filter."""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import socket
import subprocess
import time

import yaml

from src.infra.common import environment
from src.infra.protocol_resources import GATEWAY,NAMESPACE,MODEL_AUDIENCE,MODEL_SUBJECT,backend_ref

SCOPE={"app.kubernetes.io/part-of":"sub15-breaker","breaker.sub15/scope":"benchmark-wiring-v1"}


def private(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    path.write_text(json.dumps(value,indent=2)+"\n");path.chmod(0o600)
    return path


def resource_patch(current,desired):
    """CAS update without kubectl's last-applied annotation regeneration."""
    operations=[dict(op="test",path="/metadata/uid",value=current["metadata"]["uid"]),
        dict(op="test",path="/metadata/resourceVersion",value=current["metadata"]["resourceVersion"]),
        dict(op="replace",path="/spec",value=desired["spec"])]
    for field in ("labels","annotations"):
        if field in desired["metadata"]:operations.append(dict(op="add",path="/metadata/"+field,value=desired["metadata"][field]))
        elif field in current["metadata"]:operations.append(dict(op="remove",path="/metadata/"+field))
    return operations


def configure_bridge(cluster,directory,host_ip,port,*,request_timeout=60,backend_timeout=None,connect_timeout=None):
    if connect_timeout is not None and not 0.1<=connect_timeout<request_timeout:raise ValueError("invalid_mcp_connect_timeout")
    issuer=json.loads(cluster.kubectl("get","--raw","/.well-known/openid-configuration",capture=True).stdout)["issuer"]
    jwks=json.loads(cluster.kubectl("get","--raw","/openid/v1/jwks",capture=True).stdout)
    def obj(api,kind,name,spec):
        return dict(apiVersion=api,kind=kind,metadata=dict(name=name,namespace=NAMESPACE,labels=SCOPE),spec=spec)
    route="benchmark-banking-mcp"
    objects=[obj("agentgateway.dev/v1alpha1","AgentgatewayBackend",route,dict(mcp=dict(targets=[dict(
        name="banking",static=dict(host=host_ip,port=port,path="/mcp",protocol="StreamableHTTP"))]))),
        obj("gateway.networking.k8s.io/v1","HTTPRoute",route,dict(parentRefs=[dict(name=GATEWAY,sectionName="http")],rules=[dict(
            matches=[dict(path=dict(type="Exact",value="/benchmark/mcp"),method="POST")],
            backendRefs=[backend_ref(route)],timeouts=dict(request=f"{request_timeout}s"))])),
        obj("agentgateway.dev/v1alpha1","AgentgatewayPolicy",route,dict(targetRefs=[dict(
            group="gateway.networking.k8s.io",kind="HTTPRoute",name=route)],traffic=dict(retry=dict(attempts=0),
                jwtAuthentication=dict(mode="Strict",providers=[dict(issuer=issuer,audiences=[MODEL_AUDIENCE],jwks=dict(inline=json.dumps(jwks)))]),
                authorization=dict(action="Allow",policy=dict(matchExpressions=["jwt.sub == "+json.dumps(MODEL_SUBJECT)]))))),
        obj("networking.k8s.io/v1","NetworkPolicy","benchmark-gateway-host-bridge",dict(podSelector=dict(matchLabels=dict(role="gateway")),
             policyTypes=["Egress"],egress=[dict(to=[dict(ipBlock=dict(cidr=host_ip+"/32"))],ports=[dict(protocol="TCP",port=port)])]))]
    if backend_timeout is not None:
        # MCP upstream calls have their own deadline, independent of HTTPRoute.
        objects[2]["spec"]["backend"]={"http":{"requestTimeout":f"{backend_timeout}s"}}
    if connect_timeout is not None:
        objects[2]["spec"].setdefault("backend",{})["tcp"]={"connectTimeout":f"{connect_timeout}s"}
    updates=[]
    for index,item in enumerate(objects):
        raw=cluster.kubectl("get",item["kind"],item["metadata"]["name"],"-n",NAMESPACE,"--ignore-not-found","-o","json",capture=True).stdout
        if raw and any(json.loads(raw)["metadata"].get("labels",{}).get(k)!=v for k,v in SCOPE.items()):
            raise RuntimeError("refusing_foreign_benchmark_resource")
        if raw:
            current=json.loads(raw);desired=deepcopy(current);desired["spec"]=item["spec"]
            desired["metadata"].setdefault("labels",{}).update(SCOPE)
            path=private(Path(directory)/f"bridge-update-{index}.json",resource_patch(current,desired))
            updates.append(("patch",item["kind"],item["metadata"]["name"],"-n",NAMESPACE,"--type=json","--patch-file",path))
        else:
            path=private(Path(directory)/f"bridge-create-{index}.json",item)
            updates.append(("create","--validate=strict","-f",path))
    path=private(Path(directory)/"gateway-bridge.json",dict(apiVersion="v1",kind="List",items=objects))
    for update in updates:cluster.kubectl(*update,"--dry-run=server")
    for update in updates:cluster.kubectl(*update)


@contextmanager
def temporary_bridge(cluster,directory,host_ip,port,*,request_timeout,backend_timeout,connect_timeout=None):
    names=[("AgentgatewayBackend","benchmark-banking-mcp"),("HTTPRoute","benchmark-banking-mcp"),
        ("AgentgatewayPolicy","benchmark-banking-mcp"),("NetworkPolicy","benchmark-gateway-host-bridge")]
    before=[]
    for kind,name in names:
        raw=cluster.kubectl("get",kind,name,"-n",NAMESPACE,"--ignore-not-found","-o","json",capture=True).stdout
        before.append(json.loads(raw) if raw else None)
    private(Path(directory)/"bridge-original-resources.json",before)
    configure_bridge(cluster,directory,host_ip,port,request_timeout=request_timeout,backend_timeout=backend_timeout,connect_timeout=connect_timeout)
    applied=[cluster.get(kind,name,"-n",NAMESPACE) for kind,name in names]
    try:
        policy=applied[2]["spec"]
        if connect_timeout is not None and policy.get("backend",{}).get("tcp",{}).get("connectTimeout")!=f"{connect_timeout}s":
            raise RuntimeError("mcp_connect_timeout_not_applied")
        private(Path(directory)/"bridge-applied-resources.json",applied)
        yield
    finally:
        for index,((kind,name),original,expected) in enumerate(zip(names,before,applied,strict=True)):
            current=cluster.get(kind,name,"-n",NAMESPACE)
            if (current["metadata"]["uid"]!=expected["metadata"]["uid"] or current["spec"]!=expected["spec"] or
                    current["metadata"].get("labels")!=expected["metadata"].get("labels") or
                    current["metadata"].get("annotations")!=expected["metadata"].get("annotations")):
                raise RuntimeError("bridge_restore_refuses_concurrent_change")
            if original is None:cluster.kubectl("delete",kind,name,"-n",NAMESPACE)
            else:
                observed=deepcopy(current)
                current["spec"]=original["spec"]
                for field in ("labels","annotations"):
                    if field in original["metadata"]:current["metadata"][field]=original["metadata"][field]
                    else:current["metadata"].pop(field,None)
                patch=resource_patch(observed,current)
                cluster.kubectl("patch",kind,name,"-n",NAMESPACE,"--type=json","--patch-file",
                    private(Path(directory)/f"bridge-restore-{index}.json",patch))
                restored=cluster.get(kind,name,"-n",NAMESPACE)
                if (restored["metadata"]["uid"]!=original["metadata"]["uid"] or restored["spec"]!=original["spec"] or
                        any(restored["metadata"].get(field)!=original["metadata"].get(field) for field in ("labels","annotations"))):
                    raise RuntimeError("bridge_restoration_readback_differs")
        private(Path(directory)/"bridge-restoration.json",dict(restored=True,resources=len(names)))


@contextmanager
def model_timeouts(cluster,directory,*,request_timeout,backend_timeout):
    """Owned model route only; keep auth, provider, model and retry policy intact."""
    from src.infra.protocol_resources import LABELS
    specs=[];applied=[]
    for kind,name in (("HTTPRoute","banking-model-responses"),("AgentgatewayPolicy","banking-model-responses-identity")):
        original=cluster.get(kind,name,"-n",NAMESPACE)
        if any(original["metadata"].get("labels",{}).get(k)!=v for k,v in LABELS.items()):raise RuntimeError("foreign_model_timeout_resource")
        changed=deepcopy(original)
        if kind=="HTTPRoute":
            if len(changed["spec"]["rules"])!=1:raise RuntimeError("unexpected_model_route_rules")
            changed["spec"]["rules"][0].setdefault("timeouts",{})["request"]=f"{request_timeout}s"
        else:changed["spec"].setdefault("backend",{}).setdefault("http",{})["requestTimeout"]=f"{backend_timeout}s"
        patch=private(Path(directory)/(kind+"-model-timeout-patch.json"),resource_patch(original,changed))
        specs.append((kind,name,original,changed,patch))
    private(Path(directory)/"model-timeouts-original.json",[s[2] for s in specs])
    for kind,name,original,changed,patch in specs:cluster.kubectl("patch",kind,name,"-n",NAMESPACE,"--type=json","--patch-file",patch,"--dry-run=server")
    try:
        for kind,name,original,changed,patch in specs:
            cluster.kubectl("patch",kind,name,"-n",NAMESPACE,"--type=json","--patch-file",patch)
            applied.append((kind,name,original,changed))
            observed=cluster.get(kind,name,"-n",NAMESPACE)
            if observed["spec"]!=changed["spec"]:raise RuntimeError("model_timeout_not_applied")
        private(Path(directory)/"model-timeouts-binding.json",dict(request_seconds=request_timeout,backend_seconds=backend_timeout))
        yield
    finally:
        for index,(kind,name,original,changed) in enumerate(reversed(applied)):
            current=cluster.get(kind,name,"-n",NAMESPACE)
            if (current["metadata"]["uid"]!=original["metadata"]["uid"] or current["spec"]!=changed["spec"] or
                    any(current["metadata"].get(k)!=original["metadata"].get(k) for k in ("labels","annotations"))):raise RuntimeError("model_timeout_restore_concurrent_change")
            patch=private(Path(directory)/f"model-timeout-restore-{index}.json",resource_patch(current,original))
            cluster.kubectl("patch",kind,name,"-n",NAMESPACE,"--type=json","--patch-file",patch)
            restored=cluster.get(kind,name,"-n",NAMESPACE)
            if restored["spec"]!=original["spec"]:raise RuntimeError("model_timeout_restore_readback_failed")
        private(Path(directory)/"model-timeouts-restored.json",dict(restored=True))


@contextmanager
def native_hook(cluster,directory,host_ip,port,*,timeout_seconds=25):
    """Restore exactly our owned modification; never overwrite concurrent edits."""
    if type(timeout_seconds) is not int or not 1<=timeout_seconds<=330:raise ValueError("invalid_native_hook_timeout")
    cm=cluster.get("configmap","atenet-egress","-n","ate-system")
    original=deepcopy(cm["data"])
    private(Path(directory)/"native-original-configmap.json",cm)
    doc=yaml.safe_load(original["envoy.yaml"])
    resources=doc["static_resources"]
    if any(c["name"]=="benchmark_native_admission" for c in resources["clusters"]):
        raise RuntimeError("native_benchmark_hook_already_installed")
    resources["clusters"].append(dict(name="benchmark_native_admission",type="STATIC",connect_timeout="2s",
        http2_protocol_options={},load_assignment=dict(cluster_name="benchmark_native_admission",endpoints=[dict(lb_endpoints=[dict(
            endpoint=dict(address=dict(socket_address=dict(address=host_ip,port_value=port))))])])))
    filter=dict(name="envoy.filters.http.ext_proc",typed_config={
        "@type":"type.googleapis.com/envoy.extensions.filters.http.ext_proc.v3.ExternalProcessor",
        "stat_prefix":"benchmark_native_admission","grpc_service":{"envoy_grpc":{"cluster_name":"benchmark_native_admission"},"timeout":f"{timeout_seconds}s"},
        "failure_mode_allow":False,"message_timeout":f"{timeout_seconds}s","processing_mode":dict(request_header_mode="SEND",response_header_mode="SKIP",
            request_body_mode="NONE",response_body_mode="NONE",request_trailer_mode="SKIP",response_trailer_mode="SKIP")})
    count=0
    for listener in resources["listeners"]:
        for chain in listener.get("filter_chains",[]):
            for network_filter in chain.get("filters",[]):
                filters=network_filter.get("typed_config",{}).get("http_filters",[])
                for index,item in enumerate(filters):
                    if item["name"]=="envoy.filters.http.ext_proc":
                        filters.insert(index+1,deepcopy(filter));count+=1;break
    if count!=3:raise RuntimeError("unexpected_native_egress_filter_topology")
    changed=dict(original,**{"envoy.yaml":yaml.safe_dump(doc,sort_keys=False)})
    revision=hashlib.sha256(changed["envoy.yaml"].encode()).hexdigest()
    def replace(data,expected):
        current=cluster.get("configmap","atenet-egress","-n","ate-system")
        if current["metadata"]["uid"]!=cm["metadata"]["uid"] or current["data"]!=expected:
            raise RuntimeError("native_config_concurrent_change_refuse_overwrite")
        current["data"]=data
        cluster.kubectl("replace","-f",private(Path(directory)/"native-current-configmap.json",current))
        patch={"spec":{"template":{"metadata":{"annotations":{"breaker.sub15/benchmark-hook":hashlib.sha256(data["envoy.yaml"].encode()).hexdigest()}}}}}
        cluster.kubectl("patch","deployment","atenet-egress","-n","ate-system","--type=merge","-p",json.dumps(patch))
        cluster.kubectl("rollout","status","deployment/atenet-egress","-n","ate-system","--timeout=180s")
    try:
        replace(changed,original)
        private(Path(directory)/"native-hook-binding.json",dict(configmap_uid=cm["metadata"]["uid"],revision=revision,filters=count,
            shared_timeout_seconds=timeout_seconds,request_body_mode="NONE",ticket_path=True))
        yield
    finally:
        current=cluster.get("configmap","atenet-egress","-n","ate-system")
        if current["data"]==changed:replace(original,changed)
        elif current["data"]!=original:raise RuntimeError("native_restore_blocked_by_concurrent_change")


@contextmanager
def gateway_forward(cluster,directory,*,admin=False):
    with socket.socket() as sock:sock.bind(("127.0.0.1",0));port=sock.getsockname()[1]
    log=(Path(directory)/"gateway-forward.log").open("w")
    process=subprocess.Popen(["kubectl","--kubeconfig",str(cluster.kubeconfig),"--context",cluster.context,
        "port-forward","-n",NAMESPACE,("deployment/" if admin else "service/")+GATEWAY,f"{port}:{15000 if admin else 8080}","--address=127.0.0.1"],env=environment(),stdout=log,stderr=subprocess.STDOUT)
    try:
        deadline=time.monotonic()+20
        while True:
            if process.poll() is not None:raise RuntimeError("gateway_forward_failed")
            try:
                with socket.create_connection(("127.0.0.1",port),timeout=0.2):break
            except OSError:
                if time.monotonic()>deadline:raise RuntimeError("gateway_forward_timeout")
        yield f"http://127.0.0.1:{port}"
    finally:
        process.terminate()
        try:process.wait(timeout=5)
        except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
        log.close()
