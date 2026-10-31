# Independent technical review: block 03a

Reviewer: separate read-only agent session `ses_e6dc59cbdffeSjkAlyLM40uNHu`, explicitly authorized by the owner. Date: 2026-10-31. **Approved for the confirmed contracts + record-only fixture scope; no remaining blockers found. This is not human acceptance, authentication assurance or deployment approval.**

## Findings and verified corrections

1. **P2, receipt JSON Schema semantics:** initial export omitted Python outcome invariants. Draft 2020-12 conditionals now reject false fixture execution and false non-execution/known-state claims for unknown/error outcomes. Negative cross-validator tests include both original counterexamples. Dynamic arbitrary-field equality/order and keyed/evidence validation are explicitly reserved for runtime checks; no schema-only proof is promised.
2. **P2, assessment provenance:** initial readback could accept matching values from another issuer. Final readback requires unique root-level CODE assessments from `banking-contract-fixtures-v1`, exact values/error codes and no unexpected contract namespace fields. Wrong-HUMAN-owner and duplicate-score regressions pass.

The implementation also enforces the exact 26-case matrix rather than allowing empty, missing or duplicated plans to pass.

## Independently inspected evidence

- **228 offline tests pass**, including 83 contract tests.
- [MLflow a7cc4f2497d24a819edfd1d2e57b1e22](http://localhost:5001/#/experiments/2/runs/a7cc4f2497d24a819edfd1d2e57b1e22), experiment `breaker-banking-contracts-03a`: 26/26 expected matches, 12 allow / 1 deny / 12 error / 1 unknown.
- All seven implementation hashes and exported schema bundle match current source.
- Persisted stages, root outputs, assessment ownership/values/error codes and independent readback pass.
- No model/banking-tool/real-execution calls or corresponding execution spans; record-only and non-execution flags are consistent.
- Prior intermediate and failed runs remain preserved; `86aceab640b44f8e9bf4aae7fdf9747a` remains FAILED.

The review made no provider calls, source edits or tracking mutations. The fixture registry's caller identity is a trusted-adapter assumption, not authentication; its HMAC commitments are not signed admission grants. Real authority, transactional state, durable replay protection and actual tool execution remain later blocks. At review time human acceptance was pending; @caldeirav subsequently accepted the scoped feature on 2026-10-31 in [block-03a.json](block-03a.json).
