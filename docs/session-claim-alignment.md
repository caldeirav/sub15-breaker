# Session alignment: native circuit breakers versus measured performance

## Current scope

The owner accepts the **frozen encoder classifier** instead of AnyJev/Laya for
the initial demonstration. No decision-model integration, retraining, threshold
retuning or hidden backup is required. The agent still uses the same graph and
native pre-execution boundary for both reviewer choices.

This is an encoder plus binary classification head, not a claim that arbitrary
embedding similarity is an authorization decision. It produces two logits in one
forward pass, then applies the frozen temperature/threshold; it generates no text
tokens. The LLM reviewer generates a JSON verdict. Identical serialized inputs,
observed outcomes and resource/startup conditions must accompany any comparison.

## What the talk can currently substantiate

| Session statement | Current evidence / acceptance boundary |
| --- | --- |
| Native platform enforcement rather than agent self-policing | Demonstrated by six native controls with receipts, state and trace readback. |
| Ephemeral Actor execution through the gateway/native hook | Demonstrated for executed controls and the full-prefix classifier canary. Not every advertised card has run. |
| Non-generative binary review in one forward pass | Implemented by the frozen encoder classifier. AnyJev/Laya are not the implementation demonstrated. |
| Classifier is much faster than a completed LLM review | Now measured: fixed subsequent diagnostic review medians~18.2x (read) /15.5x (payment) faster; actual matched native payment review~8.9x and claim~6.3x. Small descriptive samples, not matched-safety or load-tested guarantees. Old timeouts remain errors, not speed samples. |
| Sub-15ms verification | Only a narrow model-stage result: read encoder-total median12.454ms (n=5 subsequent calls); payment16.538ms. Whole-review medians21–25ms in the tight-loop diagnostic; actual native classifier reviews53.8–212.6ms and best observed claim88.9ms. **Not sub15ms complete review/native admission.** |
| Mathematically calibrated safety | Frozen temperature scaling and provenance exist, but this is an imperfect classifier with known transfer/quality limitations. A probability is not a universal safety guarantee. Report held-out reliability, errors and coverage under the actual distribution before making a calibration claim. |
| Eliminates positional bias | Not established by these tests. Deterministic serialization is not a positional-invariance proof. |
| Validates terminal/API execution success | The banking example verifies proposed actions **before execution**. Original task utility is checked separately afterward. This does not demonstrate a generic post-execution terminal/API verifier. |

The architecture remains aligned with the session's direction; the current
demonstration does **not** substantiate an unqualified title-level numeric threshold or the
abstract's broad calibration/bias/security guarantees. Do not present those as
measured results. If15ms is an inference-only target, say so explicitly; do not
use it as a synonym for full native admission.

## Resource-isolation implementation

`src/benchmark/serving.py` now manages encoder resources by selected reviewer:
- LLM-only runs load the verified projection **tokenizer only**, not classifier
  weights. Deterministic controls load no weights; unsupported-input controls
  need only the tokenizer.
- Classifier weights load lazily for a classifier case, remain resident within
  that arm, and are explicitly released before an LLM/control arm. Unused local
  PyTorch MPS cache is released; the shared Qwen/MLX process is not reconfigured,
  unloaded, reloaded or warmed.
- `--classifier-device mps|cpu` is explicit and included in the plan. There is no
  automatic CPU/model fallback. MPS remains the default; selecting CPU does not
  establish speed or numerical equivalence without validation.
- Resource load/release events and durations are recorded separately from review
  latency. Re-entering a classifier arm may load its weights again; this is
  visible startup work, not a hidden warmup inference.

This removes unnecessary residency/competition in the LLM baseline. It is
**not dedicated hardware isolation**, and does not establish the cause of the
earlier slow prompt processing. CPU and GPU still share physical memory.

## Automatic reconciliation implementation

The demo opts into bounded read-only reconciliation after application cleanup:
1. Verify the existing native/action ownership, operation counts and span-local
   assessments against persisted data.
2. Require one imported gateway model span per attempted physical model request
   and one imported gateway MCP operation per tool-client span—not merely a
   global count or a stable but incomplete tree.
3. For generative requests, observe the exact loaded model idle with zero queued
   requests using read-only `lms ps --json`. Missing/busy/failed observations
   remain pending. Idle is a point-in-time observation, not per-request usage or
   proof that cancellation immediately stopped provider compute.
4. Require a quiet evidence interval, then re-read store fingerprints and tool
   attempts to detect late effects. No prepare/claim/execute/model operation is
   repeated.
5. Return `telemetry_reconciliation.status=incomplete` on a deadline or evidence
   gap. The card cannot be ready and dependent execution stops. Persist the
   reconciliation separately; do not rewrite old case evidence.

Default policy:30s observation deadline,1s quiet interval,.5s polling. Each I/O
also has its configured transport timeout; this is post-run evidence latency,
not added to the measured admission interval. Local roots can close before
asynchronous remote export; the final reconciled manifest explicitly records
the later readback rather than pretending the original root included it all.

## Performance evidence to collect next—not spent by these changes

- Same-input successful classifier/LLM reviews, with errors/timeouts counted
  separately and no preferred-outcome pairing. `compare_reviews` refuses a
  timeout-derived speedup and never certifies safety equivalence or15ms.
- Separate first-use from declared steady-state samples; freeze any warmups and
  repetitions before spending. Include device, input lengths and resident models.
- Report tokenizer, device enqueue, forward/host-result, whole encoder, whole
  reviewer adapter, native service and Actor claim measurements separately.
  Device enqueue is asynchronous; forward/host-result includes synchronization
  of pending device work. Neither is advertised as a pure GPU-kernel timer.
- Retain classifier mistakes and held-out calibration/coverage evidence alongside
  latency. A fast wrong answer is not a successful safety demonstration.

These source changes intentionally invalidate the old frozen execution binding.
**No `nd1-*` ID is reset and no new inference is authorized or spent.** A fresh
phase, realistic deadline profile and fixed diagnostics/allocation must be bound
before live validation. PR #49 remains draft; #47/#50 own reconciliation/serving,
#46 owns the completed input pair, #48 owns actual card validation, and #45 owns
session/demo acceptance.

## Implementation validation (no new inference)

This subsection records the earlier implementation-only check. Subsequent
authorized live measurements, all14 native cases and the scoped `supported`
external harness review are documented in [the latest results](laptop-measurement-results.md).
Seven/eight selectable backend variants meet their intended outcome; the D01/LLM
permitted-read false block remains visible and not ready. No accuracy or safety
guarantee is inferred from the speed advantage or harness review.

- All552 tests pass on Python3.11–3.13, including lazy-resource lifetime, no
  fallback, tokenizer-only loading, one-forward instrumentation, delayed gateway
  export, provider-busy/unobservable deadlines, ownership failures, late effects,
  readiness gating and comparison exclusions.
- A read-only check against the two historical native canary traces reconciled
  their exported operations and observed provider idle, then re-read the durable
  store with matching fingerprints/tool attempts. This **does not rerun or make
  the failed LLM case successful**. The comparison correctly reports
  `insufficient_completed_pairs`.
- Check artifact:
  `.infra/benchmark-guard-harness/serving-reconciliation-check-ad745c61f858486094e360eb9c0a9e9e.json`.
- No classifier forward, acting/reviewer model request, warmup, external judge,
  shared-model reload or settings change was issued by this implementation work.
  New resource behavior has unit coverage, not a fresh native serving/latency
  qualification. Slow-prefill cause and sub15ms feasibility remain unproven.
