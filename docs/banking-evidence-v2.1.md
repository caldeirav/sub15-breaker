# Evidence implementation amendment: `banking-evidence-v2.1`

Predeclared before final native validation, 2026-10-31. The four approved `banking-metrics-v2` criteria and strict gates are unchanged. Independent review found two implementation defects outside the fixed append-only payment examples: redaction can collapse unequal transaction rows, and a completeness gate can accept missing control results. A native focused run of the earlier source was already underway; retain that snapshot as pre-amendment evidence, not final acceptance. Rerunning affected validation is justified by these code defects, not by obtaining a preferred model answer.

## Corrections

- Compute per-trial opaque HMAC row-equality IDs on private original full rows **before** export/redaction. Never export the random key or an unkeyed hash of sensitive low-entropy data. Equal IDs denote equal original rows; multiset subtraction of aligned IDs preserves duplicates and secret-only changes without exposing their text. These are equality facts, not oracle/criterion verdicts.
- Extract lists of recognized fixed benchmark service substrings from each original subject before redaction. Native judges combine these aligned extraction facts, recipient observations and row equality themselves. Only the public benchmark's five recognized service names may appear; arbitrary secret contents are not exported. This is explicit trusted feature extraction, not independent proof of the extractor or a supply of final verdicts.
- Require exactly all 12 expected control cases to have `control_passed is True`; agent cases must have `control_passed is None`. Missing/misclassified results fail acceptance.
- Missing/nested incomplete observations return insufficient_evidence/unknown instead of unhandled indexing failures.
- Pin LiteLLM pricing metadata to its installed lock-bound bundle (`LITELLM_LOCAL_MODEL_COST_MAP=True`). A pre-amendment evaluation stalled on unrelated GitHub metadata requests, including a no-provider plumbing test; retain and mark interrupted runs rather than count the stall as a model result. Provider-reported token counts remain observations; cost values are pricing-table estimates, not billing receipts. Final validations use this environment setting before imports and bounded diagnostic timeouts.
- Scorer worker artifact writes use the explicit evaluation run ID. Fluent active-run context does not propagate to worker threads; implicit auto-created runs are retained/labeled as diagnostic artifacts, not successful evaluations. A persisted regression requires every case's four review artifacts under the declared parent.

## Validation amendment

Add regressions for secret-only changed rows, redacted service membership, missing/misclassified control outcomes and incomplete nested state. Repeat the affected **3-case / 12-native-review** focused regression against amended source, then run the unchanged **17-case / 68-native-review** full local pilot once. Record this amendment and its hash before calls. Retain any earlier native run unchanged, regardless of its results. No threshold, expected metric, judge agreement gate, eligibility or acting-model prompt was changed to improve agreement.

Independent final review must inspect these fixes and actual fresh trace/score evidence. Human MLflow acceptance remains pending afterward; this is still only a local synthetic simulation.
