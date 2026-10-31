# Kubernetes research examples: not the current banking deployment

The supported banking harness runs in memory; see [its runbook](../docs/banking-feasibility.md). These files are **not** deployed by `setup_infra.sh` and do not provide a banking service, trusted-context verifier, calibrated model or reset/stop integration.

| File | Role / limit |
| --- | --- |
| `workerpool.yaml` | Generic Substrate WorkerPool example; runtime selection must be verified in a real workload, not inferred from YAML |
| `actor-template.yaml` | ATE ActorTemplate with a placeholder executor image; not a banking tool-service implementation and not a Kubernetes CRD |
| `decision-sidecar.yaml` | Legacy command-only classifier deployment example requiring external weights/calibration; not the banking action/context input |
| `agentgateway-hook.yaml` | Prototype command-body HTTP authorization route; not canonical banking action/Actor/state-version binding |

Do not replace placeholders and apply these as if that completed the banking architecture. Current live gateway evidence is the separate [non-executing foundation fixture](../docs/infra.md). Real banking Actor hosting/reset belongs to block 03b and authenticated admission to block 04, after the [03a contract](../docs/next-iteration.md) is clarified, implemented and accepted.

Future workloads need digest-bound nonroot images, explicit limits/egress/RBAC/identity, isolated state and independent receipts, plus real bypass/failure tests. No real bank API, money, ambient credentials, privileged executor or host fallback is part of the reference path.
