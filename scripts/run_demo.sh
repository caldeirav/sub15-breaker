#!/usr/bin/env bash
# Installed-stack launcher: validate the lock, never install or upgrade on reboot.
set -euo pipefail
cd "$(dirname "$0")/.."
command -v uv >/dev/null || { echo 'Missing uv; follow docs/demo.md first-time setup.' >&2; exit 1; }
export UV_PYTHON_DOWNLOADS=never
uv lock --check
uv sync --locked --check
exec uv run --locked --no-sync python -m src.infra.run_demo "$@"
