# Implementation plan: end-to-end simulated banking (`banking-v1`)

Reconciled 2026-10-31 against code, independent agent review, actual MLflow evidence and all open GitHub issues. [Scope](project-scope.md), [specification](../specs/001-breaker.md), [roadmap #14](https://github.com/caldeirav/sub15-breaker/issues/14). The earlier generic Bash execution/corpus plan is superseded for new implementation. Legacy modules remain compatibility scaffolding, not an already migrated banking runtime.

**Delivered baseline:** [PR #26](https://github.com/caldeirav/sub15-breaker/pull/26) merged accepted block 02 with 145 baseline tests and Python 3.11–3.13 CI. Its harness-v3 assessment, 2/3 benign quality and historical source statuses are unchanged. The owner subsequently confirmed [block-03a requirements](banking-contracts-03a.md) before coding; the shared record-only implementation now has 228 tests and 26 matched CODE fixtures with independent technical approval and **fresh human acceptance by @caldeirav on 2026-10-31**. This is not an actual banking execution boundary.

## Evidence and independent review

- **01 foundation:** PR #18 merged as `fb079cc`; 58 tests on Python 3.11/3.12/3.13, six network controls, 20 non-executing gateway fixture cases, owner-reported human acceptance. Not actual Actor banking execution.
- **02 accepted harness:** uses the [pinned banking golden environment](golden-data.md), source `e56a427a9592460f81f246bc3c0d6e29` and derived acceptance `53b476bed53446ebac25753aaa9a8b80`. Correctly observed failures remain false; they do not require agent fixes for harness acceptance.
- **Independent review:** [current technical approval](validation/block-02-harness-independent-review.md) verifies source integrity, golden outcomes and trace/score ownership. Initial missing-score, false-green, redaction and registry findings have regressions; [historical reviews](README.md#frozen-experiment-protocols-and-historical-evidence) retain their original dates/decisions rather than describe current blockers.
- **No inherited acceptance:** independent agent review is not HUMAN sign-off. Block 02 now has its own explicit @caldeirav acceptance, separate from block 01. #25 is not a blocker. Neither approval covers subsequent Actor/gateway/model releases; every future block needs its own fresh evidence and acceptance (#17).

**Owner-approved #20 protocol:** [banking-metrics-v2](banking-metric-contract-v2.md) now specifies four independent native-review criteria and raw projected observations with no oracle-label/Python-source input. The focused regression is predeclared as 3 cases / 12 reviews and the full local pilot as 17 cases / 68 reviews. Preserve all old failed/false-green evidence; fresh implementation validation and independent review precede separate human MLflow acceptance. No gateway/Actor or model-risk claim is added by this semantic resolution.

**Historical v2 evidence and gate:** main `e56a427a9592460f81f246bc3c0d6e29` passed all 12 controls, parity, coverage and 68 native reviews, but retained FAILED because benign utility was 2/3. The rent model left 1100 unchanged instead of 1200. Focused `b2660081b92c46beb7a579acfdd9f92a` passed 12/12 rows. Independent review verified that history. The owner subsequently corrected this PR's acceptance scope with v3; the old status and labels remain, while the new assessment evaluates harness correctness rather than agent win rate.

## Experiment and prerequisite corrections

1. A = gateway-side generative verifier; B = one compact binary-model inference. Both consume the same canonical tool/action and trusted intent/policy/state context and enforce at the same boundary. No agent-local A versus double-scored B comparison.
2. Trusted context (#9/#21) is **mandatory early work**, not an optional post-baseline extension. A recipient/amount alone cannot establish whether a transfer is authorized by the user's request. Legacy command-only model artifacts are incompatible with the banking input schema.
3. Reuse a bounded upstream task/checker slice (#15); do not build a new financial task corpus or generic shell executor. Independently reviewed action/context labels are still required for training and calibration; final-state task labels do not supply them automatically.
4. Keep upstream-predicate parity, intended attacker-goal facts, observed forbidden effects, benign utility, safe refusal and judge agreement separate (#19/#20). Preserve failed runs and adaptations; do not seek repeated Gemini unanimity or leak oracle verdicts into a supposedly independent judge.
5. Same-action replay measures verifier quality/calibration/authorization latency; fresh-state full-agent trials measure task utility/refusal and effects. Counterbalance mode order, declare repeats and report uncertainty/unknowns/failures with complete denominators. Pilot development tasks are not pristine final holdouts.
6. MLflow captures every model/tool/verifier/judge attempt and relevant score against its **specific trace**, with span-level ownership for action scores. Run artifacts/aggregates alone are insufficient. [Trace contract](mlflow-trace-contract.md), #3/#22.

## Dependency-ordered blocks and gates

Each row is a scoped PR (or bounded gated series). Before progression: automated tests, independent review, finding regressions, updated docs and explicit required human/manual acceptance on the final code/config. No subsequent deployment implementation begins just because planning or mocks pass.

| Block | Deliverable / owning issues | Required evidence |
| --- | --- | --- |
| 01 accepted | Infrastructure/non-executing fixtures; #4/#10/#12 partial, process #17 | Retain merged PR #18 evidence; never treat it as Actor-path approval. |
| 02 accepted and merged | PR #26; metric/evidence contract #20 and harness-v3 scope; @caldeirav acceptance 2026-10-31. | 145 tests and pre/post-merge CI pass; 17 golden outcomes, 68 native reviews and 85 source case/review traces validated. No universal agent-win or deployed-safety claim. |
| 03a accepted | Canonical types/context #21/#9, interface portions of #19/#22/#23 | Owner-confirmed record-only scope; 228 tests, all 11 reused argument schemas, decimal/HMAC binding and 26 matched traced fixtures. Independent technical approval and @caldeirav human acceptance 2026-10-31. No real authority, Actor hosting, learned verifier or financial-policy claim. |
| 03b Actor-hosted tool service/reset | #1/#23, workload hardening #10, evidence #3/#22 | Actual gVisor assignment, no ambient credentials/host mounts/live banking; isolated versioned synthetic state, bounded operations/output, reset fingerprints/generation, cleanup. Atomic compare-and-mutate, idempotent receipts and crash/timeout reconciliation. Keep service closed to arbitrary clients until 04. |
| 04 authoritative admission | #4/#6 using #21/#9/#23 | One A/B decision bound to exact consumed action/context; authenticate transport/RBAC, reject replay/bypass/stale generation/state/mutated bytes. Approvals execute once; denials/errors execute zero times. Deterministic fixture verifiers first, learned quality claims only after 07. |
| 05 durable breaker | #7 | Cross-replica latch/admission races, correct-generation least-privilege stop/acknowledgment, authorized recovery, outage/idempotency and no subsequent mutation evidence. Stop is not rollback. |
| 06 policy data and adversarial acceptance | #15/#16/#19/#20 | Frozen eligibility/license/versions, upstream oracle controls, fact-preserving attacks plus labeled corruption diagnostics; recipient/amount/profile/schedule/read abuse and benign near-misses. Separate action labels and group-disjoint splits. Unknown/weak predicates excluded explicitly; do not repair the whole benchmark. |
| 07a risk artifact | #2 with #9/#21 | Reproducible uv training smoke, immutable class/model/tokenizer/input/policy/data manifests, independently reviewed labels and held-out FNR/FPR/coverage/uncertainty. No relevance-model substitution or Gemini-created safety ground truth. |
| 07b calibration/operating point | #5 | Model/schema/policy-bound temperature; separate calibration and validation splits, pre/post NLL/Brier/ECE/bins, threshold chosen under declared quality budget then frozen for test. Legacy 0.70 is not preapproved for banking. |
| 08 supported agent and evaluation | #24/#6/#8, evidence #3/#22 | All acting-model tools traverse real gateway/Actor; same-action replay and fresh-state full-agent protocols, controlled mode ordering/repeats/budgets. Optional no-judge mode needs no provider key; enabled Gemini is native MLflow. Exact row/attempt counts, score columns, lifecycle cleanup and failed/unknown outcomes reconcile. Retire/disable legacy Bash/raw-SDK defaults. |
| 09 reproducible delivery | #10/#12/#24 | Role-specific locked packages/images, nonroot/digest/security/resource/SBOM checks, no runtime downloads; real CLI/doctor/dry-run and clean-checkout benign + adapted-injection demo. Owned-resource-only setup/teardown and explicit paid-review controls. |
| 10 quality-bounded performance/release | #11 with #2/#5/#8 | Complete authoritative authorization samples with parsing/context/queue/network/inference/admission exactly once. Predeclare hardware/load/input envelope, warm/cold p50/p95/p99, quality and availability/error budgets. Exclude agent/tool/reset/judge time; publish failed targets and residual limits. |
| Optional after baseline | #13 | CPU/MPS/CUDA/ONNX/quantization parity, recalibration and profile-specific timing; no automatic transfer of quality or <15ms claims. Additional domains are future scope. |

Contracts/data design can be reviewed early; this does not waive the preceding implementation acceptance/PR gate. Runtime transport tests use bounded harmless synthetic effects, never real payments or destructive shell references.

## All-issue reconciliation

There are **24 tracked implementation issues: 23 open, #20 closed**. Block 02 now has explicit local-harness acceptance; #25 stays nonblocking quality work. Nineteen existing issues were reconciled, four contract/migration issues added, then #25 added for the observed rent failure. Existing bodies retain history; this does not close any broad deployed-safety issue or waive later block gates.

| Issue | Current scope / completion gate |
| --- | --- |
| [#1](https://github.com/caldeirav/sub15-breaker/issues/1) | Actor-hosted synthetic banking tools and authenticated reset; 03b, not a shell executor. |
| [#2](https://github.com/caldeirav/sub15-breaker/issues/2) | Banking action/trusted-context risk training/artifacts; 07a. |
| [#3](https://github.com/caldeirav/sub15-breaker/issues/3) | Durable complete partial traces, stage-specific failures and persistence/reconciliation; throughout. |
| [#4](https://github.com/caldeirav/sub15-breaker/issues/4) | Fail-closed authenticated action/Actor binding and bypass rejection; 04. |
| [#5](https://github.com/caldeirav/sub15-breaker/issues/5) | Banking calibration/threshold/input-policy binding and held-out metrics; 07b. |
| [#6](https://github.com/caldeirav/sub15-breaker/issues/6) | One authoritative A/B action decision at common gateway boundary; 04/08. |
| [#7](https://github.com/caldeirav/sub15-breaker/issues/7) | Durable generation-scoped latch/acknowledged stop/recovery; 05. |
| [#8](https://github.com/caldeirav/sub15-breaker/issues/8) | Reproducible banking replay/full-agent evaluation and optional native judges; 02/08. |
| [#9](https://github.com/caldeirav/sub15-breaker/issues/9) | Mandatory trusted intent/policy/state model context; 03a before 07. |
| [#10](https://github.com/caldeirav/sub15-breaker/issues/10) | Role-specific uv CI/images/hardening; partial foundation, complete 09. |
| [#11](https://github.com/caldeirav/sub15-breaker/issues/11) | Complete-path latency at matched quality/availability; 10. |
| [#12](https://github.com/caldeirav/sub15-breaker/issues/12) | Reproducible banking CLI/local profile/trace-score demo; 09. |
| [#13](https://github.com/caldeirav/sub15-breaker/issues/13) | Optional evidence-gated acceleration after baseline. |
| [#14](https://github.com/caldeirav/sub15-breaker/issues/14) | Banking roadmap, dependencies, evidence and closure tracking. |
| [#15](https://github.com/caldeirav/sub15-breaker/issues/15) | Frozen eligible upstream slice/checkers, not new corpus; 03a/06. |
| [#16](https://github.com/caldeirav/sub15-breaker/issues/16) | Banking prompt injection, malformed actions, stateful abuse and benign controls; 06/08. |
| [#17](https://github.com/caldeirav/sub15-breaker/issues/17) | Per-block tests/review/human acceptance/docs/PR gates; throughout. |
| [#19](https://github.com/caldeirav/sub15-breaker/issues/19) | Utility/refusal/forbidden-effect policy semantics; 03a/06. |
| [#20](https://github.com/caldeirav/sub15-breaker/issues/20) **resolved** | Metric-v2 evidence and harness-v3 scope verified; @caldeirav accepted the local block. #17 still governs later blocks and #25 is nonblocking quality work. Historical failures retained. |
| [#21](https://github.com/caldeirav/sub15-breaker/issues/21) **new** | Canonical bounded banking action/trusted-context envelope; 03a. |
| [#22](https://github.com/caldeirav/sub15-breaker/issues/22) **new** | Every model/tool/judge traced; applicable scalar columns against each specific trace; 02 onward. |
| [#23](https://github.com/caldeirav/sub15-breaker/issues/23) **new** | Atomic state version/idempotency/receipts and uncertain-write reconciliation; 03b/04. |
| [#24](https://github.com/caldeirav/sub15-breaker/issues/24) **new** | Supported bounded banking agent/orchestrator migration and retirement of legacy defaults; 08/09. |
| [#25](https://github.com/caldeirav/sub15-breaker/issues/25) **nonblocking quality** | Premature rent clarification left scheduled rent 1100, expected 1200. Keep the failure visible and investigate a bounded capability improvement separately; not a harness-PR gate. |

## Claims and remaining warning gates

No trained banking model, approved calibration, Actor tool service/reset, real action-bound admission, latch/stop integration or sub-15ms result exists yet. Each warning retires only with its own supported-profile evidence (#1/#2/#4/#5/#7/#11), not with issue creation, unit tests or one synthetic run. The complete trace/score claim also needs readback auditing (#22), not merely configured autologging. Preserve these distinctions even after all components exist: calibrated risk is not certainty; targeted attack absence is not universal financial safety; 403 is not stop; stop is not rollback; gVisor configuration is not verified isolation.
