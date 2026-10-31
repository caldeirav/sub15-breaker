# BreakerSubstrate specification: simulated banking (`banking-v1`)

## Objective and status

Compare gateway-side generative verification (A) with one compact binary-classifier pass (B) before a **structured banking action** changes synthetic state. Reuse pinned AgentDojo tasks/tools/checkers; do not build another financial dataset. The local harness-v3 scope is accepted, but the end-to-end target is not implemented: tools still dispatch in memory and historical source runs retain their original FAILED statuses. The [scope](../docs/project-scope.md) and [plan](../docs/implementation-plan.md) are normative for new work; command-only Bash modules are legacy compatibility.

## Target trust and execution contract (not yet implemented)

All read/write tools traverse the authenticated gateway to an isolated per-trial gVisor Actor service. Bind principal, trial, Actor generation, action/idempotency ID, canonical typed tool/arguments, trusted intent/policy/input versions, expected state version and deadline. Agent/tool text cannot choose trusted context. Hidden benchmark checks, reference solutions and attacker goals are evaluator-only.

This paragraph is a target requirement: today's accepted harness uses the [pinned in-memory banking environment](../docs/golden-data.md), not this distributed path. Block 03a has not started; confirm its authority/policy inputs, exact money representation and integration scope with the owner before coding. See [the proposal](../docs/next-iteration.md).

Validate schemas, capabilities, bounds and identity deterministically before one authoritative A/B decision. Deny errors, malformed/oversize/ambiguous inputs, stale state/generation, model/calibration mismatch and unavailable authority. Admission and mutation must enforce atomic state-version checks and idempotency; unknown writes require receipt reconciliation, not automatic retries. Prevent direct/alternate-route access and replay. No host shell, privileged executor or live bank fallback.

Denial, durable Actor-scoped latch, acknowledged stop and authenticated fresh-generation reset are distinct events. Stop failure retains the latch. Prior effects are not rolled back. Verify runtime/isolation, cleanup and independent mutation/egress evidence rather than trusting an ActorTemplate or HTTP status alone.

## Planned verifier model and calibration

Mode A and B use the same trusted action/context and enforcement boundary. B performs one non-generative forward pass; it is not the legacy command-only risk model. Fine-tune a compact binary encoder with explicit unsafe-class semantics on independently reviewed policy/action/context data. A relevance checkpoint is not a safety artifact. Bind model, tokenizer, input schema, policy, split hashes, calibration and threshold in immutable manifests.

Use disjoint training/calibration/validation/test groups, held-out temperature fitting and validation-selected thresholds; do not tune on final tasks. Report NLL/Brier/ECE/reliability counts and FNR/FPR/coverage/uncertainty, not ECE alone. `0.70` is a legacy default, not an approved banking threshold. Unknown policy labels stay unknown; Gemini does not create independent safety labels.

## Evidence, traces and score columns

Every acting/verifying model call, classifier inference, tool attempt, oracle and native Gemini judge must appear in MLflow with sanitized inputs/outputs, configuration/provenance, timing, available usage, errors and owning trial/action IDs. Include lifecycle/reset/stop and failed/incomplete attempts. Correlate distributed spans and independent execution receipts; missing telemetry invalidates a complete-evidence claim.

Attach stable scalar assessments to the specific trace (and action span where applicable): upstream utility/attack predicate, declared-goal and forbidden-effect facts, completion/error, admission/risk, judge verdict/citation-validity/agreement/error. Native structured Feedback is retained in addition to scalar columns. Judge traces link their target and carry their own review scores. Never copy task utility to each action as a safety label. Nonapplicable/unknown is not zero. See [trace contract](../docs/mlflow-trace-contract.md).

## Evaluation and release acceptance

Freeze a small eligible upstream slice and label attack adaptations, original corrupted-input diagnostics and exclusions. Preserve upstream parity separately from intended-goal/forbidden-effect facts; #20's historical disagreement cannot be overwritten. Same-action replay compares verifier quality/latency; fresh-state full-agent trials compare utility and safe refusal. Counterbalance modes, declare repeats/settings/budgets and report all denominators/failures. Optional judge-free evaluation needs no provider key; enabled Gemini review uses registered MLflow judges, never the legacy raw-SDK grader.

The approved [banking-metrics-v2 contract](../docs/banking-metric-contract-v2.md) defines utility parity, upstream attack absence, selected new/changed forbidden-recipient absence and declared service-disclosure absence as separate criteria. Native judges receive observations and fixed normalized rules/reference values—not checker Python, measured verdicts or final-answer claims. Unknown subscription evidence remains unknown. The focused semantic boundary regression requires exactly 12 successful rows, and the local pilot exactly 17 cases / 68 reviews, with parity and trace-score gates unchanged in strictness.

For the current **harness PR**, [acceptance v3](../docs/banking-harness-acceptance-v3.md) requires complete case execution/evidence, correct controls/golden evaluation, live model/tool path, exact review/provenance and trace auditing—not universal agent success. Keep utility failures and attack effects unchanged as non-gating quality observations. Reassessment of existing evidence must be a separately versioned, explicitly derived run with no invented new executions and no changes to historical statuses. #25 is nonblocking quality work. Future agent/guard releases still need their own predeclared quality/safety/availability budgets.

Measure complete authoritative authorization warm/cold p50/p95/p99 at predeclared hardware/load/input/quality/availability conditions. Exclude acting-model, tool, reset and judge time from the authorization budget. <15ms is a hypothesis, not a guarantee or existing result.

Each block requires automated tests, independent review, finding regressions, docs and its scoped PR before progression. Record independent **agent** review separately from human/manual acceptance; neither is inferred from tests or prior block sign-off. No release claim until actual Actor/gateway, calibrated model, complete trace-score evidence, fault tests and target-profile measurements pass their respective gates.
