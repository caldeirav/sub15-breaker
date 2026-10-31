# Validation records: current scope versus history

Acceptance is per implementation block. Passing harness evaluation does not mean every agent task won, and accepted infrastructure does not mean banking actions are isolated or authorized. Human approval is distinct from independent agent review, CI and code assessments.

## Delivered blocks

| Block | Authoritative record | Accepted scope / delivery |
| --- | --- | --- |
| 01 | [block-01.json](block-01.json), [checklist](block-01-infra.md) | Control plane and non-executing network/gateway fixtures; PR #18 merged |
| 02 | [block-02.json](block-02.json), [accepted checklist](block-02-harness-review.md), [technical review](block-02-harness-independent-review.md) | Banking harness-v3: correct execution/tracing/golden evaluation, not agent win rate; @caldeirav 2026-10-31; PR #26 merged |

Published counts (58 tests for block 01; 145 for block 02) describe those revisions, not universal guarantees or the size of the banking task set. JSON attestations retain the actual reported tester/date/evidence and are not rewritten during documentation maintenance.

The current banking acceptance decision is the **derived** MLflow run `53b476bed53446ebac25753aaa9a8b80`. The source `e56a427a9592460f81f246bc3c0d6e29` stays FAILED under the old 3/3 win-rate gate; rent remains utility=false. Source cases, golden outcomes and native judgments are unchanged. See [the runbook](../banking-feasibility.md) and [harness-v3 policy](../banking-harness-acceptance-v3.md).

## Historical reviews: do not apply their superseded gates

| File | Historical role |
| --- | --- |
| [block-02-banking.md](block-02-banking.md) | Initial checklist/failed-v1 evidence, before the four-criterion and harness-scope corrections |
| [block-02-independent-review.md](block-02-independent-review.md) | Initial missing-score, false-green, redaction and acceptance findings; later fixes have regressions |
| [block-02-v2-review.md](block-02-v2-review.md) | Earlier human checklist under the now-superseded live-agent win gate |
| [block-02-v2-independent-review.md](block-02-v2-independent-review.md) | Technical metric/evidence approval plus accurate old-policy failure accounting |

Their “pending,” “not accepted” and older case/test counts describe what was known at that revision. They do not override the accepted record or reopen resolved #20. Keep failures and fixes visible; do not fabricate a historical pass, erase raw native feedback or label an AI review HUMAN.

## Future blocks

Block 03a is **not implemented or accepted**. Clarify its proposed scope/requirements with the owner first. Every new block needs its own automated checks, independent review, regressions, documentation and named human/date/evidence before its scoped PR. Never reuse block-01/block-02 acceptance for a new runtime or security claim.

The publication guard is an attestation-field check, not proof that a test was performed:

```bash
uv run --locked python -m src.infra.gate docs/validation/block-02.json
```

Use the actual record for the block under review; the existing accepted record is only an example. Missing/incorrect evidence still blocks the relevant feature. Agent quality, policy discrimination, calibration, isolation/stop and latency have separate later gates.
