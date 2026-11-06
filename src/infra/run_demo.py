"""Reboot launcher for an explicitly enrolled installation; LM Studio is check-only."""
import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import sys

from src.infra.common import ROOT, VERSIONS
from src.infra.demo_stack import Config, Manager, System, boot_id, port_open, private_json, require, operator_lease as ui_lease

SCHEMA = "live-demo-installation-v1"
BINDINGS = (
    ".infra/clusters/breaker-substrate/owner.json",
    ".infra/banking-service-03b/deployment.json",
    ".infra/banking-service-03b/image.reference",
    ".infra/target-stack/profile.json",
)
XDG = ("XDG_CONFIG_HOME", "XDG_DATA_HOME")


def private_file(path):
    require(path.is_file() and not path.is_symlink() and path.stat().st_uid == os.getuid()
            and not path.stat().st_mode & 0o077,
            f"{path.name} must be an owned private regular file (chmod 600); contents were not printed.")


def private_directory(path):
    require(not path.is_symlink(), "Refusing a symlinked demo directory.")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    require(path.stat().st_uid == os.getuid() and not path.stat().st_mode & 0o077,
            "Demo directory must be private (0700) and owned by this user.")


@contextmanager
def provider_roots(roots):
    """Explicit, process-local policy for stack tools/children, never shell/global config."""
    require(set(roots) == set(XDG) and all(isinstance(v, str) and Path(v).is_absolute() for v in roots.values()),
            "Invalid saved provider configuration roots; re-enroll explicitly.")
    previous = {key: os.environ.get(key) for key in XDG}
    try:
        os.environ.update(roots)
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def selected_roots(policy):
    defaults = dict(XDG_CONFIG_HOME=str(Path.home() / ".config"), XDG_DATA_HOME=str(Path.home() / ".local/share"))
    return {key: str(Path(os.getenv(key, default) if policy == "current" else default).expanduser().resolve())
            for key, default in defaults.items()}


def sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def installation(config):
    """Bind metadata/artifacts and storage identity, not mutable database contents."""
    result = {}
    for name in BINDINGS:
        path = config.root / name
        require(path.is_file() and not path.is_symlink(), f"Missing retained {name}; follow docs/infra.md, no installer is run.")
        result[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    deployment = json.loads((config.root / BINDINGS[1]).read_text())
    require(deployment.get("deadline_profile") == "native-measure-v2" and deployment.get("repeatable_demo") is True,
            "Retained banking deployment needs native-measure-v2 and repeatable-demo; follow the one-time upgrade guide.")
    database = config.root / "mlflow.db"
    require(database.is_file() and not database.is_symlink(), "Retained mlflow.db missing; no empty database is created.")
    artifacts = config.root / ".infra/mlflow-artifacts"
    require(artifacts.is_dir() and not artifacts.is_symlink(), "Retained MLflow artifact directory missing.")
    result["tracking_storage"] = {name: dict(device=path.stat().st_dev, inode=path.stat().st_ino)
                                  for name, path in (("database", database), ("artifacts", artifacts))}
    result["classifier"] = System(config).check_artifact()
    return result


def machine_identity(system, name):
    rows = json.loads(system.command("podman", "machine", "inspect", name))
    require(len(rows) == 1 and rows[0].get("Name") == name and rows[0].get("Rootful") is True,
            "The saved machine must exist and be rootful. Do not create or replace a VM during startup.")
    row = rows[0]
    # SSH ports, socket paths and LastUp can legitimately change across reboot.
    return {key: row[key] for key in ("Name", "Created", "ConfigDir", "Rootful")}


def tracking_command_matches(argv, cwd, root):
    """Conservative support for the documented MLflow CLI, not arbitrary servers."""
    def option(name):
        if name not in argv or argv.index(name) + 1 >= len(argv):
            return ""
        return argv[argv.index(name) + 1]
    backend = option("--backend-store-uri")
    artifacts = option("--artifacts-destination")
    if ("server" not in argv or not any(Path(arg).name == "mlflow" for arg in argv)
            or not backend.startswith("sqlite:///") or not artifacts
            or option("--host") not in {"localhost", "127.0.0.1"} or option("--port") != "5001"):
        return False
    return ((cwd / backend[len("sqlite:///"):]).resolve() == (root / "mlflow.db").resolve()
            and (cwd / artifacts).resolve() == (root / ".infra/mlflow-artifacts").resolve())


class LiveSystem(System):
    def tracking_ready(self):
        if not super().tracking_ready():
            return False
        # /health and /version alone do not establish the retained DB/artifacts.
        # Follow listener ancestry to the documented CLI, without printing argv.
        try:
            listeners = self.command("lsof", "-nP", "-iTCP:5001", "-sTCP:LISTEN", "-t").split()
            require(bool(listeners) and all(pid.isdigit() for pid in listeners), "MLflow listener identity unavailable.")
            for listener in set(listeners):
                pid = listener
                matched = False
                for _ in range(8):
                    row = self.command("ps", "-p", pid, "-o", "ppid=", "-o", "command=", timeout=5).strip().split(None, 1)
                    if len(row) != 2:
                        break
                    cwd_rows = self.command("lsof", "-a", "-p", pid, "-d", "cwd", "-Fn", timeout=5).splitlines()
                    directories = [Path(line[1:]) for line in cwd_rows if line.startswith("n/")]
                    if len(directories) == 1 and tracking_command_matches(shlex.split(row[1]), directories[0], self.config.root):
                        matched = True
                        break
                    pid = row[0]
                    if not pid.isdigit() or int(pid) <= 1:
                        break
                if not matched:
                    return False
            return True
        except Exception:
            return False  # Healthy but unproven server is not silently borrowed.

    def check_model(self):
        try:
            result = super().check_model()
        except Exception:
            raise RuntimeError("LM Studio/model unavailable, busy or incompatible. Start LM Studio/server on port1234 and load the approved Qwen MLX4-bit/context8192; the launcher never starts or changes it.") from None
        rows = json.loads(self.command("lms", "ps", "--json"))
        model = next(row for row in rows if row.get("identifier") == self.config.model)
        require(model.get("format") == "safetensors" and model.get("quantization", {}).get("bits") == 4
                and model.get("architecture") == "qwen3_moe" and not model.get("engineConfigFileEnabled"),
                "Loaded model must be the approved Qwen MLX4-bit variant without an engine config file.")
        from src.infra.serving_probe import local_serving_software
        try:
            software = local_serving_software()
        except Exception:
            raise RuntimeError(f"LM Studio effective app/MLX runtime differs from infra/versions.json or cannot be observed. Require app {VERSIONS['lm_studio']}, mapped MLX {VERSIONS['mlx_engine']}; select/reload manually, never automatically.") from None
        return dict(result, software=software)

    def ensure_provider(self):
        owner = super().ensure_provider()
        from src.infra.doctor import check_hypervisor, check_podman_versions, check_provider
        with self.quiet():
            check_podman_versions()
            check_hypervisor()
            check_provider(json.loads(self.command("podman", "info", "--format", "json")))
        return owner

    def services(self, *, wait=False, refresh=False):
        deployment = json.loads((self.config.root / BINDINGS[1]).read_text())
        require(deployment.get("repeatable_demo") is True, "Repeatable demo mode required; use the one-time store upgrade, not a reset.")
        result = super().services(wait=wait, refresh=refresh)
        from src.banking_service.deploy import Deployment
        from src.infra.manage import Cluster
        from src.infra.target_stack import current_bindings
        profile = json.loads((self.config.root / ".infra/target-stack/profile.json").read_text())
        host = self.command("podman", "exec", "breaker-substrate-control-plane", "getent", "hosts", "host.containers.internal").split()[0]
        require(host == profile["host_ip"],
                "Host-forwarding address changed after restart. Stop the UI and review target_stack --configure before re-enrollment; no routes rewritten automatically.")
        with self.quiet():
            # Verify a real serving path after controller observations, not just
            # a possibly stale pre-reboot rollout condition. GET only, no tools.
            with Deployment().forward("deployment/banking-store") as endpoint:
                require(self.get_json(endpoint + "/health").get("ready") is True,
                        "Banking store health unavailable after restart; inspect retained pod events.")
            current_bindings(Cluster("breaker-substrate"), profile)
        return result


def config_for(profile, root=ROOT):
    return Config(root=root, tracking=os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5001"),
                  model_base=os.getenv("LM_STUDIO_BASE_URL", "http://localhost:1234/v1"),
                  model=os.getenv("LM_STUDIO_MODEL", VERSIONS["local_model"]),
                  artifact=Path(profile["artifact"]), machine=profile["machine"], timeout=profile["timeout"])


def enroll(path, *, machine, roots, artifact, timeout, root=ROOT):
    require(not path.exists() and not path.is_symlink(), "Installation profile already exists; inspect it rather than silently replacing approval.")
    private_file(root / ".env")
    config = config_for(dict(machine=machine, artifact=str(artifact.resolve()), timeout=timeout), root)
    config.validate()
    with provider_roots(roots):
        system = System(config)
        system.owner()  # Includes the exact selected provider fingerprint.
        identity = machine_identity(system, machine)
        bindings = installation(config)
    private_directory(path.parent)
    value = dict(schema_version=SCHEMA, root=str(root.resolve()), provider_roots=roots,
                 machine=machine, machine_identity=identity, artifact=str(config.artifact), timeout=timeout,
                 versions_sha256=sha(VERSIONS), bindings=bindings,
                 endpoints=dict(tracking=config.tracking, model_base=config.model_base, model=config.model),
                 policy=dict(start_existing_machine=True, lm_studio="check_only", downloads=False, installs=False))
    private_json(path, value)
    return value


def load_profile(path, root=ROOT):
    require(path.exists(), "Installation profile missing. Follow docs/demo.md, then bash scripts/run_demo.sh --setup --provider-config user (verification only).")
    private_file(path)
    value = json.loads(path.read_text())
    require(value.get("schema_version") == SCHEMA and value.get("root") == str(root.resolve()),
            "Installation profile belongs to another checkout/schema.")
    require(value.get("versions_sha256") == sha(VERSIONS),
            "Reviewed versions changed since enrollment; review the changes and explicitly re-enroll, no automatic upgrade.")
    require(value.get("policy") == dict(start_existing_machine=True, lm_studio="check_only", downloads=False, installs=False),
            "Unsupported saved startup policy.")
    return value


def preflight(profile, config, system, *, check_ports=True):
    """Independent blockers are collected before any VM/container/process mutation."""
    errors = []
    def check(name, function):
        try:
            function()
        except Exception as exc:
            message = str(exc) if isinstance(exc, RuntimeError) else f"{type(exc).__name__}; check local configuration (no payload printed)."
            errors.append(f"{name}: {message}")
    check("env", lambda: private_file(config.root / ".env"))
    check("assets/storage", lambda: require(installation(config) == profile["bindings"],
          "Enrolled metadata/artifacts/storage changed; review and re-enroll explicitly, never reset data."))
    check("endpoints", lambda: require(profile["endpoints"] == dict(tracking=config.tracking, model_base=config.model_base, model=config.model),
          "Effective endpoints differ from the saved profile; preserve .env and review configuration."))
    check("provider", system.owner)
    check("machine", lambda: require(machine_identity(system, config.machine) == profile["machine_identity"],
          "Recorded VM identity changed; refusing replacement/adoption."))
    check("model", system.check_model)
    check("tracking port", lambda: require(not port_open(5001) or system.tracking_ready(),
          "Port5001 is occupied by MLflow with incompatible/unhealthy/unproven storage. Use the documented loopback CLI with the retained mlflow.db and .infra/mlflow-artifacts; no server is replaced."))
    def mps():
        import torch
        require(torch.backends.mps.is_available(), "MPS unavailable; use the reviewed Apple Silicon/PyTorch environment.")
    check("classifier backend", mps)
    check("judge credential", lambda: require(bool(os.getenv("GEMINI_API_KEY")),
          "Set authorized GEMINI_API_KEY in private .env. Live UI review is pinned to gemini:/gemini-2.5-flash; no paid validation call was sent."))
    def tools():
        from src.infra.doctor import check_tools
        with system.quiet():
            check_tools()
    check("tools", tools)
    check("disk", lambda: require(shutil.disk_usage(config.root).free >= 2 * 1024**3,
          "Less than 2 GiB host disk free; free space without deleting demo history."))
    if check_ports:
        check("ports", lambda: require(not any(port_open(port) for port in (8091, 8172, 8173)),
              "UI/bridge/native port8091/8172/8173 occupied; stop the existing UI normally before startup."))
    return errors


def active_ui_status(root=ROOT):
    """Do not misdiagnose temporary, UI-owned templates or busy inference as drift."""
    path = root / ".infra/live-demo-ui/operator.lock"
    if not path.exists():
        return None
    require(not path.is_symlink() and path.stat().st_uid == os.getuid(), "UI lock must be an owned regular file.")
    with path.open("r") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            listening = port_open(8091)
            return dict(schema_version=SCHEMA, phase="ui_listening" if listening else "startup_or_cleanup",
                        ui_listening=listening, demo_ready=None,
                        message="UI owns the session. See its preparation panel for Demo ready; independent service checks deferred until cleanup.",
                        inference_requests=0, banking_tools_executed=0, judge_requests=0,
                        scope="read_only_active_ui_observation_not_demo_qualification")
    return None


def launch(profile, *, prepare=False, root=ROOT):
    config = config_for(profile, root)
    config.validate()
    manager = Manager(config, system=LiveSystem(config), progress=lambda phase: print(f"  {phase}", flush=True))
    # Acquire BOTH locks before checking/mutating shared dependencies. The UI takes
    # over the same operator lease, so a direct UI launch cannot slip into the gap.
    with manager.locked(), ui_lease(root) as lease:
        errors = preflight(profile, config, manager.system)
        require(not errors, "Startup blocked (nothing started):\n  " + "\n  ".join(errors))
        progress = config.directory / "launcher-status.json"
        private_json(progress, dict(phase="starting_services", boot_id=boot_id()))
        print("Starting retained VM/registry/Kind/services; renewing scoped credentials. LM Studio is check-only.", flush=True)
        try:
            result = manager.start_locked()
            require(result["ready"], "Service prerequisites not ready; run scripts/run_demo.sh --status for diagnostics.")
            manager.system.quiescent()
            private_json(progress, dict(phase="services_ready", inference_requests=0, judge_requests=0))
            print("Services ready (not Demo ready). UI: http://127.0.0.1:8091", flush=True)
            print(f"Private logs: {config.directory / 'logs'}; UI evidence/token: {root / '.infra/live-demo-ui'}", flush=True)
            if not prepare:
                print("No-inference startup: preparation waits for the first explicit Run click.", flush=True)
            from src.demo_ui.__main__ import main as serve_ui
            args = ["--artifact", str(config.artifact)] + (["--prepare"] if prepare else [])
            serve_ui(args, owner_lock=lease)
        except BaseException:
            private_json(progress, dict(phase="stopped_or_failed", diagnostic="Inspect retained service logs and UI evidence; no automatic replay or rollback."))
            raise
        else:
            private_json(progress, dict(phase="ui_stopped", services="retained", cleanup="UI returned after graceful close"))
        finally:
            print("Services retained. After UI cleanup, use bash scripts/demo_stack.sh stop to stop only manager-owned services; VM/LM Studio/data remain.", flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--setup", action="store_true", help="Verify/enroll the installed stack only; no installation or service start")
    mode.add_argument("--status", action="store_true", help="Read-only profile and service checks; zero inference")
    parser.add_argument("--prepare", action="store_true", help="Explicit local inference/native preparation before serving; no card or Gemini")
    parser.add_argument("--profile", type=Path, default=ROOT / ".infra/demo-stack/installation.json")
    parser.add_argument("--machine", default="podman-machine-default", help="Existing VM approved for startup during enrollment")
    parser.add_argument("--provider-config", choices=("current", "user"), default="current", help="Enrollment only: capture current XDG roots, or explicitly choose ~/.config and ~/.local/share")
    parser.add_argument("--artifact", type=Path, default=Config.artifact)
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args(argv)
    if args.prepare and (args.setup or args.status):
        parser.error("--prepare is only valid when launching the UI")
    # Must precede MLflow/LiteLLM/runtime imports; no remote pricing fetches.
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
    try:
        if args.setup:
            with Manager(Config()).locked(), ui_lease(ROOT):
                enroll(args.profile, machine=args.machine, roots=selected_roots(args.provider_config),
                       artifact=args.artifact, timeout=args.timeout)
            print(f"Installed profile enrolled: {args.profile}. No services/inference started. Next: bash scripts/run_demo.sh")
            return 0
        profile = load_profile(args.profile)
        with provider_roots(profile["provider_roots"]):
            if args.status:
                active = active_ui_status()
                if active is not None:
                    print(json.dumps(active, indent=2))
                    return 0
                config = config_for(profile)
                manager = Manager(config, system=LiveSystem(config))
                errors = preflight(profile, config, manager.system, check_ports=False)
                result = manager.status()
                result.update(phase="service_ready_not_demo_ready" if result["ready"] and not errors else "blocked",
                              installation_errors=errors, ui_listening=port_open(8091), lm_studio_policy="check_only")
                print(json.dumps(result, indent=2))
                return 0 if result["ready"] and not errors else 1
            launch(profile, prepare=args.prepare)
        return 0
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        message = str(exc) if isinstance(exc, RuntimeError) else f"{type(exc).__name__}; inspect local configuration and private logs (payload omitted)."
        print(f"Demo launcher: {message}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
