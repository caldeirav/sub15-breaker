"""Positive/negative controls prove NetworkPolicy is enforced, not just accepted."""
import json
import time

from src.infra.common import ROOT, VERSIONS

NAMESPACE = "breaker-netcheck"
OWNER = "sub15-breaker"


def resource(kind, name, spec):
    version = "networking.k8s.io/v1" if kind == "NetworkPolicy" else "v1"
    return dict(apiVersion=version, kind=kind,
                metadata=dict(name=name, namespace=NAMESPACE, labels={"app.kubernetes.io/part-of": OWNER}), spec=spec)


def pod(name, server=False):
    code = ("from http.server import HTTPServer,SimpleHTTPRequestHandler; "
            "HTTPServer(('0.0.0.0',8080),SimpleHTTPRequestHandler).serve_forever()" if server
            else "import threading; threading.Event().wait()")
    result = resource("Pod", name, dict(
        automountServiceAccountToken=False, restartPolicy="Always",
        securityContext=dict(runAsNonRoot=True, runAsUser=65532, runAsGroup=65532,
                             seccompProfile=dict(type="RuntimeDefault")),
        containers=[dict(name="probe", image=VERSIONS["probe_image"], command=["python", "-B", "-c", code],
                         securityContext=dict(allowPrivilegeEscalation=False, readOnlyRootFilesystem=True,
                                              capabilities=dict(drop=["ALL"])),
                         resources=dict(requests=dict(cpu="10m", memory="32Mi"), limits=dict(cpu="100m", memory="64Mi")),
                         volumeMounts=[dict(name="code", mountPath="/probe", readOnly=True)],
                         **(dict(readinessProbe=dict(httpGet=dict(path="/", port=8080), initialDelaySeconds=1)) if server else {}))],
        volumes=[dict(name="code", configMap=dict(name="probe-code"))]))
    result["metadata"]["labels"]["role"] = name
    return result


def policy(name, selector, **rules):
    return resource("NetworkPolicy", name, dict(podSelector=dict(matchLabels=selector), **rules))


def manifests():
    namespace = dict(apiVersion="v1", kind="Namespace", metadata=dict(name=NAMESPACE,
        labels={"app.kubernetes.io/part-of": OWNER, "pod-security.kubernetes.io/enforce": "restricted"}))
    config = dict(apiVersion="v1", kind="ConfigMap", metadata=dict(name="probe-code", namespace=NAMESPACE),
                  data={"probe_client.py": (ROOT / "src/infra/probe_client.py").read_text()})
    items = [namespace, config, policy("default-deny", {}, policyTypes=["Ingress", "Egress"])]
    items.extend(pod(name, server=name in ("target", "control")) for name in ("target", "control", "trusted", "untrusted"))
    port = [dict(protocol="TCP", port=8080)]
    items.extend([
        policy("target-ingress", {"role": "target"}, policyTypes=["Ingress"],
               ingress=[dict(**{"from": [dict(podSelector=dict(matchLabels={"role": "trusted"}))]}, ports=port)]),
        policy("control-ingress", {"role": "control"}, policyTypes=["Ingress"],
               ingress=[dict(**{"from": [dict(podSelector={})]}, ports=port)]),
        policy("trusted-egress", {"role": "trusted"}, policyTypes=["Egress"],
               egress=[dict(to=[dict(podSelector=dict(matchLabels={"role": "target"}))], ports=port)]),
        policy("untrusted-egress", {"role": "untrusted"}, policyTypes=["Egress"],
               egress=[dict(to=[dict(podSelector=dict(matchExpressions=[dict(key="role", operator="In", values=["target", "control"])]))], ports=port)]),
    ])
    return dict(apiVersion="v1", kind="List", items=items)


def check(cluster):
    cluster.ensure_owned()
    (cluster.directory / "network-check.json").unlink(missing_ok=True)
    # Never overwrite a namespace belonging to a different local project.
    existing = cluster.kubectl("get", "namespace", NAMESPACE, "--ignore-not-found", "-o", "json", capture=True).stdout
    if existing and json.loads(existing)["metadata"].get("labels", {}).get("app.kubernetes.io/part-of") != OWNER:
        raise RuntimeError(f"Refusing to adopt namespace {NAMESPACE}")
    path = cluster.directory / "network-probes.json"
    path.write_text(json.dumps(manifests(), indent=2) + "\n")
    cluster.kubectl("apply", "-f", path)
    cluster.kubectl("wait", "--for=condition=Ready", "pods", "--all", "-n", NAMESPACE, "--timeout=240s")
    ips = {item["metadata"]["name"]: item["status"]["podIP"] for item in cluster.get("pods", "-n", NAMESPACE)["items"]}
    results = []
    # Positives before AND after negatives ensure a dead server cannot pass a deny test.
    checks = [("trusted", "target", True), ("untrusted", "control", True),
              ("untrusted", "target", False), ("trusted", "control", False),
              ("trusted", "target", True), ("untrusted", "control", True)]
    try:
        for source, destination, expected in checks:
            response = cluster.kubectl("exec", "-n", NAMESPACE, source, "--", "python", "-B",
                                       "/probe/probe_client.py", ips[destination], "8080", capture=True, timeout=30)
            result = json.loads(response.stdout)
            result.update(source=source, destination=destination, expected=expected)
            results.append(result)
            if result["reachable"] != expected:
                raise RuntimeError(f"NetworkPolicy enforcement failed: {source} -> {destination}, expected reachable={expected}")
    finally:
        report = dict(scope="network-policy-controls-only", cluster=cluster.name,
                      timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                      passed=len(results) == len(checks) and all(r["reachable"] == r["expected"] for r in results), checks=results)
        (cluster.directory / "network-check.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f"NetworkPolicy ingress/egress controls passed. Evidence: {cluster.directory / 'network-check.json'}")
    print(f"Benign pods remain in {NAMESPACE} for independent manual inspection; no shell payload was executed.")
