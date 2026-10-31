#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
command -v uv >/dev/null || { echo 'Missing uv' >&2; exit 1; }
if uv lock --check && uv sync --locked --check; then
  echo 'OK uv lock and project environment'
else
  echo 'MISSING uv project environment or current lock (run uv lock if needed, then uv sync --locked)'
  exit 1
fi
exec uv run --locked python -m src.infra.doctor "$@"
