"""Lifecycle tests never operate the real provider, model, tracking or ledger."""
from copy import deepcopy
from dataclasses import replace
import base64
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from src.infra.demo_stack import Config, HostProcesses, Manager, System, canonical_boot, local_endpoint, operator_lease, private_json, validate_model_backend


class FakeSystem:
    def __init__(self):
        self.calls = []
        self.tracking = True
        self.replay = False
        self.model_ok = self.artifact_ok = True
        self.active = False
        self.rows = {
            "kind-registry": dict(Name="kind-registry", Id="a" * 64, State=dict(Running=True, StartedAt="original-registry")),
            "breaker-substrate-control-plane": dict(Name="breaker-substrate-control-plane", Id="b" * 64, State=dict(Running=True, StartedAt="original-node")),
        }

    def check_model(self):
        if not self.model_ok:
            raise RuntimeError("Manually start the approved local model.")
        return dict(ready=True, inference_requests=0)

    def check_artifact(self):
        if not self.artifact_ok:
            raise RuntimeError("Missing compatible classifier artifact.")
        return dict(ready=True, weights_loaded=False)

    def ensure_provider(self):
        self.calls.append("provider-check")

    def owner(self):
        return dict(project="sub15-breaker")

    def provider_ready(self):
        return dict(ready=True)

    def containers(self):
        return deepcopy(list(self.rows.values()))

    def container(self, name):
        return deepcopy(next(row for row in self.rows.values() if name in {row["Name"], row["Id"]}))

    def command(self, *args, **kwargs):
        assert args[0] == "podman" and args[1] in {"start", "stop"}
        self.calls.append(args)
        row = next(row for row in self.rows.values() if row["Id"] == args[-1])
        row["State"]["Running"] = args[1] == "start"
        if args[1] == "start":
            row["State"]["StartedAt"] = "manager-start"

    def wait_api(self):
        self.calls.append("api-readiness")

    def services(self, *, wait=False, refresh=False):
        self.calls.append(("services", wait, refresh))
        return dict(ready=True, credentials="renewed" if refresh else "checked")

    def tracking_ready(self):
        return self.tracking

    def review_ready(self):
        return self.replay

    def quiescent(self):
        if self.active:
            raise RuntimeError("Active demo work; refusing shutdown.")


class FakeProcesses:
    def __init__(self, system):
        self.system = system
        self.live = {}
        self.launched = []
        self.stopped = []

    def check(self, record):
        actual = self.live.get(record["pid"])
        if actual is None:
            return False
        if {k: v for k, v in actual.items() if k != "boot_id"} != {k: v for k, v in record.items() if k != "boot_id"}:
            raise RuntimeError("PID reused; refusing to signal.")
        return True

    def launch(self, argv, log, root):
        pid = 1000 + len(self.launched)
        record = dict(pid=pid, pgid=pid, started="fixed", command_sha256="c" * 64, log=str(log))
        self.launched.append(argv)
        self.live[pid] = dict(record, endpoint_port=int(argv[argv.index("--port") + 1]))
        if "mlflow" in argv:
            self.system.tracking = True
        else:
            self.system.replay = True
        return record

    def stop(self, record):
        if not self.check(record):
            return
        self.stopped.append(record["pid"])
        del self.live[record["pid"]]


@pytest.fixture
def stack(tmp_path, monkeypatch):
    monkeypatch.setattr("src.infra.demo_stack.port_open", lambda port: False)
    (tmp_path / "mlflow.db").touch()
    (tmp_path / ".infra/mlflow-artifacts").mkdir(parents=True)
    config = Config(root=tmp_path, artifact=tmp_path / "artifact", timeout=1)
    system = FakeSystem()
    processes = FakeProcesses(system)
    return Manager(config, system=system, processes=processes), system, processes


def test_start_borrows_existing_services_and_stop_does_not_take_them_down(stack):
    manager, system, processes = stack
    assert manager.start()["ready"]
    assert manager.start()["ready"]
    assert manager.state()["processes"] == manager.state()["containers"] == {}
    assert not processes.launched
    assert manager.stop()["stopped"] and not processes.stopped
    assert not any(isinstance(call, tuple) and call[0] == "podman" for call in system.calls)


def test_resume_and_stop_only_recorded_containers_not_shared_provider_or_model(stack):
    manager, system, processes = stack
    system.rows["kind-registry"]["State"]["Running"] = False
    system.rows["breaker-substrate-control-plane"]["State"]["Running"] = False
    system.tracking = False
    assert manager.start()["ready"]
    starts = list(system.calls)
    assert manager.start()["ready"]
    assert len(processes.launched) == 1
    assert [c for c in system.calls if isinstance(c, tuple) and c[0] == "podman"] == [c for c in starts if isinstance(c, tuple) and c[0] == "podman"]
    assert manager.path.stat().st_mode & 0o777 == 0o600
    assert manager.stop()["stopped"]
    stops = [c for c in system.calls if isinstance(c, tuple) and c[:2] == ("podman", "stop")]
    assert [c[-1] for c in stops] == ["b" * 64, "a" * 64]
    assert processes.stopped == [1000]
    assert manager.stop()["stopped"]  # Idempotent after the successful stop.


@pytest.mark.parametrize("missing", ["model_ok", "artifact_ok"])
def test_missing_model_or_artifact_fails_before_service_start(stack, missing):
    manager, system, processes = stack
    setattr(system, missing, False)
    with pytest.raises(RuntimeError):
        manager.start()
    assert not system.calls and not processes.launched and not manager.path.exists()


def test_status_is_read_only_and_explicitly_not_priming_or_demo_execution(stack):
    manager, system, processes = stack
    result = manager.status()
    assert result["ready"] and result["inference_requests"] == result["judge_requests"] == 0
    assert result["banking_tools_executed"] == 0 and not result["classifier_primed"] and not result["demo_started"]
    assert not manager.config.directory.exists() and not processes.launched
    assert ("services", False, False) in system.calls


def test_missing_mlflow_database_does_not_create_an_empty_store(stack):
    manager, system, processes = stack
    (manager.config.root / "mlflow.db").unlink()
    system.tracking = False
    with pytest.raises(RuntimeError, match="empty tracking"):
        manager.start()
    assert not processes.launched and not (manager.config.root / "mlflow.db").exists()


def test_missing_existing_artifact_store_does_not_create_a_replacement(stack):
    manager, system, processes = stack
    (manager.config.root / ".infra/mlflow-artifacts").rmdir()
    system.tracking = False
    with pytest.raises(RuntimeError, match="empty artifact history"):
        manager.start()
    assert not processes.launched and not (manager.config.root / ".infra/mlflow-artifacts").exists()


def test_occupied_tracking_port_is_never_killed_or_replaced(stack, monkeypatch):
    manager, system, processes = stack
    system.tracking = False
    monkeypatch.setattr("src.infra.demo_stack.port_open", lambda port: True)
    with pytest.raises(RuntimeError, match="occupied"):
        manager.start()
    assert not processes.launched and not processes.stopped


def test_active_demo_prevents_all_shutdown_mutations(stack):
    manager, system, processes = stack
    system.tracking = False
    manager.start()
    system.active = True
    before = manager.path.read_bytes()
    with pytest.raises(RuntimeError, match="Active demo"):
        manager.stop()
    assert not processes.stopped and manager.path.read_bytes() == before


def test_changed_process_identity_prevents_shutdown(stack):
    manager, system, processes = stack
    system.tracking = False
    manager.start()
    processes.live[1000]["started"] = "another-process"
    with pytest.raises(RuntimeError, match="PID reused"):
        manager.stop()
    assert not processes.stopped


@pytest.mark.parametrize("change", ["id", "restart", "ambiguous_start"])
def test_replaced_or_externally_restarted_container_is_not_stopped(stack, change):
    manager, system, processes = stack
    node = system.rows["breaker-substrate-control-plane"]
    node["State"]["Running"] = False
    manager.start()
    if change == "id":
        node["Id"] = "e" * 64
    elif change == "restart":
        node["State"]["StartedAt"] = "operator-restart"
    else:
        state = manager.state()
        state["containers"][node["Name"]] = dict(id=node["Id"], status="starting")
        manager.save(state)
    with pytest.raises(RuntimeError):
        manager.stop()
    assert not processes.stopped
    assert not any(isinstance(c, tuple) and c[:2] == ("podman", "stop") for c in system.calls)


def test_state_from_another_checkout_and_concurrent_manager_are_rejected(stack):
    manager, _, _ = stack
    state = manager.state()
    state["root"] = "/another-checkout"
    private_json(manager.path, state)
    with pytest.raises(RuntimeError, match="another checkout"):
        manager.state()
    with manager.locked():
        with pytest.raises(RuntimeError, match="Another demo-stack"):
            with manager.locked():
                pass


def test_owned_server_crash_cannot_be_silently_adopted_as_existing_service(stack):
    manager, system, processes = stack
    system.tracking = False
    manager.start()
    processes.live.clear()  # Something still answers on the original endpoint.
    with pytest.raises(RuntimeError, match="leader is gone"):
        manager.start()
    assert len(processes.launched) == 1


def test_failed_service_readiness_retains_ownership_for_inspection(stack, monkeypatch):
    manager, system, processes = stack
    system.tracking = False
    monkeypatch.setattr(system, "services", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("rollout failed")))
    with pytest.raises(RuntimeError, match="rollout failed"):
        manager.start()
    assert manager.state()["processes"]["mlflow"]["pid"] == 1000
    assert manager.stop()["stopped"] and processes.stopped == [1000]


def test_optional_saved_replay_is_started_without_running_a_model(stack, monkeypatch):
    manager, system, processes = stack
    config = replace(manager.config, review=True)
    config.read_token.parent.mkdir(parents=True)
    monkeypatch.setattr("src.benchmark.review_backend.ReviewStore", lambda path: object())
    manager = Manager(config, system=system, processes=processes)
    result = manager.start()
    assert result["ready"] and result["inference_requests"] == result["judge_requests"] == 0
    assert len(processes.launched) == 1 and "src.benchmark.review_backend" in processes.launched[0]
    assert config.read_token.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("url", ["https://remote.test", "http://user:password@localhost:5001", "http://localhost:5001/?secret=x"])
def test_remote_or_credential_bearing_service_addresses_are_rejected(url):
    with pytest.raises(RuntimeError):
        local_endpoint(url)


@pytest.mark.parametrize("change", [dict(tracking="http://localhost:5555"), dict(model_base="http://localhost:9999/v1")])
def test_service_addresses_cannot_diverge_from_installed_gateway_ports(change):
    with pytest.raises(RuntimeError, match="installed gateway profile"):
        replace(Config(), **change).validate()


def test_gateway_health_check_uses_actual_installed_provider_schema():
    from src.infra.protocol_resources import manifests
    config = Config()
    bundle = manifests(host_ip="192.168.127.254", model=config.model, issuer="unit-issuer",
                       jwks={"keys": [{"kty": "RSA"}]}, experiment_id="5")
    backend = next(row for row in bundle["items"] if row["kind"] == "AgentgatewayBackend" and row["metadata"]["name"] == "local-banking-model")
    backend["metadata"]["generation"] = 1
    backend["status"] = dict(conditions=[dict(type="Accepted", status="True", observedGeneration=1)])
    # host/port are siblings of custom, not inside the custom model configuration.
    validate_model_backend(backend, config.model, "192.168.127.254")
    backend["spec"]["ai"]["provider"]["port"] = 9999
    with pytest.raises(RuntimeError, match="host/port"):
        validate_model_backend(backend, config.model, "192.168.127.254")


def test_real_process_ownership_rejects_reused_pid_without_sending_a_signal(monkeypatch):
    processes = HostProcesses()
    record = dict(pid=123, pgid=123, started="old", command_sha256="a" * 64)
    monkeypatch.setattr(processes, "identity", lambda pid: dict(record, started="new"))
    signals = []
    monkeypatch.setattr(os, "killpg", lambda *args: signals.append(args))
    with pytest.raises(RuntimeError, match="identity changed"):
        processes.stop(record)
    assert not signals


def test_real_detached_owned_process_can_be_stopped(tmp_path):
    processes = HostProcesses()
    record = processes.launch([sys.executable, "-c", "import time; time.sleep(60)"], tmp_path / "owned.log", tmp_path)
    try:
        assert processes.check(record)
        processes.stop(record)
        assert not processes.check(record)
    finally:
        if processes.check(record):
            processes.stop(record)


def test_system_model_checks_only_metadata_without_loading_or_generation(tmp_path, monkeypatch):
    system = System(Config(root=tmp_path))
    calls = []
    def command(*args, **kwargs):
        calls.append(args)
        return json.dumps([dict(identifier=system.config.model, contextLength=8192, status="idle", queued=0)])
    monkeypatch.setattr(system, "command", command)
    monkeypatch.setattr(system, "get_json", lambda url: dict(data=[dict(id=system.config.model)]))
    assert system.check_model()["inference_requests"] == 0
    assert calls == [("lms", "ps", "--json")]


def test_registry_and_node_identity_validation_happens_before_any_start(tmp_path, monkeypatch):
    system = System(Config(root=tmp_path))
    monkeypatch.setattr(system, "owner", lambda: dict(identity=dict(nodes={"node": "a" * 64})))
    monkeypatch.setattr(system, "container", lambda name: dict(Name=name, Id="b" * 64))
    with pytest.raises(RuntimeError, match="replaced"):
        system.containers()


@pytest.mark.parametrize("expiry", [0, 1, None])
def test_expired_driver_tokens_have_actionable_read_only_status_failure(tmp_path, expiry):
    system = System(Config(root=tmp_path))
    directory = tmp_path / ".infra/banking-service-03b"
    directory.mkdir(parents=True)
    payload = base64.urlsafe_b64encode(json.dumps(dict(exp=expiry)).encode()).decode().rstrip("=")
    for name in ("platform.token", "runtime.token"):
        path = directory / name
        path.write_text(f"header.{payload}.signature")
        path.chmod(0o600)
    before = {p.name: p.read_bytes() for p in directory.iterdir()}
    with pytest.raises(RuntimeError, match="run bash scripts/demo_stack.sh start"):
        system.check_driver_tokens()
    assert before == {p.name: p.read_bytes() for p in directory.iterdir()}


def test_symlinked_lifecycle_state_is_not_adopted_or_overwritten(stack, tmp_path):
    manager, system, processes = stack
    manager.config.directory.mkdir(parents=True, mode=0o700)
    other = tmp_path / "unrelated.json"
    other.write_text('{"unrelated": true}')
    manager.path.symlink_to(other)
    with pytest.raises(RuntimeError, match="private file"):
        manager.start()
    assert other.read_text() == '{"unrelated": true}' and not system.calls and not processes.launched


def test_rollout_subprocess_stdout_cannot_corrupt_json_output(tmp_path, monkeypatch, capfd):
    from types import SimpleNamespace
    system = System(Config(root=tmp_path))
    (tmp_path / "deployment.json").write_text(json.dumps(dict(deadline_profile="native-measure-v2")))
    calls = []
    class Cluster:
        def kubectl(self, *args, **kwargs):
            calls.append((args, kwargs))
            if not kwargs.get("capture"):
                # FD-level child output bypasses Python redirect_stdout.
                subprocess.run([sys.executable, "-c", "print('unexpected rollout noise')"], check=True)
            if args[0] == "wait":
                raise RuntimeError("stop at test boundary")
            return SimpleNamespace(stdout="rollout ready")
    monkeypatch.setattr("src.banking_service.deploy.DIRECTORY", tmp_path)
    monkeypatch.setattr("src.banking_service.deploy.Deployment", lambda: SimpleNamespace(cluster=Cluster()))
    with pytest.raises(RuntimeError, match="test boundary"):
        system.services(wait=True)
    assert len(calls) == 4 and all(kwargs.get("capture") is True for _, kwargs in calls)
    assert capfd.readouterr().out == ""


@pytest.mark.parametrize("actors,pending", [([dict(metadata=dict(name="active-actor"))], "0"), ([], "1"), ([], "0")])
def test_shutdown_guard_reads_actor_and_action_state_without_mutating_it(tmp_path, monkeypatch, actors, pending):
    from types import SimpleNamespace
    system = System(Config(root=tmp_path))
    monkeypatch.setattr("src.infra.demo_stack.port_open", lambda port: False)
    calls = []
    def ate(*args, **kwargs):
        assert args == ("get", "actors", "-a", "breaker-banking", "-o", "json") and kwargs["operator"]
        return SimpleNamespace(stdout=json.dumps(dict(actors=actors)))
    def kubectl(*args, **kwargs):
        calls.append(args)
        assert args[:4] == ("exec", "-n", "breaker-banking", "deployment/banking-store")
        code = args[-1]
        assert "mode=ro" in code and "PRAGMA query_only=ON" in code and "SELECT count(*)" in code
        assert "UPDATE " not in code and "DELETE " not in code and "INSERT " not in code
        return SimpleNamespace(stdout=pending)
    monkeypatch.setattr("src.banking_service.deploy.Deployment", lambda: SimpleNamespace(ate=ate, cluster=SimpleNamespace(kubectl=kubectl)))
    if actors or pending != "0":
        with pytest.raises(RuntimeError, match="refusing|reconcile"):
            system.quiescent()
    else:
        system.quiescent()
    assert len(calls) == (0 if actors else 1)


def test_shell_entry_point_checks_existing_environment_and_never_installs(tmp_path):
    source = Path(__file__).resolve().parents[1] / "scripts/demo_stack.sh"
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "demo_stack.sh").write_bytes(source.read_bytes())
    binary = tmp_path / "bin"
    binary.mkdir()
    uv = binary / "uv"
    uv.write_text('#!/bin/bash\nprintf "%s\\n" "$*" >> "$CALL_LOG"\n')
    uv.chmod(0o755)
    log = tmp_path / "calls"
    result = subprocess.run(["bash", str(scripts / "demo_stack.sh"), "status", "--json"],
                            env=dict(os.environ, PATH=f"{binary}:/usr/bin:/bin", CALL_LOG=str(log)), capture_output=True)
    assert result.returncode == 0
    assert log.read_text().splitlines() == ["lock --check", "sync --locked --check",
        "run --locked --no-sync python -m src.infra.demo_stack status --json"]


def test_proven_reboot_retires_old_ownership_but_never_adopts_running_containers(stack, monkeypatch):
    manager, system, processes = stack
    monkeypatch.setattr("src.infra.demo_stack.boot_id", lambda: "old-boot")
    node = system.rows["breaker-substrate-control-plane"]
    node["State"]["Running"] = False
    manager.start()
    previous = manager.path.read_bytes()
    monkeypatch.setattr("src.infra.demo_stack.boot_id", lambda: "new-boot")
    node["State"]["StartedAt"] = "provider-autostart"
    assert manager.start()["ready"]
    assert manager.state()["containers"] == {}
    assert next((manager.config.directory / "recovery").glob("*.json")).read_bytes() == previous
    manager.stop()
    assert node["State"]["Running"]  # Restarted externally, now borrowed.
    assert not processes.stopped


def test_reboot_does_not_bypass_replaced_container_identity(stack, monkeypatch):
    manager, system, _ = stack
    monkeypatch.setattr("src.infra.demo_stack.boot_id", lambda: "old-boot")
    system.rows["kind-registry"]["State"]["Running"] = False
    manager.start()
    before = manager.path.read_bytes()
    monkeypatch.setattr("src.infra.demo_stack.boot_id", lambda: "new-boot")
    system.rows["kind-registry"]["Id"] = "replacement"
    with pytest.raises(RuntimeError, match="replaced across reboot"):
        manager.start()
    assert manager.path.read_bytes() == before


def test_process_from_prior_boot_is_not_inspected_or_signalled(monkeypatch):
    processes = HostProcesses()
    monkeypatch.setattr("src.infra.demo_stack.boot_id", lambda: "new-boot")
    monkeypatch.setattr(processes, "identity", lambda pid: pytest.fail("must not inspect a reused post-reboot PID"))
    monkeypatch.setattr(os, "killpg", lambda *a: pytest.fail("must not signal a post-reboot PID"))
    processes.stop(dict(pid=123, boot_id="old-boot"))


def test_status_explains_blocked_provider_dependency_chain(stack, monkeypatch):
    manager, system, processes = stack
    monkeypatch.setattr(system, "provider_ready", lambda: (_ for _ in ()).throw(RuntimeError("Recorded VM stopped")))
    monkeypatch.setattr(system, "containers", lambda: pytest.fail("downstream check should be blocked"))
    monkeypatch.setattr(system, "services", lambda **kw: pytest.fail("downstream check should be blocked"))
    result = manager.status()
    assert not result["ready"]
    assert result["services"]["containers"]["blocked_by"] == "provider"
    assert result["services"]["cluster_services"]["blocked_by"] == "containers"
    assert result["services"]["model"]["ready"] and result["services"]["artifact"]["ready"]
    assert not processes.launched


def test_vm_helpers_do_not_inherit_the_ui_ctrl_c_process_group(tmp_path, monkeypatch):
    from types import SimpleNamespace
    calls = []
    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(stdout="{}")
    monkeypatch.setattr(subprocess, "run", run)
    system = System(Config(root=tmp_path))
    system.command("podman", "machine", "start", "retained")
    system.command("podman", "info", "--format", "json")
    assert calls[0][1]["start_new_session"] is True
    assert calls[1][1]["start_new_session"] is False


def test_resumed_store_waits_for_actual_readiness_without_retrying_ownership_errors(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from src.banking_service.deploy import StoreNotReady
    system = System(Config(root=tmp_path, timeout=1))
    observations = [StoreNotReady("resuming"), None]
    def verify(manifest):
        result = observations.pop(0)
        if result: raise result
    deployment = SimpleNamespace(verify_deployment=verify)
    monkeypatch.setattr("src.infra.demo_stack.time.sleep", lambda seconds: None)
    system.verify_banking(deployment, {}, wait=True)
    assert observations == []
    observations[:] = [RuntimeError("foreign store"), None]
    with pytest.raises(RuntimeError, match="foreign store"):
        system.verify_banking(deployment, {}, wait=True)
    assert observations == [None]
    observations[:] = [StoreNotReady("resuming"), None]
    with pytest.raises(RuntimeError, match="not ready after restart"):
        system.verify_banking(deployment, {}, wait=False)
    assert observations == [None]


def test_old_boot_process_records_are_archived_without_claiming_new_listener(stack, monkeypatch):
    manager, system, processes = stack
    state = manager.state()
    state["boot_id"] = "old-boot"
    state["processes"]["mlflow"] = dict(pid=1000, pgid=1000, started="old", command_sha256="old",
                                        boot_id="old-boot", endpoint_port=5001)
    manager.save(state)
    processes.live[1000] = dict(pid=1000, started="unrelated-new-boot-process")
    monkeypatch.setattr("src.infra.demo_stack.boot_id", lambda: "new-boot")
    assert manager.start()["ready"]
    assert manager.state()["processes"] == {}
    assert not processes.launched and not processes.stopped
    assert len(list((manager.config.directory / "recovery").glob("*.json"))) == 1


def test_timezone_changes_do_not_authorize_false_reboot_recovery():
    first = "{ sec = 1790000000, usec = 123 } Mon Sep 21 12:00:00 2026"
    second = "{ sec = 1790000000, usec = 123 } Mon Sep 21 20:00:00 2026"
    assert canonical_boot(first) == canonical_boot(second) == "darwin:1790000000:123"


def test_service_only_start_and_stop_cannot_race_even_a_deferred_direct_ui(stack):
    manager, system, processes = stack
    with operator_lease(manager.config.root):
        with pytest.raises(RuntimeError, match="already running"):
            manager.start()
        with pytest.raises(RuntimeError, match="already running"):
            manager.stop()
    assert not system.calls and not processes.launched and not processes.stopped


def test_runtime_forwarders_survive_ctrl_c_until_owned_cleanup(tmp_path, monkeypatch):
    from contextlib import nullcontext
    from types import SimpleNamespace
    from src.banking_service import deploy
    from src.benchmark.deployment import gateway_forward
    calls = []
    class Child:
        def poll(self): return None
        def terminate(self): calls.append("terminate")
        def wait(self, **kwargs): return 0
    def popen(argv, **kwargs):
        assert kwargs["start_new_session"] is True
        calls.append(argv)
        return Child()
    monkeypatch.setattr(subprocess, "Popen", popen)
    monkeypatch.setattr(deploy, "DIRECTORY", tmp_path)
    monkeypatch.setattr(deploy.httpx, "Client", lambda **kwargs: nullcontext(SimpleNamespace(get=lambda url: SimpleNamespace(status_code=200))))
    monkeypatch.setattr("src.benchmark.deployment.socket.create_connection", lambda *a, **kw: nullcontext())
    deployment = object.__new__(deploy.Deployment)
    deployment.cluster = SimpleNamespace(kubeconfig=tmp_path / "kubeconfig", context="fixture")
    with deployment.forward("service/banking-store"):
        assert "terminate" not in calls
    assert calls[-1] == "terminate"
    with gateway_forward(deployment.cluster, tmp_path):
        assert len(calls) == 3
    assert calls[-1] == "terminate"


def test_inflight_infra_commands_are_not_signalled_by_ui_ctrl_c(monkeypatch):
    from types import SimpleNamespace
    from src.infra.common import run
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: calls.append(kw) or SimpleNamespace(stdout=""))
    run(["kubectl", "fixture"], capture=True)
    assert calls[0]["start_new_session"] is True
