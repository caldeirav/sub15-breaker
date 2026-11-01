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


def configure_bridge(cluster,directory,host_ip,port,*,request_timeout=60):
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
    for item in objects:
        raw=cluster.kubectl("get",item["kind"],item["metadata"]["name"],"-n",NAMESPACE,"--ignore-not-found","-o","json",capture=True).stdout
        if raw and any(json.loads(raw)["metadata"].get("labels",{}).get(k)!=v for k,v in SCOPE.items()):
            raise RuntimeError("refusing_foreign_benchmark_resource")
    path=private(Path(directory)/"gateway-bridge.json",dict(apiVersion="v1",kind="List",items=objects))
    cluster.kubectl("apply","--dry-run=server","--validate=strict","-f",path)
    cluster.kubectl("apply","-f",path)


@contextmanager
def native_hook(cluster,directory,host_ip,port):
    """Restore exactly our owned modification; never overwrite concurrent edits."""
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
        "stat_prefix":"benchmark_native_admission","grpc_service":{"envoy_grpc":{"cluster_name":"benchmark_native_admission"},"timeout":"25s"},
        "failure_mode_allow":False,"message_timeout":"25s","processing_mode":dict(request_header_mode="SEND",response_header_mode="SKIP",
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
            shared_timeout_seconds=25,request_body_mode="NONE",ticket_path=True))
        yield
    finally:
        current=cluster.get("configmap","atenet-egress","-n","ate-system")
        if current["data"]==changed:replace(original,changed)
        elif current["data"]!=original:raise RuntimeError("native_restore_blocked_by_concurrent_change")


@contextmanager
def gateway_forward(cluster,directory):
    with socket.socket() as sock:sock.bind(("127.0.0.1",0));port=sock.getsockname()[1]
    log=(Path(directory)/"gateway-forward.log").open("w")
    process=subprocess.Popen(["kubectl","--kubeconfig",str(cluster.kubeconfig),"--context",cluster.context,
        "port-forward","-n",NAMESPACE,"service/"+GATEWAY,f"{port}:8080","--address=127.0.0.1"],env=environment(),stdout=log,stderr=subprocess.STDOUT)
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
