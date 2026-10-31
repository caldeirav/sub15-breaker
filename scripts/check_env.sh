#!/usr/bin/env bash
set -uo pipefail
cd "$(dirname "$0")/.."
status=0
for cmd in podman kind uv kubectl kubectl-ate curl; do
  if command -v "$cmd" >/dev/null 2>&1; then echo "OK $cmd"; else echo "MISSING $cmd"; status=1; fi
done
if command -v uv >/dev/null 2>&1; then
  if uv lock --check && uv sync --locked --check; then
    echo 'OK uv lock and project environment'
  else
    echo 'MISSING uv project environment or current lock (run uv lock if needed, then uv sync --locked)'
    status=1
  fi
fi
if podman info >/dev/null 2>&1; then echo 'OK podman service'; else echo 'MISSING podman service'; status=1; fi
if curl -fsS --max-time 2 http://localhost:1234/v1/models >/dev/null; then echo 'OK LM Studio :1234'; else echo 'MISSING LM Studio :1234'; status=1; fi
if curl -fsS --max-time 2 http://localhost:5001/health >/dev/null; then echo 'OK MLflow :5001'; else echo 'MISSING MLflow :5001'; status=1; fi
if [[ -f .env ]]; then echo 'OK .env'; else echo 'MISSING .env (copy .env.example)'; status=1; fi
exit "$status"
