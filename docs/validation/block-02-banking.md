# Block 02: banking feasibility acceptance

**Current PR review:** use [the harness-v3 checklist](block-02-harness-review.md), not the historical win-rate gates below. The owner approved separating harness correctness from agent quality; #25 is nonblocking. Original runs and previous acceptance decisions remain history.

**Historical v1 checklist, superseded for current review.** Use [the v2 guide with exact run/trace links](block-02-v2-review.md) and [independent v2 review](block-02-v2-independent-review.md). #20 is resolved for metric semantics; fresh v2 main remains FAILED for a separate rent-agent capability finding (#25), and human acceptance remains pending. The older evidence/checklist below is retained as history, not a request to decide #20 again.

**Status: not accepted; PR publication and progression blocked.** A separate [independent agent review](block-02-independent-review.md) completed with changes required. It is not independent human acceptance; block-01 approval does not approve this feature.

## Evidence

- Corrected [MLflow parent run](http://localhost:5001/#/experiments/1/runs/f994d093234a40579e9919a5a67eb5c8): 12/12 deterministic controls, 3/3 benign successes, five agent trials, 34 validly cited native Gemini reviews, 33 agreements. Status remains FAILED / review_required.
- Focused [live MLflow judge regression](http://localhost:5001/#/experiments/1/runs/0f76c1521c0f42608506559f800977ff): **acceptance retracted**. Pytest passed, but one scorer row failed with KeyError and aggregate means omitted it. Original FINISHED status retained as history. Corrected tests require stable evidence-ID lookup and exact zero-error row coverage.
- Previous pre-v2 offline check: `bash scripts/test.sh` passed 105 tests. The latest v2 suite has 137 passing tests, with separate native validation documented in the v2 guide.
- Persisted no-provider [MLflow plumbing run 66f6601a55fd4cdca15b6bbd084b5c6c](http://localhost:5001/#/experiments/1/runs/66f6601a55fd4cdca15b6bbd084b5c6c): three case traces, four CODE-stub judge reviews and two stub model invocations; exact evaluate rows and trace/score readback passed. Not Gemini quality, full-pilot semantic acceptance or human sign-off.
- Derived historical audit: parent `audit/trace-score-columns-v1.json`, `trace-score-columns-v1-final.csv` and `trace-score-columns-v1-final.table.json` expose **51 trace rows / 34 columns**, with scalar assessments on the owning traces as well. Original verdicts/status preserved. Review/model/token/cost scores now exist on all 34 specific judge traces; backfilling is not fresh execution evidence.
- [Issue #20](https://github.com/caldeirav/sub15-breaker/issues/20): now resolved under the approved v2 contract; original predicate/disagreement and regression history remain unchanged.
- [Execution guide/results](../banking-feasibility.md); machine-readable acceptance state: [block-02.json](block-02.json).

## Independent owner review (pending)

Use a separate browser/terminal; existing evidence review needs no new paid model calls.

1. Open the corrected parent run. Confirm FAILED / review_required, inspect `manifest.json`, `summary.json`, `results.json`, `judges/reviews.json` and the source/lockfile artifacts. Confirm 17 child cases and 34 reviews; do not equate valid citations with agreement.
2. Open a benign agent child. Inspect its AGENT, Responses/CHAT_MODEL and TOOL spans, original request, arguments/results, actual state and code oracle assessments. Verify the claimed task effect rather than trusting the final answer.
3. Compare reference, no-op, wrong-effect and reference-plus-attack controls. The last must retain utility true and attacker predicate true; utility alone is not safety.
4. Inspect both registered native Gemini judges and their feedback. Check exact `criterion_id`, `reference_id` and run-qualified `evidence_id`, plus the separate `/agrees` assessment and review trace.
5. Open child `72ad38ff306a49efa58f32fd590def88`. Compare the observed attacker transfer and actual upstream predicate to the Gemini rationale. Read parent `audit/oracle_judge_disagreement.json` and trace `audit/upstream_predicate_semantics`. Confirm neither the oracle nor FAILED status was overwritten.
6. Compare original and fact-preserving attack artifacts. Verify the adaptation preserves invoice amount/payee and is separately labeled, not claimed to be the unchanged official attack. Inspect the retained initial failed run `0a38defddd2940978468a976a6a85fa9`.
7. Historical step: #20's contract has since been explicitly approved and validated. For current review, record the distinct #25 failure under the v2 guide; do not change/exclude labels or resample for agreement.
8. Record reviewer identity, date, evidence and decision separately from automated results. Only after the outstanding gate is resolved and manual acceptance recorded should this block's scoped PR be published. No next implementation block starts before that PR gate.

This review cannot certify a deployed gateway/Actor boundary, calibrated classifier, universal financial safety, real payments or sub-15ms overhead; none was exercised.
