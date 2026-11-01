"""Read-only version gate: never upgrade or substitute an installed gateway."""
import json
from pathlib import Path
import subprocess


GATEWAY_REVISION = "26f5aebe99a36a037fe54f8080a608aca5547e15"


def gateway_capability(binary, versions_path):
    """Report the actual binary against the repository pin, without starting it."""
    expected = json.loads(Path(versions_path).read_text())["agentgateway"].removeprefix("v")
    result = subprocess.run([str(binary), "--version"], capture_output=True, text=True,
                            check=True, timeout=10)
    observed = json.loads(result.stdout)
    return dict(expected_version=expected, expected_revision=GATEWAY_REVISION,
                observed_version=observed.get("version"), observed_revision=observed.get("git_revision"),
                compatible=(observed.get("version") == expected and
                            observed.get("git_revision") == GATEWAY_REVISION))
