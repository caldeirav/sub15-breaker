## Scope

Linked issue(s):
Validation block / evidence:
Current banking scope and golden environment: `docs/project-scope.md`, `docs/golden-data.md`.

## Acceptance gates

- [ ] Automated tests and relevant live integration checks pass on the final diff.
- [ ] Independent manual validation is recorded with human tester, date, and evidence.
- [ ] Independent agent review (if used) is recorded separately; it is not labeled human acceptance.
- [ ] Confirmed findings have regression tests; affected checks were rerun.
- [ ] README/runbooks and limitations match the implemented behavior.
- [ ] The publication guard passes for **this block's own evidence record**. Do not reuse accepted block-01/block-02 sign-off for block 03a or later features.
- [ ] No kubeconfigs, secrets, model weights, or sensitive raw traces are included.
- [ ] Issues are marked fixed only if all their acceptance criteria are satisfied.
- [ ] Every applicable model/tool/verifier/judge attempt is traceable in MLflow, including failures; per-trace scalar score columns and span/action ownership pass persisted readback (banking contract: `docs/mlflow-trace-contract.md`).
- [ ] Evaluation asserts exact expected case/criterion rows and zero hidden scorer errors before aggregate means; historical verdicts/failed runs and derived-audit provenance remain intact.

## Results and remaining limitations

State exactly what was observed. Keep action denial, verified containment, Actor termination, and latency targets separate.
For harness work, agent utility/attack outcomes are reported, not required wins. For later model/guard releases, declare their own quality/availability operating point. Do not present legacy command data, sidecar routes or undeployed manifests as banking components.

## AI assistance

Disclose any AI-assisted implementation, review, or testing and the human validation performed. No AI co-author/DCO trailers.
