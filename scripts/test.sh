#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
uv lock --check
uv sync --locked
uv pip check --python .venv/bin/python
uv run --locked python -m pytest -q
for script in scripts/*.sh scripts/libexec/docker; do
  bash -n "$script"
done
git diff --check
