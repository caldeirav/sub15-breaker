"""Exercise dependency preflights without contacting services or a cluster."""
import ast
from importlib.metadata import packages_distributions
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tomllib

import pytest


@pytest.mark.parametrize("directory", ["src", "tests"])
def test_third_party_imports_are_declared_dependencies(directory):
    root = Path(__file__).resolve().parents[1]
    config = tomllib.loads((root / "pyproject.toml").read_text())

    def normalize(name):
        return re.sub(r"[-_.]+", "-", name).lower()

    requirements = list(config["project"]["dependencies"])
    if directory == "tests":
        requirements.extend(config["dependency-groups"]["dev"])
    declared = {
        normalize(re.match(r"[A-Za-z0-9_.-]+", requirement).group())
        for requirement in requirements
    }
    distributions = packages_distributions()
    missing = []
    for path in sorted((root / directory).rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and not node.level:
                modules = [node.module] if node.module else []
            else:
                continue
            for module in modules:
                name = module.split(".")[0]
                if name in sys.stdlib_module_names or name == "src":
                    continue
                owners = {normalize(owner) for owner in distributions.get(name, [])}
                if not owners.intersection(declared):
                    missing.append(f"{path.relative_to(root)}:{node.lineno}: {module}")
    assert not missing, "Imports without a declared, installed dependency:\n" + "\n".join(missing)


@pytest.fixture
def infra_scripts(tmp_path):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    source = Path(__file__).resolve().parents[1] / "scripts"
    for name in ("check_env.sh", "setup_infra.sh"):
        shutil.copyfile(source / name, scripts / name)
    (tmp_path / ".env").touch()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("uv", "podman", "kind", "kubectl", "kubectl-ate", "curl"):
        stub = bin_dir / name
        stub.write_text(
            '#!/bin/bash\n'
            'name=${0##*/}\n'
            'printf "%s %s\\n" "$name" "$*" >> "$CALL_LOG"\n'
            'if [[ "$name" == uv && "$1" == "${UV_FAIL:-}" ]]; then exit 1; fi\n'
            'exit 0\n'
        )
        stub.chmod(0o755)
    env = dict(os.environ, PATH=f"{bin_dir}:/usr/bin:/bin", CALL_LOG=str(tmp_path / "calls"))
    return scripts, env


@pytest.mark.parametrize("failure", ["", "lock", "sync"])
def test_check_env_validates_lock_and_environment(infra_scripts, failure):
    scripts, env = infra_scripts
    env["UV_FAIL"] = failure
    result = subprocess.run(
        ["/bin/bash", str(scripts / "check_env.sh")],
        env=env, capture_output=True, text=True,
    )
    assert result.returncode == (1 if failure else 0)
    calls = Path(env["CALL_LOG"]).read_text().splitlines()
    assert "uv lock --check" in calls
    assert ("uv sync --locked --check" in calls) == (failure != "lock")
    assert ("OK uv lock and project environment" in result.stdout) == (not failure)


def test_setup_refuses_stale_lock_before_cluster_changes(infra_scripts):
    scripts, env = infra_scripts
    env["UV_FAIL"] = "lock"
    result = subprocess.run(
        ["/bin/bash", str(scripts / "setup_infra.sh")],
        env=env, capture_output=True, text=True,
    )
    assert result.returncode == 1
    assert "run uv lock" in result.stderr
    assert Path(env["CALL_LOG"]).read_text().splitlines() == ["uv lock --check"]


def test_shell_syntax_check_does_not_ignore_later_scripts(infra_scripts):
    scripts, env = infra_scripts
    source = Path(__file__).resolve().parents[1] / "scripts/test.sh"
    shutil.copyfile(source, scripts / "test.sh")
    (scripts / "aaa-valid.sh").write_text("#!/bin/bash\nexit 0\n")
    (scripts / "zzz-invalid.sh").write_text("#!/bin/bash\nif then\n")
    result = subprocess.run(["/bin/bash", str(scripts / "test.sh")], env=env, capture_output=True, text=True)
    assert result.returncode != 0
    assert "zzz-invalid.sh" in result.stderr and "syntax error" in result.stderr
