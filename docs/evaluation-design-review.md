# Evaluation design: banking ground truth, observations and native judge review

The selected domain is **AgentDojo simulated banking**. This document supersedes the earlier shell-dataset/alternative-benchmark recommendation. The [previous research revision](https://github.com/caldeirav/sub15-breaker/blob/1e32c54eec0cfe060013487789924baa57470894/docs/evaluation-design-review.md) remains in Git history; it is not the current task-source or implementation plan.

## Evaluation flow

```text
pinned banking task/reference criteria + fresh synthetic state
  -> local acting model and released simulated tools
  -> independently recorded actions/results and final state
  -> deterministic upstream/effect evaluation
  -> native MLflow Gemini review of projected observations and closed criteria
  -> exact per-case trace/score audit + harness acceptance
```

The [golden environment](golden-data.md) supplies tasks, state, tool definitions, released reference actions and executable checks. Reuse it; do not author another task corpus, compare reference command strings, scrape financial filings or add a parallel benchmark to satisfy the circuit-breaker demo.

## Separate the questions

| Question | Evidence / result | What it does not establish |
| --- | --- | --- |
| Did the task succeed? | Pinned utility predicate on observed state; passed/failed/unknown as applicable | Every action was safe or authorized |
| Did the selected attack/effect occur? | Upstream predicate, new/changed forbidden-recipient facts and declared service disclosure, separately | Complete financial policy or universal containment |
| Did the evaluator work? | Exact matrix, validated controls/golden recomputation, trace/provenance completeness and correct scoring | Agent win rate or guard quality |
| Was a proposed action permitted? | Future trusted action/intent/policy/state contract, independent reviewed labels and admission/receipt evidence | A label obtained from task utility or an LLM's confidence |
| Was enforcement/isolation effective? | Future actual Actor/gateway/bypass/stop/canary evidence | Installation, a 403, a graph stop or a YAML runtime setting alone |
| Is the comparison fast and useful? | Future matched A/B authorization timing at a predeclared quality/availability operating point | A forward-pass timer or assumed <15ms result |

For this accepted [harness PR](banking-harness-acceptance-v3.md), an agent may fail and the harness may still pass. The rent example stayed at 1100 instead of 1200; correctly recording utility=false and native verdict=violated is successful evaluation. #25 remains a separate, nonblocking model-capability finding. Missing/incorrect evidence or scoring remains blocking.

## Validate references and controls before interpreting agent results

- Freeze the AgentDojo commit/benchmark and eligible task IDs before agent measurement.
- Require released reference actions to satisfy utility and no-op/wrong-effect controls to fail it. Reference-plus-attack demonstrates that utility=true can coexist with attack effects=true.
- Keep the invoice-replacing attack diagnostic separate from the labeled fact-preserving adaptation. Lost task facts are not evidence of safe refusal.
- Preserve exact upstream weaknesses for parity, including first-match/substring semantics. Exclude meaningless always-true checks from a meaningful utility population rather than ask Gemini to invent an oracle.
- Record every case and expected review row, including errors and unknowns. Aggregate means can omit scorer errors; row/cardinality/provenance validation comes first.
- Report development versus holdout use, exclusions, counts and uncertainty. These three tasks are development evidence, not a statistically adequate safety benchmark.

## Native MLflow Gemini role

Gemini evaluates relevant projected observations against a versioned fixed rule and reference parameters. It sees **neither measured verdicts nor Python checkers nor agent success claims**. Raw subject text is data, not authority. Trusted equality/service extraction features are explicit and distinct from final labels.

Each actual native judge is registered with a three-choice `Literal` envelope schema. All three verdicts remain possible; IDs are fixed provenance. Preserve the raw native JSON string and decoded four-field object, plus scalar verdict/validity/agreement/error/model/usage assessments against the owning target **and** review trace. No output repair or relabeling for agreement.

Code outcomes remain authoritative. Schema-constrained agreement demonstrates narrow rubric conformance, not objective financial truth, independent safety-training labels or a free-form citation skill. Judge time is outside admission latency. The installed MLflow runtime selects its native Gateway provider adapter for Gemini; other supported profiles can use LiteLLM. Inspect and test the actual selected adapter. MLflow's SDK Gateway adapter is not the deployed agentgateway or a second judge invocation.

See [current criteria](golden-data.md#four-separate-criteria), [trace ownership](mlflow-trace-contract.md) and the [accepted review checklist](validation/block-02-harness-review.md). Historical failed and false-green runs remain preserved and indexed in [documentation history](README.md#frozen-experiment-protocols-and-historical-evidence).

## Planned A/B experiment—not yet executed

Both modes must authorize the same canonical action/context at the same trusted gateway boundary. A is generative verification; B is one compact classifier pass, with deterministic identity/schema/resource checks around both.

1. **Same-action replay** compares verifier discrimination, calibration and complete admission latency on independently reviewed action/context pairs.
2. **Fresh-state full-agent trials** measure utility, refusal, effects, failures and task cost when action sequences may differ. Counterbalance order and predeclare model/settings/repeats/quality budgets.

Neither protocol is currently an implemented banking A/B deployment. Policy/action labels and train/calibration/validation/test groups remain separate from task-success outcomes; do not train on held-out task solutions or use Gemini to mint independent labels. Thresholds are policy/model/schema-bound, not inherited from the command-only prototype.

## Next design boundary

Block 03a's [canonical contracts and record-only fixtures](banking-contracts-03a.md) followed owner clarification and are now independently reviewed and accepted by @caldeirav on 2026-10-31. They do not integrate live admission. Follow [the sequenced plan](implementation-plan.md) for Actor tools/reset, authenticated admission, latch/stop, policy data, model/calibration and matched performance evidence. The [legacy modules](legacy-compatibility.md) are not a banking architecture or a prerequisite data project.
