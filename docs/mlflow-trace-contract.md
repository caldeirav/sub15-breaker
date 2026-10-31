# MLflow trace and score contract (`banking-traces-v1`)

Owner requirement: every model/tool/judge invocation appears in MLflow and relevant scores appear as columns **against each specific trace**. [Issue #22](https://github.com/caldeirav/sub15-breaker/issues/22) owns completeness; #3 owns durable partial evidence, #8 evaluation and #24 end-to-end migration. This contract distinguishes pilot remediation from still-missing distributed execution.

## Harness acceptance versus quality

The owner-approved [v3 harness policy](banking-harness-acceptance-v3.md) gates correct evidence/evaluation, not agent task wins. New derived run `53b476bed53446ebac25753aaa9a8b80` and decision trace `tr-c9b382d52a5f77846abf74a247ccb7c2` hold CODE scalar `harness/*` pass/gate assessments and separate, non-gating `agent_quality/*` counts. They link the unchanged 17-case / 68-review / 85-trace source population and record zero new model/tool/judge invocations. The source run remains historically FAILED; its rent utility=false and judge violated result are not overwritten. Human review follows [the current checklist](validation/block-02-harness-review.md).

## Metric-v2 additions

The owner-approved [banking-metrics-v2](banking-metric-contract-v2.md) adds four native judges named `banking_v2_<criterion>_gemini`: `utility`, `upstream_attack_absent`, `forbidden_transfer_absent`, `declared_goal_absent`. Each review links a versioned projection `outputs.evidence_id` to `outputs.source_evidence_id` in the original case. Judge inputs contain relevant observed state plus a closed rule and parameters, never measured verdicts or Python checkers.

The final [v2.2 provenance schema](banking-provenance-v2.2.md) binds each actual registered native judge to three complete JSON-encoded envelope choices. All verdicts remain available with fixed exact IDs. Keep `native_feedback_value` separate from decoded `structured_feedback`; never repair typos or call deterministic decoding an independent model citation. Opaque keyed row-equality IDs and recognized-service extraction facts preserve pre-redaction effects without exporting secrets; these are explicit trusted observation features, not final verdicts. Native usage costs are estimates from the lock-bound bundled LiteLLM price map, not billing receipts.

On each case, retain `oracle/*` unchanged and add `metrics/contract_version`, `effects/observed_attacker_transfer_count`, `effects/forbidden_recipient_transfer`, `effects/declared_goal_reached` when known, `effects/declared_goal_known`, `effects/normalized_utility_parity` and `effects/normalized_attack_parity`. On target cases, each versioned judge has `/verdict`, `/valid_evidence_citations`, `/agrees`, `/has_error` and available model/usage columns; review traces retain generic `judge/*` equivalents. Unknown disclosure omits the boolean and marks known=false, never fabricating false. New main runs export `trace-scores.json` and `audit/trace-score-coverage.json` for all 17 case and 68 review traces. Historical names/assessments remain intact.

## Ownership and provenance

- A case has one CHAIN/AGENT root associated with its trial run; model calls are CHAT_MODEL spans, tool attempts TOOL spans, outcome checks CHAIN spans. Failed calls still produce spans and status/error evidence. Each attempted action has a stable evidence/action ID.
- Native MLflow Gemini judges run in separate LLM review traces, explicitly linked by `target_trace_id`, criterion/reference/evidence IDs and judge model/config. They retain their own scalar review assessments AND criterion-namespaced assessments on the target case. This holds even when invoked inside `mlflow.genai.evaluate` or pytest tracing.
- Native structured Feedback remains authoritative model-review provenance. Code-owned scalar projections do not turn Gemini output into ground truth. Record actual provider model/settings, sanitized request/response, duration, available token usage/cost and errors. Unsupported usage remains absent, not zero. Internal model wire spans suppressed by the native judge are not invented; the actual native judge invocation boundary is the LLM span.
- Acting-model calls use explicit sanitized invocation spans rather than exporting an additional uncontrolled raw autolog payload. Model retries are disabled in the pilot; future retry attempts must be separately identifiable. Local classifier and A verifier calls must implement the same visibility in the eventual gateway path.
- Lifecycle/reset/stop/gateway receipts and cross-process propagation are future completion gates. Propagated tracing IDs do not authenticate principal/Actor/policy. Durable receipts/attempt ledgers reconcile telemetry; missing exports cannot be counted as successful evidence.

## Scalar assessment columns

These are named MLflow **Feedback assessments**, not only JSON outputs/run metrics. Values are scalar and table-selectable. Full structured evidence stays in trace inputs/outputs and artifacts.

| Owning trace | Names / meaning |
| --- | --- |
| Case | `oracle/utility`, `oracle/selected_attack_goal_reached`, `oracle/state_changed`, `oracle/execution_error`, `execution/completed`, `execution/status`; known tool/model attempt counts. |
| Target case, per criterion | Current: `banking_v2_<criterion>_gemini/verdict`, plus `/valid_evidence_citations`, `/agrees`, `/has_error`. Historical v1 names `banking_utility_gemini` and `banking_selected_attack_absent_gemini` remain on old traces only. Native Feedback is retained alongside scalar decoding. |
| Specific review trace | `judge/verdict`, `judge/valid_evidence_citations`, `judge/agrees`, `judge/has_error`, `judge/model` and available `judge/input_tokens`, `judge/output_tokens`, `judge/cost_usd`, with target/criterion metadata. Same reviewed result, not a second model call; unavailable usage is omitted. |
| Tool span on owning case | `tool/execution_error`, `tool/state_changed`, scoped using `span_id`. Do not copy final task utility to each action. |
| Model span on owning case | Actual model/config/usage/error attributes; attempt counts on the case. No classifier-risk column unless a classifier was actually invoked. |
| Future gateway/action path | Applicable policy label, risk/logits, allow/deny/error, state freshness, receipt/execution/unknown and timings. These cannot be backfilled as if the current direct-dispatch pilot had enforced them. |
| Implemented v2 outcome contract | Versioned selected declared-goal and forbidden-recipient facts under #20; retain upstream parity. Broader policy/refusal acceptance under #19 remains future. No universal `safe=true` derived from these checks. |

On a root with nested tool/model spans, action-specific scores belong to the selected span, while the row's final-outcome columns describe the case. A separate review row has review scores, not a fabricated copy of task correctness. Missing/nonapplicable differs from `false`: control cases have zero model attempts by design; unavailable risk or usage is absent with explicit applicability/status.

## Viewing and exporting

In local MLflow, select experiment **breaker-banking-feasibility** → **Traces**. Use the trace table's column selector and **Assessments** to enable the scalar names above; open a row's Assessments pane for provenance/rationale and select a TOOL span for span-scoped scores. Judge rows use the `judge/*` columns; target rows use `oracle/*`, `execution/*` and criterion-specific judge columns. The names are verified through persisted trace readback/export; UI preference storage and visual layout vary by MLflow version and are not inferred from API success.

The audit export must include `trace_id`, trial/case, kind, target/criterion, model/tool counts and a flattened map of scalar assessments. It must reconcile trace associations, root evidence, model attempts and tool actions, **four reviews per case for v2** (68 across 17 main-pilot cases), exact expected row coverage, zero scorer errors and required assessment values. Historical v1 used two reviews per case. Aggregate means cannot establish row coverage: MLflow may omit failed scorer rows from means, as the independent review demonstrated.

The remediated pilot retains a model-attempt ledger with unique span IDs and sanitized request/response digests, checks actual model inputs/outputs/configuration against it, and requires a unique action↔TOOL-span mapping with matching score **values**, not merely score names/counts. Tool attempts are recorded before JSON decoding. Requested and returned model/response IDs are distinct; unsupported returned fields/usage remain explicitly unavailable. Canonical model identity is stored as `mlflow.llm.model`.

Historical corrected-run export: `audit/trace-score-columns-v1.json`, `trace-score-columns-v1-final.csv` and `trace-score-columns-v1-final.table.json` on parent `f994d093234a40579e9919a5a67eb5c8` contain 51 trace rows and 34 flattened columns. All 34 judge traces have their own derived scalar review/model/token/cost assessments. The raw historical spans are unchanged. `audit/attacker_recipient_transfer`, `/attacker_recipient_transfer_count` and `/attacker_subject_service_match` are separately derived observed facts, not a retroactive approved policy oracle; source metadata identifies the derivation.

Historical scalar backfills use `CODE` source `banking-derived-audit-v1`, metadata identifying the source artifact/target and `derived=true`, and an audit artifact. Do not overwrite native Feedback/oracles or change historical run status. A readback audit of old traces verifies preserved evidence, not a fresh live test of changed implementation.

## Acceptance tests

Offline tests must cover model/tool/judge exceptions, malformed/empty output, missing scores/spans, duplicate/missing cases/reviews, disagreement, incomplete execution, password-only mutation, sanitization canaries and evaluation trace cloning. Explicit persisted local MLflow tests can use judge/client stubs with no provider calls; mark those as plumbing validation, not native-model quality evidence. Paid Gemini checks require a declared protocol and must assert every expected row/error status before means. Distributed gateway/Actor completeness remains open until actual services pass #22's contract.
