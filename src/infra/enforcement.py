"""Exercise a real gateway against non-executing signed-receipt fixtures."""
import base64
import hashlib
import json
import secrets
import time

from src.infra.common import ROOT, VERSIONS
from src.infra.network import pod

NAMESPACE = "breaker-enforcement"


def manifests():
    def obj(api, kind, name, spec):
        return dict(apiVersion=api, kind=kind, metadata=dict(name=name, namespace=NAMESPACE), spec=spec)

    items = [dict(apiVersion="v1", kind="Namespace", metadata=dict(name=NAMESPACE,
        labels={"app.kubernetes.io/part-of": "sub15-breaker", "pod-security.kubernetes.io/enforce": "restricted"}))]
    code = {name: (ROOT / "src/infra" / name).read_text() for name in ("auth_fixture.py", "http_probe.py", "probe_client.py")}
    items.append(dict(apiVersion="v1", kind="ConfigMap", metadata=dict(name="probe-code", namespace=NAMESPACE), data=code))
    code_hash = hashlib.sha256(json.dumps(code, sort_keys=True).encode()).hexdigest()
    for role in ("authorizer", "recorder"):
        template = pod(f"fixture-{role}", server=True)
        template["metadata"]["labels"] = {"role": role}
        template["metadata"]["annotations"] = {"breaker.dev/code-sha": code_hash}
        container = template["spec"]["containers"][0]
        container["command"] = ["python", "-B", "/probe/auth_fixture.py"]
        container["env"] = [dict(name="FIXTURE_ROLE", value=role)]
        container["envFrom"] = [dict(secretRef=dict(name="fixture-credentials"))]
        container["readinessProbe"]["httpGet"]["path"] = "/health"
        items.append(obj("apps/v1", "Deployment", f"fixture-{role}", dict(
            replicas=1, selector=dict(matchLabels=dict(role=role)), template=dict(
                metadata={k: template["metadata"][k] for k in ("labels", "annotations")}, spec=template["spec"]))))
        items.append(obj("v1", "Service", f"fixture-{role}", dict(selector=dict(role=role), ports=[dict(port=8080)])))
    client = pod("client")
    client["metadata"]["namespace"] = NAMESPACE
    client["spec"]["containers"][0]["env"] = [dict(name="FIXTURE_TOKEN", valueFrom=dict(secretKeyRef=dict(name="fixture-credentials", key="FIXTURE_TOKEN")))]
    items.append(client)
    gateway_template = dict(
        metadata=dict(labels=dict(role="gateway")),
        spec=dict(automountServiceAccountToken=False,
            securityContext=dict(runAsNonRoot=True, runAsUser=65532, runAsGroup=65532, seccompProfile=dict(type="RuntimeDefault")),
            containers=[dict(name="agentgateway", securityContext=dict(allowPrivilegeEscalation=False,
                readOnlyRootFilesystem=True, capabilities=dict(drop=["ALL"])),
                resources=dict(requests=dict(cpu="50m", memory="64Mi"), limits=dict(cpu="1", memory="256Mi")))]))
    items.append(obj("agentgateway.dev/v1alpha1", "AgentgatewayParameters", "internal", dict(
        service=dict(spec=dict(type="ClusterIP")), deployment=dict(spec=dict(template=gateway_template)))))
    items.append(obj("gateway.networking.k8s.io/v1", "Gateway", "breaker-gateway", dict(
        gatewayClassName="agentgateway", infrastructure=dict(parametersRef=dict(group="agentgateway.dev", kind="AgentgatewayParameters", name="internal")),
        listeners=[dict(name="http", protocol="HTTP", port=8080)])))
    items.append(obj("gateway.networking.k8s.io/v1", "HTTPRoute", "execute", dict(
        parentRefs=[dict(name="breaker-gateway")], rules=[dict(
            matches=[dict(path=dict(type="Exact", value="/execute"), method="POST")],
            backendRefs=[dict(name="fixture-recorder", port=8080)])])))
    items.append(obj("agentgateway.dev/v1alpha1", "AgentgatewayPolicy", "authorize", dict(
        targetRefs=[dict(group="gateway.networking.k8s.io", kind="HTTPRoute", name="execute")],
        traffic=dict(extAuth=dict(failureMode="FailClosed", backendRef=dict(name="fixture-authorizer", port=8080),
            forwardBody=dict(maxSize="16Ki"), http=dict(path='"/authorize"',
                allowedRequestHeaders=["content-type", "authorization", "x-breaker-grant"], allowedResponseHeaders=["x-breaker-grant"]))))))
    def policy(name, selector, **rules):
        return obj("networking.k8s.io/v1", "NetworkPolicy", name, dict(podSelector=dict(matchLabels=selector), **rules))
    items.append(policy("default-deny", {}, policyTypes=["Ingress", "Egress"]))
    items.append(policy("dns", {}, policyTypes=["Egress"], egress=[dict(to=[dict(
        namespaceSelector=dict(matchLabels={"kubernetes.io/metadata.name": "kube-system"}),
        podSelector=dict(matchLabels={"k8s-app": "kube-dns"}))], ports=[dict(protocol=p, port=53) for p in ("UDP", "TCP")])]))
    port = [dict(protocol="TCP", port=8080)]
    for role, allowed in (("gateway", "client"), ("authorizer", "gateway"), ("recorder", "gateway")):
        items.append(policy(f"{role}-ingress", dict(role=role), policyTypes=["Ingress"],
            ingress=[dict(**{"from": [dict(podSelector=dict(matchLabels=dict(role=allowed)))]}, ports=port)]))
    items.append(policy("client-egress", dict(role="client"), policyTypes=["Egress"],
        egress=[dict(to=[dict(podSelector=dict(matchLabels=dict(role="gateway")))], ports=port)]))
    items.append(policy("gateway-egress", dict(role="gateway"), policyTypes=["Egress"],
        egress=[dict(to=[dict(podSelector=dict(matchExpressions=[dict(key="role", operator="In", values=["authorizer", "recorder"])]))], ports=port),
                dict(to=[dict(namespaceSelector=dict(matchLabels={"kubernetes.io/metadata.name": "agentgateway-system"}),
                              podSelector=dict(matchLabels={"app.kubernetes.io/name": "agentgateway"}))],
                     ports=[dict(protocol="TCP", port=9978)])]))
    return dict(apiVersion="v1", kind="List", items=items)


def wait_gateway(cluster):
    from src.infra.manage import condition_is_current
    cluster.kubectl("wait", "--for=condition=Programmed", "gateway/breaker-gateway", "-n", NAMESPACE, "--timeout=240s")
    # Programmed means the controller accepted config, not that XDS reached the proxy.
    cluster.kubectl("rollout", "status", "deployment/breaker-gateway", "-n", NAMESPACE, "--timeout=240s")
    route = cluster.get("httproute", "execute", "-n", NAMESPACE)
    if not any(all(condition_is_current(dict(metadata=route["metadata"], status=parent), cond)
                   for cond in ("Accepted", "ResolvedRefs")) for parent in route.get("status", {}).get("parents", [])):
        raise RuntimeError("Fixture route is not Accepted/ResolvedRefs at its current generation")
    policy = cluster.get("agentgatewaypolicy", "authorize", "-n", NAMESPACE)
    if not any(condition_is_current(dict(metadata=policy["metadata"], status=ancestor), "Accepted")
               for ancestor in policy.get("status", {}).get("ancestors", [])):
        raise RuntimeError("Fixture authorization policy is not Accepted at its current generation")


def check(cluster):
    cluster.ensure_owned()
    report_path = cluster.directory / "enforcement-check.json"
    report_path.unlink(missing_ok=True)
    existing = cluster.kubectl("get", "namespace", NAMESPACE, "--ignore-not-found", "-o", "json", capture=True).stdout
    if existing and json.loads(existing)["metadata"].get("labels", {}).get("app.kubernetes.io/part-of") != "sub15-breaker":
        raise RuntimeError("Refusing to adopt an unrelated fixture namespace")
    path = cluster.directory / "enforcement-probes.json"
    # Create the namespace before its namespaced Secret/workloads.
    bundle = manifests()
    namespace_path = cluster.directory / "enforcement-namespace.json"
    namespace_path.write_text(json.dumps(bundle["items"][0]))
    cluster.kubectl("apply", "-f", namespace_path)
    credentials = cluster.directory / "fixture-credentials.json"
    if not credentials.exists():
        credentials.write_text(json.dumps(dict(apiVersion="v1", kind="Secret",
            metadata=dict(name="fixture-credentials", namespace=NAMESPACE), type="Opaque",
            stringData=dict(FIXTURE_TOKEN=secrets.token_urlsafe(32), FIXTURE_SIGNING_KEY=secrets.token_urlsafe(32)))))
        credentials.chmod(0o600)
    cluster.kubectl("apply", "-f", credentials)
    path.write_text(json.dumps(bundle, indent=2))
    cluster.kubectl("apply", "--server-side", "-f", path)
    for name in ("fixture-authorizer", "fixture-recorder"):
        cluster.kubectl("rollout", "status", f"deployment/{name}", "-n", NAMESPACE, "--timeout=240s")
    cluster.kubectl("wait", "--for=condition=Ready", "pod/client", "-n", NAMESPACE, "--timeout=180s")
    wait_gateway(cluster)
    recorder_pod = cluster.get("pods", "-n", NAMESPACE, "-l", "role=recorder")["items"][0]["metadata"]["name"]
    def records():
        output = cluster.kubectl("exec", "-n", NAMESPACE, recorder_pod, "--", "python", "-B", "-c",
            "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8080/records').read().decode())", capture=True).stdout
        return json.loads(output)["records"]
    gateway = cluster.get("service", "breaker-gateway", "-n", NAMESPACE)["spec"]["clusterIP"]
    def send(body, auth="valid", method="POST", content_type="application/json", spoof=""):
        output = cluster.kubectl("exec", "-n", NAMESPACE, "client", "--", "python", "-B", "/probe/http_probe.py",
            f"http://{gateway}:8080/execute", base64.b64encode(body).decode(), auth, method, content_type, spoof, capture=True).stdout
        return json.loads(output)
    results = []
    cases = [
        ("allow", b'{"command":"fixture:allow"}', "valid", "POST", "application/json", "", True),
        ("unicode", json.dumps(dict(command="fixture:allow:\u03bb\u4e16\u754c"), ensure_ascii=False).encode(), "valid", "POST", "application/json", "", True),
        ("deny", b'{"command":"fixture:deny"}', "valid", "POST", "application/json", "", False),
        ("unauthed", b'{"command":"fixture:allow"}', "none", "POST", "application/json", "", False),
        ("bad-token", b'{"command":"fixture:allow"}', "invalid", "POST", "application/json", "", False),
        ("error", b'{"command":"fixture:error"}', "valid", "POST", "application/json", "", False),
        ("extra-field", b'{"command":"fixture:allow","extra":1}', "valid", "POST", "application/json", "", False),
        ("duplicate-key", b'{"command":"fixture:deny","command":"fixture:allow"}', "valid", "POST", "application/json", "", False),
        ("bad-json", b'{broken', "valid", "POST", "application/json", "", False),
        ("wrong-method", b'{"command":"fixture:allow"}', "valid", "GET", "application/json", "", False),
        ("wrong-content-type", b'{"command":"fixture:allow"}', "valid", "POST", "text/plain", "", False),
        ("oversize", json.dumps(dict(command="fixture:allow:" + "a" * 20000)).encode(), "valid", "POST", "application/json", "", False),
        ("unicode-byte-limit", json.dumps(dict(command="fixture:allow:" + "\u4e16" * 6000), ensure_ascii=False).encode(), "valid", "POST", "application/json", "", False),
        ("character-limit", json.dumps(dict(command="fixture:allow:" + "a" * 8200)).encode(), "valid", "POST", "application/json", "", False),
        ("forged-grant-denial", b'{"command":"fixture:deny"}', "valid", "POST", "application/json", "spoof", False),
        ("forged-grant-approval", b'{"command":"fixture:allow"}', "valid", "POST", "application/json", "spoof", False),
    ]
    try:
        for name, body, auth, method, content_type, spoof, allowed in cases:
            before = len(records())
            result = send(body, auth, method, content_type, spoof)
            after = records()
            passed = (result["status"] == 200 if allowed else result["status"] >= 400) and len(after) == before + int(allowed)
            if allowed:
                passed = passed and after[-1]["digest"] == hashlib.sha256(body).hexdigest()
            results.append(dict(case=name, status=result["status"], records_added=len(after)-before, passed=passed))
            if not passed:
                raise RuntimeError(f"Gateway fixture case failed: {name}: {result}")
        # Direct Service and Pod-IP bypass attempts must time out, not reach the recorder.
        for destination in (cluster.get("service", "fixture-recorder", "-n", NAMESPACE)["spec"]["clusterIP"],
                            cluster.get("pod", recorder_pod, "-n", NAMESPACE)["status"]["podIP"]):
            output = cluster.kubectl("exec", "-n", NAMESPACE, "client", "--", "python", "-B",
                "/probe/probe_client.py", destination, "8080", capture=True).stdout
            result = json.loads(output)
            results.append(dict(case="direct-recorder-bypass", passed=not result["reachable"]))
            if result["reachable"]:
                raise RuntimeError("Direct recorder bypass is reachable")
        authorizers = cluster.get("pods", "-n", NAMESPACE, "-l", "role=authorizer")["items"]
        before = len(records())
        try:
            cluster.kubectl("scale", "deployment/fixture-authorizer", "-n", NAMESPACE, "--replicas=0")
            for item in authorizers:
                cluster.kubectl("wait", "--for=delete", "pod/" + item["metadata"]["name"], "-n", NAMESPACE, "--timeout=180s")
            result = send(b'{"command":"fixture:allow"}')
            passed = result["status"] >= 400 and len(records()) == before
            results.append(dict(case="authorizer-unavailable", status=result["status"], passed=passed))
            if not passed:
                raise RuntimeError("Unavailable authorizer did not fail closed")
        finally:
            cluster.kubectl("scale", "deployment/fixture-authorizer", "-n", NAMESPACE, "--replicas=1")
            cluster.kubectl("rollout", "status", "deployment/fixture-authorizer", "-n", NAMESPACE, "--timeout=180s")
        result = send(b'{"command":"fixture:allow:recovered"}')
        passed = result["status"] == 200 and len(records()) == before + 1
        results.append(dict(case="authorizer-recovered", status=result["status"], passed=passed))
        if not passed:
            raise RuntimeError("Authorizer recovery positive control failed")
    finally:
        report_path.write_text(json.dumps(dict(scope="non-executing-gateway-fixture-only", cluster=cluster.name,
            passed=len(results) == len(cases) + 4 and all(r["passed"] for r in results), cases=results,
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())), indent=2))
    print(f"Gateway fixture enforcement passed. Evidence: {report_path}")
    print("No shell commands executed. This is not a Substrate Actor isolation or trained-model validation result.")
