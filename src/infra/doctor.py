"""Check local prerequisites separately from optional research services."""
import argparse
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request

from src.infra.common import ROOT, VERSIONS, environment, run


def check_tools():
    specs = {
        "kind": (["kind", "version"], VERSIONS["kind"]),
        "helm": (["helm", "version", "--short"], VERSIONS["helm"]),
        "kubectl": (["kubectl", "version", "--client", "-o", "json"], VERSIONS["kubectl"]),
        "kubectl-ate": (["kubectl-ate", "--version"], VERSIONS["substrate"]),
    }
    for name, (args, expected) in specs.items():
        if not shutil.which(name, path=environment()["PATH"]):
            raise RuntimeError(f"Missing {name}; run bash scripts/install_tools.sh --with-go")
        output = run(args, capture=True).stdout.strip()
        actual = json.loads(output)["clientVersion"]["gitVersion"] if name == "kubectl" else output
        if expected not in actual.split()[0:4] and expected not in actual.split("+")[0].split():
            raise RuntimeError(f"Unsupported {name}: expected {expected}, got {actual}. Run scripts/install_tools.sh")
        print(f"OK {name} {expected}")


def check_provider(info):
    host = info["host"]
    if host.get("cgroupVersion") != "v2":
        raise RuntimeError("This local profile requires cgroup v2")
    if host.get("security", {}).get("rootless"):
        raise RuntimeError("This validated Kind/Substrate profile requires a rootful Podman connection; see docs/infra.md")
    if host.get("memTotal", 0) < 8 * 1024**3:
        raise RuntimeError("At least 8 GiB of VM memory is required; 16 GiB or more is recommended")
    print(f"OK Podman {host.get('arch')} / kernel {host.get('kernel')} / cgroup v2 / rootful")


def check_podman_versions():
    """The host package version alone does not qualify its persisted guest."""
    info=json.loads(run(["podman","version","--format","json"],capture=True).stdout)
    client=info.get("Client",{}).get("Version","")
    server=info.get("Server",{}).get("Version","")
    if not all(isinstance(v,str) and re.fullmatch(r"\d+\.\d+\.\d+",v) for v in (client,server)):
        raise RuntimeError("Cannot verify stable Podman host and guest versions")
    if client!=server:
        raise RuntimeError(f"Podman host/guest mismatch: {client}/{server}; finish the coherent update before workloads")
    expected=VERSIONS.get("podman","").removeprefix("v")
    if expected and client!=expected:
        raise RuntimeError("Podman host/guest differ from the reviewed profile")
    print(f"OK Podman host and guest {client}")


def check_hypervisor():
    """Observe the selected macOS helper, not merely the Podman client version."""
    if platform.system() != "Darwin":
        return
    info = json.loads(run(["podman", "machine", "info", "--format", "json"], capture=True).stdout)
    if info.get("Host", {}).get("VMType") != "libkrun":
        return
    processes = run(["ps", "-Ao", "pid=,comm="], capture=True).stdout.splitlines()
    helpers=[]
    for line in processes:
        parts=line.strip().split(None,1)
        if len(parts)==2 and parts[0].isdigit() and parts[1].endswith("/krunkit"):
            helpers.append(parts)
    if len(helpers) > 1:
        raise RuntimeError("Multiple krunkit helpers observed; inspect the selected provider before proceeding")
    if not helpers:
        raise RuntimeError("No running libkrun helper observed; host binaries are not proof of the selected runtime")
    pid,path=helpers[0]
    helper = Path(path)
    if not helper.is_file():
        raise RuntimeError("Cannot observe the selected libkrun helper; do not infer its version from Podman")
    mappings=run(["lsof","-a","-p",pid,"-d","txt","-Fin"],capture=True).stdout.splitlines()
    inode=None;loaded_inode=None
    for field in mappings:
        if field.startswith("i"):inode=field[1:]
        elif field=="n"+str(helper):loaded_inode=inode
    if loaded_inode!=str(helper.stat().st_ino):
        raise RuntimeError("Running krunkit does not map the installed helper; an approved VM restart is required")
    output = run([helper, "--version"], capture=True).stdout.strip()
    match = re.fullmatch(r"krunkit (\d+)\.(\d+)\.(\d+)", output)
    policy = json.loads((ROOT/"infra/version-policy.json").read_text())["libkrun_helper"]
    minimum = tuple(map(int, policy["minimum_krunkit"].split(".")))
    if not match or tuple(map(int, match.groups())) < minimum:
        raise RuntimeError(f"Unsafe/unreviewed libkrun helper: {output}; require krunkit >= {policy['minimum_krunkit']} "
                           "for the known reboot/control-API issue (#38). No automatic helper upgrade or VM replacement.")
    expected=VERSIONS.get("krunkit")
    if expected and output!="krunkit "+expected:
        raise RuntimeError("Selected krunkit differs from the reviewed bundle")
    print(f"OK selected {output}; version prerequisite only, not VM stability proof")


def research_services():
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    endpoints = [
        ("LM Studio", os.getenv("LM_STUDIO_BASE_URL", "http://localhost:1234/v1").rstrip("/") + "/models"),
        ("sidecar readiness", os.getenv("DECISION_SIDECAR_URL", "http://localhost:8000").rstrip("/") + "/health"),
    ]
    tracking = os.getenv("MLFLOW_TRACKING_URI", "sqlite:///mlflow.db")
    if tracking.startswith(("http://", "https://")):
        endpoints.append(("MLflow", tracking.rstrip("/") + "/health"))
    for label, endpoint in endpoints:
        with urllib.request.urlopen(endpoint, timeout=3) as response:
            if response.status != 200:
                raise RuntimeError(f"{label} health check failed")
        print(f"OK {label}")
    print("Research health checks do not validate model quality, distinct enforcement routes, reset freshness, or containment.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--research", action="store_true")
    parser.add_argument("--cluster", help="Also verify a managed infrastructure cluster")
    parser.add_argument("--target-stack",action="store_true",help="Require complete current target-stack qualification; never run model inference")
    parser.add_argument("--skip-substrate", action="store_true")
    args = parser.parse_args()
    if args.target_stack and (not args.cluster or args.skip_substrate):
        parser.error("--target-stack requires --cluster and the full Substrate profile")
    try:
        check_tools()
        check_hypervisor()
        check_podman_versions()
        check_provider(json.loads(run(["podman", "info", "--format", "json"], capture=True).stdout))
        if args.cluster:
            from src.infra.manage import Cluster
            cluster=Cluster(args.cluster)
            cluster.verify(require_substrate=not args.skip_substrate)
            if args.target_stack:
                from src.infra.qualification import require_current_cached
                require_current_cached(cluster)
                print("OK automated target-stack qualification is current; human acceptance is separate")
        if args.research:
            research_services()
    except (RuntimeError, ValueError, OSError, subprocess.SubprocessError) as exc:
        print(f"Preflight failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
