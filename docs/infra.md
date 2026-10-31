# Local infrastructure and validation

This is block 01 of the [implementation roadmap](https://github.com/caldeirav/sub15-breaker/issues/14). It establishes a reproducible local control plane and tests network/gateway behavior with **non-executing fixtures**. It does not implement the shell executor, per-trial Actor reset, learned safety weights, or Actor termination. Do not run the destructive golden suite yet.

**Banking scope update:** the [current target](project-scope.md) reuses simulated banking tools rather than building a generic shell executor. This foundation remains valid infrastructure evidence, but it does not deploy a banking Actor service, transactional state/reset or a banking gateway verifier. The [local pilot](banking-feasibility.md) bypasses that distributed boundary by design and is not infrastructure acceptance. Follow the revised [block dependencies](implementation-plan.md) before enabling real workloads; no live bank APIs or payment credentials are needed.

## Supported profile and trust boundaries

The initial validation environment is macOS/Apple Silicon, a rootful Podman machine with cgroup v2, and a dedicated single-node Kind cluster. The scripts support downloading macOS/Linux arm64/amd64 binaries, but other host combinations need their own live validation. Allow at least 8 GiB VM RAM (16+ recommended), several CPU cores, and substantial free disk for cluster/control-plane images and Go caches. No KVM is needed for the intended gVisor path; microVMs and native-host MPS are not part of this profile.

Pins are in [`infra/versions.json`](../infra/versions.json):

| Component | Pin |
| --- | --- |
| Kind / Kubernetes | v0.33.0 / v1.37.0, node image pinned by digest |
| kubectl / Helm / Go | v1.37.0 / v3.20.1 / go1.27.3 |
| Cilium | 1.20.4, kube-proxy retained, Kubernetes IPAM |
| Gateway API / agentgateway | v1.7.0 / v1.7.0 |
| Substrate / kubectl-ate | v1.0.0-rc.1, checkout commit pinned |
| Probe image | Python 3.12 slim Bookworm, multi-architecture digest pinned |

The Kind configuration enables ClusterTrustBundle, ClusterTrustBundleProjection, PodCertificateRequest, and the certificates v1beta1 API required by this Substrate release. It disables the default CNI so Cilium can enforce NetworkPolicy. **Kind must not wait for NodeReady before Cilium installation**: nodes need the CNI to become ready. The script waits after installation instead.

Infrastructure installers necessarily create privileged Kubernetes/Kind components such as Cilium and Substrate's node agent. Those trusted infrastructure processes are not agent sandboxes. The benign probe workloads run nonroot with read-only root filesystems, dropped capabilities, bounded resources, and no ambient Kubernetes service-account token. The gateway additionally uses its chart's explicitly scoped XDS token projection. No arbitrary shell executor is deployed by setup.

## Install tools and start Podman

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), Podman, git, and curl first. On macOS, install Podman using its official installer or your package manager, then initialize/start a machine if needed:

```bash
podman machine list
# Only if no machine exists:
podman machine init --cpus 8 --memory 16384 --disk-size 100
# If the machine is stopped:
podman machine start
podman info
```

The validated profile uses a rootful connection. If yours is rootless, explicitly stop that machine, use `podman machine set --rootful MACHINE_NAME`, and start it again. This changes your machine's default connection, so review the effect on other workloads; the project scripts do not make that host-wide change automatically. A stopped or unreachable provider fails preflight without deleting anything.

```bash
uv python install
uv sync --locked
bash scripts/install_tools.sh --with-go
bash scripts/check_env.sh
```

The installer downloads pinned Kind, kubectl, Helm, and kubectl-ate binaries into ignored `.tools/bin`, checking upstream SHA-256 files before installation. `--with-go` also installs the exact upstream Go toolchain used by Substrate's installer. These are system/Go tools, not Python dependencies; all project Python dependencies still use uv. Release checksums are downloaded over HTTPS from upstream, not independently signed attestations. Tool installation is local, not a replacement of your system binaries or shell profile.

Scripts prepend `.tools/bin`. For interactive commands:

```bash
export PATH="$PWD/.tools/bin:$PATH"
```

## Create or repair the dedicated cluster

```bash
bash scripts/setup_infra.sh
```

Setup creates only `breaker-substrate`, using ignored `.infra/clusters/breaker-substrate/kubeconfig`, installs Cilium, Gateway API and agentgateway, then installs Substrate from the pinned release checkout using prebuilt release images. It checks the checkout commit and rejects tracked modifications, untracked files, and ignored artifacts before executing installer code. Go caches stay outside that checkout. No local image registry is needed; in particular, port 5001 remains available for MLflow. The upstream installer also records its configuration in the user's normal ate-setup cache; treat those files as local operator artifacts, not version-controlled evidence.

The upstream Substrate Kind installer invokes `docker info`. A **scoped** `scripts/libexec/docker` adapter forwards that command to Podman only within the installer's environment. No global Docker alias, socket, or executable is replaced. Prebuilt-image installation avoids Docker buildx/ko builds.

Substrate's release installer supplies PostgreSQL, RustFS snapshot storage, certificate controller, API server, router/egress, identity service, and atelet. Credential injection is disabled. Its ingress allowlist initially admits only the local `atenet-client` identity. The default `ate-client` bootstrap identity used by kubectl-ate is a **global owner of this disposable local install**, not a production authorization setup. Do not grant untrusted workloads Kubernetes token-minting/exec privileges or reuse this install as a shared platform. The Substrate router currently uses its default Envoy dataplane; the separate agentgateway controller is for the breaker HTTP authorization tests. Installing that controller does not automatically put it in front of every Actor.

Setup is idempotent for the same owned node configuration. Ownership is bound to a hashed Podman connection identity and immutable node-container IDs, not merely a retained local name. A changed provider or same-named replacement is rejected before adoption, kubeconfig refresh, or deletion. A change to the node image/Kind configuration requires explicit destruction/recreation. Existing unrelated clusters are not touched. `kagenti` was removed once during this environment repair with explicit user authorization; deleting it is **not** part of the reusable setup.

Creation never automatically deletes anything on failure. If Kind creation is interrupted before the ownership identity is recorded, inspect the partial node containers and explicitly remove only the intended incomplete cluster before retrying; setup refuses to silently claim it. A normal controller/install failure after ownership is recorded can be resumed by phase. Keep the marker and private kubeconfig together; do not edit an identity mismatch away to force adoption.

For staged diagnosis:

```bash
bash scripts/setup_infra.sh cluster
bash scripts/setup_infra.sh controllers
bash scripts/setup_infra.sh substrate
bash scripts/setup_infra.sh verify
```

`verify` checks rollouts, current GatewayClass acceptance, established CRDs, certificate APIs, Substrate services, and an authenticated read-only ATE API call. It server-dry-runs the updated WorkerPool example; it does not create a WorkerPool or Actor. A successful process exit, CRD creation, or Gateway `Programmed` condition alone is not treated as end-to-end readiness.

An explicit `--skip-substrate` on setup/verify limits that run to the networking/controller foundation. It is not a passing result for the full foundation block.

## Run independent network and gateway checks

```bash
bash scripts/setup_infra.sh network-check
bash scripts/setup_infra.sh enforcement-check
```

`network-check` creates restricted, benign HTTP/client pods in `breaker-netcheck` and proves:

- trusted client -> target succeeds;
- untrusted client -> control succeeds;
- untrusted client -> target times out (ingress denied);
- trusted client -> control times out (egress denied);
- both positive controls still succeed after the negative checks.

It connects to actual pod IPs and requires successful positive controls, so an unavailable server cannot masquerade as isolation. Only a timeout while **establishing the connection** counts as a denied path. A post-connect send/response stall, unrelated exec error, or connection refusal fails the check rather than counting as isolation.

`enforcement-check` uses the actual agentgateway dataplane, a deterministic authorizer, and an HTTP recorder in `breaker-enforcement`. The recorder **does not execute commands**. The fixture accepts only `fixture:allow`/`fixture:allow:...` sentinels, authenticates a random test bearer token, and issues a short-lived HMAC grant bound to the exact buffered body. The recorder verifies that grant and rejects replay. Tokens/keys are ignored local test artifacts and Kubernetes Secrets, never committed credentials.

The authorizer rejects any client-supplied grant. Do not remove that header with an ordinary late request-header modifier: agentgateway's [filter order](https://agentgateway.dev/docs/kubernetes/latest/documentation/about/policies/filter-order/) places header modification after external authorization, which can erase the newly issued trusted grant too. An early stripping design would need a separately validated PreRouting policy; this fixture deliberately uses explicit rejection instead.

The harness checks positive forwarding/body integrity (including Unicode), policy denial, missing/wrong credentials, injected authorizer errors, malformed/duplicate/extra JSON fields, separate character/UTF-8 byte limits, method/content-type/size rejection, forged client grants, and direct recorder Service/Pod-IP bypass. It also scales the authorizer to zero, requires no forwarding during the outage, restores it in a `finally` block, and verifies recovery with a positive control. A positive must produce exactly one record; a negative must produce none. Default-deny networking admits only client -> gateway -> authorizer/recorder plus DNS and **gateway -> controller XDS on TCP 9978**. Blocking XDS leaves a `Programmed` Gateway with an unready proxy, so the harness waits for the dataplane Deployment too. Do not interrupt fault injection unnecessarily; if the process is forcibly killed, restore `deployment/fixture-authorizer` to one replica and rerun the checks.

These are integration controls for the pinned HTTP fixture path. They do not prove Actor network isolation, trained-model semantics, all proxy framing/timeout cases, or sub-15ms latency. Those remain acceptance work in [#1](https://github.com/caldeirav/sub15-breaker/issues/1) and [#4](https://github.com/caldeirav/sub15-breaker/issues/4). `k8s/` research examples are not deployed automatically. Their executor/model image placeholders remain intentional blockers.

## Manual acceptance before publishing the block PR

Run the automated checks first, then independently perform the manual checks in [`validation/block-01-infra.md`](validation/block-01-infra.md). Leave manual acceptance pending until the human tester supplies results. Capture nonsecret evidence, turn confirmed findings into regression tests, rerun affected checks, and update the docs before publishing the PR or starting the next feature block. See [#17](https://github.com/caldeirav/sub15-breaker/issues/17).

For block 01, the repository owner reported all independent-terminal tests passed on 2026-10-31. That user-reported acceptance is recorded separately from the automated results; no raw manual transcript was supplied. Final automated checks and the publication guard must still pass before opening the PR. The same acceptance process applies to later blocks.

The local reports are under `.infra/clusters/breaker-substrate/`:

- `readiness.json`: explicit full/partial scope, performed/skipped checks, declared pins separately from observed server/Helm/image versions, and rollout/API evidence;
- `network-check.json`: ingress/egress controls;
- `enforcement-check.json`: per-case gateway outcomes and record deltas.

Always check each report's timestamp and scope and rerun after relevant changes. Reports do not certify manual approval. Do not commit kubeconfigs, fixture Secrets, upstream caches, or unreviewed raw traces. Only a redacted validation summary belongs in the PR.

## Interactive inspection and explicit teardown

```bash
export PATH="$PWD/.tools/bin:$PATH"
export KUBECONFIG="$PWD/.infra/clusters/breaker-substrate/kubeconfig"
kubectl get nodes -o wide
kubectl get pods -A
kubectl get gatewayclass agentgateway
kubectl ate get atespaces -o json
```

The private kubeconfig targets only this cluster; there is no need to change your global current-context. Probe pods remain available for inspection. To delete **only** the owned cluster:

```bash
bash scripts/setup_infra.sh destroy --confirm breaker-substrate
```

This destroys its workloads/storage. Tools, cached source, and evidence remain on disk. The script requires the exact confirmation and project ownership record; it does not prune other Podman images, volumes, machines, or clusters.
