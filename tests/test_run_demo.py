"""Installed launcher regression tests: no host services, inference or providers."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from src.infra import run_demo as demo
from src.infra.demo_stack import Manager, System, private_json


class BorrowedSystem:
    """A healthy borrowed stack; no commands or real services."""
    def __init__(self): self.calls = []
    def check_model(self): return dict(ready=True)
    def check_artifact(self): return dict(ready=True)
    def provider_ready(self): return dict(ready=True)
    def ensure_provider(self): self.calls.append("provider")
    def containers(self): return []
    def tracking_ready(self): return True
    def wait_api(self): self.calls.append("api")
    def services(self, **kwargs): return dict(ready=True)
    def quiescent(self): pass


@pytest.fixture
def installed(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("# synthetic fixture, never real credentials\n")
    env.chmod(0o600)
    for name in demo.BINDINGS:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(dict(deadline_profile="native-measure-v2", repeatable_demo=True)))
    (tmp_path / "mlflow.db").write_text("retained fixture history")
    (tmp_path / ".infra/mlflow-artifacts").mkdir()
    machine = dict(Name="retained", Created="original", ConfigDir={"Path": "/provider"}, Rootful=True,
                   State="stopped", SSHConfig={"Port": 123})
    calls = []
    def command(self, *args, **kwargs):
        calls.append(args)
        assert args == ("podman", "machine", "inspect", "retained")
        return json.dumps([machine])
    monkeypatch.setattr(System, "command", command)
    monkeypatch.setattr(System, "owner", lambda self: dict(owned=True))
    monkeypatch.setattr(System, "check_artifact", lambda self: dict(ready=True, manifest_sha256="frozen"))
    monkeypatch.setattr(demo, "port_open", lambda port: False)
    monkeypatch.setattr("src.infra.doctor.check_tools", lambda: None)
    monkeypatch.setattr("torch.backends.mps.is_available", lambda: True)
    monkeypatch.setenv("GEMINI_API_KEY", "synthetic-not-a-provider-key")
    for key in ("MLFLOW_TRACKING_URI", "LM_STUDIO_BASE_URL", "LM_STUDIO_MODEL"):
        monkeypatch.delenv(key, raising=False)
    profile_path = tmp_path / ".infra/demo-stack/installation.json"
    roots = dict(XDG_CONFIG_HOME="/explicit/config", XDG_DATA_HOME="/explicit/data")
    profile = demo.enroll(profile_path, machine="retained", roots=roots, artifact=tmp_path / "artifact", timeout=1, root=tmp_path)
    return SimpleNamespace(root=tmp_path, profile=profile, path=profile_path, roots=roots, calls=calls,
                           config=demo.config_for(profile, tmp_path), machine=machine)


def test_enrollment_is_metadata_only_private_and_does_not_replace_profile(installed):
    assert installed.calls == [("podman", "machine", "inspect", "retained")]
    assert installed.path.stat().st_mode & 0o777 == 0o600
    assert demo.load_profile(installed.path, installed.root) == installed.profile
    before = installed.path.read_bytes()
    with pytest.raises(RuntimeError, match="already exists"):
        demo.enroll(installed.path, machine="retained", roots=installed.roots, artifact=Path("unused"), timeout=1, root=installed.root)
    assert installed.path.read_bytes() == before


def test_config_roots_are_explicit_scoped_and_restored_on_failure(monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", "/inherited/alternate")
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    intended = demo.selected_roots("user")
    assert intended["XDG_CONFIG_HOME"] == str(Path.home() / ".config")
    with pytest.raises(ValueError), demo.provider_roots(intended):
        assert os.environ["XDG_CONFIG_HOME"] == intended["XDG_CONFIG_HOME"]
        raise ValueError("fixture")
    assert os.environ["XDG_CONFIG_HOME"] == "/inherited/alternate"
    assert "XDG_DATA_HOME" not in os.environ
    assert demo.selected_roots("current")["XDG_CONFIG_HOME"] == "/inherited/alternate"


def test_preflight_collects_independent_blockers_without_starting(installed, monkeypatch):
    system = System(installed.config)
    monkeypatch.setattr(system, "check_model", lambda: (_ for _ in ()).throw(RuntimeError("Start the approved model manually.")))
    monkeypatch.setattr(system, "owner", lambda: (_ for _ in ()).throw(RuntimeError("No recorded provider connection.")))
    monkeypatch.delenv("GEMINI_API_KEY")
    monkeypatch.setattr(demo, "port_open", lambda port: port == 8091)
    errors = demo.preflight(installed.profile, installed.config, system)
    assert len(errors) == 4
    assert all(any(row.startswith(name) for row in errors) for name in ("model:", "provider:", "judge credential:", "ports:"))
    assert not any("start" in call for call in installed.calls)


@pytest.mark.parametrize("change", ["mode", "image", "storage", "classifier", "endpoint", "vm"])
def test_changed_installation_fails_before_mutation(installed, monkeypatch, change):
    system = System(installed.config)
    monkeypatch.setattr(system, "check_model", lambda: dict(ready=True))
    if change == "mode":
        (installed.root / demo.BINDINGS[1]).write_text(json.dumps(dict(deadline_profile="native-measure-v2", repeatable_demo=False)))
    elif change == "image":
        (installed.root / demo.BINDINGS[2]).write_text("replacement")
    elif change == "storage":
        database = installed.root / "mlflow.db"
        replacement = installed.root / "other.db"
        replacement.write_text("empty replacement")
        replacement.replace(database)
    elif change == "classifier":
        monkeypatch.setattr(System, "check_artifact", lambda self: dict(ready=True, manifest_sha256="different"))
    elif change == "endpoint":
        installed.profile["endpoints"]["model_base"] = "http://localhost:9999/v1"
    else:
        installed.machine["Created"] = "replacement-vm"
    assert demo.preflight(installed.profile, installed.config, system)
    assert all(call[:3] == ("podman", "machine", "inspect") for call in installed.calls)


def test_machine_identity_does_not_bind_ephemeral_ssh_port_or_state(installed):
    installed.machine.update(State="running", LastUp="new-boot")
    installed.machine["SSHConfig"]["Port"] = 9876
    assert demo.machine_identity(System(installed.config), "retained") == installed.profile["machine_identity"]


def test_private_env_and_profile_and_reviewed_version_drift(installed):
    env = installed.root / ".env"
    env.chmod(0o644)
    with pytest.raises(RuntimeError, match="chmod 600"):
        demo.private_file(env)
    assert "synthetic" not in str(demo.preflight(installed.profile, installed.config, System(installed.config)))
    profile = deepcopy(installed.profile)
    profile["versions_sha256"] = "changed"
    private_json(installed.path, profile)
    with pytest.raises(RuntimeError, match="versions changed"):
        demo.load_profile(installed.path, installed.root)


@pytest.mark.parametrize("kind", ["missing", "foreign", "unloaded", "busy", "context", "variant", "engine"])
def test_lm_studio_is_never_started_reloaded_or_downloaded(installed, monkeypatch, kind):
    system = demo.LiveSystem(installed.config)
    row = dict(identifier=installed.config.model, contextLength=8192, status="idle", queued=0,
               format="safetensors", quantization=dict(bits=4), architecture="qwen3_moe")
    if kind == "busy": row["status"] = "busy"
    if kind == "context": row["contextLength"] = 4096
    if kind == "variant": row["quantization"] = dict(bits=8)
    if kind == "foreign": row["identifier"] = "other-model"
    calls = []
    def command(*args, **kwargs):
        calls.append(args)
        assert args == ("lms", "ps", "--json")
        if kind == "missing": raise RuntimeError("secret fixture error never propagated")
        return json.dumps([] if kind == "unloaded" else [row])
    monkeypatch.setattr(system, "command", command)
    monkeypatch.setattr(system, "get_json", lambda *args: dict(data=[dict(id=installed.config.model)]))
    def software():
        if kind == "engine": raise RuntimeError("wrong engine")
        return dict(mapped_engine=demo.VERSIONS["mlx_engine"])
    monkeypatch.setattr("src.infra.serving_probe.local_serving_software", software)
    with pytest.raises(RuntimeError) as exc:
        system.check_model()
    assert "secret fixture" not in str(exc.value)
    assert all(call == ("lms", "ps", "--json") for call in calls)


def test_approved_effective_model_passes_metadata_only(installed, monkeypatch):
    system = demo.LiveSystem(installed.config)
    row = dict(identifier=installed.config.model, contextLength=8192, status="idle", queued=0,
               format="safetensors", quantization=dict(bits=4), architecture="qwen3_moe")
    monkeypatch.setattr(system, "command", lambda *a, **kw: json.dumps([row]))
    monkeypatch.setattr(system, "get_json", lambda *a: dict(data=[dict(id=installed.config.model)]))
    monkeypatch.setattr("src.infra.serving_probe.local_serving_software", lambda: dict(mapped_engine="1.14.0"))
    assert system.check_model()["inference_requests"] == 0


@pytest.mark.parametrize("change", [None, "database", "artifacts", "host", "non_cli"])
def test_borrowed_mlflow_requires_retained_storage_and_documented_cli(tmp_path, change):
    argv = ["python", "-m", "mlflow", "server", "--host", "127.0.0.1", "--port", "5001",
            "--backend-store-uri", "sqlite:///mlflow.db", "--artifacts-destination", ".infra/mlflow-artifacts"]
    if change == "database": argv[argv.index("--backend-store-uri") + 1] = "sqlite:///other.db"
    if change == "artifacts": argv[-1] = "other-artifacts"
    if change == "host": argv[argv.index("--host") + 1] = "0.0.0.0"
    if change == "non_cli": argv[2] = "other-module"
    assert demo.tracking_command_matches(argv, tmp_path, tmp_path) is (change is None)


@pytest.mark.parametrize("compatible", [True, False])
def test_tracking_identity_follows_listener_parent_without_exposing_arguments(installed, monkeypatch, compatible):
    monkeypatch.setattr(System, "tracking_ready", lambda self: True)
    system = demo.LiveSystem(installed.config)
    def command(*args, **kwargs):
        if args[0] == "lsof":
            if "-t" in args: return "123\n"
            return f"p123\nn{installed.root}\n"
        if args[:3] == ("ps", "-p", "123"):
            return "100 python -m uvicorn local-app"
        return "1 python -m mlflow server --host 127.0.0.1 --port 5001 --backend-store-uri sqlite:///" + ("mlflow.db" if compatible else "foreign.db") + " --artifacts-destination .infra/mlflow-artifacts"
    monkeypatch.setattr(system, "command", command)
    assert system.tracking_ready() is compatible


def test_ui_and_service_locks_precede_mutation_and_survive_graceful_handoff(installed, monkeypatch):
    system = BorrowedSystem()
    monkeypatch.setattr(demo, "LiveSystem", lambda config: system)
    monkeypatch.setattr(demo, "preflight", lambda *args, **kwargs: [])
    monkeypatch.setattr("src.infra.demo_stack.port_open", lambda port: False)
    observed = []
    def serve(args, *, owner_lock):
        observed.append(args)
        with pytest.raises(RuntimeError, match="Another demo-stack"):
            Manager(installed.config, system=system).start()
        with pytest.raises(RuntimeError, match="already running"):
            with demo.ui_lease(installed.root): pass
        from src.demo_ui.state import Controller
        controller = Controller({}, installed.root / ".infra/live-demo-ui", lambda *a: pytest.fail("no inference"), owner_lock=owner_lock)
        assert not controller.status()["ready"]
        controller.close()
    monkeypatch.setitem(sys.modules, "src.demo_ui.__main__", SimpleNamespace(main=serve))
    with demo.ui_lease(installed.root):
        with pytest.raises(RuntimeError, match="already running"):
            demo.launch(installed.profile, root=installed.root)
    assert not system.calls
    demo.launch(installed.profile, root=installed.root)
    assert observed == [["--artifact", str(installed.config.artifact)]]
    status = json.loads((installed.config.directory / "launcher-status.json").read_text())
    assert status["phase"] == "ui_stopped"
    assert system.calls == ["provider", "api"]


def test_preparation_is_explicit_and_failure_preserves_state(installed, monkeypatch):
    system = BorrowedSystem()
    monkeypatch.setattr(demo, "LiveSystem", lambda config: system)
    monkeypatch.setattr(demo, "preflight", lambda *a, **kw: [])
    monkeypatch.setattr("src.infra.demo_stack.port_open", lambda port: False)
    def serve(args, **kwargs):
        assert args[-1] == "--prepare"
        raise RuntimeError("synthetic preparation failure")
    monkeypatch.setitem(sys.modules, "src.demo_ui.__main__", SimpleNamespace(main=serve))
    with pytest.raises(RuntimeError, match="preparation failure"):
        demo.launch(installed.profile, root=installed.root, prepare=True)
    assert Manager(installed.config).state()["last_start"]
    assert (installed.root / "mlflow.db").read_text() == "retained fixture history"
    assert json.loads((installed.config.directory / "launcher-status.json").read_text())["phase"] == "stopped_or_failed"


def test_launcher_preflight_failure_does_not_start_or_renew_anything(installed, monkeypatch):
    system = BorrowedSystem()
    monkeypatch.setattr(demo, "LiveSystem", lambda config: system)
    monkeypatch.setattr(demo, "preflight", lambda *a, **kw: ["model: start LM Studio manually", "provider: check saved roots"])
    with pytest.raises(RuntimeError, match="nothing started") as exc:
        demo.launch(installed.profile, root=installed.root)
    assert "model:" in str(exc.value) and "provider:" in str(exc.value)
    assert system.calls == []
    assert not (installed.config.directory / "state.json").exists()


def test_active_ui_status_does_not_treat_temporary_template_or_busy_model_as_drift(installed, monkeypatch):
    assert demo.active_ui_status(installed.root) is None
    with demo.ui_lease(installed.root):
        monkeypatch.setattr(demo, "port_open", lambda port: True)
        status = demo.active_ui_status(installed.root)
        assert status["phase"] == "ui_listening" and status["demo_ready"] is None
        assert status["inference_requests"] == status["judge_requests"] == 0
    assert demo.active_ui_status(installed.root) is None


def test_shell_entry_point_checks_lock_but_never_installs(tmp_path):
    root = Path(__file__).resolve().parents[1]
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "run_demo.sh").write_bytes((root / "scripts/run_demo.sh").read_bytes())
    binary = tmp_path / "bin"
    binary.mkdir()
    uv = binary / "uv"
    uv.write_text('#!/bin/bash\nprintf "%s\\n" "$*" >> "$CALL_LOG"\n')
    uv.chmod(0o755)
    log = tmp_path / "calls"
    result = subprocess.run(["bash", str(scripts / "run_demo.sh"), "--status"], capture_output=True,
        env=dict(os.environ, PATH=f"{binary}:/usr/bin:/bin", CALL_LOG=str(log)))
    assert result.returncode == 0
    assert log.read_text().splitlines() == ["lock --check", "sync --locked --check",
        "run --locked --no-sync python -m src.infra.run_demo --status"]
