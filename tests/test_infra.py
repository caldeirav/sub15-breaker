"""Infrastructure regressions run without a provider, cluster, or API credentials."""
import hashlib
from http.client import HTTPConnection
import json
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest
import yaml

from src.infra import doctor, enforcement, gate, manage, network, probe_client, tools
from src.infra.auth_fixture import FixtureServer, grant, parse_command, verify_grant
from src.infra.common import ROOT, VERSIONS


@pytest.mark.parametrize("name", ["kagenti", "kind", "../breaker-x", "breaker-", "breaker-X", "breaker-x;id"])
def test_cluster_names_cannot_target_unrelated_resources(name):
    with pytest.raises(ValueError):
        manage.validate_cluster_name(name)


@pytest.mark.parametrize("status,observed,expected", [("True", 2, True), ("False", 2, False),
                                                   ("True", 1, False), ("True", None, False)])
def test_readiness_rejects_stale_conditions(status, observed, expected):
    value = dict(metadata=dict(generation=2), status=dict(conditions=[dict(type="Accepted", status=status, observedGeneration=observed)]))
    assert manage.condition_is_current(value, "Accepted") == expected


def test_destroy_requires_ownership_and_exact_confirmation(tmp_path, monkeypatch):
    monkeypatch.setattr(manage, "STATE", tmp_path)
    cluster = manage.Cluster("breaker-test")
    with pytest.raises(RuntimeError, match="ownership"):
        cluster.destroy("breaker-test")
    cluster.directory.mkdir(parents=True)
    identity = dict(provider_sha256="provider", nodes={"breaker-test-control-plane": "a" * 64})
    cluster.marker.write_text(json.dumps(dict(project="sub15-breaker", cluster="breaker-test", identity=identity)))
    monkeypatch.setattr(cluster, "identity", lambda: identity)
    calls = []
    monkeypatch.setattr(manage, "run", lambda args, **kwargs: calls.append(args))
    with pytest.raises(ValueError, match="exact"):
        cluster.destroy("kagenti")
    assert calls == []
    cluster.destroy("breaker-test")
    assert calls[0] == ["kind", "delete", "cluster", "--name", "breaker-test", "--kubeconfig", cluster.kubeconfig]


def test_retained_marker_cannot_delete_replacement_cluster(tmp_path, monkeypatch):
    monkeypatch.setattr(manage, "STATE", tmp_path)
    cluster = manage.Cluster("breaker-test")
    cluster.directory.mkdir(parents=True)
    cluster.marker.write_text(json.dumps(dict(project="sub15-breaker", cluster="breaker-test",
        identity=dict(provider_sha256="old-provider", nodes={"node": "old-container"}))))
    monkeypatch.setattr(cluster, "identity", lambda: dict(provider_sha256="new-provider", nodes={"node": "new-container"}))
    calls = []
    monkeypatch.setattr(manage, "run", lambda args, **kwargs: calls.append(args))
    with pytest.raises(RuntimeError, match="identity changed"):
        cluster.destroy("breaker-test")
    assert not calls


def test_pinned_cluster_config_supports_certificate_api_and_external_cni():
    config = yaml.safe_load((ROOT / "infra/kind.yaml").read_text())
    assert config["networking"]["disableDefaultCNI"] is True
    for name in ("ClusterTrustBundle", "ClusterTrustBundleProjection", "PodCertificateRequest"):
        assert config["featureGates"][name] is True
    assert config["runtimeConfig"]["certificates.k8s.io/v1beta1"] == "true"
    assert "@sha256:" in VERSIONS["node_image"]
    assert "@sha256:" in VERSIONS["probe_image"]
    assert (ROOT / "scripts/libexec/docker").stat().st_mode & 0o111


def test_cluster_creation_does_not_wait_for_cni_before_installing_it(tmp_path, monkeypatch):
    monkeypatch.setattr(manage, "STATE", tmp_path)
    monkeypatch.setattr(doctor, "check_tools", lambda: None)
    monkeypatch.setattr(doctor, "check_hypervisor", lambda: None)
    monkeypatch.setattr(doctor, "check_provider", lambda info: None)
    monkeypatch.setattr(manage.shutil, "which", lambda *args, **kwargs: "/fake/tool")
    calls = []
    def fake_run(args, **kwargs):
        calls.append(args)
        output = ""
        if args[:2] == ["podman", "info"]:
            output = "{}"
        if args[:3] == ["kind", "get", "clusters"]:
            output = "other-project\n"
        if args[:3] == ["kind", "get", "kubeconfig"]:
            output = "apiVersion: v1\n"
        if args[:4] == ["podman", "system", "connection", "list"]:
            output = "[]"
        if args[:3] == ["kind", "get", "nodes"]:
            output = "breaker-test-control-plane\n"
        if args[:2] == ["podman", "inspect"]:
            output = "a" * 64
        return SimpleNamespace(stdout=output)
    monkeypatch.setattr(manage, "run", fake_run)
    cluster = manage.Cluster("breaker-test")
    cluster.create()
    create = next(c for c in calls if c[:3] == ["kind", "create", "cluster"])
    assert create[create.index("--wait") + 1] == "0s"
    assert "delete" not in [str(x) for c in calls for x in c]
    assert cluster.kubeconfig.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("rootless,cgroup,memory", [(True, "v2", 16), (False, "v1", 16), (False, "v2", 4)])
def test_unsupported_provider_profiles_fail(rootless, cgroup, memory):
    info = dict(host=dict(cgroupVersion=cgroup, security=dict(rootless=rootless), memTotal=memory * 1024**3))
    with pytest.raises(RuntimeError):
        doctor.check_provider(info)


def test_checksums_fail_before_installing_corrupt_tools(tmp_path):
    path = tmp_path / "binary"
    path.write_bytes(b"verified release")
    tools.verify_checksum(path, hashlib.sha256(path.read_bytes()).hexdigest())
    with pytest.raises(RuntimeError, match="mismatch"):
        tools.verify_checksum(path, "0" * 64)
    with pytest.raises(ValueError, match="Invalid"):
        tools.verify_checksum(path, "not-a-checksum")


def test_network_controls_include_independent_positive_and_negative_paths():
    items = network.manifests()["items"]
    policies = {x["metadata"]["name"]: x["spec"] for x in items if x["kind"] == "NetworkPolicy"}
    assert policies["default-deny"]["podSelector"]["matchLabels"] == {}
    assert set(policies["default-deny"]["policyTypes"]) == {"Ingress", "Egress"}
    assert policies["target-ingress"]["ingress"][0]["from"] == [dict(podSelector=dict(matchLabels=dict(role="trusted")))]
    assert policies["trusted-egress"]["egress"][0]["to"] == [dict(podSelector=dict(matchLabels=dict(role="target")))]
    assert policies["control-ingress"]["ingress"][0]["from"] == [dict(podSelector={})]
    for item in items:
        if item["kind"] == "Pod":
            spec = item["spec"]
            assert spec["automountServiceAccountToken"] is False
            assert spec["securityContext"]["runAsNonRoot"] is True
            assert spec["containers"][0]["securityContext"]["readOnlyRootFilesystem"] is True


@pytest.mark.parametrize("body", [b'{"command":"a","command":"b"}', b'{"command":"a","extra":1}',
                                 b'[]', b'{"command":false}', b'{"command":""}', b'{broken',
                                 json.dumps(dict(command="a" * 8193)).encode(), b'{"command":"\\ud800"}'])
def test_fixture_rejects_ambiguous_or_unbounded_commands(body):
    with pytest.raises((ValueError, UnicodeError)):
        parse_command(body)


def test_fixture_grants_bind_exact_bytes_key_and_expiry():
    body = b'{"command":"fixture:allow"}'
    token = grant(body, "signing-key", now=100)
    assert verify_grant(token, body, "signing-key", now=101)["digest"] == hashlib.sha256(body).hexdigest()
    with pytest.raises(ValueError, match="signature"):
        verify_grant(token, body, "wrong-key", now=101)
    with pytest.raises(ValueError, match="differs"):
        verify_grant(token, body + b" ", "signing-key", now=101)
    with pytest.raises(ValueError, match="Expired"):
        verify_grant(token, body, "signing-key", now=160)


def test_gateway_fixture_preserves_default_deny_and_permits_scoped_xds():
    items = enforcement.manifests()["items"]
    policies = {x["metadata"]["name"]: x["spec"] for x in items if x["kind"] == "NetworkPolicy"}
    egress = policies["gateway-egress"]["egress"]
    xds = next(rule for rule in egress if rule["ports"] == [dict(protocol="TCP", port=9978)])
    assert xds["to"][0]["namespaceSelector"]["matchLabels"] == {"kubernetes.io/metadata.name": "agentgateway-system"}
    assert xds["to"][0]["podSelector"]["matchLabels"] == {"app.kubernetes.io/name": "agentgateway"}
    assert policies["recorder-ingress"]["ingress"][0]["from"] == [dict(podSelector=dict(matchLabels=dict(role="gateway")))]
    auth = next(x for x in items if x["kind"] == "AgentgatewayPolicy")["spec"]["traffic"]["extAuth"]
    assert auth["failureMode"] == "FailClosed"
    assert auth["forwardBody"]["maxSize"] == "16Ki"
    assert "x-breaker-grant" in auth["http"]["allowedResponseHeaders"]
    for deployment in (x for x in items if x["kind"] == "Deployment"):
        assert "namespace" not in deployment["spec"]["template"]["metadata"]


def test_gateway_programmed_does_not_replace_dataplane_readiness():
    calls = []
    class FakeCluster:
        def kubectl(self, *args):
            calls.append(args)
            if args[:3] == ("rollout", "status", "deployment/breaker-gateway"):
                raise RuntimeError("XDS never reached the proxy")
    with pytest.raises(RuntimeError, match="XDS"):
        enforcement.wait_gateway(FakeCluster())
    assert calls[0][0:2] == ("wait", "--for=condition=Programmed")
    assert calls[1][0:3] == ("rollout", "status", "deployment/breaker-gateway")


def test_workload_examples_use_pinned_substrate_api():
    pool = yaml.safe_load((ROOT / "k8s/workerpool.yaml").read_text())
    actor = yaml.safe_load((ROOT / "k8s/actor-template.yaml").read_text())
    assert pool["apiVersion"] == "ate.dev/v1"
    assert pool["spec"]["sandboxClasses"] == [dict(name="gvisor", configRef=dict(name="gvisor-default"))]
    assert actor["workerSelector"]["matchLabels"] == pool["metadata"]["labels"]
    assert "sandboxConfig" not in actor
    assert actor["resources"]["limits"]["cpuMillicores"] > 0
    assert actor["resources"]["limits"]["memoryBytes"] > 0


def test_fixture_http_contract_records_only_authenticated_approved_bytes():
    servers = [FixtureServer(("127.0.0.1", 0), role, "test-token", "test-signing-key")
               for role in ("authorizer", "recorder")]
    threads = [threading.Thread(target=s.serve_forever, daemon=True) for s in servers]
    for thread in threads:
        thread.start()
    def post(server, body, **headers):
        connection = HTTPConnection(*server.server_address, timeout=3)
        try:
            connection.request("POST", "/authorize" if server.role == "authorizer" else "/execute",
                               body, {"content-type": "application/json", **headers})
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()
    body = b'{"command":"fixture:allow"}'
    try:
        authorizer, recorder = servers
        assert post(authorizer, body)[0] == 401
        status, headers, _ = post(authorizer, body, authorization="Bearer test-token")
        assert status == 200
        signed = headers["x-breaker-grant"]
        assert post(recorder, body, **{"x-breaker-grant": signed})[0] == 200
        assert post(recorder, body, **{"x-breaker-grant": signed})[0] == 409
        assert post(recorder, body + b" ", **{"x-breaker-grant": signed})[0] == 400
        assert post(authorizer, body, authorization="Bearer test-token", **{"x-breaker-grant": "spoof"})[0] == 400
        assert post(authorizer, b'{"command":"fixture:deny"}', authorization="Bearer test-token")[0] == 403
        assert post(authorizer, b'{"command":"fixture:error"}', authorization="Bearer test-token")[0] == 503
        assert len(recorder.records) == 1
        assert recorder.records[0]["digest"] == hashlib.sha256(body).hexdigest()
    finally:
        for server in servers:
            server.shutdown()
            server.server_close()
        for thread in threads:
            thread.join(timeout=3)


def test_publication_gate_never_infers_human_acceptance():
    record = json.loads((ROOT / "docs/validation/block-01.json").read_text())
    record["manual"] = dict(status="pending", tester="", date="", evidence="")
    assert any("manual" in problem for problem in gate.failures(record))
    complete = {name: dict(status="passed", evidence="reviewed evidence")
                for name in ("automated", "manual", "regressions", "documentation")}
    complete["manual"].update(tester="Human reviewer", date="2026-01-01")
    assert gate.failures(complete) == []
    complete["manual"]["status"] = True
    assert gate.failures(complete)
    assert gate.failures([])
    assert gate.failures(dict(manual=[]))


@pytest.mark.parametrize("status", [" M cmd/ate-setup/main.go", "?? cmd/ate-setup/injected.go", "!! cmd/ate-setup/ignored.go"])
def test_installer_refuses_modified_untracked_or_ignored_source(tmp_path, monkeypatch, status):
    calls = []
    def fake_run(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(stdout=VERSIONS["substrate_commit"] if args[1] == "rev-parse" else status)
    monkeypatch.setattr(manage, "run", fake_run)
    with pytest.raises(RuntimeError, match="untracked"):
        manage.verify_checkout(tmp_path)
    assert "--untracked-files=all" in calls[-1] and "--ignored" in calls[-1]


def test_partial_readiness_reports_do_not_claim_substrate_verified():
    report = manage.readiness_report("breaker-test", False, {"gitVersion": "observed-version"}, {}, [], [])
    assert report["checks"]["substrate"] is False
    assert report["skipped_checks"] == ["substrate"]
    assert report["scope"] == "networking-controller-readiness-only"
    assert report["observed"]["kubernetes_server"]["gitVersion"] == "observed-version"
    assert report["configured_pins"] == VERSIONS


def test_only_connect_timeout_counts_as_network_denial(monkeypatch):
    def fail(*args, **kwargs):
        raise TimeoutError("connection timeout")
    monkeypatch.setattr(probe_client.socket, "create_connection", fail)
    assert probe_client.probe("127.0.0.1", 8080) == dict(reachable=False, reason="connect-timeout")


@pytest.mark.parametrize("stage", ["send", "receive"])
def test_connected_but_stalled_server_cannot_pass_isolation(monkeypatch, stage):
    class Connection:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def sendall(self, data):
            if stage == "send":
                raise TimeoutError("send stalled")
        def recv(self, size):
            raise TimeoutError("response stalled")
    monkeypatch.setattr(probe_client.socket, "create_connection", lambda *args, **kwargs: Connection())
    with pytest.raises(RuntimeError, match="not isolation evidence"):
        probe_client.probe("127.0.0.1", 8080)


def test_documentation_local_links_and_fences_are_valid():
    import re
    paths = [ROOT / "README.md", *sorted((ROOT / "docs").rglob("*.md"))]
    for path in paths:
        text = path.read_text()
        assert text.count("```") % 2 == 0, path
        for target in re.findall(r"\]\(([^)]+)\)", text):
            if not target.startswith(("https://", "http://", "#")):
                assert (path.parent / target.split("#", 1)[0]).exists(), f"{path}: {target}"
