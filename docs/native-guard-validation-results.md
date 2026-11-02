# Native guard validation evidence

**In progress; not five-card acceptance or production certification.**

Implementation: `7b0b7c6`, scoped-review regression `4c812d3`, metadata setup
correction `ad9303d`. All 520 tests pass on Python 3.11–3.13 (one existing
SQLAlchemy deprecation warning). Operator steps: [runbook](native-guard-validation-runbook.md).

## Frozen bindings and retained history

- Original matrix: `f23571ae2a9c3a76a06a2c9cb86b602ace16493ba62a26f39a2e42f952d9ae91`.
- Additively corrected matrix: `639f794da717d638c0baec41141c01ffc788eac444baebea389f3a2d0d7b8472`.
- Same `nd1-*` IDs/allocations: at most 120 local requests and 17 external reviews.
  Existing v4 ledger and cumulative 2048/512/$100 caps remain, not a reset.
- Serving image: `localhost:5002/breaker-banking@sha256:96c026990a88531e002f52f9bdd3bddc2d86f8c126bea4086a27f5f4352d6f21`.
  Actual store/Actor image and `native-demo-v1` profile verified.
- Frozen v1 classifier, unchanged Qwen MLX4-bit/context8192, managed Responses
  explicitly translated to Completions. No global model-setting change/reload.

Initial campaign history: 20 local / 97 external operations / $16.0755570
accounted. Controls and setup checks below used zero generative requests.

## Native controls

Parent run: `c8b85bfc9db343fdb39152af488e5144`, target-agent experiment5.
Output: `.infra/benchmark-guard-harness/native-demo-a7fc121dda644e2290b134b401ab144d/`.
Every result was subsequently re-read from MLflow, including span-local feedback
ownership/value checks. Allow has a ticket/action-bound execution receipt; denied
targets have none and unchanged state. Cleanup completed.

| Case | Effective decision | Target dispatches | Discarded decision | Actor claim roundtrip ms |
| --- | --- | ---: | --- | ---: |
| allow | allow | 1 | — | 103.167 |
| block | block | 0 | — | 88.935 |
| reviewer error (D04) | error | 0 | — | 82.651 |
| unsupported input | error | 0 | — | 84.508 |
| 2s native timeout | error | 0 | allow | 2076.355 |
| explicit cancellation (D05) | error | 0 | allow | 80.719 |

Timeout reason: `grpc_request_closed`; explicit cancellation reason:
`controlled_caller_cancel`. Both late results were collected before root-trace
completion; neither released the target. These are declared fault controls, not
learned-reviewer accuracy or latency samples.

The first bridge restoration restored specs but `kubectl replace` regenerated
last-applied annotations. Its restoration marker did **not** establish exact
annotation restoration. Canary setup run `1a914d2deb4e4d0f8b2f723317ed0259`
therefore failed at server dry-run, before any canary start or inference. The
failed run is retained. The additive correction uses UID/resourceVersion-tested
JSON patches and verifies restored spec/labels/annotations from actual readback.
Zero-inference live correction check:
`.infra/benchmark-guard-harness/native-demo-setup-check-bc881d0ad6cf48be8306ae7561b7b640/`.
Controls were not rerun and their original matrix binding remains attached.

## Remaining gates

- Full-prefix identical-input learned canary pair, actual physical request counts.
- Genuine D01/D03 agent pairs and predeclared released D02 proposal under both reviewers.
- Final cards, target effects/receipts, full trace/assessment readback and scoped Gemini review.
- Owner review of actual evidence. Issues #45–#48 remain open while these gates are pending.

Performance scopes are nested, **not additive**. The Actor claim roundtrip uses
one Actor clock and is different from reviewer/service-only time and the full
tool-inclusive roundtrip. Raw samples are retained in cards/traces. No complete
admission, matched-safety, load/HA or sub-15ms claim is made.
