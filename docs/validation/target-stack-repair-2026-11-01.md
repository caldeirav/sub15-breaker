# Managed target-stack repair — 2026-11-01

The owner authorized the coherent shared-stack update and full infrastructure
tests after the review in [#38](https://github.com/caldeirav/sub15-breaker/issues/38).
This supersedes the earlier preparation-only Podman boundary. It does not
authorize VM replacement, deletion of retained data, paid providers or a passing
manual-test assessment.

**Qualification is pending the full provider window and local serving probe.**
The target doctor intentionally fails until the complete qualification is
recorded. No architecture-sprint acceptance or financial-policy claim is made.

## Applied versions and preservation

- Signed/notarized Red Hat Podman5.8.9 arm64 distribution, SHA256
  `2c86fb0ebdd81a4bf9d93d1aba632e62f4e65850f68f1a75e4feed8c77a46d11`.
- Host and guest both report5.8.9, source
  `40030f4073bd4e1bf4f2fd9df2f6952b4d9d350a`; running krunkit1.3.2 maps the
  installed executable inode. A changed disk binary cannot masquerade as an
  updated running helper.
- Booted guest Fedora CoreOS44.20260928.3.2, kernel7.2.7-200.fc44.aarch64,
  `quay.io/podman/machine-os@sha256:4a4de361103e1501f0a647ce35aae844138752aa1eda5af0cc0a67eab601b130`.
  The metadata blob digest was verified before application and names the same
  Podman5.8.9 source. Podman's apply path uses `ostree-unverified-image`;
  integrity is pinned by HTTPS/OCI digest, not an independently attested guest
  image signature. Zincati remains disabled/inactive.
- All20 original container IDs, the default/rootful connection and the owned
  Kind node/provider identity are unchanged. Only the owned node and registry
  were started. No unrelated stopped workloads were started.
- Before new controls, the banking SQLite database passed integrity checks and
  retained12 trials,35 actions and171 outbox rows. No durable-store key was
  replaced. Subsequent controlled trials add evidence rather than erase history.
- The private stopped-disk copy matched the original full SHA256. Installation,
  machine and project configuration archives were listed successfully; five
  selected files were extracted privately and hash-checked. The MLflow SQLite
  backup passed integrity checks and retained original run statuses. This is a
  same-host rollback backup, **not a boot-tested disaster-recovery guarantee**.
- Kubernetes1.37.0 remains the owner-selected temporary exception. No Kind/node
  recreation or provider change occurred. Existing gateway1.7.0, Substrate
  1.0.0-rc.1 and Cilium1.20.4 were retained; Helm3.22.1 is the selected project CLI.
- LM Studio0.4.28+2 is the installed/running app. Its mapped MLX plugin is1.13.1.
  The approved Qwen3-30B-A3B-Instruct-2507 MLX4-bit model remains loaded with
  context8192. No weight download, global sampler/template edit or model reload
  was requested.

## Measured checks so far

| Check | Evidence / scope |
| --- | --- |
| Offline regressions | **344 pass**; includes version coherence, loaded-executable identity, protocol/resource invariants, budget persistence, short-window rejection, secret/schema handling and qualification scope/freshness |
| Foundation | Passed after dependency-aware startup checks; authenticated Substrate API read required |
| Network controls | **6/6**, including positive controls after negative paths |
| Gateway enforcement | **20/20**, including authorizer outage/recovery, exact forwarding and direct backend denial |
| Actual gVisor/Actor controls | **23/23**, run `caa5b76ea32d4839b82b350d79bb797f`; all11 tools, idempotency, binding/fencing, reset, store restart, before/after-commit crash reconciliation, cleanup/outbox/readback; zero models/judges |
| Managed Responses/MCP/OTLP | **12/12 cases**, run `cc78642fece44d6b9e8eb22fd0889ee3`, trace `tr-e522cf5e557e03b2aabb7ff6a60c3f71`;74 persisted spans, including38 gateway spans for23 caller requests;34 current object/spec/network-policy bindings |
| Provider continuity | Two-hour window started2026-11-01T06:11:58Z, run `460494ac88ee4e0fa34ad42cfbdd2982`, trace `tr-a91e4ed95b2ee2f963faa6efedb2bcac`; completion not yet claimed |
| Real local serving | Not run yet; gated on the full window and persisted protocol/privacy proof |

The protocol matrix extends the existing managed Gateway, not another gateway
installation. It proves Responses→Completions conversion, exact decimal/null and
tool-ID/result preservation, schema preservation, usage, explicit zero retries,
valid signature/audience/subject authorization, actual gateway→local model
metadata connectivity, and Service/Pod bypass denial. Both modern2026 sessionless
MCP and explicit2025 compatibility are exercised. It checks unknown tools,
visible tool errors, removed modern handshake rejection, session authorization
and cleanup. Gateway→MLflow uses direct OTLP/HTTP and W3C context; all native and
gateway parents, CODE scores and synthetic secret/credential absence passed
persisted readback.

## Failures retained and corrected

1. The first post-update foundation check observed an authenticated API-read
   failure after rollouts appeared successful. Actual API pods recovered during
   database/certificate startup. Verification now checks those dependencies
   before API deployments and explicitly waits for API pods; the authenticated
   read is still mandatory and failures are not treated as readiness.
2. Protocol run `074a97d0750c4e31be1446227f10ebe8` remains FAILED. It showed that
   declaring a Completions upstream does not select a Responses frontend. Added
   the explicit Kubernetes `policies.ai.routes` mapping and a regression.
3. Protocol run `c22adf85a72f4d94b56e2dbcc8ece234` remains FAILED. Its conversion,
   auth and model-metadata cases passed, but an old-style `initialize` with a2026
   version was correctly rejected. Current spec/source review established the
   sessionless `server/discover` and per-request metadata/header requirements;
   the modern probe now uses them, with a separate declared legacy case. Saved
   upstream records were added without changing the failed outcome.
4. A configuration attempt failed before the matrix because a newly added Secret
   key had not yet appeared in the existing Pod's projected volume. The bounded
   projection check now reports missing keys as pending and verifies both token
   and code hashes before traffic. It does not retry model inference.

These failures are configuration/test-development evidence, not additional model
requests or hidden successful banking trials. The original live/diagnostic runs
and their spent budgets remain unchanged.

## Remaining acceptance boundary

The serving probe predeclares five compatibility reservations: two gateway-auth
denials and three real local generations. It requires completed Responses,
canonical function arguments, paired output, a genuine final assistant response,
usage and persisted linked traces. The tool result is explicitly synthetic and
no banking tool executes. It cannot supply task utility or final-agent evidence.

The new doctor requires all persisted proofs plus current versions, guest image,
object identity/generations/spec hashes, serving software and loaded model. It
does not infer qualification from health/model listings or narrow old reports.
Automatic qualification remains separate from fresh human acceptance.

The canonical banking MCP application, supported LangGraph graph and final
nine-trial agent matrix remain sprint31 application work. No financial guard,
production end-to-end transport, HA/node-loss durability or universal future
completion guarantee is supplied by these infrastructure tests.
