# Historical documentation evidence

This is an **evidence archive, not current setup instructions**. Current guides:
[documentation index](../../docs/README.md). Only the latest demo has a current
[versioned result page](../../docs/results/demo-nd11-nd12.md).

## Preservation boundary

`docs-2026-11-02/` contains **byte-for-byte copies** of all former `docs/validation/`
records (including the five JSON attestations) and seven frozen protocol/rubric
Markdown assets. Paths inside these records intentionally describe their original
revision. Their hashes and reported human/agent/automated decisions are unchanged;
stale/pending/failed text is not silently promoted to acceptance.

[`SHA256SUMS`](docs-2026-11-02/SHA256SUMS) binds all27 moved files to their contents
at source revision **`394b16518cf0b090d873562715190dbf92c1e4d0`**. A regression test
checks the complete archive against that manifest, without needing Git/network.
Original relative links that leave the archived subset should be read against
[the complete original docs tree](https://github.com/caldeirav/sub15-breaker/tree/394b16518cf0b090d873562715190dbf92c1e4d0/docs),
not rewritten inside an immutable record. This archive's historical commands
and acceptance counts are not current operational permission.

The form loader still uses frozen `banking-action-label-policy.md` and
`suite-grounded-labels.md`; legacy feasibility/reassessment and opt-in native
validation still load the same five metric/evidence/provenance/registry/harness
policy files from this new location. Only their resource paths changed. No
runtime scoring, rubric bytes, labels, provider calls or review provenance changed.

## Consolidation map

All former pages remain recoverable at the source revision above. Their
still-applicable content is now maintained in these guides:

| Former documentation family | Current home |
| --- | --- |
| Scope, shared contracts, Actor service, harness/experiment design and legacy boundaries | [Architecture](../../docs/architecture.md) and [agent flow](../../docs/agent-flow.md) |
| Action labels, suite-grounding rules, human-review walkthrough, ModernBERT v1/v2 plans and frozen-model diagnosis | [Model/calibration](../../docs/model.md); original training artifacts remain authoritative research evidence |
| Golden data, metric/evidence amendments, evaluation/harness acceptance and MLflow trace contract | [Validation](../../docs/validation.md); frozen historical protocol bytes stay here |
| Infrastructure guide, target-stack reviews, readiness and transport investigations | [Local environment](../../docs/infra.md) and relevant failure/startup sections of [agent flow](../../docs/agent-flow.md) |
| Native-demo plans/runbooks, transport/capacity/readiness/startup follow-ups, review API/backend plans | [Demo](../../docs/demo.md), with implemented commands and explicit operator/authorization limits |
| Current acceptance + ready-golden methods/results and source bindings | [Latest demo report](../../docs/results/demo-nd11-nd12.md), merged without dropping performance, startup or accounting evidence |
| Older nd1–nd10 result pages and superseded future-work/block ledgers | Removed from current docs; original text in Git history, raw run artifacts/negative reviews unchanged; current backlog in [roadmap #14](https://github.com/caldeirav/sub15-breaker/issues/14) |
| Old documentation audit/session claims | Superseded by source-verified topic guides; unsupported guarantees and relevant caveats remain explicit |

No `.infra/`, model/training dataset, MLflow database/run status, cumulative budget,
reservation, original source artifact or private key was deleted or modified by
this documentation cleanup. Existing saved review bundles still contain historical
runs, including failures; documentation consolidation does not regenerate them or
issue a new judge review. A new live run requires its own approved allocation.
