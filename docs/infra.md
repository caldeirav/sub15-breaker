# Local environment and operation

[Quick start](../README.md#run-locally) · [Architecture](architecture.md)
· [Demo](demo.md) · [Full validation](validation.md)

## Prerequisites and supported profile

Run commands from the repository root. Offline development requires Git, uv and
Python3.11–3.13. The live measured profile is macOS/Apple Silicon, rootful Podman
with cgroupv2, a dedicated single-node Kind cluster and gVisor Actors. Native-host
MPS inference and the Linux VM are different execution environments; do not
assume MPS exists in cluster containers. Other hosts/backends need qualification.

Allow at least8GiB VM memory (16+ recommended), several cores and substantial disk
for images/toolchains; the measured host has48GiB unified memory. Install Podman
and uv separately. Review shared VM/connection changes with the operator—setup
does not authorize replacing a machine, upgrading global helpers or deleting data.

Authoritative pins: [`infra/versions.json`](../infra/versions.json), compatibility/
review exceptions: [`infra/version-policy.json`](../infra/version-policy.json).

| Component | Reviewed pin |
| --- | --- |
| Podman host/guest; krunkit |5.8.9;1.3.2 |
| Guest OS |Fedora CoreOS44.20260928.3.2, digest-bound |
| Kind; Kubernetes |0.33.0;1.37.0, digest-bound node |
| kubectl; Helm; Go |1.37.0;3.22.1;1.27.3 |
| Cilium; Gateway API; agentgateway |1.20.4;1.7.0;1.7.0 |
| Substrate / kubectl-ate |1.0.0-rc.1, checkout `f86fde9dfb5424c8d16f613de80469bdbef06541` |
| LM Studio; MLX engine |0.4.28+2;1.13.1 |
| Acting/reviewer model |Qwen3-30B-A3B-Instruct-2507 MLX4-bit, identifier `qwen/qwen3-30b-a3b-2507`, loaded context8192 |

Pins describe a tested baseline, not latest-release recommendations or proof of
what is currently running. Check freshness without installing/upgrading:

```bash
uv run --locked python -m src.infra.releases
```

Expired exceptions, drift or inaccessible metadata fail the relevant check. A
passing release check is not runtime/availability acceptance. On macOS the actual
loaded krunkit helper is checked separately; an unrelated PATH binary is not proof.
The preflight rejects known-risk helpers below1.3.1. Do not automatically restart
a disappearing VM and call recovery a stability pass.

## 1. Install dependencies and project tools

```bash
uv python install
uv sync --locked
podman machine list
```

Only if no suitable machine exists, explicitly provision one:

```bash
podman machine init --cpus 8 --memory 16384 --disk-size 100
podman machine start
```

If an existing machine is stopped, start only the intended machine. The supported
connection must be rootful; changing that mode requires an operator-approved stop,
`podman machine set --rootful MACHINE_NAME` and restart, accounting for other
workloads. Do not make this change blindly on an active shared machine.

```bash
podman info
bash scripts/install_tools.sh --with-go
bash scripts/check_env.sh
export PATH="$PWD/.tools/bin:$PATH"
```

Tools download into `.tools/`, with upstream HTTPS checksums and pinned source;
they do not replace system binaries/shell profiles. Python dependencies remain in
`pyproject.toml`/`uv.lock`; use uv, not ad hoc pip/requirements files.

## 2. Create/verify the owned stack

```bash
bash scripts/setup_infra.sh
bash scripts/setup_infra.sh verify
bash scripts/setup_infra.sh network-check
bash scripts/setup_infra.sh enforcement-check
```

Setup creates only the dedicated `breaker-substrate` cluster and private
`.infra/clusters/breaker-substrate/kubeconfig`; it installs Cilium, Gateway API,
agentgateway and Substrate from its checked clean pinned checkout/release images.
Kind starts without waiting for NodeReady until Cilium is installed. Required
certificate APIs/feature gates and actual rollout/authenticated API readiness are
verified. Gateway `Programmed` or CRD existence alone does not prove readiness.

Ownership binds the selected provider and immutable node-container IDs. A
same-named replacement or changed connection rejects before adoption/deletion.
Failures never auto-delete a cluster or retained state. A partially created,
unowned node needs operator inspection, not edited ownership markers. Resume
owned installation by `cluster`, `controllers`, `substrate` or `verify` phases.
`--skip-substrate` is explicitly partial, not full-stack acceptance.

The enforcement check creates the owned fixture namespace/Gateway reused by
`target_stack --configure`; installing the controller alone does not create it.
These checks make no model calls. Network checks require healthy positive controls
before/after the negative paths; the recorder accepts non-executing sentinels only.

Substrate installs trusted PostgreSQL, snapshot storage, certificate/API/identity/
router/atelet services. Those privileged infrastructure processes are not agent
sandboxes. Bootstrap global-owner identity is for the disposable local operator,
not a shared production trust model. A scoped installer-only Docker adapter uses
Podman; no global Docker alias/socket is replaced.

## 3. Configure model, tracking and banking service

Create `.env` from `.env.example` only if absent; preserve existing secrets.

| Setting | Live harness use |
| --- | --- |
| `LM_STUDIO_BASE_URL` |Configured upstream provider, typically `http://localhost:1234/v1`; agent requests still use managed gateway |
| `LM_STUDIO_MODEL` |Exact approved loaded identifier; set `qwen/qwen3-30b-a3b-2507` for the measured profile |
| `MLFLOW_TRACKING_URI` |HTTP tracking server, normally `http://localhost:5001` |
| `GEMINI_API_KEY` / supported `GOOGLE_API_KEY` fallback |Authorized external native review only; not needed for offline tests/replay |
| `MLFLOW_GENAI_JUDGE_DEFAULT_MODEL` |Pinned external review profile, default `gemini:/gemini-2.5-flash` |
| `LITELLM_LOCAL_MODEL_COST_MAP=True` |Use bundled lock-bound pricing, not remote import-time pricing downloads |

The benchmark selects experiment **`breaker-banking-target-agent`**. The older
`BANKING_MLFLOW_EXPERIMENT` setting belongs to the compatibility feasibility runner.
Start MLflow only if absent, using the [README command](../README.md#run-locally).
Do not replace the existing database/artifact store just to get an empty experiment.

Build/deploy the banking service, then configure and verify the managed model/MCP/
OTLP infrastructure (no generation or banking tool execution; these commands do
mutate owned deployment/gateway resources):

```bash
bash scripts/build_banking_image.sh
uv run --locked python -m src.banking_service.deploy \
  --image "$(cat .infra/banking-service-03b/image.reference)" \
  --deadline-profile native-measure-v2 --max-trials 256
uv run --locked --env-file .env python -m src.infra.target_stack --configure
```

`target_stack --configure` requires the owned banking-driver ServiceAccount, so
banking deployment comes first on a fresh stack. On an existing deployment refresh
credentials as needed and verify the current digest/profile instead of rebuilding
or replacing the store merely to renew tokens.

The build uses the locked `banking-service` group, nonroot/read-only/least-capability
runtime, a project-owned local registry on port5002 and a digest-bound image. Port5001
remains for MLflow. Deployment provisions project namespaces/identities/store/PVC/
WorkerPool/templates; it preserves the existing key and historical rows. A new
image digest is a new run binding—not the old demo's image/evidence.

Driver credentials expire after one hour. Renew only owned credentials:

```bash
uv run --locked python -m src.banking_service.deploy --refresh-credentials
```

This verifies ownership, mints audience-bound tokens and atomically writes private
files, without replacing deployments/PVC/key/history. Never paste tokens in argv,
docs, public trace exports or a browser app. The read-only demo API has a different
limited-purpose token.

### Artifact handoff is still required

Live runs require more than checkout/setup: a complete verified classifier export
(`benchmark-guard.json`, exact weight/config/tokenizer files), compatible reviewed
original corpus, hybrid/training provenance, regression selection artifacts and
the **existing cumulative v4 budget ledger**. Defaults expect these under
`.infra/benchmark-guard-harness/`, notably `modernbert-training-v1/model/`,
`modernbert-initial-validation/` and `combined-budget/`. `accuracy.py` validates
source/training exclusions; an arbitrary JSONL/weights directory is not enough.

Obtain the reviewed bundle/operator handoff, verify hashes/permissions and retain
its relative layout. Frozen artifacts can contain absolute provenance paths;
relocation needs a deliberate compatible handoff, not edits to source manifests.
Weights/keys/raw traces are not committed. No clean-checkout download/import or
installed-console release is claimed (#10). Never fill a missing trained head
with a base/random checkpoint or recreate a ledger to reset spending.

## Checks before a fresh approved run

```bash
uv run --locked --env-file .env python -m src.banking_service.runtime_controls
```

These change owned fixture/runtime resources and synthetic state, but make no
model/judge calls. Network checks need healthy positives before/after negative
paths; only a connect-timeout establishes the tested network denial. Enforcement
fixtures use non-executing sentinels, not bank actions or a shell. Runtime controls
exercise actual Actors/tools, reset/idempotency/crash/store-restart/outbox behavior;
they consume durable capacity and need explicit scheduling, not blind repetition.

Before model spending, verify current deployment/image/profile, loaded/idle Qwen,
tracking, artifact/ledger integrity, whole-campaign capacity and the non-effectful
MCP transport batch. The modern startup gate additionally reserves real model
protocol probes and classifier priming. **List/dry-run is only an inventory and
planning-envelope preview; it does not validate these prerequisites.**

The legacy `check_env.sh --research` expects a command-only sidecar; it is not a
banking doctor. `--target-stack` is a stricter qualification workflow including a
complete provider-window proof; the owner-deferred soak means it must not be
misrepresented as passed or required for the already delivered functional demo.

## Deadlines and transport

`banking_service/deadlines.py` defines `native-measure-v2`:

| Boundary | Seconds |
| --- | ---: |
| Acting/reviewer client |300 |
| Model backend / route |315 /330 |
| Native learned hook / fault-control hook |330 /2 |
| Actor store claim |350 |
| Tool worker / reap allowance / commit |15 /5 /10 |
| Actor server / client |390 /410 |
| MCP backend / client / route |430 /450 /470 |
| Ticket / episode / reconciliation |900 /3600 /120 |

These are upper allowances, not expected performance or completion guarantees.
Route and backend timeouts are separate; long response time does not override
TCP connect. The demo protocol additionally declares30s MCP connect, HTTP/1.1
reuse, backlog128, at most32 connections,45s idle/header/body I/O timeout and128
requests per connection. It verifies applied **and effective** gateway configuration
and restores owned originals. The generic full-comparison path is not identical
to the demo's transport-probe/connect policy; do not silently claim it is.

## Inspection, cleanup and deferred reliability

```bash
export KUBECONFIG="$PWD/.infra/clusters/breaker-substrate/kubeconfig"
kubectl get nodes -o wide
kubectl get pods -A
kubectl ate get atespaces -o json
```

No global kube context change is needed. Each experiment fences/drains its work,
deletes only UID-verified owned Actors and restores temporary hook/routes. Check
the recorded cleanup and late state; resource restoration is not rollback of a
committed effect. Keep receipts, SQLite/PVC and key together. Do not prune trials,
delete markers, reset reservations or delete the store to make another run fit.

Only if explicitly intending to destroy this owned cluster and its workload
storage:

```bash
bash scripts/setup_infra.sh destroy --confirm breaker-substrate
```

This is destructive, not normal demo cleanup, and does not authorize deleting
other machines/clusters/images/volumes. The interrupted two-hour stability check
remains deferred [#39](https://github.com/caldeirav/sub15-breaker/issues/39), not a
pass. A separately approved new monitor directory is required for sustained-uptime
claims; no automatic recovery, skipped samples or fresh inference is implied.
