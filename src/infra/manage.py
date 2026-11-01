"""Create and verify a dedicated Podman/Kind infrastructure foundation."""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time

from src.infra.common import ROOT, STATE, VERSIONS, environment, run


def validate_cluster_name(name):
    if not re.fullmatch(r"breaker-[a-z0-9](?:[a-z0-9-]{0,35}[a-z0-9])?", name):
        raise ValueError("Cluster name must start with breaker- and contain only lowercase DNS-label characters")
    return name


def condition_is_current(resource, name):
    generation = resource.get("metadata", {}).get("generation")
    return any(c.get("type") == name and c.get("status") == "True"
               and (generation is None or c.get("observedGeneration") == generation)
               for c in resource.get("status", {}).get("conditions", []))


def verify_checkout(checkout):
    commit = run(["git", "rev-parse", "HEAD"], cwd=checkout, capture=True).stdout.strip()
    if commit != VERSIONS["substrate_commit"]:
        raise RuntimeError("Substrate checkout does not match the pinned release commit")
    status = run(["git", "status", "--porcelain", "--untracked-files=all", "--ignored"], cwd=checkout, capture=True).stdout.strip()
    if status:
        raise RuntimeError("Substrate checkout has modified, untracked, or ignored files; refusing to execute it")


def readiness_report(name, require_substrate, server, nodes, releases, images):
    return dict(scope="infrastructure-readiness-only" if require_substrate else "networking-controller-readiness-only",
                cluster=name, configured_pins=VERSIONS,
                checks=dict(node_readiness=True, cilium_rollout=True, gateway_controller=True,
                            certificate_api=True, substrate=require_substrate),
                skipped_checks=[] if require_substrate else ["substrate"],
                observed=dict(kubernetes_server=server, nodes=nodes, helm_releases=releases, images=images),
                timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))


class Cluster:
    def __init__(self, name):
        self.name = validate_cluster_name(name)
        self.context = f"kind-{name}"
        self.directory = STATE / "clusters" / name
        self.kubeconfig = self.directory / "kubeconfig"
        self.marker = self.directory / "owner.json"

    def kubectl(self, *args, capture=False, timeout=1200):
        return run(["kubectl", "--kubeconfig", self.kubeconfig, "--context", self.context,
                    "--request-timeout=60s", *args], capture=capture, timeout=timeout)

    def helm(self, *args):
        return run(["helm", "--kubeconfig", self.kubeconfig, "--kube-context", self.context,
                    *args], timeout=1200)

    def get(self, *args):
        return json.loads(self.kubectl("get", *args, "-o", "json", capture=True).stdout)

    def ensure_owned(self):
        if not self.marker.exists():
            raise RuntimeError("No project ownership record. Run setup; do not adopt an unrelated cluster implicitly.")
        owner = json.loads(self.marker.read_text())
        if owner.get("project") != "sub15-breaker" or owner.get("cluster") != self.name:
            raise RuntimeError("Cluster ownership record does not match")
        if not owner.get("identity"):
            raise RuntimeError("Ownership record lacks provider/container identity; explicitly recreate the development cluster")
        if owner["identity"] != self.identity():
            raise RuntimeError("Provider or Kind node identity changed; refusing to adopt or delete a replaced cluster")

    def identity(self):
        connections = json.loads(run(["podman", "system", "connection", "list", "--format", "json"], capture=True).stdout)
        provider = dict(default=[c["URI"] for c in connections if c.get("Default")],
                        host=os.getenv("CONTAINER_HOST", ""), connection=os.getenv("CONTAINER_CONNECTION", ""))
        names = run(["kind", "get", "nodes", "--name", self.name], capture=True).stdout.splitlines()
        if not names:
            raise RuntimeError("Managed cluster has no Kind node containers")
        nodes = {}
        for name in names:
            value = run(["podman", "inspect", "--format", "{{.Id}}", name], capture=True).stdout.strip()
            if not re.fullmatch(r"[a-f0-9]{64}", value):
                raise RuntimeError("Invalid provider container identity")
            nodes[name] = value
        return dict(provider_sha256=hashlib.sha256(json.dumps(provider, sort_keys=True).encode()).hexdigest(), nodes=nodes)

    def fingerprint(self):
        return hashlib.sha256((ROOT / "infra/kind.yaml").read_bytes()
                              + VERSIONS["node_image"].encode()).hexdigest()

    def create(self):
        from src.infra.doctor import check_tools, check_provider, check_hypervisor, check_podman_versions
        check_tools()
        check_hypervisor()
        check_podman_versions()
        for cmd in ("podman", "kind", "kubectl", "helm"):
            if shutil.which(cmd, path=environment()["PATH"]) is None:
                raise RuntimeError(f"Missing {cmd}; run bash scripts/install_tools.sh --with-go (install Podman separately)")
        # Fail before creating anything if the provider is stopped/unreachable.
        check_provider(json.loads(run(["podman", "info", "--format", "json"], capture=True).stdout))
        clusters = run(["kind", "get", "clusters"], capture=True).stdout.splitlines()
        if self.name in clusters:
            self.ensure_owned()
            if json.loads(self.marker.read_text()).get("fingerprint") != self.fingerprint():
                raise RuntimeError("Pinned cluster configuration changed. Explicitly destroy/recreate this owned cluster; no automatic deletion.")
        else:
            self.directory.mkdir(parents=True, exist_ok=True)
            self.directory.chmod(0o700)
            run(["kind", "create", "cluster", "--name", self.name, "--image", VERSIONS["node_image"],
                  "--config", ROOT / "infra/kind.yaml", "--kubeconfig", self.kubeconfig, "--wait", "0s"], timeout=900)
            self.marker.write_text(json.dumps(dict(project="sub15-breaker", cluster=self.name,
                fingerprint=self.fingerprint(), identity=self.identity()), indent=2) + "\n")
        config = run(["kind", "get", "kubeconfig", "--name", self.name], capture=True).stdout
        self.kubeconfig.write_text(config)
        self.kubeconfig.chmod(0o600)
        # Required by Substrate's gVisor loopback networking; only owned Kind nodes.
        nodes = run(["kind", "get", "nodes", "--name", self.name], capture=True).stdout.splitlines()
        for node in nodes:
            run(["podman", "exec", node, "sysctl", "net.ipv4.conf.all.proxy_arp=1"])

    def controllers(self):
        self.ensure_owned()
        self.helm("upgrade", "--install", "cilium", "cilium", "--repo", "https://helm.cilium.io/",
                  "--version", VERSIONS["cilium"], "--namespace", "kube-system",
                  "--values", ROOT / "infra/cilium-values.yaml", "--wait", "--timeout", "10m")
        self.kubectl("wait", "--for=condition=Ready", "nodes", "--all", "--timeout=180s")
        self.kubectl("apply", "--server-side", "-f",
                     f"https://github.com/kubernetes-sigs/gateway-api/releases/download/{VERSIONS['gateway_api']}/standard-install.yaml")
        self.helm("upgrade", "--install", "agentgateway-crds", "oci://cr.agentgateway.dev/charts/agentgateway-crds",
                  "--version", VERSIONS["agentgateway"], "--namespace", "agentgateway-system", "--create-namespace",
                  "--wait", "--timeout", "5m")
        self.helm("upgrade", "--install", "agentgateway", "oci://cr.agentgateway.dev/charts/agentgateway",
                  "--version", VERSIONS["agentgateway"], "--namespace", "agentgateway-system",
                  "--wait", "--timeout", "10m")

    def substrate(self):
        self.ensure_owned()
        if shutil.which("go", path=environment()["PATH"]) is None:
            raise RuntimeError("Substrate installation requires Go; run bash scripts/install_tools.sh --with-go")
        checkout = STATE / "substrate"
        if not checkout.exists():
            run(["git", "clone", "--depth", "1", "--branch", VERSIONS["substrate"],
                 "https://github.com/agent-substrate/substrate.git", checkout])
        verify_checkout(checkout)
        env = environment()
        env.update(KUBECONFIG=str(self.kubeconfig), KUBECTL_CONTEXT=self.context,
                   KIND_CLUSTER_NAME=self.name,
                   PATH=f"{ROOT / 'scripts/libexec'}:{env['PATH']}", GOTOOLCHAIN="local")
        run(["go", "run", "./cmd/ate-setup", "--no-dev-env", "--kind", "--context", self.context,
             "--kubeconfig", self.kubeconfig, "--image-repo", "ghcr.io/agent-substrate/substrate",
             "--image-tag", VERSIONS["substrate"], "--rollout-timeout", "10m",
             "deploy", "ate-system", "--credential-provider", '{"enabled":false}',
             "--ingress-allowed-spiffe-ids", "spiffe://cluster.local/ns/ate-system/sa/atenet-client"],
            cwd=checkout, env=env, timeout=2400)

    def verify(self, require_substrate=True):
        from src.infra.doctor import check_hypervisor, check_podman_versions
        self.ensure_owned()
        check_hypervisor()
        check_podman_versions()
        (self.directory / "readiness.json").unlink(missing_ok=True)
        self.kubectl("wait", "--for=condition=Ready", "nodes", "--all", "--timeout=180s")
        self.kubectl("rollout", "status", "daemonset/cilium", "-n", "kube-system", "--timeout=180s")
        deployments = self.get("deployments", "-n", "agentgateway-system")["items"]
        if not deployments:
            raise RuntimeError("No agentgateway controller deployment")
        for deployment in deployments:
            self.kubectl("rollout", "status", f"deployment/{deployment['metadata']['name']}",
                         "-n", "agentgateway-system", "--timeout=180s")
        gateway_class = self.get("gatewayclass", "agentgateway")
        if not condition_is_current(gateway_class, "Accepted"):
            raise RuntimeError("agentgateway GatewayClass is not Accepted at the current generation")
        for crd in ("gateways.gateway.networking.k8s.io", "httproutes.gateway.networking.k8s.io",
                    "agentgatewaypolicies.agentgateway.dev"):
            self.kubectl("wait", "--for=condition=Established", f"crd/{crd}", "--timeout=60s")
        cert_api = json.loads(self.kubectl("get", "--raw", "/apis/certificates.k8s.io/v1beta1", capture=True).stdout)
        resources = {r["name"] for r in cert_api["resources"]}
        if not {"clustertrustbundles", "podcertificaterequests"} <= resources:
            raise RuntimeError("Required certificate feature gates/runtime APIs are not enabled")
        if require_substrate:
            self.kubectl("wait", "--for=condition=Established", "crd/workerpools.ate.dev", "--timeout=60s")
            deployments = self.get("deployments", "-n", "ate-system")["items"]
            required = {"ate-api-server", "ate-controller", "ate-idp-server", "atenet-router", "atenet-egress", "rustfs"}
            if not required <= {d["metadata"]["name"] for d in deployments}:
                raise RuntimeError("Substrate local-profile deployments are missing")
            # After a provider reboot, old deployment availability can precede
            # database/certificate recovery. Check those dependencies first.
            self.kubectl("rollout", "status", "statefulset/postgres", "-n", "ate-system", "--timeout=180s")
            self.kubectl("rollout", "status", "deployment/podcertificate-controller", "-n", "podcertificate-controller-system", "--timeout=180s")
            for deployment in deployments:
                self.kubectl("rollout", "status", f"deployment/{deployment['metadata']['name']}",
                             "-n", "ate-system", "--timeout=180s")
            self.kubectl("rollout", "status", "daemonset/atelet", "-n", "ate-system", "--timeout=180s")
            self.kubectl("wait", "--for=condition=Ready", "pods", "-n", "ate-system",
                         "-l", "app=ate-api-server", "--timeout=180s")
            self.kubectl("apply", "--server-side", "--dry-run=server", "--validate=strict", "-f", ROOT / "k8s/workerpool.yaml")
            run(["kubectl-ate", "--kubeconfig", self.kubeconfig, "--context", self.context,
                 "get", "atespaces", "-o", "json"], capture=True)
        server = json.loads(self.kubectl("get", "--raw", "/version", capture=True).stdout)
        if server["gitVersion"] != VERSIONS["kubectl"]:
            raise RuntimeError("Kubernetes server version differs from the pinned profile")
        releases = json.loads(run(["helm", "--kubeconfig", self.kubeconfig, "--kube-context", self.context,
                                  "list", "--all-namespaces", "-o", "json"], capture=True).stdout)
        for name, namespace, version in (("cilium", "kube-system", VERSIONS["cilium"]),
                ("agentgateway", "agentgateway-system", VERSIONS["agentgateway"]),
                ("agentgateway-crds", "agentgateway-system", VERSIONS["agentgateway"])):
            if not any(r["name"] == name and r["namespace"] == namespace and r["status"] == "deployed"
                       and r["chart"].removeprefix(name + "-").lstrip("v") == version.lstrip("v") for r in releases):
                raise RuntimeError(f"Installed Helm release does not match pin: {namespace}/{name}")
        images = []
        namespaces = ["kube-system", "agentgateway-system"]
        if require_substrate:
            namespaces += ["ate-system", "podcertificate-controller-system"]
        for namespace in namespaces:
            for pod in self.get("pods", "-n", namespace)["items"]:
                for container in pod.get("status", {}).get("containerStatuses", []):
                    images.append(dict(namespace=namespace, pod=pod["metadata"]["name"],
                        container=container["name"], image=container["image"], imageID=container.get("imageID", "")))
        evidence = readiness_report(self.name, require_substrate, server, self.get("nodes"), releases, images)
        (self.directory / "readiness.json").write_text(json.dumps(evidence, indent=2) + "\n")
        print(f"Infrastructure readiness passed. Evidence: {self.directory / 'readiness.json'}")
        print("This does not certify gateway authorization, NetworkPolicy enforcement, Actor execution/reset, or model safety.")

    def destroy(self, confirmation):
        if confirmation != self.name:
            raise ValueError("Pass --confirm with the exact managed cluster name")
        self.ensure_owned()
        run(["kind", "delete", "cluster", "--name", self.name, "--kubeconfig", self.kubeconfig])
        print("Cluster deleted; ignored local evidence and tool downloads were retained.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("setup", "cluster", "controllers", "substrate", "verify", "network-check", "enforcement-check", "destroy"), nargs="?", default="setup")
    parser.add_argument("--cluster", default="breaker-substrate")
    parser.add_argument("--skip-substrate", action="store_true", help="Explicitly limit setup/verify to the networking foundation")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()
    try:
        cluster = Cluster(args.cluster)
        if args.command == "setup":
            cluster.create()
            cluster.controllers()
            if not args.skip_substrate:
                cluster.substrate()
            cluster.verify(require_substrate=not args.skip_substrate)
        elif args.command == "verify":
            cluster.verify(require_substrate=not args.skip_substrate)
        elif args.command == "destroy":
            cluster.destroy(args.confirm)
        elif args.command == "network-check":
            from src.infra.network import check
            check(cluster)
        elif args.command == "enforcement-check":
            from src.infra.enforcement import check
            check(cluster)
        else:
            getattr(cluster, {"cluster": "create"}.get(args.command, args.command))()
    except (RuntimeError, ValueError, OSError, subprocess.SubprocessError) as exc:
        print(f"Infrastructure failed: {exc}", file=sys.stderr)
        print("No research workload was deployed. Inspect the managed cluster and fix the failing prerequisite before proceeding.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
