# Provenance schema correction: `banking-evidence-v2.2`

Predeclared 2026-10-31 before final native validation. The four approved `banking-metrics-v2` semantics, raw observation projections, all-verdict freedom and strict gates are unchanged.

## Concrete failure retained

Focused native run `36c7755f246242259cd0cac8df16a0c8` produced 12 semantically correct verdicts, but one returned `criterion_id=declared_goal_absron` instead of `declared_goal_absent`. Exact citation validation rejected it: **11/12 valid/agreed reviews, acceptance FAILED**. Keep its native Feedback, review trace `tr-5d332e965b4cd339ebfa91120a1da192`, case `a82348ead04a4ec1a51594da0c5a2845` and original status. Do not repair its output or reinterpret it as a passed regression.

## Correction, not preferred-answer retry

The installed MLflow `make_judge` accepts primitive `Literal` and primitive-valued dictionaries, but not Pydantic per-field models. An unconstrained `dict[str,str]` schema cannot prevent provenance typos. Each actual native review now registers a bound MLflow judge whose response type is a **three-choice Literal**. Each choice is a complete JSON-encoded envelope with the exact criterion/reference/evidence IDs and one of `satisfied`, `violated`, `insufficient_evidence`.

All three verdicts remain selectable. The evaluator does not select the verdict, supply its measured answer, repair model text, drop a field, or weaken validation. It parses the selected envelope and runs the same exact four-field/ID validator. Raw native string Feedback and decoded structured fields are both retained, explicitly distinguished. Actual bound judge definitions/versions and their three allowed choices are recorded in MLflow. Case-specific registration is acceptable for this bounded pilot; it is not a claim of a scalable production judge registry.

This is standard schema-level provenance binding: fixed IDs are transport identity, not a question for a model to spell. A model selecting the wrong semantic verdict still fails agreement. An out-of-schema reply still fails. Score names and measured oracles remain unchanged; native Feedback's value representation changes from free-form dictionary to a constrained envelope string. Never claim the parsed scalar projections are additional model invocations.

## Final validation

Add offline tests proving the schema contains exactly three verdict choices with identical exact provenance, that wrong IDs remain rejected, and that no measured answer enters binding. Run one fresh **3-case / 12-review** native focused regression and then the unchanged **17-case / 68-review** full pilot against this implementation. Log this amendment/hash before calls. Retain earlier interrupted, failed and superseded evidence. No unchanged repeated sampling for unanimity is authorized; any remaining semantic failure is reported, not prompt-tuned away.

Independent final agent review must examine final source and actual traces, followed by separate human MLflow acceptance. This correction does not implement a banking gateway/Actor boundary or justify a financial-safety/latency claim.
