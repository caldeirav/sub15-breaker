#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
command -v uv >/dev/null || { echo 'Missing uv' >&2; exit 1; }
uv lock --check || { echo 'Dependency lock is missing or stale; run uv lock and commit uv.lock.' >&2; exit 1; }
exec uv run --locked python -m src.infra.manage "$@"
