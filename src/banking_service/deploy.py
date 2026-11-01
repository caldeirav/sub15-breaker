"""Owned additive deployment and lifecycle for the local banking validation profile."""
import argparse
import base64
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import secrets
import socket
import subprocess
import tempfile
import time

import httpx

from src.infra.common import ROOT, STATE, environment, run
from src.infra.manage import Cluster

NAMESPACE = "breaker-banking"
SPACE = "breaker-banking"
STORE_HOST = "banking-store.breaker-banking.svc.cluster.local"
AUDIENCE = "breaker-banking-runtime"
DIRECTORY = STATE / "banking-service-03b"
LABELS = {"app.kubernetes.io/part-of": "sub15-breaker", "breaker.sub15/scope": "banking-03b"}
WORKER_IMAGE = "ghcr.io/agent-substrate/substrate/ateworker-gvisor@sha256:02a31963cdfb1d250d205a55fb870385b1ba5bad1be1308d556a6296f76bf145"
REGISTRY_IMAGE = "docker.io/library/registry@sha256:6c5666b861f3505b116bb9aa9b25175e71210414bd010d92035ff64018f9457e"


def private_json(name, value):
    DIRECTORY.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = DIRECTORY/name
    path.write_text(json.dumps(value, indent=2))
    path.chmod(0o600)
    return path


def obj(kind, name, spec=None, api="v1", **extra):
    return dict(apiVersion=api, kind=kind, metadata=dict(name=name, namespace=NAMESPACE, labels=dict(LABELS)),
                **({"spec": spec} if spec is not None else {}), **extra)


def require_owned_resources(cluster):
    names={"deployments":{"banking-store"},"services":{"banking-store"},"secrets":{"banking-key"},
        "configmaps":{"banking-identity"},"persistentvolumeclaims":{"banking-data"},"serviceaccounts":{"banking-driver"},
        "networkpolicies":{"banking-store"},"workerpools.ate.dev":{"banking"}}
    for kind,targets in names.items():
        for item in cluster.get(kind,"-n",NAMESPACE)["items"]:
            if item["metadata"]["name"] in targets and any(item["metadata"].get("labels",{}).get(k)!=v for k,v in LABELS.items()):
                raise RuntimeError("Refusing to overwrite an unowned banking resource")


def verify_store_rollout(deployment,pods,image):
    status=deployment.get("status",{})
    if (deployment["spec"].get("replicas")!=1 or status.get("observedGeneration")!=deployment["metadata"]["generation"] or
            any(status.get(key)!=1 for key in ("replicas","updatedReplicas","readyReplicas","availableReplicas"))):
        raise RuntimeError("Store rollout is incomplete or unobserved")
    if len(pods)!=1:raise RuntimeError("Store selector does not identify exactly one serving pod")
    pod=pods[0]
    if (pod["metadata"].get("deletionTimestamp") or not pod["metadata"].get("uid") or
            any(pod["metadata"].get("labels",{}).get(k)!=v for k,v in LABELS.items()) or
            pod.get("status",{}).get("phase")!="Running" or
            not any(c.get("type")=="Ready" and c.get("status")=="True" for c in pod["status"].get("conditions",[]))):
        raise RuntimeError("Observed store pod is not owned and ready")
    statuses=[s for s in pod["status"].get("containerStatuses",[]) if s["name"]=="store"]
    containers=[c for c in pod["spec"]["containers"] if c["name"]=="store"]
    if (len(statuses)!=1 or len(containers)!=1 or statuses[0].get("ready") is not True or
            containers[0]["image"]!=image or statuses[0].get("imageID","").split("@")[-1]!=image.split("@")[-1]):
        raise RuntimeError("Observed serving store image differs from validated image")
    return pod


class Deployment:
    def __init__(self):
        self.cluster = Cluster("breaker-substrate")
        self.cluster.ensure_owned()
        self.last_actor = None

    def ate(self, *args, operator=False, capture=True):
        argv = ["kubectl-ate", "--kubeconfig", self.cluster.kubeconfig, "--context", self.cluster.context]
        if not operator: argv += ["--token-file", DIRECTORY/"platform.token"]
        return run([*argv, *args], capture=capture, timeout=300)

    def apply(self, objects):
        path = private_json("resources.json", dict(apiVersion="v1", kind="List", items=objects))
        self.cluster.kubectl("apply", "-f", str(path))

    def refresh_credentials(self):
        """Renew scoped driver tokens without redeploying or replacing durable data."""
        self.cluster.ensure_owned()
        require_owned_resources(self.cluster)
        account = self.cluster.get("serviceaccount", "banking-driver", "-n", NAMESPACE)
        if any(account["metadata"].get("labels", {}).get(k) != v for k, v in LABELS.items()):
            raise RuntimeError("Refusing to mint credentials for an unowned banking driver")
        # Mint both before replacing either file. Tokens never enter argv/logs.
        values = {}
        for audience, filename in (("api.ate-system.svc", "platform.token"), (AUDIENCE, "runtime.token")):
            token = self.cluster.kubectl("create", "token", "banking-driver", "-n", NAMESPACE,
                f"--audience={audience}", "--duration=1h", capture=True).stdout.strip()
            if not token or len(token.split(".")) != 3:
                raise RuntimeError("TokenRequest did not return a JWT")
            values[filename] = token
        DIRECTORY.mkdir(parents=True, exist_ok=True, mode=0o700)
        for filename, token in values.items():
            with tempfile.NamedTemporaryFile(mode="w", dir=DIRECTORY, delete=False) as stream:
                pending = Path(stream.name)
                try:
                    stream.write(token)
                    stream.flush()
                    pending.chmod(0o600)
                    pending.replace(DIRECTORY/filename)
                finally:
                    pending.unlink(missing_ok=True)

    def setup(self, image):
        namespaces = self.cluster.get("namespaces")["items"]
        current = next((n for n in namespaces if n["metadata"]["name"] == NAMESPACE), None)
        if current and any(current["metadata"].get("labels", {}).get(k) != v for k,v in LABELS.items()):
            raise RuntimeError("Banking namespace is not owned; refusing adoption")
        self.apply([dict(apiVersion="v1", kind="Namespace", metadata=dict(name=NAMESPACE, labels=LABELS))])
        # Namespace ownership does not authorize overwriting unrelated named resources.
        require_owned_resources(self.cluster)
        self.apply([obj("ServiceAccount", "banking-driver", automountServiceAccountToken=False)])
        self.refresh_credentials()
        spaces = json.loads(self.ate("get", "atespaces", "-o", "json", operator=True).stdout)
        items = spaces.get("atespaces", spaces.get("items", []))
        if not any(x.get("metadata", {}).get("name") == SPACE for x in items):
            self.ate("create", "atespace", SPACE, operator=True)
            private_json("space-owner.json", dict(atespace=SPACE, cluster=self.cluster.name))
        elif not (DIRECTORY/"space-owner.json").exists():
            raise RuntimeError("Refusing to adopt an atespace without an ownership record")
        policy = private_json("access-policy.json", dict(metadata=dict(name="default"),
            bindings=[dict(role="editor", members=[f"user:system:serviceaccount:{NAMESPACE}:banking-driver"])]))
        # An existing policy is never replaced: it may contain operator-managed roles.
        listing = self.ate("get", "access-policy", "-a", SPACE, "-o", "json", operator=True)
        existing = json.loads(listing.stdout) if listing.stdout.strip() else {}
        if not existing.get("bindings"):
            self.ate("create", "access-policy", "-a", SPACE, "-f", str(policy), operator=True)
        elif existing.get("bindings") != json.loads(policy.read_text())["bindings"]:
            raise RuntimeError("Existing atespace policy differs; inspect it instead of replacing it")
        kube_discovery = json.loads(self.cluster.kubectl("get", "--raw", "/.well-known/openid-configuration", capture=True).stdout)
        driver_jwks = json.loads(self.cluster.kubectl("get", "--raw", "/openid/v1/jwks", capture=True).stdout)
        actor_jwks = json.loads(self.cluster.kubectl("get", "--raw",
            "/api/v1/namespaces/ate-system/services/https:idp:443/proxy/openid/v1/jwks", capture=True).stdout)
        identities = dict(driver=dict(issuer=kube_discovery["issuer"], audience=AUDIENCE,
            subject=f"system:serviceaccount:{NAMESPACE}:banking-driver", jwks=driver_jwks),
            actor=dict(issuer="https://idp.ate-system.svc", audience=AUDIENCE, atespace=SPACE, jwks=actor_jwks))
        private_json("identity.json", identities)  # public verification material only
        secrets_in_cluster = self.cluster.get("secrets", "-n", NAMESPACE)["items"]
        key = next((s for s in secrets_in_cluster if s["metadata"]["name"] == "banking-key"), None)
        key_object = [] if key else [obj("Secret", "banking-key", data={"key": base64.b64encode(secrets.token_bytes(32)).decode()})]
        config = obj("ConfigMap", "banking-identity", data={"identity.json": json.dumps(identities)})
        pvc = obj("PersistentVolumeClaim", "banking-data", dict(accessModes=["ReadWriteOnce"],
            storageClassName="standard", resources=dict(requests=dict(storage="1Gi"))))
        container = dict(name="store", image=image, imagePullPolicy="Never", args=["store"],
            env=[dict(name="BANKING_STORE_PATH", value="/data/state.sqlite"),
                dict(name="BANKING_KEY_FILE", value="/keys/key"), dict(name="BANKING_IDENTITY_CONFIG", value="/identity/identity.json")],
            securityContext=dict(runAsNonRoot=True, runAsUser=10001, runAsGroup=10001, allowPrivilegeEscalation=False,
                readOnlyRootFilesystem=True, capabilities=dict(drop=["ALL"])),
            resources=dict(requests=dict(cpu="100m", memory="256Mi"), limits=dict(cpu="1", memory="512Mi")),
            ports=[dict(containerPort=8080)], readinessProbe=dict(httpGet=dict(path="/health",port=8080),periodSeconds=2),
            volumeMounts=[dict(name=n,mountPath=p,readOnly=ro) for n,p,ro in
                (("data","/data",False),("keys","/keys",True),("identity","/identity",True),("tmp","/tmp",False))])
        deployment = obj("Deployment", "banking-store", dict(replicas=1, strategy=dict(type="Recreate"),
            selector=dict(matchLabels=dict(app="banking-store")), template=dict(
                metadata=dict(labels=dict(LABELS,app="banking-store"), annotations={"breaker.sub15/identity": hashlib.sha256(json.dumps(identities).encode()).hexdigest()}),
                spec=dict(automountServiceAccountToken=False, securityContext=dict(fsGroup=10001,
                    seccompProfile=dict(type="RuntimeDefault")), containers=[container], volumes=[
                        dict(name="data",persistentVolumeClaim=dict(claimName="banking-data")),
                        dict(name="keys",secret=dict(secretName="banking-key",defaultMode=288)),
                        dict(name="identity",configMap=dict(name="banking-identity")),
                        dict(name="tmp",emptyDir=dict(medium="Memory",sizeLimit="16Mi"))]))), api="apps/v1")
        network = obj("NetworkPolicy", "banking-store", {
            "podSelector": {"matchLabels": {"app": "banking-store"}},
            "policyTypes": ["Ingress", "Egress"],
            "ingress": [{"from": [{
                "namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "ate-system"}},
                "podSelector": {"matchLabels": {"app": "atenet-egress"}}}],
                "ports": [{"protocol": "TCP", "port": 8080}]}],
            "egress": []}, api="networking.k8s.io/v1")
        pool = obj("WorkerPool", "banking", dict(replicas=2, sandboxClasses=[dict(name="gvisor",configRef=dict(name="gvisor-default"))],
            workerImage=WORKER_IMAGE,template=dict(resources=dict(requests=dict(cpu="250m",memory="512Mi"),limits=dict(cpu="2",memory="2Gi")))),api="ate.dev/v1")
        # Pool metadata labels, rather than pod labels, select the Actor worker.
        pool["metadata"]["labels"]["workload"]="breaker-banking"
        self.apply([config,*key_object,pvc,deployment,network,
            obj("Service","banking-store",dict(selector=dict(app="banking-store"),ports=[dict(port=8080,targetPort=8080)])),pool])
        self.cluster.kubectl("rollout","status","deployment/banking-store","-n",NAMESPACE,"--timeout=180s")
        template_name="banking-"+hashlib.sha256((image+json.dumps(identities)).encode()).hexdigest()[:12]
        template=dict(metadata=dict(atespace=SPACE,name=template_name),workerSelector=dict(matchLabels=dict(workload="breaker-banking")),
            containers=[dict(name="banking",image=image,wakeupProbe=dict(httpGet=dict(path="/health",port=8080)),
                securityContext=dict(capabilities=dict(drop=["ALL"],add=["SETUID","SETGID"])),env=[dict(name="BANKING_STORE_URL",value=f"http://{STORE_HOST}:8080"),
                    dict(name="BANKING_IDENTITY_JSON",value=json.dumps(identities))])],
            resources=dict(limits=dict(cpuMillicores=1000,memoryBytes=536870912)),
            snapshotConfig=dict(goldenSnapshotConfig=dict(mode="GOLDEN_SNAPSHOT_MODE_DISABLED")))
        templates=json.loads(self.ate("get","actor-templates","-a",SPACE,"-o","json").stdout)
        if not any(t.get("metadata",{}).get("name")==template_name for t in templates.get("actorTemplates",templates.get("items",[]))):
            self.ate("create","actor-template","-f",str(private_json("actor-template.json",template)))
        private_json("deployment.json",dict(image=image,template=template_name,space=SPACE,namespace=NAMESPACE,
            state_durability="single-node PVC; no node/disk-loss or HA guarantee",traffic="Actor egress authenticated by injected platform JWT; local-cluster HTTP segment"))

    def verify_deployment(self,manifest):
        require_owned_resources(self.cluster)
        store=self.cluster.get("deployment","banking-store","-n",NAMESPACE)
        pods=self.cluster.get("pods","-n",NAMESPACE,"-l","app=banking-store")["items"]
        pod=verify_store_rollout(store,pods,manifest["image"])
        owners=[r for r in pod["metadata"].get("ownerReferences",[]) if r.get("kind")=="ReplicaSet" and r.get("controller") is True]
        if len(owners)!=1:raise RuntimeError("Serving store pod lacks a unique ReplicaSet owner")
        replica=self.cluster.get("replicaset",owners[0]["name"],"-n",NAMESPACE)
        if replica["metadata"]["uid"]!=owners[0]["uid"] or not any(r.get("kind")=="Deployment" and r.get("uid")==store["metadata"]["uid"] and r.get("controller") is True for r in replica["metadata"].get("ownerReferences",[])):
            raise RuntimeError("Serving store pod is not owned by the validated Deployment")
        service=self.cluster.get("service","banking-store","-n",NAMESPACE)
        if service["spec"].get("selector")!={"app":"banking-store"} or [(p["port"],p["targetPort"]) for p in service["spec"]["ports"]]!=[(8080,8080)]:
            raise RuntimeError("Store service routes outside the validated pod selector/port")
        template=json.loads(self.ate("get","actor-template",manifest["template"],"-a",SPACE,"-o","json").stdout)
        if store["spec"]["template"]["spec"]["containers"][0]["image"]!=manifest["image"] or template["containers"][0]["image"]!=manifest["image"]:
            raise RuntimeError("Observed store/Actor image differs from validated deployment")
        pool=self.cluster.get("workerpool","banking","-n",NAMESPACE)
        if pool["spec"]["workerImage"]!=WORKER_IMAGE or pool["spec"]["sandboxClasses"]!=[dict(name="gvisor",configRef=dict(name="gvisor-default"))]:
            raise RuntimeError("Observed worker runtime differs from validated deployment")

    def create_actor(self,fault_stage=None):
        self.last_actor=None
        config=json.loads((DIRECTORY/"deployment.json").read_text())
        template_name=config["template"]
        if fault_stage is not None:
            if fault_stage not in {"after_claim","after_commit"}:raise ValueError("unsupported_validation_fault")
            template_name+="-"+fault_stage.replace("_","-")
            templates=json.loads(self.ate("get","actor-templates","-a",SPACE,"-o","json").stdout)
            if not any(t.get("metadata",{}).get("name")==template_name for t in templates.get("actorTemplates",templates.get("items",[]))):
                template=json.loads((DIRECTORY/"actor-template.json").read_text())
                template["metadata"]["name"]=template_name
                template["containers"][0]["env"].append(dict(name="BANKING_VALIDATION_FAULT_STAGE",value=fault_stage))
                self.ate("create","actor-template","-f",str(private_json("fault-template.json",template)))
        name="banking-"+secrets.token_hex(6)
        self.ate("create","actor",name,"--template",template_name,"-a",SPACE)
        actor=json.loads(self.ate("get","actor",name,"-a",SPACE,"-o","json").stdout)
        private_json(f"actor-{name}.json",actor)
        self.last_actor = actor
        policy=dict(metadata=dict(name="default",atespace=SPACE),rules=[dict(http=dict(hostnames=[STORE_HOST],ports=dict(numbers=[8080]),
            effects=dict(replaceHeaders=[dict(header="Authorization",prefix="Bearer ",actorJwt=dict(audiences=[AUDIENCE],expirationSeconds=300))])))])
        self.ate("create","egress-policy",name,"-a",SPACE,"-f",str(private_json("egress-policy.json",policy)))
        self.ate("resume","actor",name,"-a",SPACE)
        return json.loads(self.ate("get","actor",name,"-a",SPACE,"-o","json").stdout)

    def delete_actor(self,name):
        path=DIRECTORY/f"actor-{name}.json"
        if not path.exists():raise RuntimeError("Refusing to delete an Actor without an owned UID record")
        old=json.loads(path.read_text())
        current=json.loads(self.ate("get","actor",name,"-a",SPACE,"-o","json").stdout)
        if old["metadata"]["uid"] != current["metadata"]["uid"]:raise RuntimeError("Actor UID changed; refusing deletion")
        self.ate("delete","actor",name,"-a",SPACE)

    @contextmanager
    def forward(self,target,remote_port=8080,actor=False):
        with socket.socket() as s:
            s.bind(("127.0.0.1",0));port=s.getsockname()[1]
        argv=(["kubectl-ate","--kubeconfig",str(self.cluster.kubeconfig),"--context",self.cluster.context,
            "--token-file",str(DIRECTORY/"platform.token"),"proxy","actor",target,f"{port}:{remote_port}","-a",SPACE]
            if actor else ["kubectl","--kubeconfig",str(self.cluster.kubeconfig),"--context",self.cluster.context,
                "port-forward","-n",NAMESPACE,target,f"{port}:{remote_port}","--address=127.0.0.1"])
        log=(DIRECTORY/f"forward-{port}.log").open("w")
        process=subprocess.Popen(argv,env=environment(),stdout=log,stderr=subprocess.STDOUT)
        try:
            deadline=time.monotonic()+30
            while True:
                if process.poll() is not None:raise RuntimeError(f"Forward failed; inspect {log.name}")
                try:
                    with httpx.Client(timeout=1,trust_env=False) as client:
                        response=client.get(f"http://127.0.0.1:{port}/health")
                        if response.status_code==200:break
                except httpx.TransportError:pass
                if time.monotonic()>=deadline:raise RuntimeError("Forward readiness deadline")
                # Bounded I/O wait rather than a fixed startup sleep.
                import select
                select.select([],[],[],0.1)
            yield f"http://127.0.0.1:{port}"
        finally:
            process.terminate()
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill();process.wait(timeout=5)
            log.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--image",help="Digest-bound image preloaded into Kind and available through its local registry")
    mode.add_argument("--refresh-credentials",action="store_true",help="Renew owned driver tokens only; preserve deployments, keys and state")
    args=parser.parse_args()
    if args.refresh_credentials:
        Deployment().refresh_credentials()
        print("Renewed scoped banking driver credentials; deployments and durable data unchanged.")
        return
    if "@sha256:" not in args.image:raise SystemExit("A digest-bound image is required")
    Deployment().setup(args.image)


if __name__=="__main__":main()
