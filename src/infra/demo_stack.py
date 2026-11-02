"""Manage an installed demo stack without running cases, inference or judges."""
import argparse
from contextlib import contextmanager, redirect_stderr, redirect_stdout
import base64
from dataclasses import dataclass
import fcntl
import hashlib
import importlib.metadata
import io
import json
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit
from uuid import uuid4

import httpx

from src.infra.common import ROOT, VERSIONS, environment

SCHEMA = "demo-stack-v1"
CLUSTER = "breaker-substrate"
RUNTIME_PORTS = (8172, 8173)


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def local_endpoint(value):
    url = urlsplit(value)
    require(url.scheme == "http" and url.hostname in {"127.0.0.1", "localhost"}
            and not url.username and not url.password and not url.query and not url.fragment,
            "Only credential-free local HTTP service endpoints are supported.")
    return url


def port_open(port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.3):
            return True
    except OSError:
        return False


def validate_model_backend(backend, model, host):
    from src.infra.manage import condition_is_current
    provider = backend.get("spec", {}).get("ai", {}).get("provider", {})
    require(provider.get("custom", {}).get("model") == model and provider.get("host") == host
            and provider.get("port") == 1234 and condition_is_current(backend, "Accepted"),
            "Managed model backend is missing, rejected or targets another model/host/port.")


def private_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as stream:
        pending = Path(stream.name)
        try:
            pending.chmod(0o600)
            json.dump(value, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
            pending.replace(path)
        finally:
            pending.unlink(missing_ok=True)


@dataclass(frozen=True)
class Config:
    root: Path = ROOT
    tracking: str = "http://localhost:5001"
    model_base: str = "http://localhost:1234/v1"
    model: str = VERSIONS["local_model"]
    artifact: Path = ROOT / ".infra/benchmark-guard-harness/modernbert-training-v1/model"
    review: bool = False
    review_port: int = 8090
    machine: str | None = None
    timeout: int = 180

    @property
    def directory(self):
        return self.root / ".infra/demo-stack"

    @property
    def bundle(self):
        return self.root / ".infra/benchmark-guard-harness/ready-golden-review-package"

    @property
    def read_token(self):
        return self.root / ".infra/benchmark-guard-harness/ready-golden-read.token"

    def validate(self):
        tracking = local_endpoint(self.tracking)
        require(tracking.path in {"", "/"} and tracking.port == 5001,
                "The installed gateway profile requires MLflow on local HTTP port5001 with no path.")
        model = local_endpoint(self.model_base)
        require(model.path.rstrip("/") == "/v1" and model.port == 1234,
                "The installed gateway profile requires LM_STUDIO_BASE_URL on local port1234, ending in /v1.")
        require(self.model == VERSIONS["local_model"], "Load the approved model identifier from infra/versions.json; no model substitution.")
        require(1 <= self.review_port <= 65535 and self.review_port != tracking.port,
                "Review API and MLflow need distinct valid ports.")
        require(1 <= self.timeout <= 600, "Startup timeout must be between 1 and 600 seconds.")
        if self.machine:
            require(re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,100}", self.machine), "Invalid existing Podman machine name.")


class HostProcesses:
    """Stop only a session leader with the recorded PID, start time and command."""
    def identity(self, pid):
        if type(pid) is not int or pid <= 1:
            return None
        result = subprocess.run(["ps", "-p", str(pid), "-o", "lstart=", "-o", "stat=", "-o", "command="],
                                text=True, capture_output=True, timeout=5, env=dict(os.environ, LC_ALL="C"))
        if result.returncode or not result.stdout.strip():
            return None
        # lstart is five fields; the next field is the process state.
        fields = result.stdout.strip().split(maxsplit=6)
        if len(fields) != 7 or fields[5].startswith("Z"):
            return None
        try:
            group = os.getpgid(pid)
        except ProcessLookupError:
            return None
        return dict(pid=pid, pgid=group, started=" ".join(fields[:5]),
                    command_sha256=hashlib.sha256(fields[6].encode()).hexdigest())

    def check(self, record):
        actual = self.identity(record.get("pid"))
        if actual is None:
            return False
        require(actual == {key: record[key] for key in actual} and actual["pgid"] == actual["pid"],
                "Managed process identity changed; refusing to signal or adopt a reused PID.")
        return True

    def launch(self, argv, log, root):
        log.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        env = environment()
        # These local servers do not need provider or application bearer secrets.
        env = {k: v for k, v in env.items() if not k.endswith(("_API_KEY", "_TOKEN"))}
        with log.open("x") as stream:
            log.chmod(0o600)
            child = subprocess.Popen(argv, cwd=root, env=env, stdin=subprocess.DEVNULL,
                                     stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
        record = self.identity(child.pid)
        if record is None or record["pgid"] != child.pid:
            child.terminate()
            child.wait(timeout=5)
            raise RuntimeError("Could not establish owned server process identity; inspect its private log.")
        return dict(record, log=str(log))

    def stop(self, record):
        if not self.check(record):
            return
        os.killpg(record["pgid"], signal.SIGTERM)
        deadline = time.monotonic() + 15
        while self.identity(record["pid"]) is not None:
            require(time.monotonic() < deadline, "Server did not stop gracefully; no blind SIGKILL was sent.")
            self.check(record)
            time.sleep(0.1)
        try:
            os.waitpid(record["pid"], os.WNOHANG)
        except ChildProcessError:
            pass  # A process started by an earlier CLI invocation is not our child.


class System:
    def __init__(self, config):
        self.config = config

    def command(self, *args, timeout=30):
        # Do not echo inspection payloads, raw errors, environment or credentials.
        try:
            result = subprocess.run(list(map(str, args)), cwd=self.config.root, env=environment(),
                                    text=True, capture_output=True, check=True, timeout=timeout)
        except (OSError, subprocess.SubprocessError) as exc:
            raise RuntimeError(f"{args[0]} operation failed ({type(exc).__name__}); inspect the existing service, not its secret payloads.") from None
        return result.stdout

    def get_json(self, url, *, token=None):
        headers = {"Authorization": "Bearer " + token} if token else {}
        with httpx.Client(timeout=5, trust_env=False, follow_redirects=False) as client:
            response = client.get(url, headers=headers)
            response.raise_for_status()
            return response.json()

    def check_model(self):
        rows = json.loads(self.command("lms", "ps", "--json"))
        matches = [row for row in rows if row.get("identifier") == self.config.model]
        require(len(matches) == 1 and matches[0].get("contextLength") == VERSIONS["local_model_context"],
                "Manually load the approved LM Studio model with context8192; the script never loads/reloads models.")
        require(matches[0].get("status") == "idle" and matches[0].get("queued") == 0,
                "The approved local model is busy or unobserved; no model request was issued.")
        listing = self.get_json(self.config.model_base.rstrip("/") + "/models")
        require(any(row.get("id") == self.config.model for row in listing.get("data", [])),
                "The configured LM Studio HTTP server does not list the approved model.")
        return dict(ready=True, mode="checked_only", inference_requests=0)

    def check_artifact(self):
        from src.benchmark.encoder import manifest
        from src.benchmark.guards import Calibration
        from src.benchmark.projection import POLICY_ID
        value = manifest(self.config.artifact, policy_id=POLICY_ID)
        calibration = value["calibration"]
        bound = Calibration(**{key: calibration[key] for key in (
            "model_id", "policy_id", "calibration_set_id", "temperature", "threshold", "input_version")})
        require(bound.model_id == value["model_id"] and bound.policy_id == POLICY_ID,
                "Classifier calibration does not match the verified model/policy.")
        return dict(ready=True, model_id=value["model_id"], weights_loaded=False, priming_forwards=0)

    def owner(self):
        path = self.config.root / ".infra/clusters" / CLUSTER / "owner.json"
        require(path.is_file(), "Existing owned cluster missing; follow docs/infra.md first. No installation is performed.")
        owner = json.loads(path.read_text())
        require(owner.get("project") == "sub15-breaker" and owner.get("cluster") == CLUSTER
                and owner.get("identity", {}).get("nodes"), "Invalid cluster ownership record; refusing adoption.")
        connections = json.loads(self.command("podman", "system", "connection", "list", "--format", "json"))
        provider = dict(default=[c["URI"] for c in connections if c.get("Default")],
                        host=os.getenv("CONTAINER_HOST", ""), connection=os.getenv("CONTAINER_CONNECTION", ""))
        require(hashlib.sha256(json.dumps(provider, sort_keys=True).encode()).hexdigest() == owner["identity"]["provider_sha256"],
                "Selected Podman connection differs from the recorded cluster provider.")
        return owner

    def ensure_provider(self):
        owner = self.owner()
        try:
            info = json.loads(self.command("podman", "info", "--format", "json"))
        except RuntimeError:
            require(self.config.machine is not None,
                    "Podman is unreachable. Start the existing machine manually or pass --machine EXISTING_NAME.")
            rows = json.loads(self.command("podman", "machine", "inspect", self.config.machine))
            require(len(rows) == 1 and rows[0].get("Name") == self.config.machine
                    and rows[0].get("Rootful") is True and rows[0].get("State") == "stopped",
                    "Only an explicitly named, existing stopped rootful machine may be started.")
            # Match the selected connection to this machine, not an arbitrary same-name VM.
            connections = json.loads(self.command("podman", "system", "connection", "list", "--format", "json"))
            defaults = [c for c in connections if c.get("Default")]
            require(not os.getenv("CONTAINER_HOST") and not os.getenv("CONTAINER_CONNECTION") and len(defaults) == 1
                    and defaults[0].get("IsMachine") is True
                    and defaults[0].get("Name") == self.config.machine + "-root",
                    "Explicit machine does not match the selected owned rootful connection.")
            self.command("podman", "machine", "start", self.config.machine, timeout=self.config.timeout)
            require(self.owner() == owner, "Provider identity changed after machine startup; refusing to continue.")
            info = json.loads(self.command("podman", "info", "--format", "json"))
        require(info.get("host", {}).get("cgroupVersion") == "v2"
                and info["host"].get("security", {}).get("rootless") is False,
                "The installed demo requires its reviewed rootful cgroup-v2 provider.")
        return owner

    def container(self, name):
        rows = json.loads(self.command("podman", "container", "inspect", name))
        require(len(rows) == 1, "Container identity is not unique.")
        row = rows[0]
        require(not row.get("State", {}).get("Paused") and not row.get("State", {}).get("Restarting"),
                "Container is paused/restarting; inspect it rather than overriding its state.")
        return row

    def containers(self):
        owner = self.owner()
        result = []
        for name, identifier in owner["identity"]["nodes"].items():
            row = self.container(name)
            require(row.get("Id") == identifier and row.get("Name", "").lstrip("/") == name,
                    "Owned Kind node was replaced; refusing to start/stop it.")
            result.append(row)
        registry = self.container("kind-registry")
        require(registry.get("Config", {}).get("Labels", {}).get("io.sub15-breaker.owner") == "banking-03b",
                "Missing or foreign banking registry; use the existing setup guide, not implicit adoption.")
        require(registry.get("ImageName") == self.registry_image(), "Registry image differs from the pinned banking profile.")
        return [registry, *result]

    @staticmethod
    def registry_image():
        from src.banking_service.deploy import REGISTRY_IMAGE
        return REGISTRY_IMAGE

    def wait_api(self):
        from src.infra.manage import Cluster
        cluster = Cluster(CLUSTER)
        deadline = time.monotonic() + self.config.timeout
        while True:
            try:
                with self.quiet():
                    result = cluster.kubectl("get", "--raw", "/readyz", capture=True, timeout=8)
                if result.stdout.strip() == "ok":
                    return
            except (OSError, subprocess.SubprocessError):
                pass
            require(time.monotonic() < deadline, "Existing Kubernetes API did not become ready; no cluster recreation is attempted.")
            time.sleep(0.5)

    def tracking_ready(self):
        base = self.config.tracking.rstrip("/")
        try:
            with httpx.Client(timeout=3, trust_env=False, follow_redirects=False) as client:
                health = client.get(base + "/health")
                version = client.get(base + "/version")
                return health.status_code == 200 and version.status_code == 200 and version.text.strip() == importlib.metadata.version("mlflow")
        except httpx.HTTPError:
            return False

    def review_ready(self):
        from src.benchmark.review_backend import ReviewStore
        store = ReviewStore(self.config.bundle)
        require(self.config.read_token.is_file() and not self.config.read_token.stat().st_mode & 0o077,
                "Review token missing or not private; start can create a new limited token, never a platform credential.")
        token = self.config.read_token.read_text().strip()
        base = f"http://127.0.0.1:{self.config.review_port}"
        ready = self.get_json(base + "/api/v1/readiness", token=token)
        return ready.get("bundle_verified") is True and self.get_json(base + "/api/v1/runs", token=token) == store.get("/api/v1/runs")

    @contextmanager
    def quiet(self):
        # Existing infrastructure helpers print commands. Keep --json output valid.
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            yield

    def check_driver_tokens(self):
        # Expiry is only a local freshness check; services still verify signatures.
        directory = self.config.root / ".infra/banking-service-03b"
        for name in ("platform.token", "runtime.token"):
            try:
                path = directory / name
                require(not path.stat().st_mode & 0o077, "Driver token files must be private (0600).")
                encoded = path.read_text().strip().split(".")
                require(len(encoded) == 3, "Driver credential format is invalid; use start to renew scoped credentials.")
                payload = json.loads(base64.urlsafe_b64decode(encoded[1] + "=" * (-len(encoded[1]) % 4)))
                require(type(payload.get("exp")) is int and payload["exp"] > time.time() + 60,
                        "Driver credentials are expired/near expiry; run bash scripts/demo_stack.sh start to renew them.")
            except (OSError, ValueError, IndexError):
                raise RuntimeError("Driver credentials missing/malformed; run bash scripts/demo_stack.sh start to renew them.") from None

    def services(self, *, wait=False, refresh=False):
        from src.banking_service.deploy import Deployment, DIRECTORY
        from src.infra.manage import condition_is_current
        from src.infra.protocol_resources import GATEWAY, NAMESPACE
        with self.quiet():
            deployment = Deployment()
            cluster = deployment.cluster
            manifest = json.loads((DIRECTORY / "deployment.json").read_text())
            require(manifest.get("deadline_profile") == "native-measure-v2", "Existing banking deployment needs native-measure-v2; no redeployment is performed.")
            if wait:
                for namespace, resource in (("kube-system", "daemonset/cilium"),
                        ("ate-system", "statefulset/postgres"), ("ate-system", "daemonset/atelet")):
                    cluster.kubectl("rollout", "status", resource, "-n", namespace,
                                    f"--timeout={self.config.timeout}s", timeout=self.config.timeout + 10, capture=True)
                cluster.kubectl("wait", "--for=condition=Ready", "nodes", "--all",
                                f"--timeout={self.config.timeout}s", timeout=self.config.timeout + 10, capture=True)
            else:
                nodes = cluster.get("nodes")["items"]
                require(bool(nodes) and all(any(c.get("type") == "Ready" and c.get("status") == "True"
                                               for c in n.get("status", {}).get("conditions", [])) for n in nodes),
                        "The owned Kubernetes node is not ready.")
                postgres = cluster.get("statefulset", "postgres", "-n", "ate-system")
                require(postgres.get("status", {}).get("readyReplicas", 0) >= postgres["spec"].get("replicas", 1) > 0,
                        "Substrate PostgreSQL is not ready.")
                for namespace, name in (("kube-system", "cilium"), ("ate-system", "atelet")):
                    daemon = cluster.get("daemonset", name, "-n", namespace)
                    status = daemon.get("status", {})
                    require(status.get("numberReady", 0) >= status.get("desiredNumberScheduled", 0) > 0,
                            f"Required {name} node service is not ready.")
            for namespace in ("ate-system", "agentgateway-system", "podcertificate-controller-system", "breaker-banking", NAMESPACE):
                rows = cluster.get("deployments", "-n", namespace)["items"]
                require(bool(rows), f"Missing installed services in {namespace}; follow docs/infra.md.")
                for row in rows:
                    require(row["spec"].get("replicas", 1) > 0, "A deployment is scaled to zero; restore its reviewed configuration manually.")
                    if wait:
                        cluster.kubectl("rollout", "status", "deployment/" + row["metadata"]["name"], "-n", namespace,
                                        f"--timeout={self.config.timeout}s", timeout=self.config.timeout + 10, capture=True)
                    else:
                        require(row.get("status", {}).get("observedGeneration") == row["metadata"].get("generation")
                                and row.get("status", {}).get("availableReplicas", 0) >= row["spec"].get("replicas", 1),
                                f"Services in {namespace} are not ready.")
            if refresh:
                deployment.refresh_credentials()
            self.check_driver_tokens()
            deployment.verify_deployment(manifest)
            require(cluster.get("persistentvolumeclaim", "banking-data", "-n", "breaker-banking")["status"]["phase"] == "Bound",
                    "Retained banking PVC is not bound; no storage replacement is performed.")
            profile = json.loads((self.config.root / ".infra/target-stack/profile.json").read_text())
            gateway = cluster.get("gateway", GATEWAY, "-n", NAMESPACE)
            require(gateway["metadata"]["uid"] == profile["gateway_uid"]
                    and all(condition_is_current(gateway, key) for key in ("Accepted", "Programmed")),
                    "Installed managed gateway identity/readiness differs from its profile.")
            backend = cluster.get("agentgatewaybackend", "local-banking-model", "-n", NAMESPACE)
            validate_model_backend(backend, self.config.model, profile["host_ip"])
            traces = cluster.get("agentgatewaybackend", "banking-mlflow-traces", "-n", NAMESPACE)
            require(traces["spec"]["static"] == dict(host=profile["host_ip"], port=5001),
                    "Gateway trace export does not target the configured local tracking service.")
            route = cluster.get("httproute", "banking-model-responses", "-n", NAMESPACE)
            require(any(p.get("name") == GATEWAY and p.get("sectionName") == "http" for p in route["spec"]["parentRefs"]),
                    "Model route does not target the expected shared gateway.")
            require(any(all(condition_is_current(dict(metadata=route["metadata"], status=parent), key)
                                for key in ("Accepted", "ResolvedRefs")) for parent in route.get("status", {}).get("parents", [])),
                    "Managed model route has not been accepted/resolved.")
        return dict(ready=True, scope="installed_services_only", credentials="renewed" if refresh else "checked",
                    per_run_bridge="created_by_demo", native_hook="installed_by_demo", classifier="deferred_until_authorized_demo")

    def quiescent(self):
        require(not any(port_open(port) for port in RUNTIME_PORTS), "A per-run bridge/native listener is active; stop the demo normally before stopping services.")
        from src.banking_service.deploy import Deployment
        with self.quiet():
            deployment = Deployment()
            actors = json.loads(deployment.ate("get", "actors", "-a", "breaker-banking", "-o", "json", operator=True).stdout)
            require(not actors.get("actors", actors.get("items", [])), "Banking Actors still exist; refusing to interrupt active or unresolved work.")
            code = ('import os,sqlite3; '
                    'db=sqlite3.connect("file:"+os.environ["BANKING_STORE_PATH"]+"?mode=ro",uri=True); '
                    'db.execute("PRAGMA query_only=ON"); '
                    'print(db.execute("SELECT count(*) FROM actions WHERE status IN (\'prepared\',\'executing\')").fetchone()[0])')
            pending = deployment.cluster.kubectl("exec", "-n", "breaker-banking", "deployment/banking-store", "--", "python", "-c", code, capture=True, timeout=20).stdout
            require(pending.strip() == "0", "Prepared/executing banking actions remain; reconcile them before shutdown.")


class Manager:
    def __init__(self, config, *, system=None, processes=None):
        config.validate()
        self.config = config
        self.system = system or System(config)
        self.processes = processes or HostProcesses()
        self.path = config.directory / "state.json"

    def state(self):
        if not self.path.exists():
            return dict(schema_version=SCHEMA, root=str(self.config.root.resolve()), processes={}, containers={})
        require(not self.path.is_symlink() and self.path.stat().st_uid == os.getuid()
                and not self.path.stat().st_mode & 0o077, "Lifecycle state must be a private file owned by this user.")
        value = json.loads(self.path.read_text())
        require(value.get("schema_version") == SCHEMA and value.get("root") == str(self.config.root.resolve()),
                "Lifecycle state belongs to another checkout/schema; refusing adoption.")
        require(isinstance(value.get("processes"), dict) and set(value["processes"]) <= {"mlflow", "review-api"}
                and isinstance(value.get("containers"), dict), "Lifecycle state contains unexpected resource types.")
        return value

    @contextmanager
    def locked(self):
        require(not self.config.directory.is_symlink(), "Refusing a symlinked lifecycle directory.")
        self.config.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        require(self.config.directory.stat().st_uid == os.getuid() and not self.config.directory.stat().st_mode & 0o077,
                "Lifecycle directory must be private and owned by this user.")
        path = self.config.directory / "lock"
        require(not path.is_symlink(), "Refusing a symlinked lifecycle lock.")
        with path.open("a") as stream:
            path.chmod(0o600)
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError("Another demo-stack start/stop is running.") from None
            yield

    def save(self, value):
        private_json(self.path, value)

    def server(self, name, port, ready, argv, state):
        record = state["processes"].get(name)
        if record:
            alive = self.processes.check(record)
            require(record.get("endpoint_port") == port, "Managed service configuration changed; stop it using its existing configuration first.")
        else:
            alive = False
        if ready():
            require(record is None or alive,
                    "Recorded server leader is gone but its endpoint is occupied; inspect it before restarting or adopting it.")
            return "managed" if alive else "pre_existing"
        require(not alive and not port_open(port), f"{name} is unhealthy or its port is occupied; no unrelated process will be replaced.")
        log = self.config.directory / "logs" / f"{name}-{uuid4().hex}.log"
        record = dict(self.processes.launch(argv, log, self.config.root), endpoint_port=port)
        state["processes"][name] = record
        try:
            self.save(state)
        except BaseException:
            self.processes.stop(record)
            raise
        deadline = time.monotonic() + self.config.timeout
        while not ready():
            require(self.processes.check(record), f"{name} exited; inspect its private lifecycle log.")
            require(time.monotonic() < deadline, f"{name} startup timed out; owned process retained for inspection/stop.")
            time.sleep(0.2)
        return "started"

    def start(self):
        with self.locked():
            state = self.state()
            # Catch missing model/artifact before starting anything else.
            self.system.check_model()
            self.system.check_artifact()
            if self.config.review:
                from src.benchmark.review_backend import ReviewStore
                ReviewStore(self.config.bundle)
            self.system.ensure_provider()
            rows = self.system.containers()  # Verify ALL IDs before starting any node.
            for row in rows:
                name = row["Name"].lstrip("/")
                previous = state["containers"].get(name)
                if previous:
                    require(previous["id"] == row["Id"], "Managed container was replaced; refusing adoption.")
                    if row["State"]["Running"]:
                        require(previous.get("started_at") == row["State"].get("StartedAt"),
                                "Container restarted outside this manager; inspect its ownership before continuing.")
                if not row["State"]["Running"]:
                    state["containers"][name] = dict(id=row["Id"], status="starting")
                    self.save(state)
                    self.system.command("podman", "start", row["Id"], timeout=self.config.timeout)
                    current = self.system.container(row["Id"])
                    require(current["State"]["Running"], "Owned container did not start.")
                    state["containers"][name] = dict(id=row["Id"], status="running", started_at=current["State"]["StartedAt"])
                    self.save(state)
            tracking_port = local_endpoint(self.config.tracking).port
            if not self.system.tracking_ready():
                require((self.config.root / "mlflow.db").is_file(), "Existing mlflow.db missing; refusing to create a new empty tracking store.")
                require((self.config.root / ".infra/mlflow-artifacts").is_dir(),
                        "Existing .infra/mlflow-artifacts missing; refusing to serve a new empty artifact history.")
            tracking = self.server("mlflow", tracking_port, self.system.tracking_ready,
                [sys.executable, "-m", "mlflow", "server", "--host", "127.0.0.1", "--port", str(tracking_port),
                 "--backend-store-uri", "sqlite:///" + str((self.config.root / "mlflow.db").resolve()),
                 "--artifacts-destination", str(self.config.root / ".infra/mlflow-artifacts")], state)
            self.system.wait_api()
            self.system.services(wait=True, refresh=True)
            if self.config.review:
                # Only generate the separate limited replay token, never model/platform secrets.
                if not self.config.read_token.exists():
                    import secrets
                    fd = os.open(self.config.read_token, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                    with os.fdopen(fd, "w") as stream:
                        stream.write(secrets.token_urlsafe(32))
                self.server("review-api", self.config.review_port, lambda: self.safe_review(),
                    [sys.executable, "-m", "src.benchmark.review_backend", "--serve", str(self.config.bundle),
                     "--port", str(self.config.review_port), "--token-file", str(self.config.read_token)], state)
            state["last_start"] = dict(tracking=tracking, review_requested=self.config.review)
            self.save(state)
        return self.status()

    def safe_review(self):
        try:
            return self.system.review_ready()
        except (OSError, ValueError, RuntimeError, httpx.HTTPError):
            return False

    def status(self):
        rows = {}
        def check(name, function):
            try:
                value = function()
                require(value is not False, f"{name} is unavailable or incompatible.")
                rows[name] = dict(ready=True, detail=value)
            except Exception as exc:
                rows[name] = dict(ready=False, error_type=type(exc).__name__, message=str(exc) if isinstance(exc, RuntimeError) else "Read-only check failed; inspect local configuration/service.")
        check("model", self.system.check_model)
        check("artifact", self.system.check_artifact)
        check("containers", lambda: self.running_containers())
        check("mlflow", self.system.tracking_ready)
        check("cluster_services", self.system.services)
        check("lifecycle", self.lifecycle_ready)
        if self.config.review:
            check("review_api", self.system.review_ready)
        return dict(schema_version=SCHEMA, ready=all(row["ready"] for row in rows.values()), services=rows,
                    inference_requests=0, banking_tools_executed=0, judge_requests=0,
                    demo_started=False, classifier_primed=False, scope="service_prerequisites_not_demo_qualification")

    def lifecycle_ready(self):
        state = self.state()
        for name, record in state["processes"].items():
            require(self.processes.check(record), f"Managed {name} exited; inspect its log and use start to recover only if its port is free.")
        return dict(ready=True, managed_processes=sorted(state["processes"]),
                    managed_containers=sorted(state["containers"]), shared_vm="never_stopped", model="check_only")

    def running_containers(self):
        rows = self.system.containers()
        require(all(row["State"]["Running"] for row in rows), "Owned registry/Kind containers are stopped.")
        return dict(ready=True, count=len(rows))

    def stop(self):
        with self.locked():
            state = self.state()
            if not state["processes"] and not state["containers"]:
                return dict(stopped=True, message="Nothing was started by this manager; pre-existing/shared services preserved.")
            self.system.quiescent()  # Before signaling ANY server or stopping a node.
            verified = {}
            for name, record in state["processes"].items():
                self.processes.check(record)  # Validate all PID identities before changes.
            owned = {row["Name"].lstrip("/"): row for row in self.system.containers()}
            for name, record in state["containers"].items():
                require(name in owned, "Managed container no longer belongs to the installed stack.")
                row = owned[name]
                require(row["Id"] == record["id"], "Owned container ID changed; refusing shutdown.")
                if row["State"]["Running"]:
                    require(record.get("status") == "running" and row["State"].get("StartedAt") == record.get("started_at"),
                            "Container startup ownership is ambiguous or changed; refusing shutdown.")
                    verified[name] = row
            for name in ("review-api", "mlflow"):
                if name in state["processes"]:
                    self.processes.stop(state["processes"][name])
                    require(not port_open(state["processes"][name]["endpoint_port"]),
                            "Server leader exited but the endpoint remains occupied; ownership retained for inspection.")
                    del state["processes"][name]
                    self.save(state)
            # Nodes before registry. Never stop the shared Podman VM or LM Studio.
            for name in sorted(state["containers"], key=lambda name: name == "kind-registry"):
                if name in verified:
                    self.system.command("podman", "stop", "--time", "60", state["containers"][name]["id"], timeout=75)
                del state["containers"][name]
                self.save(state)
            return dict(stopped=True, message="Only manager-started processes/containers stopped; data, shared services, Podman VM and model preserved.")


def main():
    from dotenv import load_dotenv
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("start", "stop", "status"))
    parser.add_argument("--json", action="store_true", help="Machine-readable status; nonzero when not ready")
    parser.add_argument("--with-review-api", action="store_true", help="Also serve/check the existing saved-replay bundle")
    parser.add_argument("--machine", help="Explicit existing Podman VM to start only if the provider is stopped; never stopped by this script")
    parser.add_argument("--artifact", type=Path, default=Config.artifact)
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()
    load_dotenv(ROOT / ".env")
    try:
        config = Config(tracking=os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5001"),
                        model_base=os.getenv("LM_STUDIO_BASE_URL", "http://localhost:1234/v1"),
                        model=os.getenv("LM_STUDIO_MODEL", VERSIONS["local_model"]), artifact=args.artifact.resolve(),
                        review=args.with_review_api, machine=args.machine, timeout=args.timeout)
        manager = Manager(config)
        result = getattr(manager, args.command)()
        if args.json:
            print(json.dumps(result, indent=2))
        elif args.command == "stop":
            print(result["message"])
        else:
            print("Demo service prerequisites: " + ("ready" if result["ready"] else "not ready"))
            for name, row in result["services"].items():
                print(f"  {name}: " + ("ready" if row["ready"] else row["message"]))
            print("No demo, model inference, classifier priming or judges were run.")
            print("LM Studio/model are check-only; per-run bridge/native gate/classifier belong to the demo.")
        return 0 if result.get("ready", result.get("stopped", False)) else 1
    except Exception as exc:
        message = str(exc) if isinstance(exc, RuntimeError) else f"{type(exc).__name__}: check installed prerequisites and private lifecycle logs."
        print(json.dumps(dict(ready=False, error=message, demo_started=False, inference_requests=0)))
        return 1


if __name__ == "__main__":
    sys.exit(main())
