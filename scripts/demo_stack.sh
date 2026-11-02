#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
command -v uv >/dev/null || { echo 'Missing uv; install it before managing the demo stack.' >&2; exit 1; }
uv lock --check
uv sync --locked --check
exec uv run --locked --no-sync python -m src.infra.demo_stack "$@"
