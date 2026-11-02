# Block 03a: step-by-step human validation

**Human acceptance: PASSED — @caldeirav, 2026-10-31.** After receiving this walkthrough, the owner reported that everything matched and explicitly authorized acceptance, commit and merge. This is owner-reported review, not an agent-inferred result; no raw manual transcript or per-case inspection list was supplied. Acceptance covers shared contracts and record-only fixtures only—not real banking execution or authentication. This is fresh block-03a acceptance, not reused block-02 approval. The steps below remain reproducible inspection instructions.

Acceptance is also recorded in [MLflow run 23d8ef48c8934bd380914cd8965f20e5](http://localhost:5001/#/experiments/2/runs/23d8ef48c8934bd380914cd8965f20e5), trace `tr-5a12526a63df8fdfa673a5a545a3404e`, with read-back-verified **HUMAN / @caldeirav** assessment `human/block03a_accepted=true`. The source fixture summary's recording-time pending status remains historical; subsequent acceptance is linked in `audit/human-acceptance.json`.

Use the existing [run a7cc4f2497d24a819edfd1d2e57b1e22](http://localhost:5001/#/experiments/2/runs/a7cc4f2497d24a819edfd1d2e57b1e22), experiment **breaker-banking-contracts-03a**. No rerun, provider key, model, bank action or cluster change is needed. Implementation scope: [banking-contracts-03a.md](../banking-contracts-03a.md); machine record: [block-03a.json](block-03a.json).

## 1. Verify the run before inspecting examples

Open the run's **Artifacts**:

- `protocol.json`: all 11 tools, 26 named controls, structural-fixture-only decisions, keyed commitments, controlled fixture clock and `financial_authorization=false`.
- `summary.json`: `passed=true`, `cases=26`, and zero `new_model_calls`, `banking_tool_calls`, `real_executions`. The result mix is **12 allow / 1 deny / 12 error / 1 unknown**.
- `audit/trace-score-readback.json`: 26 rows, all `passed=true`.
- `implementation/source-sha256.json`: seven implementation snapshots. The artifacts are the code under review, not a separately deployed service.

**Important:** a control that correctly rejects stale/tampered input has `passed=true` and `outcome=error`. Red child spans may be expected validation rejections; do not require every span to look successful. Compare the declared outcome, exact failing stage/code and record count.

## 2. Enable useful trace columns

Open this run's **Traces** view, or the experiment's Traces table filtered to this run. Use `summary.json` to map `case_id` to `trace_id` if needed. Enable these **Assessments** in the column selector:

`contract/passed`, `contract/proposal_parsed`, `contract/context_bound`, `contract/outcome`, `contract/error_code`, `contract/receipt_recorded`, `contract/executed`, `contract/replayed`, `contract/record_count`.

Each present score must have a unique root-level source **CODE / banking-contract-fixtures-v1**. Same-named HUMAN/wrong-owner or duplicate assessments must not substitute for automated validation. `contract/error_code` is absent when there was no thrown contract exception; a policy error verdict instead has a decision `reason_code`.

All spans are **CHAIN** phases. There should be no invented TOOL, AGENT, CHAT_MODEL or LLM invocation. These cases validate tool schemas without calling tools.

## 3. Inspect a positive money/binding flow

Select `valid_send_money`, trace **`tr-81aaa7971c32f48aeaa515ac548d4220`**. Expand its span tree and compare **Outputs**:

| Span | What to inspect | Expected |
| --- | --- | --- |
| `parse_proposal` (`0d04f387558196d7`) | `arguments.amount`, schema and expected versions | Amount is string `"12.30"`; proposal version `banking-action-v1`; context/generation/state expectations 1/1/7 |
| `resolve_validate_bind` (`98419614ace386f3`) | `proposal.arguments.amount`, `context`, `binding`, `tool_catalog_digest` | Amount is string `"12.3"`, same numeric value; principal/trial/Actor/policy came from owned fixture context; keyed action/context/bound commitments exist |
| `fixture_structural_decision` (`c7c385542954947e`) | Scope, verdict and binding | allow; `decision_scope=structural_fixture`, `fixture_only=true`, `financial_authorization=false` |
| `record_only_receipt` (`fe6ae9cfd927e1e8`) | Nested `receipt` | `status=recorded_only`, `executed=false`, fixture=true, state version **7 → 7** |

Compare each **same-named** action/context/bound digest across the bound action, decision and receipt: it should match. The three different digest fields are domain-separated and are **not** supposed to equal one another. Also compare action ID, decision ID and Actor/generation references across their appropriate objects.

The root should show allow / one record / executed=false / replayed=false / passed=true. This proves a structurally valid object was bound and recorded—not that money moved, the recipient exists or a financial policy approved it. Trailing-zero normalization is exact canonicalization, not rounding.

## 4. Verify rejection happens at the correct point

Inspect these rows; each should have `contract/passed=true`, `executed=false` and record_count=0:

| Case / trace | Where it must stop | Exact code |
| --- | --- | --- |
| `spoofed_authority` — `tr-11403492fed2ff027c836a38983e4935` | `parse_proposal` | `invalid_action_schema` |
| `stale_state` — `tr-0b9df24fe2565cfd365687db06e9ab8f` | `resolve_validate_bind` | `stale_state` |
| `stale_generation` — `tr-bd6af9f05d6a86ef12807b3e29490c0c` | `resolve_validate_bind` | `stale_actor_generation` |
| `tampered_action` — `tr-ac8926a72a263e22b447a6ddd8fbbd93` | `record_only_receipt`, after the original decision | `binding_mismatch` |
| `float_adapter_loss` — `tr-228907e05edccbeeb4b908f96afcaeec` | `explicit_float_adapter` | `upstream_float_value_loss` |

For stale state, compare root **Inputs → trusted_context.state_version=7** with parsed **expected_state_version=6**. For generation compare 1 with 0. This is an optimistic-version check, not evidence of a real Actor lifecycle.

For spoof/tamper injection details, open `implementation/fixtures.py`: the fixture adds `principal_id` to the proposal, or edits the subject after issuing the decision. **Raw rejected bodies and every mutated argument snapshot are not exported in this run.** The persisted trace shows the original safe projection and the exact rejection stage/code; the source snapshot supplies the injected mutation. Do not claim the trace independently shows data it did not record.

For float loss, the bound amount remains exact string **`9007199254740993`**. The adapter must reject it, not return the silently rounded `9007199254740992`. There must be no later decision or receipt in that case.

The `expired` case uses a deliberately advanced **controlled fixture clock**. Compare root `effective_now` to context `expires_at`, not the wall clock when you review these historical records. Other stored deadlines will naturally be in the past now.

## 5. Check every non-allow blocks recording

Open the `fixture_structural_decision` and `record_only_receipt` outputs:

| Case | Trace | Decision / reason | Receipt and ledger |
| --- | --- | --- | --- |
| `capability_denied` | `tr-3ba2139a6eb9347f80d722fbbc304215` | deny / `fixture_capability_denied` | not_executed, false, zero records |
| `policy_unknown` | `tr-d71e18a3be4afe44f81a14000944eef1` | unknown / `fixture_policy_needs_review` | not_executed, false, zero records |
| `policy_unavailable` | `tr-08cc8daf9e6101fb38235a2b981c242a` | error / `fixture_policy_unavailable` | not_executed, false, zero records |

Capability denial's context allows only `get_balance` while its proposal requests `update_user_info`. Parsing/binding can succeed while the capability verdict is deny; those are separate checks.

Distinguish **unknown decision** from **unknown execution**. In this fixture we know no execution was attempted, so an unknown decision correctly produces `not_executed/false`. A future uncertain execution receipt with `status=unknown` must use `executed=null` and unknown after-state—not falsely assert non-execution.

## 6. Compare identical replay with changed-payload reuse

### Identical replay

Select `idempotent_replay`, trace **`tr-3dbbc5a5fb8a914543aaeae627a3a36e`**:

- Compare `record_only_receipt` span `977ebbe5923c58e0` with `repeat_record_attempt` span `cfa7c861783b4e86`.
- Both must return receipt ID **`294b635d2c894beba7706f990cd31f02`**, with matching binding/action/decision references.
- First `replayed=false`; second `replayed=true`; root record_count stays **1**, executed=false, passed=true.

### Changed repeat

Select `changed_idempotent_payload`, trace **`tr-9a75d599320fc5f8f993da806bbfa055`**:

- The first `record_only_receipt` (`d38bfbe21e43114f`) exists.
- `repeat_record_attempt` (`089567097d1432c6`) rejects with **`action_id_conflict`**, with no second receipt.
- Root outcome=error, record_count=**1**, executed=false, passed=true. One record is correct because the first harmless attempt was already recorded. The source snapshot shows the changed city; a complete second-argument snapshot is not exported.

This is a bounded process-local replay ledger, not durable deduplication, cross-replica safety or exactly-once banking execution.

## 7. Inspect sensitive-action export and schema semantics

Select `valid_update_password`, trace **`tr-fdde78b8739b2a031b1eb9ef69899046`**:

- In parsed/bound outputs, password must be **`[WITHHELD]`**. Full `context.user_request` is also withheld.
- MAC commitments may be visible; `algorithm=hmac-sha256`, `profile_id=fixture-binding-v1` and public `key_ref` are expected. Neither `_key`/`binding_key` bytes nor plaintext generated password may appear.
- Do not flag `idempotency_key` or `key_ref` merely for containing “key”: they are identifiers, not secret key material.
- Decision stays fixture-only/non-financial; receipt is recorded_only/executed=false. No password was actually changed.

Open `schemas/banking-actions-v1.json`:

- `tool_arguments` and classifications cover all 11 tools. `action_with_tool_arguments` ties tool selectors to strict argument schemas; bare DTO shape alone is insufficient.
- Under `models.ExecutionReceipt.allOf`, unknown/error execution requires null executed/after-state, and a fixture cannot claim executed=true. Real-executed shapes need nonnull evidence/after-state.
- Read `x-required-runtime-checks` and `validation_requirements`: arbitrary state equality/order, time ordering, context authority and MAC/evidence validation are runtime obligations. Schema-only validation is not authentication.

Optional local checks—no providers or server needed:

```bash
uv run --locked python -m pytest -q tests/test_banking_contracts.py
uv run --locked python -m src.banking_contracts.schemas
```

These run 83 contract regressions and export the bundle to an ignored local directory; they do not rerun the live agent or Gemini.

## 8. Report acceptance or findings

Keep initial failed run `86aceab640b44f8e9bf4aae7fdf9747a` and intermediate `414f6f05f99c4b0384dac4cec3eac66a` as history. Current evidence must not be “cleaned up” by editing old outcomes/statuses. The accepted live banking adapter/golden definitions/native judges were not integrated or changed.

Report your name, date and inspected cases, with findings, or explicitly accept **block 03a shared contracts and record-only fixtures only**. A missing/incorrect stage, unexpected record, wrong score owner, secret leak, value loss or false execution claim is blocking. A correctly matched negative rejection is not.

You are **not** approving financial policy, caller authentication, real gateway/Actor execution, production key management, durable state, trained models, calibration or latency. Those remain later blocks with separate acceptance.
