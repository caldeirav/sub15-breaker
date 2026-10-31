## Scope

Linked issue(s):
Validation block / evidence:

## Acceptance gates

- [ ] Automated tests and relevant live integration checks pass on the final diff.
- [ ] Independent manual validation is recorded with human tester, date, and evidence.
- [ ] Independent agent review (if used) is recorded separately; it is not labeled human acceptance.
- [ ] Confirmed findings have regression tests; affected checks were rerun.
- [ ] README/runbooks and limitations match the implemented behavior.
- [ ] `uv run --locked python -m src.infra.gate docs/validation/block-01.json` passes for block 01 (use the corresponding record for later blocks).
- [ ] No kubeconfigs, secrets, model weights, or sensitive raw traces are included.
- [ ] Issues are marked fixed only if all their acceptance criteria are satisfied.
- [ ] Every applicable model/tool/verifier/judge attempt is traceable in MLflow, including failures; per-trace scalar score columns and span/action ownership pass persisted readback (banking contract: `docs/mlflow-trace-contract.md`).
- [ ] Evaluation asserts exact expected case/criterion rows and zero hidden scorer errors before aggregate means; historical verdicts/failed runs and derived-audit provenance remain intact.

## Results and remaining limitations

State exactly what was observed. Keep action denial, verified containment, Actor termination, and latency targets separate.

## AI assistance

Disclose any AI-assisted implementation, review, or testing and the human validation performed. No AI co-author/DCO trailers.
