# Block 01: infrastructure manual acceptance

**Human acceptance: PASSED (user-reported, 2026-10-31). Ready for PR publication after final automated checks.**

Tester: the repository owner, using the independent-terminal checklist supplied in this conversation. The owner confirmed: “All tests passed successfully.” This records the user's sign-off, not an agent-inferred result. No raw manual transcript was supplied. Source-level safeguards below rely on their automated regression tests rather than an assertion that every failure was separately injected by hand.

Scope: pinned Podman/Kind/Cilium/agentgateway/Substrate foundation and non-executing network/enforcement fixtures. No real shell execution, model training, Actor reset, or Actor termination is accepted by this block.

## Recorded automated results (2026-10-31)

- 58 unit/regression tests passed on each of Python 3.11, 3.12, and 3.13 on the macOS/arm64 host.
- Clean-cluster full infrastructure readiness passed at 07:29:48 UTC, with no skipped Substrate checks.
- All 6 network ingress/egress controls passed at 07:31:44 UTC.
- All 20 non-executing gateway cases passed at 07:34:17 UTC, including authorizer outage/recovery and direct-recorder bypass checks.
- Repeat full setup and owned-cluster reuse were exercised; independent code review confirmed all reported fixes.
- GitHub CI results are tracked separately on the PR. These local automated observations alone are not human sign-off or proof of Actor isolation; the separate user acceptance is recorded above.

These timestamps describe the current local reports, not permanent guarantees. Rerun after relevant changes and independently inspect the deployed state.

## Automated prerequisites

```bash
uv run --locked python -m pytest -q
bash scripts/check_env.sh
bash scripts/setup_infra.sh verify
bash scripts/setup_infra.sh network-check
bash scripts/setup_infra.sh enforcement-check
git diff --check
```

Do not proceed on failed prerequisites. Review the current `.infra/clusters/breaker-substrate/*.json` reports; record their timestamps and version pins. The code under test must match the final reviewed diff. Human results cannot be inferred from an agent-run harness.

## Independent human checks

Set these in a new terminal at the repository root:

```bash
export PATH="$PWD/.tools/bin:$PATH"
export KUBECONFIG="$PWD/.infra/clusters/breaker-substrate/kubeconfig"
```

| Check | Manual procedure | Expected result | Human result / evidence |
| --- | --- | --- | --- |
| Cluster identity | `kubectl config current-context`; `kubectl get nodes -o wide` | `kind-breaker-substrate`, one Ready arm64/v1.37.0 node in this environment. | Passed (user report) |
| Control plane | `kubectl get pods -A`; `kubectl get gatewayclass agentgateway -o yaml` | No failing required workloads; GatewayClass Accepted at current generation. | Passed (user report) |
| ATE API | `kubectl ate get atespaces -o json` | Authenticated response, possibly `{}` before any ATE space exists. The shared-owner warning is expected only for this local install. | Passed (user report) |
| Network policy | `kubectl get networkpolicy -n breaker-netcheck`; repeat the commands below | Positive controls succeed; unauthorized paths time out, not merely fail due to a dead server. | Passed (user report) |
| Gateway evidence | `kubectl get gateway,httproute,agentgatewaypolicy -n breaker-enforcement -o yaml`; `kubectl get pods -n breaker-enforcement` | Current conditions accepted and the gateway **pod** Ready, not only Gateway Programmed. | Passed (user report) |
| Forwarding vs denial | Repeat the sentinel requests below, inspect recorder before/after | One new receipt on allow, zero on denial or missing credentials; `executed:false`. | Passed (user report) |
| Direct bypass | Probe recorder Service and Pod IP from the fixture client | Both connection attempts time out. | Passed (user report) |
| Authorizer outage/recovery | Stop the fixture authorizer, attempt approval, restore it, repeat | Zero new receipts during outage; one new receipt after recovery. | Passed (user report) |
| Artifact hygiene | Inspect `git status --short`; `git check-ignore .infra/clusters/breaker-substrate/kubeconfig .tools/bin/kubectl` | No kubeconfig, secret, upstream checkout, MLflow artifacts, or tool binaries staged for commit. | Passed: local ignored-path and staged-file review, separate from user attestation |
| Idempotence | `bash scripts/setup_infra.sh` then rerun verification and both harnesses | Same cluster retained, no unexpected context change, all checks still pass. | Passed (user report) |

### Inspect ingress and egress controls independently

```bash
TARGET=$(kubectl get pod target -n breaker-netcheck -o jsonpath='{.status.podIP}')
CONTROL=$(kubectl get pod control -n breaker-netcheck -o jsonpath='{.status.podIP}')
kubectl exec -n breaker-netcheck trusted -- python -B /probe/probe_client.py "$TARGET" 8080
kubectl exec -n breaker-netcheck untrusted -- python -B /probe/probe_client.py "$CONTROL" 8080
kubectl exec -n breaker-netcheck untrusted -- python -B /probe/probe_client.py "$TARGET" 8080
kubectl exec -n breaker-netcheck trusted -- python -B /probe/probe_client.py "$CONTROL" 8080
```

Expected `reachable`: true, true, false/timeout, false/timeout. Repeat the two positive controls afterwards. A missing pod, exec error, refused connection, or malformed response is **not** a passing negative test.

### Inspect one approval, one denial, and authentication

```bash
GATEWAY=$(kubectl get service breaker-gateway -n breaker-enforcement -o jsonpath='{.spec.clusterIP}')
ALLOW=$(printf '%s' '{"command":"fixture:allow"}' | base64)
DENY=$(printf '%s' '{"command":"fixture:deny"}' | base64)
kubectl exec -n breaker-enforcement deployment/fixture-recorder -- python -B -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8080/records').read().decode())"
kubectl exec -n breaker-enforcement client -- python -B /probe/http_probe.py "http://$GATEWAY:8080/execute" "$ALLOW" valid
kubectl exec -n breaker-enforcement client -- python -B /probe/http_probe.py "http://$GATEWAY:8080/execute" "$DENY" valid
kubectl exec -n breaker-enforcement client -- python -B /probe/http_probe.py "http://$GATEWAY:8080/execute" "$ALLOW" none
kubectl exec -n breaker-enforcement deployment/fixture-recorder -- python -B -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8080/records').read().decode())"
```

Expected: first request 200 with `executed:false`; the other two non-2xx. Exactly one new receipt between the two record snapshots. These sentinels are not Bash commands and must not be replaced with golden destructive payloads.

## Findings -> regressions -> sign-off

Record each finding, root cause, added automated test, rerun result, and any documentation change. Confirmed findings and automated regressions are summarized below; they are not a substitute for human checks.

| Finding | Regression / resolution | Human verification |
| --- | --- | --- |
| Waiting for CNI readiness before installing it | Kind uses `--wait 0s`; cluster-creation regression checks ordering. | Block accepted with passing automated coverage |
| Non-executable scoped Podman adapter | Adapter executable mode checked by the test suite. | Block accepted with passing automated coverage |
| Gateway Programmed but proxy unready; XDS blocked | Explicit proxy rollout wait plus scoped TCP 9978 egress; manifest and readiness regressions. | Healthy deployment confirmed in manual checklist |
| Request-header removal erased the authorization grant | Fixture rejects caller-supplied grants instead; live approval/forgery and byte-binding tests cover the path. | Approval/denial behavior confirmed; forgery covered automatically |
| Same-named replacement could reuse a local ownership record | Provider/node-container identity binding and replacement-deletion regression. | Automated negative test; manual idempotence confirmed |
| Post-connect response stalls looked like denied connectivity | Only connect-timeout is accepted; send/receive-stall regressions fail closed. | Automated stall tests; manual network controls confirmed |
| Untracked installer source and ambiguous partial readiness | Strict checkout checks and explicit performed/skipped/observed evidence regressions. | Block accepted with passing automated coverage |
| Shell syntax check only inspected its first file | Per-file checks and a later-invalid-script regression. | Block accepted with passing automated coverage |
| Additional findings | None reported by the user | No outstanding manual finding reported |

The owner's sign-off is recorded in [`block-01.json`](block-01.json). Before publishing the PR, rerun the final automated checks and publication guard:

```bash
uv run --locked python -m src.infra.gate docs/validation/block-01.json
```

This local publication guard must pass before publishing the block PR. It checks the recorded approval fields, not the truth of an attestation; it is not a substitute for human review or a configured GitHub branch-protection rule. Do not mark #1/#4 fully closed: Actor execution/reset, full request-framing/timeout coverage, and production identity remain later acceptance work.
