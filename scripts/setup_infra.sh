#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
for cmd in uv podman kind kubectl kubectl-ate; do command -v "$cmd" >/dev/null || { echo "Missing $cmd" >&2; exit 1; }; done
uv lock --check || { echo 'Dependency lock is missing or stale; run uv lock and commit uv.lock.' >&2; exit 1; }
if grep -q REPLACE_WITH k8s/workerpool.yaml k8s/actor-template.yaml k8s/decision-sidecar.yaml; then
  echo 'Configure image placeholders and the executor before provisioning; see README.md.' >&2
  exit 1
fi
podman info >/dev/null
export KIND_EXPERIMENTAL_PROVIDER=podman
cluster=${KIND_CLUSTER_NAME:-breaker-substrate}
if ! kind get clusters | grep -Fxq "$cluster"; then kind create cluster --name "$cluster"; fi
context="kind-$cluster"
for crd in workerpools.ate.dev agentgatewaypolicies.agentgateway.dev httproutes.gateway.networking.k8s.io; do
  kubectl --context "$context" get crd "$crd" >/dev/null 2>&1 || { echo "Required CRD $crd is not installed; install the matching controllers first." >&2; exit 1; }
done
kubectl --context "$context" apply -f k8s/workerpool.yaml -f k8s/decision-sidecar.yaml -f k8s/agentgateway-hook.yaml
kubectl --context "$context" ate create actor-template -f k8s/actor-template.yaml
