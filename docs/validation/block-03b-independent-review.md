# Independent source/evidence review: Actor-backed banking

Reviewer: separate read-only agent session `ses_e6d84525fffeMOgaJR7APJ67GN`, explicitly authorized by the owner. Final review: 2026-11-01. **Scoped source/evidence review approved, with no remaining concrete defect found. This is not overall service acceptance or human sign-off.**

Confirmed findings were fixed and regression-tested: interrupted-generation recovery and reservation release; stable lost-response/two-hop reconciliation and stopping on uncertainty; authoritative password-change flags; partial feedback repair and fresh exact readback; exact-capacity export; header deadlines; deployment/policy/pool ownership; observed ready serving-image/rollout checks; Gemini-only/exclusive budgets; final summary/export ordering; strict boolean feedback and exact string state-version columns.

Independently verified:

- 54 service regressions pass. Full local suite contains 282 tests; supported-version PR CI is not yet claimed.
- Runtime `649504e7c52c4f05ae39f1b8e5b96d2c`: 23 case roots and 51 durable events with unique owned CODE scores; 14 claimed attempts / 13 results; five UID-correlated gVisor assignments and passing security probes; seven backend source snapshots match.
- Live `f3d8498e82f94d7aadd36404e34c829b` remains **FAILED**, passed=false. All 71 events reconcile: ten model attempts yield nine results plus one error, seven prepared/claimed/completed tools and twelve paired judge attempts/results.
- Seven live receipts match actions, bindings, Actor identities and recorded gVisor assignments. All 28 derived receipt columns pass strict owned readback and repeated, write-forbidden idempotence checks.
- Native Gemini reviews have valid provenance and agree with deterministic projections: **8 satisfied, 4 insufficient_evidence**. This is not twelve task wins or an erased serving error.
- Diagnostic `0009aa95aee848bab7bae3dce0a9524e` is FINISHED and reproduces the parser HTTP500 with the same safe request, no tool/judge spans and no inferred successful rent effect.

The review made no edits, tracking mutations, cluster operations or model/provider calls. At review time publication remained blocked by the predeclared non-fault live-gate failure [#28](https://github.com/caldeirav/sub15-breaker/issues/28) and fresh human acceptance, not a required 3/3 task win rate. The owner later authorized an interim draft handoff with remaining acceptance tracked in [#29](https://github.com/caldeirav/sub15-breaker/issues/29); this does not change the review findings or passing/failing attestations. See [the machine record](block-03b.json) and [inspection guide](block-03b-service.md).
