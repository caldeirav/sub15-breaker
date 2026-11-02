# Target-stack infrastructure review — 2026-11-01

**Result: BLOCKED, not infrastructure acceptance.** Sprint #31 is held behind
[#38](https://github.com/caldeirav/sub15-breaker/issues/38). No finished-feature
human test pass is claimed. Original failed live runs and prior acceptance
records are unchanged.

## Interim handoff provenance

The owner explicitly authorized merging PR #30 to retain the tested Actor/store
foundation and end duplicate integration testing of the interim direct-Responses
loop. It merged as `a5231bbd8a01f93ca1c5094ada8af8246ba18e0b`.
Python3.11–3.13 CI passed. Serving #28, acceptance carryover #29, target sprint
#31/#32–#37 and broader security/tracing/lifecycle issues remain open. Merge
authorization is not manual-test acceptance or a repair of historical failures.

## What the live inspection established

| Component | Observed / release review | Meaning |
| --- | --- | --- |
| Owned provider/node | Same Podman provider and immutable Kind node IDs matched the ownership record | Restored without adoption, replacement or deletion |
| Podman host + VM | 5.8.1; maintained5.8.x patch5.8.9, latest stable major6.1.4 | Owner declined shared upgrade; no client/guest/VM/provider change applied |
| macOS helper | Running `/opt/podman/bin/krunkit`1.1.1, bundled libkrun-efi ABI1.16.0 | Separate, previously unchecked lifecycle prerequisite; below reviewed minimum1.3.1 |
| Kind / Kubernetes | 0.33.0 / 1.37.0, original digest-bound node | Owner selected temporary1.37.0 retention; current stable patch1.37.2 has no published `kindest/node:1.37.2` image |
| Helm | Selected project tool upgraded3.20.1 →3.22.1, checksum-verified | Maintained3.x line; no Helm4 migration or cluster chart upgrade |
| Cilium / Gateway API | 1.20.4 / 1.7.0 | Match current reviewed releases |
| Managed gateway | Controller+dataplane1.7.0; dataplane source `26f5aebe99a36a037fe54f8080a608aca5547e15` | Confirmed inside `/app/agentgateway`; host standalone1.4.1 is **not** the deployed runtime |
| Substrate | Release1.0.0-rc.1 and digest-bound running components match foundation evidence | Published release is named RC; do not silently substitute main/nightlies |
| gVisor | Enabled SandboxConfig release20261026.0, arm64 asset digest `6257e49955f13e6caceb2c4181c5dc5406c460e805940c944e67ad65553f5b02` | Configured/observed asset; not a fresh post-repair Actor execution proof |
| LM Studio | 0.4.28+2; selected MLX1.13.1 matches official stable listing | No app/runtime reload, global bind change or weight download |
| Loaded model | `qwen/qwen3-30b-a3b-2507`, MLX4-bit, qwen3_moe, loaded context8192, idle | Correct Instruct family, not Coder; metadata is not flow completion or proof of historical effective settings |
| MLflow | Configured host endpoint returns3.17.2; experiment3 historical runtime and FAILED live runs are readable | Earlier MCP lookup failure was a different tracking-store selection, not loss of those runs |
| Durable banking store | PVC bound; read-only counts12 trials,35 actions,171 outbox events after initial recovery | Prior receipts/evidence retained; no reset/key replacement/data deletion |

The recovered foundation verify passed. The network matrix passed **6 controls**
including positive controls after denials. The managed gateway fixture passed
**20 controls**, including authorization outage/recovery and direct-bypass
denial. These are their original narrow scopes, not target model/tool readiness.
Prior evidence was copied before rerunning the checks.

## Confirmed VM lifecycle failure

The same VM stopped again after those controls, without a stop command from this
session. The owner confirmed the stop was not intentional. One diagnostic-only
restart of the same VM was authorized to inspect its previous boot; the node was
not recreated and no unrelated containers were started.

Previous boot: **12:46:32–13:20:45 +08:00**, 2026-11-01. The guest journal records:

```text
13:20:44 systemd-logind: Reboot key pressed short.
13:20:44 systemd-logind: Rebooting...
13:20:44 systemd-logind: System is rebooting.
```

The helper and network proxy then disappeared; VM SSH and Kubernetes API were
unreachable. This is not merely an old kubeconfig or an unready Pod.

This matches the documented symptom in
[Podman #29084](https://github.com/podman-container-tools/podman/issues/29084).
[Fix #29101](https://github.com/podman-container-tools/podman/pull/29101) bumped
krunkit to1.3.1 and describes more robust REST-control parsing. Installed1.1.1
predates the fix. **The event sender and exact causal path on this host are not
proved.** Do not assert macOS memory policing, an OOM kill, a host sleep event,
malicious input or a model failure without evidence.

The preflight now checks the selected libkrun helper independently and rejects
this known-risk version before normal creation/verification. A future patched
version must also pass a defined stability window, repeated endpoint checks and
the affected actual-runtime controls; a successful start alone is insufficient.

## Integration gaps the earlier foundation did not cover

1. The only deployed gateway route is the benign `/execute` fixture. There are
   **no model or MCP AgentgatewayBackends**. Controller installation and a
   Programmed condition do not put the gateway on the banking request path.
2. The node reaches loopback LM Studio via Podman's host forwarding
   `192.168.127.254:1234`; LM Studio remains bound to127.0.0.1. This avoids an
   unnecessary global LAN bind change. It does **not** prove Pod/gateway egress,
   Responses→Completions conversion, tool-call serialization or completion.
3. Substrate's bundled collector exports traces to **Jaeger/debug**, not MLflow.
   A running collector is not the required gateway→MLflow path. Configure the
   managed gateway's OTLP/HTTP exporter or a correctly scoped bridge, verify
   source-side privacy, experiment ownership, trace context and persisted
   readback. MLflow does not accept direct OTLP/gRPC.
4. Banking platform/runtime driver tokens had expired. A scoped renewal command
   is implemented and regression-tested; it has not yet been live-validated
   behind the repaired hypervisor gate. It does not redeploy or replace state.
5. `check_env.sh --research` is a legacy sidecar health profile, not a banking
   target-stack doctor. It must not be used as permission to resume sprint31.
   A target-specific capability gate remains required after this lifecycle
   repair; protocol/auth/privacy failures must fail closed.

The earlier infrastructure scope was explicitly a non-executing foundation, but
the unchecked helper lifecycle and lack of a strong target-stack transition gate
should have been surfaced before proposing sprint integration. The initial
standalone-gateway mismatch diagnosis was also too broad; this review corrects
it with actual deployed binary/source evidence.

## Prepared repair, not installed

The owner authorized **preparing** a targeted helper repair, not applying an
admin installation or replacing shared components.

The official Podman5.8.9 arm64 installer was downloaded for inspection only:

- [Official release asset](https://github.com/podman-container-tools/podman/releases/download/v5.8.9/podman-installer-macos-arm64.pkg)
- SHA256 `2c86fb0ebdd81a4bf9d93d1aba632e62f4e65850f68f1a75e4feed8c77a46d11`, matching release metadata.
- Apple verifies Red Hat installer signature/team `HYSCB8KRL2` and notarization.
- Tagged packaging source selects **krunkit1.3.2**, gvproxy0.9.0, vfkit0.6.4.
- The new helper depends on `libkrun.dylib` plus bundled rendering libraries;
  the installed helper uses `libkrun-efi.dylib`. **Do not swap only the binary**
  or mix old/new libraries. The new helper's ABI metadata is not an independent
  proof of the libkrun source patch version.
- Relocated signed-helper `--version` inspection fails because its hardened
  loader expects the installed library paths. No signing/loader bypass or host
  library modification was made; successful candidate execution is not claimed.
- The installer preinstall script removes **`/opt/podman`** before replacing the
  complete distribution. Its postinstall also invokes `podman-mac-helper` and
  updates tool/man path files. It does not contain a VM/data-directory deletion,
  but is still a shared/admin change and needs explicit approval and backup.

The supported repair candidate is therefore the **complete signed5.8.9 patch
bundle**, not an unreviewed helper-only hybrid or a separate experimental
provider. This revises the earlier no-Podman-upgrade boundary and cannot be
applied under preparation-only approval.

Before any approved installation: inventory/quiesce only explicitly permitted
workloads; stop the VM cleanly with permission; back up `/opt/podman`, machine
configuration, the VM disk, project identity/kubeconfig, banking state/keys and
the correct MLflow data to private storage; verify recoverability and free disk;
record rollback and the default/rootful connection fingerprint. Do not copy a
running VM disk as a consistency guarantee. No such backup/cutover is yet claimed.

After approval/installation: verify signed bundle paths/versions, client/guest
API compatibility, unchanged machine/container identity and data counts, a
**two-hour normal-workload/idle stability window without automatic restarts**,
controller/network/gateway/Actor controls, and only
then the missing managed model/MCP/MLflow capability path. Preserve any failed
attempt and never automatically recreate the VM or cluster to get green tests.

## Budget and acceptance boundaries

The final offline regression run on this infrastructure branch passes **298
tests**, including helper-version/runtime-selection, release drift/expiry and
scoped token-renewal controls. `check_env.sh --cluster breaker-substrate` now
fails explicitly on krunkit1.1.1 before claiming infrastructure readiness. This
negative preflight is the expected result, not a passing live acceptance gate.

No application model requests, paid judges or new banking-tool execution were
performed in this review. The sprint's **0/8 compatibility +0/72 final requests**
remain available. Kubernetes1.37.0 retention and no shared Podman upgrade were
owner-selected; the later helper-repair preparation approval is not installation
approval. Version exceptions/review reminders are recorded through2026-11-08;
expiration fails freshness checks rather than silently upgrading anything.

This review cannot certify that infrastructure will never need maintenance.
Its purpose is a reproducible, tested baseline plus explicit drift/expiry and
capability gates, with no return to application work while prerequisites fail.
