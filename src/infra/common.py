"""Shared paths and subprocess boundaries for local infrastructure."""
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / ".tools"
STATE = ROOT / ".infra"
VERSIONS = json.loads((ROOT / "infra/versions.json").read_text())


def environment():
    return dict(os.environ, PATH=f"{TOOLS / 'bin'}:{os.environ.get('PATH', '')}",
                KIND_EXPERIMENTAL_PROVIDER="podman")


def run(args, *, capture=False, cwd=ROOT, env=None, timeout=1200):
    display = [str(arg) if len(str(arg)) <= 240 else str(arg)[:240] + "...[truncated]" for arg in args]
    print("+ " + " ".join(display), flush=True)
    try:
        return subprocess.run(list(map(str, args)), cwd=cwd, env=env or environment(),
                              check=True, text=True, capture_output=capture, timeout=timeout)
    except subprocess.CalledProcessError as exc:
        if capture and exc.stderr:
            print(exc.stderr[-4000:], file=sys.stderr)
        raise
