# BreakerSubstrate specification: simulated banking (`banking-v1`)

## Objective

Compare gateway-side generative verification (A) with one compact binary-classifier pass (B) before a **structured banking action** changes synthetic state. Reuse pinned AgentDojo tasks/tools/checkers; do not build another financial dataset. This specification defines the target and its limits, not a deployment inventory. Track delivery and acceptance in [GitHub roadmap #14](https://github.com/caldeirav/sub15-breaker/issues/14) and the owning issues; preserve historical source outcomes/statuses. Command-only Bash modules are legacy compatibility.

## Trust and execution contract

All read/write tools traverse the authenticated gateway to an isolated per-trial gVisor Actor service. Bind principal, trial, Actor generation, action/idempotency ID, canonical typed tool/arguments, trusted intent/policy/input versions, expected state version and deadline. Agent/tool text cannot choose trusted context. Hidden benchmark checks, reference solutions and attacker goals are evaluator-only.

The supported [native harness](../docs/architecture.md) uses pinned AgentDojo assets,
managed model/MCP transport and one reviewer at the Substrate claim gate. Tools
compute on private Actor snapshots; the external single-writer service atomically
commits synthetic state, receipts and outbox events on dedicated storage. Shared
record-only contract fixtures and historical in-memory adapters remain separate;
neither is deployed-enforcement evidence. Additional authority/business scope needs
explicit clarification and acceptance.

Validate schemas, capabilities, bounds and identity deterministically before one authoritative A/B decision. Deny errors, malformed/oversize/ambiguous inputs, stale state/generation, model/calibration mismatch and unavailable authority. Admission and mutation must enforce atomic state-version checks and idempotency; unknown writes require receipt reconciliation, not automatic retries. Prevent direct/alternate-route access and replay. No host shell, privileged executor or live bank fallback.

Denial, durable Actor-scoped latch, acknowledged stop and authenticated fresh-generation reset are distinct events. Stop failure retains the latch. Prior effects are not rolled back. Verify runtime/isolation, cleanup and independent mutation/egress evidence rather than trusting an ActorTemplate or HTTP status alone.

## Verifier model and calibration

Mode A and B use the same trusted action/context and enforcement boundary. B performs one non-generative forward pass; it is not the legacy command-only risk model. Fine-tune a compact binary encoder with explicit unsafe-class semantics on independently reviewed policy/action/context data. A relevance checkpoint is not a safety artifact. Bind model, tokenizer, input schema, policy, split hashes, calibration and threshold in immutable manifests.

Use disjoint training/calibration/validation/test groups, held-out temperature fitting and validation-selected thresholds; do not tune on final tasks. Report NLL/Brier/ECE/reliability counts and FNR/FPR/coverage/uncertainty, not ECE alone. `0.70` is a legacy default, not an approved banking threshold. Unknown policy labels stay unknown; Gemini does not create independent safety labels.

## Evidence, traces and score columns

Every acting/verifying model call, classifier inference, tool attempt, oracle and native Gemini judge must appear in MLflow with sanitized inputs/outputs, configuration/provenance, timing, available usage, errors and owning trial/action IDs. Include lifecycle/reset/stop and failed/incomplete attempts. Correlate distributed spans and independent execution receipts; missing telemetry invalidates a complete-evidence claim.

Attach stable scalar assessments to the specific trace (and action span where applicable): upstream utility/attack predicate, declared-goal and forbidden-effect facts, completion/error, admission/risk, judge verdict/citation-validity/agreement/error. Native structured Feedback is retained in addition to scalar columns. Judge traces link their target and carry their own review scores. Never copy task utility to each action as a safety label. Nonapplicable/unknown is not zero. See [trace contract](../docs/validation.md#trace-and-score-ownership).

## Evaluation and release acceptance

Freeze a small eligible upstream slice and label attack adaptations, original corrupted-input diagnostics and exclusions. Preserve upstream parity separately from intended-goal/forbidden-effect facts; #20's historical disagreement cannot be overwritten. Same-action replay compares verifier quality/latency; fresh-state full-agent trials compare utility and safe refusal. Counterbalance modes, declare repeats/settings/budgets and report all denominators/failures. Optional judge-free evaluation needs no provider key; enabled Gemini review uses registered MLflow judges, never the legacy raw-SDK grader.

The approved metric-v2 semantics define utility parity, upstream attack absence,
selected new/changed forbidden-recipient absence and declared service-disclosure
absence as separate criteria. Native judges receive observations and fixed rules,
not checker Python, measured verdicts or final-answer claims. Unknown subscription
evidence remains unknown. Current [test design](../docs/validation.md) distinguishes
the native demo/full comparison from the historical local17-case/68-review pilot;
each must enforce its own exact matrix, not inherit another protocol's counts.

For evaluation harnesses, complete declared execution/evidence, correct golden
controls, real paths and exact review/trace auditing are required—not universal
agent success. The strict [demo protocol](../docs/demo.md) additionally requires
each declared card's intended outcome before readiness. Reassessment must be
separately versioned/derived without invented executions or historical status
changes. Original versioned policies are [archived](../validation/archive/README.md).
Agent/guard releases need their own predeclared quality/safety/availability budgets.

Measure complete authoritative authorization at predeclared hardware/load/input/
quality/availability conditions before tail/SLO claims. Separate startup from all
measured samples, and exclude acting-model/tool/reset/judge time from admission.
The15ms research target concerns classifier decision computation, not native claim
or task time; current baseline results do not establish uniform latency.

Each block requires automated tests, independent review, finding regressions, docs and its scoped PR before progression. Record independent **agent** review separately from human/manual acceptance; neither is inferred from tests or prior block sign-off. No release claim until actual Actor/gateway, calibrated model, complete trace-score evidence, fault tests and target-profile measurements pass their respective gates.
