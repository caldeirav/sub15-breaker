"""Extend the existing managed gateway; never deploy a standalone gateway.

The second listener is an authenticated, non-executing protocol fixture. The
model listener uses the existing banking driver identity and only the local
Completions provider. Fixture and actual-model routes cannot fall back to each
other. Banking MCP execution remains the application bridge's separate scope.
"""
import hashlib
from ipaddress import ip_address
import json

from src.infra.common import ROOT
from src.infra.network import pod

NAMESPACE = "breaker-enforcement"
GATEWAY = "breaker-gateway"
LABELS = {"app.kubernetes.io/part-of":"sub15-breaker", "breaker.sub15/scope":"target-protocol-v1"}
FIXTURE_AUDIENCE = "breaker-infrastructure-probe"
FIXTURE_SUBJECT = f"system:serviceaccount:{NAMESPACE}:target-protocol-client"
MODEL_AUDIENCE = "breaker-banking-runtime"
MODEL_SUBJECT = "system:serviceaccount:breaker-banking:banking-driver"


def resource(api, kind, name, spec=None, **extra):
    return dict(apiVersion=api, kind=kind, metadata=dict(name=name, namespace=NAMESPACE, labels=dict(LABELS)),
                **({"spec":spec} if spec is not None else {}), **extra)


def backend_ref(name):
    return dict(group="agentgateway.dev", kind="AgentgatewayBackend", name=name)


def manifests(*, host_ip, model, issuer, jwks, experiment_id):
    address = ip_address(host_ip)
    if address.version != 4 or not address.is_private or address.is_loopback or address.is_unspecified:
        raise ValueError("Expected the observed private Podman host-forwarding IPv4 address")
    if not str(experiment_id).isdigit() or not model or not issuer or not jwks.get("keys"):
        raise ValueError("Explicit model, issuer, public JWKS and experiment ID required")
    names = ["protocol_fixture.py", "protocol_client.py", "probe_client.py"]
    code = {name:(ROOT/"src/infra"/name).read_text() for name in names}
    code_hash = hashlib.sha256(json.dumps(code,sort_keys=True).encode()).hexdigest()
    items = [resource("v1","ConfigMap","target-protocol-code",data=code),
             resource("v1","ServiceAccount","target-protocol-client",automountServiceAccountToken=False)]
    server = pod("target-protocol-fixture",server=True)
    server["metadata"] = dict(labels=dict(LABELS, role="recorder",app="target-protocol-fixture"),
                              annotations={"breaker.dev/code-sha":code_hash})
    server["spec"]["volumes"][0]["configMap"]["name"] = "target-protocol-code"
    container = server["spec"]["containers"][0]
    container["command"] = ["python","-B","/probe/protocol_fixture.py"]
    container["readinessProbe"]["httpGet"]["path"] = "/health"
    items += [resource("apps/v1","Deployment","target-protocol-fixture",dict(replicas=1,
        selector=dict(matchLabels=dict(app="target-protocol-fixture")),template=dict(metadata=server["metadata"],spec=server["spec"]))),
        resource("v1","Service","target-protocol-fixture",dict(selector=dict(app="target-protocol-fixture"),ports=[dict(port=8080)]))]
    client = pod("target-protocol-client")
    client["metadata"] = dict(name="target-protocol-client",namespace=NAMESPACE,labels=dict(LABELS,role="client"))
    client["spec"]["volumes"][0]["configMap"]["name"] = "target-protocol-code"
    client["spec"]["securityContext"]["fsGroup"] = 65532
    client["spec"]["serviceAccountName"] = "target-protocol-client"
    client["spec"]["volumes"] += [dict(name="credentials",secret=dict(secretName="target-protocol-credentials",defaultMode=288)),
                                      dict(name="tmp",emptyDir=dict(medium="Memory",sizeLimit="16Mi"))]
    client["spec"]["containers"][0]["volumeMounts"] += [dict(name="credentials",mountPath="/credentials",readOnly=True),dict(name="tmp",mountPath="/tmp")]
    items.append(client)
    # Separate field manager owns this extra listener, not the original fixture's
    # http listener. SSA must never use force-conflicts or replace the Gateway.
    items.append(resource("gateway.networking.k8s.io/v1","Gateway",GATEWAY,dict(gatewayClassName="agentgateway",
        listeners=[dict(name="infra-protocol",protocol="HTTP",port=8081,allowedRoutes=dict(namespaces=dict(**{"from":"Same"})))])))
    for name,spec in {
        "recording-completions":dict(ai=dict(provider=dict(custom=dict(formats=[dict(type="Completions",path="/v1/chat/completions")]),
            host="target-protocol-fixture."+NAMESPACE+".svc.cluster.local",port=8080))),
        "local-banking-model":dict(ai=dict(provider=dict(custom=dict(model=model,formats=[dict(type="Completions",path="/v1/chat/completions")]),host=host_ip,port=1234))),
        "protocol-mcp":dict(mcp=dict(targets=[dict(name="fixture",static=dict(host="target-protocol-fixture."+NAMESPACE+".svc.cluster.local",port=8080,path="/mcp",protocol="StreamableHTTP"))])),
        "local-model-metadata":dict(static=dict(host=host_ip,port=1234)),
        "banking-mlflow-traces":dict(static=dict(host=host_ip,port=5001), policies=dict(auth=dict(credentials=[dict(
            location=dict(header=dict(name="x-mlflow-experiment-id")),secretRef=dict(name="target-trace-config",key="experiment-id"))]))),
    }.items():
        if "ai" in spec:
            # The Kubernetes frontend defaults to Completions independently of
            # the custom provider's upstream formats. Both sides need a mapping.
            spec.setdefault("policies",{})["ai"]={"routes":{"/v1/responses":"Responses"}}
        items.append(resource("agentgateway.dev/v1alpha1","AgentgatewayBackend",name,spec))
    routes = [
        ("protocol-responses","infra-protocol","/v1/responses","POST","recording-completions",None),
        ("protocol-mcp","infra-protocol","/mcp","POST","protocol-mcp",None),
        ("protocol-mcp-delete","infra-protocol","/mcp","DELETE","protocol-mcp",None),
        ("protocol-model-metadata","infra-protocol","/infra/model-metadata","GET","local-model-metadata","/v1/models"),
        ("banking-model-responses","http","/v1/responses","POST","local-banking-model",None),
    ]
    for name,listener,path,method,backend,rewrite in routes:
        rule = dict(matches=[dict(path=dict(type="Exact",value=path),method=method)], backendRefs=[backend_ref(backend)],
                    timeouts=dict(request="60s"))
        if rewrite:
            rule["filters"]=[dict(type="URLRewrite",urlRewrite=dict(path=dict(type="ReplaceFullPath",replaceFullPath=rewrite)))]
        items.append(resource("gateway.networking.k8s.io/v1","HTTPRoute",name,dict(parentRefs=[dict(name=GATEWAY,sectionName=listener)],rules=[rule])))
        is_model = name == "banking-model-responses"
        audience, subject = (MODEL_AUDIENCE,MODEL_SUBJECT) if is_model else (FIXTURE_AUDIENCE,FIXTURE_SUBJECT)
        items.append(resource("agentgateway.dev/v1alpha1","AgentgatewayPolicy",name+"-identity",dict(
            targetRefs=[dict(group="gateway.networking.k8s.io",kind="HTTPRoute",name=name)], traffic=dict(
                retry=dict(attempts=0), jwtAuthentication=dict(mode="Strict",providers=[dict(issuer=issuer,audiences=[audience],jwks=dict(inline=json.dumps(jwks)))]),
                authorization=dict(action="Allow",policy=dict(matchExpressions=["jwt.sub == "+json.dumps(subject)]))))))
    items.append(resource("v1","Secret","target-trace-config",type="Opaque",stringData={"experiment-id":str(experiment_id)}))
    items.append(resource("agentgateway.dev/v1alpha1","AgentgatewayPolicy","target-gateway-tracing",dict(
        targetRefs=[dict(group="gateway.networking.k8s.io",kind="Gateway",name=GATEWAY)],frontend=dict(tracing=dict(
            backendRef=backend_ref("banking-mlflow-traces"),protocol="HTTP",path="/v1/traces",randomSampling="true",clientSampling="true",
            resources=[dict(name="service.name",expression='"breaker-managed-agentgateway"')])))))
    def policy(name, selector, **rules):
        return resource("networking.k8s.io/v1","NetworkPolicy",name,dict(podSelector=dict(matchLabels=selector),**rules))
    port=[dict(protocol="TCP",port=8081)]
    items += [policy("target-protocol-client",dict(role="client"),policyTypes=["Egress"],egress=[dict(
        to=[dict(podSelector=dict(matchLabels=dict(role="gateway")))],ports=port)]),
        policy("target-protocol-ingress",dict(role="gateway"),policyTypes=["Ingress"],ingress=[dict(
            **{"from":[dict(podSelector=dict(matchLabels=dict(role="client")))]},ports=port)]),
        policy("target-gateway-host-services",dict(role="gateway"),policyTypes=["Egress"],egress=[dict(
            to=[dict(ipBlock=dict(cidr=host_ip+"/32"))],ports=[dict(protocol="TCP",port=p) for p in (1234,5001)])])]
    return dict(apiVersion="v1",kind="List",items=items)
