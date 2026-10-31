"""Check local prerequisites separately from optional research services."""
import argparse
import json
import os
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
    parser.add_argument("--skip-substrate", action="store_true")
    args = parser.parse_args()
    try:
        check_tools()
        check_provider(json.loads(run(["podman", "info", "--format", "json"], capture=True).stdout))
        if args.cluster:
            from src.infra.manage import Cluster
            Cluster(args.cluster).verify(require_substrate=not args.skip_substrate)
        if args.research:
            research_services()
    except (RuntimeError, ValueError, OSError, subprocess.SubprocessError) as exc:
        print(f"Preflight failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
