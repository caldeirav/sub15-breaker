# Bounded native validation

**The nd1 commands below are historical and spent. Do not execute them again.**
Latest protocol/evidence: [completion-first plan](laptop-measurement-plan.md) and
[validated results](laptop-measurement-results.md). nd2 measurements and nd3 native
validation are also spent; use their read-only report/trace artifacts for review.
Rehearsal/presentation needs a new approved phase, never a reset of these IDs.

This extends the existing `wiring.run_case` / compiled agent graph. It does not
improve or retune the frozen classifier. **No card is ready until its recorded
validation evidence says so.** Historical failures and spending remain intact.

## Issue ownership and closure gates

| Issue | This branch owns | Closure evidence required |
| --- | --- | --- |
| #46 | Complete fixture prefixes, strict live arguments, schema-ordered projection | Reference/store roundtrip tests for tasks0/2/13; both native canaries with identical materialized inputs and reconciled physical reviewer calls |
| #47 | MCP backend deadline, cancellation/fence/drain, late decisions, receipts and trace-local timings | Offline lifecycle tests plus native allow/block/error/unsupported/timeout/cancel controls, resource restoration, persisted span/assessment readback |
| #48 | Bounded matrix, selectors, cards, post-run review | Frozen v4 allocation, real D01/D03 pairs and released D02 proposal, honest readiness and scoped Gemini review |
| #45 | Parent delivery/acceptance | All five cards actually validated; owner review of evidence; no automatic closure from source merge |

Broader production/security/model-quality issues are not closed by these controls.

## Non-spending inspection

```sh
uv run --locked python -m src.benchmark.compare --list-demo-cases
uv run --locked python -m src.benchmark.compare --demo-case pay-bill --guard classifier --dry-run
```

These commands need no keys and touch neither cluster nor ledger. D01/D03 use
genuine model proposals. D02 is an explicitly scripted released attack after the
two-step reference prefix. D04/D05 are fault controls, not reviewer accuracy data.

## Prerequisites and freeze

1. Pass the complete suite on Python 3.11–3.13 using **separate environments**.
2. Commit the implementation. Build `scripts/build_banking_image.sh`; deploy the
   resulting digest-bound reference with
   `Deployment().setup(image, deadline_profile="native-demo-v1")`. Preserve the
   existing PVC, trials, runtime keys and campaign history.
3. Verify owned cluster, store deployment, Actor template/profile and actual image.
   Keep the shared Qwen model loaded; do not change global LM Studio settings.
4. Use the frozen v1 artifact at
   `.infra/benchmark-guard-harness/modernbert-training-v1/model/` and the existing
   `.infra/benchmark-guard-harness/combined-budget/` ledger.
5. Freeze once:

```sh
uv run --locked python -m src.benchmark.demo --freeze-demo
```

The immutable `nd1-*` validation allocation is **120 local requests / 17 Gemini
operations maximum** (not spent requests). This includes four extra LLM canary
slots beyond the original 116-local card proposal. Existing cumulative v4 limits
and all historical conservative cost holds still apply. Any changed bound code,
fixture, model or image invalidates execution; it does not reset a spent case.

## Execute once, in order

```sh
uv run --locked python -m src.benchmark.demo --execute-demo --stage controls
uv run --locked python -m src.benchmark.demo --execute-demo --stage canary
uv run --locked python -m src.benchmark.demo --execute-demo --stage cards --demo-case pay-bill
uv run --locked python -m src.benchmark.demo --execute-demo --stage cards --demo-case deny-extra-transfer
uv run --locked python -m src.benchmark.demo --execute-demo --stage cards --demo-case update-profile
```

Each case has an irreversible start marker, including zero-request controls.
`--stage cards` excludes canaries and unrelated controls; D04/D05 refer to the
already-spent error/cancel controls, so do **not** execute them a second time.
Alternatively, one `--execute-demo` runs the entire ordered validation once.
Canaries require all native controls to pass. Real cards require both complete,
identical-input canaries. Evidence gaps stop execution. A reviewer mistake remains
a not-ready card, not a reason to repeat sampling or force the decision.

After all declared cases have persisted, explicitly run post-run review once:

```sh
uv run --locked python -m src.benchmark.demo --review-demo PATH_TO_CONTROLS PATH_TO_CANARIES PATH_TO_CARD_RUNS
```

Supply every validation output directory (paths printed by the runner); do not
include duplicate case files. This performs up to sixteen original task reviews
and one harness review scoped to the declared matrix, not the old three-task
completion rubric. Provider errors and negative reviews are retained; no repair,
fallback or automatic retry. Review cannot turn a failed execution green.

## Evidence and performance review

Each output directory contains immutable-by-ledger-hash case JSON, `cards.json`,
`review.html`, and either `result.json` or failure/partial records. MLflow target
agent traces contain native admission, Actor dispatch, original checker results,
physical model transport and cleanup. Feedback is attached to the relevant native
or dispatch span and read back with ownership/value checks before returning.

Review these independently:
- Intended versus effective review, original utility, and enforcement correctness.
- Prefix dispatches versus target dispatches; ticket/action-bound execution receipt
  or its absence; per-target before/after fingerprints.
- Errors/unknowns, discarded late allow, fence/cleanup and persisted trace audit.
- Raw serial timing samples and small-sample p50/p95, separately for each backend
  and for faults: snapshot/prepare, materialization, reviewer, admission service,
  Actor claim roundtrip, tool evaluation, commit, and tool-inclusive HTTP roundtrip.

These durations are **nested, not additive**. Actor claim timing uses one Actor
clock and includes the claim return path; host preparation/materialization is
outside it. Service-only or tool-inclusive timing is not complete admission
latency. No matched-safety, load/HA, production safety or sub-15ms claim follows.

Rehearsal/presentation require a separately approved matrix and fresh IDs/state;
this validation namespace intentionally cannot be reset or clicked until green.

## Recorded setup-only correction (2026-11-02)

The first six controls completed in run `c8b85bfc9db343fdb39152af488e5144`.
Canary setup run `1a914d2deb4e4d0f8b2f723317ed0259` then failed during
server dry-run, **before any learned case started or inference was spent**.
`kubectl replace` had regenerated the restored last-applied annotation from a
live object. Specs were restored, but that annotation was not byte-identical;
the initial restoration marker alone did not prove complete metadata restoration.
The following client-side apply attempted to erase `resourceVersion` and failed.

The correction uses UID/resourceVersion-tested JSON patches for existing owned
resources and reads back restored spec, labels and annotations. A separate
zero-inference live setup check proved repeated update/restoration works at
`.infra/benchmark-guard-harness/native-demo-setup-check-bc881d0ad6cf48be8306ae7561b7b640/`.

An **additive immutable correction**, not a replacement/reset, binds only the
deployment correction and the runner/budget code needed to verify that binding.
It cannot change fixtures, reviewer/Actor code, image, IDs or allocations; it is
allowed only before any demo inference or learned-case start marker exists.
The original matrix, six spent control markers/traces and failed setup remain.

```sh
uv run --locked python -m src.benchmark.demo --freeze-setup-correction 1a914d2deb4e4d0f8b2f723317ed0259
uv run --locked python -m src.benchmark.demo --use-setup-correction --execute-demo --stage canary
```

Subsequent card and review commands must also include `--use-setup-correction`.
Do not run controls again. Their enforcement evidence is inherited with its
original matrix binding; new learned evidence uses the corrected binding. This
is an explicit infrastructure setup correction, not another model sample.

The corrected canary invocation subsequently stopped on one20s LLM-reviewer
timeout. **Do not repeat the spent canary or run the real cards past that gate.**
The allocated `nd1-review` slot was used once to review the incomplete matrix and
returned `not_supported`; do not invoke it again. See
[the retained results](native-guard-validation-results.md) for exact traces,
provider-tail reconciliation, spending and the consolidated HTML review page.

### Follow-up source changes: isolation and automatic reconciliation

See [session claim alignment](session-claim-alignment.md). The runner now loads
classifier weights only in a selected classifier arm and releases local weights
before an LLM/control arm. Projection-only LLM cases use the verified tokenizer.
Classifier device is explicit (`--classifier-device mps|cpu`); no shared-model
settings/reload or automatic fallback is introduced.

New demo records require bounded gateway/provider reconciliation and late store
readback before readiness. Timeout/incomplete evidence blocks dependent cases.
Matched-review comparison artifacts exclude errored/cancelled/control/unmatched
samples and keep canaries separate from genuine-agent cards.

These changes invalidate the spent `nd1` source binding. **Do not use the old
freeze/setup-correction commands to authorize another attempt.** A fresh phase
and allocation must bind the resource and reconciliation profile first. No new
phase, model request or startup warmup has been allocated by this source change.
