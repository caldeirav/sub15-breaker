# Actor-backed synthetic banking service

This local research profile executes the pinned AgentDojo banking functions in gVisor Actors. It uses a separate trusted service for durable synthetic state, idempotency receipts and an evidence outbox. It is not financial authorization, an agentgateway A/B verifier, a production identity/key-management system or a high-availability database.

Delivery progress and acceptance are tracked in [roadmap #14](https://github.com/caldeirav/sub15-breaker/issues/14), [Actor lifecycle #1](https://github.com/caldeirav/sub15-breaker/issues/1) and [transaction semantics #23](https://github.com/caldeirav/sub15-breaker/issues/23). This guide describes the service boundary and operating assumptions; unit tests and image builds do not establish actual Actor acceptance.

## Authority and persistence

```text
controlled driver / opt-in local agent
  -> authenticated prepare -> trusted state/receipt service -> SQLite on owned PVC
  -> authenticated Actor request containing only an opaque action ticket
       Actor -> platform egress injects Actor JWT -> claim owned ticket/snapshot
       Actor -> pinned upstream function on private snapshot
       Actor -> authenticated commit of proposed result/state
  -> atomic state + receipt + outbox transaction -> bounded result/status
  -> verified MLflow export -> outbox acknowledgment
```

Authoritative state lives **outside disposable Actors**. An Actor computes a proposed transition; the trusted transaction service publishes its synthetic effect. Its current Actor UID, trial generation, expected state version, deadline and single in-flight ticket fence the commit. An Actor's Python return or an HTTP 200 alone is not a committed effect.

Each trial has isolated logical state. A fresh Actor/generation on reset restores the pinned initial snapshot, verifies its keyed fingerprint and invalidates old tickets. Completed receipts remain queryable after replacement. Pending/uncertain attempts must be reconciled or fenced; they must not be blindly executed again.

The SQLite profile uses WAL, FULL synchronization and bounded action/event storage on a dedicated PVC with one active service replica. It covers service-process restart and retained history across Actor replacement. The local StorageClass is node-local: no HA, host/VM/node/disk-loss recovery, backup or distributed exactly-once guarantee is claimed. No workload mounts a host directory or reuses Substrate's PostgreSQL credentials. Actor `durableDir` snapshots and Actor-owned external volumes alone do not provide retained per-action receipts after Actor deletion.

## Authentication and confinement

- The operator provisions a dedicated driver ServiceAccount and an atespace-editor role limited to the project's atespace. Bootstrap global-owner credentials are used only by the operator for initial provisioning, never by the service or Actor.
- Driver requests require a Kubernetes-signed JWT with the configured issuer, audience, exact subject and lifetime. Actor callbacks require an injected Substrate Actor JWT with the expected issuer/audience/subject, Actor claim kind and current UID. Caller-selected key URLs are not used.
- Public JWKS are obtained through the authenticated cluster API and provisioned as verification configuration. Unknown/rotated keys fail closed until configuration is refreshed; a token is not accepted because its unverified claims look plausible.
- The operator's loopback `kubectl-ate proxy` uses the install's existing `atenet-client` mTLS transport identity. The separate banking-driver JWT is still required by the application. The proxy credential is not given to the model, and this local operator path is not a general-purpose gateway rollout.
- The Actor can egress only to the dedicated store. Platform egress injects its Actor JWT without putting platform private keys or global-owner credentials in the workload. The local profile's egress-to-store HTTP segment is inside the trusted cluster network; this is not an end-to-end encrypted production transport claim.
- The pinned runtime does not apply OCI working directory or user defaults as an ordinary container engine does, and its private overlay root starts with mode 0700. The image sets an absolute Python module path. Before dropping privileges, its entry point restores only that private guest root to the image's read/execute mode 0555; no recursive/shared-cache/host permission change is made. It then drops to UID/GID 10001, clears effective capabilities and enables `no_new_privs` before importing/serving the application. Only SETUID/SETGID are available during that startup transition. The live probe checks the resulting identity, capabilities and absence of an ambient Kubernetes token.
- Actual platform assignment, worker UID, Actor-UID-correlated gVisor logs and the in-sandbox probe are required together. A desired WorkerPool sandbox class or image `USER` line is insufficient.

This is a controlled execution profile. Native Substrate ingress is not the later authoritative agentgateway financial-policy boundary. No untrusted general client is granted the driver credential.

## Tool and evidence semantics

All 11 argument schemas come from the pinned suite. The opt-in Actor-backed agent sees canonical decimal-string amount schemas directly; it cannot silently submit binary floats as exact-money claims. The explicit compatibility adapter rejects decimal round-trip loss before admission. Reads and writes both require authenticated tickets and bounded arguments/results.

Upstream functions operate on synthetic state only; `read_file` is the benchmark's simulated file tool, not a host filesystem executor. A bounded child process computes each transition in the Actor. A tool exception does not publish a partially changed snapshot. The service has no shell endpoint and must never fall back to local host tool execution when the Actor is unavailable.

State, receipt and outbox rows commit atomically. Identical completed retries return the original receipt, including when the caller's old expected state version precedes that completed write. Changed-payload ID reuse fails. Concurrent duplicate claims cannot create parallel authoritative mutations. Tool invocation and committed effect are separate facts; private computation may be interrupted without a committed effect.

The outbox records attempted tools before their computation and preserves results/lifecycle evidence. The local-model adapter also persists model attempts/results before giving results to the agent loop. Outbox capacity/persistence failure blocks new work. An MLflow outage leaves evidence pending, not a successful acceptance result. Export checks exact event contents and CODE ownership before acknowledgment; duplicate/ambiguous exports block reconciliation rather than disappear into averages.

Private state, synthetic passwords and identity tokens are not public trace data. Export uses explicit redaction and keyed state fingerprints; raw provider/runtime exceptions are not returned as evidence. Public identifiers and verification keys are distinct from secrets. Arbitrary secret detection is not claimed.

## Local operation

Use the existing owned local cluster from [the infrastructure guide](infra.md). Starting it does not authorize recreation, provider changes, unrelated-container operations or component upgrades. The deployment checks immutable ownership before mutation. Keep local credentials, manifests containing Secret data and runtime logs under ignored `.infra/` paths.

Build the role-specific image and publish it to the owned development registry:

```bash
bash scripts/build_banking_image.sh
```

The registry binds localhost port 5002, leaving MLflow's 5001 unchanged. The script refuses to adopt an unrelated `kind-registry`, pins its image and imports the exact banking image digest for the store pod. Actor pulls use the existing Substrate localhost-registry rewrite. The Actor/store image installs only the locked `banking-service` dependency group, not training/dashboard dependencies; there are no runtime dependency downloads.

Deploy using the generated digest-bound reference:

```bash
uv run --locked python -m src.banking_service.deploy \
  --image "$(cat .infra/banking-service-03b/image.reference)"
```

The deployment creates only project-owned banking namespace resources, a single-writer store/PVC, scoped identities, a gVisor WorkerPool and immutable Actor templates. It does not apply the legacy sidecar manifests or alter the original in-memory banking runner. Receipts/keys must be retained together; a changed durable-store key blocks startup rather than silently changing fingerprints.

Driver credentials expire after one hour. After an approved infrastructure
recovery, renew the owned credentials without rebuilding the image, redeploying
the service or replacing its durable state:

```bash
uv run --locked python -m src.banking_service.deploy --refresh-credentials
```

Renewal checks cluster/resource/ServiceAccount ownership, mints both audience-bound
tokens before replacing either file, and writes private files atomically. Tokens
are never passed in command arguments or printed. It is operator-mediated local
renewal, not a production credential-rotation service or proof that Actor/tool
traffic is healthy.

Run the explicit positive actual-Actor canary, without model calls:

```bash
uv run --locked --env-file .env python -m src.banking_service.validation
```

This entry point declares its narrow control matrix in MLflow and is **not full service acceptance**. Lifecycle, restart, isolation, failure and live-agent validations need their own declared matrices and persisted readback. Model/judge trials must honor the owner's explicit budget; no retries for favorable outcomes or agreement.

The broader provider-free runtime matrix includes authenticated isolation, identical replay versus changed payload, fresh-generation reset, persistent-store pod restart and unavailable MLflow export. Dedicated immutable fault templates terminate the Actor after claiming an action or after committing its state/receipt, demonstrating unknown versus reconciled completed outcomes without a request-controlled fault switch:

```bash
uv run --locked --env-file .env python -m src.banking_service.runtime_controls
```

The opt-in live adapter has a separate, explicit paid-call entry point:

```bash
uv run --locked --env-file .env python -m src.banking_service.live \
  --controls-run CONTROLS_RUN_ID --execute-authorized-live-budget
```

It requires a completed, exact-matrix runtime-control run whose deployment matches both configured and observed ready images/ownership. Each live Actor must independently pass runtime/probe checks before budget reservation. It permits only the configured native Gemini provider for the authorized reviews, and uses exclusive on-disk reservations for the three local trials and twelve criterion reviews. Existing reservations block resampling; do not remove them to obtain a preferred result. Judge attempts/results, as well as acting-model and tool evidence, enter the durable outbox. A successful summary is published only after final export/readback succeeds. None of these controls is a financial-policy decision or human acceptance.

Cleanup must verify recorded Actor UIDs. Store/export failure cannot prevent an independent cleanup attempt, mask the primary failure or justify deleting another resource. Incomplete cleanup/export remains visible and blocks acceptance. The persistent store is not deleted with an Actor; deleting retained state requires a separate explicit operator decision.
