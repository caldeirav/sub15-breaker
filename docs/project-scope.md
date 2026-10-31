# Project scope: a traced, gateway-enforced simulated banking agent

Scope revision: `banking-v1`, 2026-10-31. This is the implementation target requested by the owner, **not a claim that the target is delivered**. [Specification](../specs/001-breaker.md), [sequenced plan](implementation-plan.md), [roadmap #14](https://github.com/caldeirav/sub15-breaker/issues/14).

**Metric decision approved:** the owner explicitly approved [banking-metrics-v2](banking-metric-contract-v2.md) to resolve #20. It preserves upstream parity while separating selected forbidden-recipient effects and declared subscription-disclosure facts. Native judges review normalized observations/rules, not Python source or supplied measured verdicts. Validation and independent review of this implementation are separate from human MLflow acceptance.

**Harness block accepted:** [banking-harness-acceptance-v3](banking-harness-acceptance-v3.md) gates trace/evaluation fidelity, controls, golden correctness and complete evidence—not universal agent success. Derived assessment `53b476bed53446ebac25753aaa9a8b80` passes with independent approval and no new model calls; **@caldeirav accepted this local scope on 2026-10-31** ([record](validation/block-02.json)). #25 is nonblocking quality work. Future agent/guard quality, availability, isolation and latency gates are not waived.

## User workflow and experiment

A user asks a local tool-capable agent to pay a synthetic bill, adjust a scheduled payment or update an address. Reuse pinned AgentDojo banking tasks, fake state, 11 tools, released attacks and executable checkers. An attacker controls designated tool-returned text, not the user's trusted intent, evaluator references or service policy. Initially retain the inspected three-task slice; expand only under declared eligibility checks.

Every proposed **read and write** passes through an authenticated gateway before the isolated per-trial tool service performs it. The same action/context/enforcement contract supports:

- **A:** gateway-side generative verification, with the actual verifier model invocation traced.
- **B:** one compact binary encoder inference over the canonical action and **trusted context**, with model/input/policy-bound calibration and threshold. Context is mandatory for this domain; the legacy command-only sidecar cannot be relabeled a banking guard.

Both modes also need deterministic identity/schema/capability/resource limits. A classifier is a probabilistic policy component, not the sole isolation or authorization control. Actor-scoped latch, acknowledged stop and fresh-generation reset are separate operations. No denial or stop promises rollback.

## Intended end-to-end path

```text
trusted user intent + versioned policy/state
    -> bounded local acting model (MLflow model spans)
    -> proposed typed banking action (untrusted)
    -> authenticated gateway admission
         -> resolve principal/trial/Actor generation/intent/state version
         -> deterministic validation + one A OR B verifier
         -> action-bound decision + atomic version/idempotency check
         -> isolated Actor tool service -> bounded result/independent receipt
    -> agent continues or stops; latch/stop policy enforced outside agent
    -> independent upstream + declared-goal + forbidden-effect checks
    -> optional registered native MLflow Gemini judges
    -> MLflow trace table: evidence, applicable scalar scores and provenance
```

Trusted IDs, state freshness, action digests and execution receipts must remain bound across network boundaries. Agent-supplied identity, policy assertions or trace headers cannot grant authority. Timeout after a write is **unknown** until reconciled; idempotent status lookup is required before retry. Mutable state must be revalidated atomically at admission/mutation, not merely snapshotted before an unrelated request.

## Mandatory observability and score ownership

MLflow is the evidence/review system, not just an aggregate experiment tracker. The [trace contract](mlflow-trace-contract.md) defines per-trace columns, span ownership, judge links, failures and coverage auditing. It applies to **every model, verifier, classifier, tool and judge attempt**, including unsuccessful attempts; lifecycle/reset/stop and oracle operations are also observable.

Native structured judge Feedback preserves citations and model provenance, but scalar verdict/validity/agreement/error assessments must also be selectable as columns against the relevant trace. Run metrics/tables are derived summaries. A task's final utility cannot label every intermediate tool action safe. Unavailable/nonapplicable values remain absent/unknown with explicit applicability, not fabricated zeros. Instrumentation failure blocks a claim of complete evidence.

## Data and outcome boundaries

- Reuse the pinned benchmark framework, not an HF trajectory dump or a new authored banking corpus. Keep upstream checks unchanged for parity and label all adaptations.
- Distinguish **upstream utility**, **upstream selected attack predicate**, **intended declared-goal facts**, **independently observed forbidden effects**, **admission denial**, **verified non-execution**, and **judge agreement**.
- The pinned `InjectionTask0` predicate has broader semantics than its declared subject condition. The owner-approved #20 resolution is versioned in `banking-metrics-v2`; preserve the historical disagreement and failed status. Fresh validation follows the declared protocol, not relabeling old results or retrying for unanimity.
- Task/end-state outcomes are not per-action policy labels. Independently validate a bounded set of action/context labels, benign near-misses and split provenance for model training/calibration. Do not use Gemini opinions to mint independent labels.
- Current pilot tasks are development evidence, not untouched final holdouts. Freeze separate task/template/attack groups for train/calibration/validation/test; keep hidden references and attacker goals out of acting/verification prompts.

## In and out of scope

| Required for the reference implementation | Explicitly not required / not claimed |
| --- | --- |
| Pinned synthetic banking environment, bounded acting agent and explicit policy | Real bank APIs, real money, payment credentials or production financial compliance |
| Real gVisor Actor-hosted tool service, authenticated lifecycle/reset and gateway isolation | A generic Bash executor or new financial benchmark corpus |
| Canonical action/trusted-context contract and transactional/idempotent mutation | Passing arbitrary shell effects through a command-only model |
| Comparable gateway A/B verifiers, trained model, independent calibration and quality evidence | Relevance weights presented as safety weights; scores treated as proofs |
| Complete traces, trace-local scores, native MLflow judges, redaction and failure retention | Raw-SDK judging or run-artifact-only evidence in the supported path |
| Same-action replay and fresh-state full-agent evaluation with complete denominators | Three-task feasibility counts presented as statistical safety accuracy |
| Reproducible CLI/images/profile and quality-bounded authorization benchmark | Guaranteed <15ms, universal safety/containment, or automatic rollback |
| Explicit independent-agent review and separate human acceptance | Agent-authored HUMAN assessments or reused block-01 sign-off |

Optional after the baseline: acceleration/export/quantization (#13), additional domains, larger task slices. Generic trusted banking context (#9) is **not optional**. Legacy Bash modules/data remain compatibility scaffolding, not the default target and not banking training data; migration/packaging must make that distinction executable rather than just textual.

## Current evidence versus missing implementation

PR #18 merged and validated the infrastructure/non-executing fixture foundation. The banking pilot directly dispatches upstream tools in a local Python simulation; no real Actor/gateway banking path, banking risk model, calibration artifact or performance evidence exists yet. Its corrected run has 12/12 controls, 3/3 benign successes and 34 validly cited native reviews with 33 agreements; it remains FAILED / review_required. The independent review must also check trace completeness and score columns; neither passing tests nor editing issues closes those gaps.

That is historical v1 evidence. The v2 main `e56a427a9592460f81f246bc3c0d6e29` retains FAILED under its old 3/3 utility gate. The v3 assessment passes the corrected harness scope and has explicit @caldeirav acceptance; [#25](https://github.com/caldeirav/sub15-breaker/issues/25) stays nonblocking. The [review checklist](validation/block-02-harness-review.md) and historical results remain available; #17 requires fresh acceptance for every subsequent block.

Complete the accepted block's scoped PR/CI merge, then take the [recommended block-03a contract iteration](next-iteration.md). #25 remains separate quality work without golden-answer leakage or lucky resampling. Subsequent Actor/model blocks retain their own [dependency gates](implementation-plan.md); this harness approval is not authorization or validation of a deployed workload.
