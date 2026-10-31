# Block 03a: shared contracts and record-only fixtures

Status: implemented on `feat/banking-action-contracts`, technically reviewed and **accepted by @caldeirav on 2026-10-31**, with commit/publication/merge authorized after final checks. See [the acceptance record](validation/block-03a.json). The accepted banking pilot is unchanged; these fixtures do not invoke banking tools, models, agentgateway, an Actor or a bank.

## Requirements confirmed before implementation

The owner explicitly selected: **contracts + fixtures only**, **exact decimal strings**, **service-owned structural policy fixtures**, **all 11 upstream tools**, and **private-keyed HMAC fixture commitments**. A separate read-only technical review was also authorized. None of these approvals is human acceptance of the finished feature or permission to add financial authorization rules.

`src/banking_contracts/` is independent of `src/feasibility/`. It supplies:

- Strict, versioned proposal, context/policy, binding, decision, receipt and error DTOs.
- Bounded unique-key JSON and canonical UTF-8 serialization.
- Reused pinned AgentDojo argument definitions, read/write classification and an explicit float adapter.
- Context lookup/freshness/binding validation, structural decisions and a bounded local replay ledger.
- JSON Schema exports plus CODE-only traced controls and score readback.

Family/bundle version: `banking-actions-v1`. The proposal's own `schema_version` is **`banking-action-v1`**, not the family name. Each DTO declares its specific version. Supported Python defaults are fixed to v1; unknown versions are rejected, not negotiated.

## Proposal and trusted context

```json
{
  "schema_version": "banking-action-v1",
  "action_id": "fixture-action-1",
  "idempotency_key": "fixture-idempotency-1",
  "expected_context_version": 1,
  "expected_actor_generation": 1,
  "expected_state_version": 7,
  "tool_name": "send_money",
  "arguments": {
    "recipient": "FIXTURE-RECIPIENT",
    "amount": "12.30",
    "subject": "Contract example only",
    "date": "2026-10-31"
  }
}
```

The body cannot select a principal, Actor ID, policy, intent, deadline, risk score or decision. A **trusted adapter** supplies the principal/interaction lookup key outside JSON. The fixture registry resolves its own snapshot with trial/Actor generation, state/context/intent/policy versions, capabilities and expiry. Optimistic expected versions must match. Dates are aware and canonicalized to UTC; the CLI labels its injected clock as controlled fixture time.

**No caller authentication is implemented.** A principal string supplied by a trusted adapter is an assumption, not a credential. The fixture consumer rejects nonfixture authority/action profiles. Generic DTOs can describe later admission/execution outcomes but are shapes, not proof of a trusted issuer or real effects. Hidden golden answers are never used as context/policy.

## Validation and binding

Use `parse_proposal` and `FixtureRegistry.bind`/`verify`, not bare DTO construction as authority. The exported `action_with_tool_arguments` schema combines each selector with its strict argument schema. Context freshness, policy applicability, MAC checks and some cross-field relations remain runtime checks.

- Duplicate JSON keys, malformed UTF-8/surrogates, nonfinite values, unknown fields/versions and oversized data are rejected. IDs and integer versions are bounded; booleans/strings are not silently coerced to versions.
- Canonical JSON sorts keys and emits UTF-8. It does not normalize Unicode/path text, reorder semantic arrays or erase meaningful optional/null distinctions.
- Effective upstream defaults are checked against profile limits: omitting `n` cannot bypass its default of 100. A requested-count limit is not an unexecuted backend output-limit guarantee.
- HMAC-SHA-256 domain-separates action, trusted context and combined binding, including the public tool-catalog digest and input version. Private per-registry keys are never exported; key/profile references are identifiers, not key material.
- Keyed commitments avoid public low-entropy password fingerprints. They are not signed admission grants, authenticated transport, production key management or a distributed replay protocol.

JSON Schema includes expressible outcome conditionals: fixture receipts cannot claim execution; real executed shapes need evidence and known state; unknown/error execution cannot be reported as false. **Standard JSON Schema cannot compare arbitrary property values.** `x-required-runtime-checks` and bundle `validation_requirements` explicitly retain Python/protocol checks for state ordering/equality, time ordering, identity/freshness and binding/evidence. Enforce schema formats where applicable; do not claim schema-only security validation.

## Exact money and explicit compatibility

Amounts are finite plain decimal strings, not JSON floats, exponent notation, NaN/Inf or coerced booleans. Canonicalization removes insignificant trailing zeros/negative zero without changing numeric value or using context-rounded Decimal normalization. Currency defaults to absent, units to `benchmark-native`; a declared profile can add precision/currency/bounds. No IBAN inference or FX exists.

`to_upstream_arguments` explicitly converts to the pinned float API and rejects nonfinite or decimal round-trip value loss instead of rounding. This is not a claim that binary floating point represents every decimal mathematically exactly. Optional nulls/omissions retain upstream meaning; no tool is called by adaptation.

## Decisions, records and privacy

Fixture verdicts are allow/deny/error/unknown. Only allow creates a **recorded_only** receipt; the others create non-execution and no ledger entry. Even allow means structural fixture success, **not financial authorization**. Produced receipts have `executed=false`, unchanged descriptor state version and `fixture_only=true`.

Before recording, the consumer revalidates owned context, expected versions, catalogue/keyed bindings, decision fields and expiry. A bounded lock-protected local ledger scopes action/idempotency IDs by principal/trial/Actor generation. Matching replay returns the original receipt with `replayed=true`; changed payload/key reuse conflicts. Deadline is rechecked after queueing. This is not durable deduplication, transactional bank-state admission, cross-replica safety or exactly-once execution; real reset and mutation services remain later work.

Export withholds original intent text and sensitive argument fields. Errors use safe codes, not echoed input. The generated password example is ephemeral, not plaintext trace/artifact data. Arbitrary secret detection is not claimed. Known model keys are scrubbed if present; fixture key bytes are never serialized.

## Commands and evidence

```bash
# Offline tests: no provider or tracking server.
bash scripts/test.sh

# Export schemas to an ignored directory, without providers or tracking.
uv run --locked python -m src.banking_contracts.schemas

# Persisted CODE fixtures: existing MLflow server only, no provider key required.
uv run --locked --env-file .env python -m src.banking_contracts.fixtures
```

Current result: **228 offline tests**, including **83 contract tests**, and Draft 2020-12 cross-validation. Final MLflow [a7cc4f2497d24a819edfd1d2e57b1e22](http://localhost:5001/#/experiments/2/runs/a7cc4f2497d24a819edfd1d2e57b1e22) in `breaker-banking-contracts-03a` matches **26/26 declared controls**: 12 allow, one deny, 12 error and one unknown. All have zero model calls, banking-tool calls and real executions. A correct rejection is a passed control, not a real attack prevented.

Artifacts: `protocol.json`, `schemas/banking-actions-v1.json`, implementation hashes, `summary.json`, `audit/trace-score-readback.json`. Each case has CHAIN phases and owning `contract/*` CODE scores. Readback requires the exact CODE issuer, unique assessments, matching values/errors and run/evidence ownership. There are no invented LLM/TOOL spans.

Initial run `86aceab640b44f8e9bf4aae7fdf9747a` stays FAILED: the driver sent the family version instead of the proposal version; explicit version/full-path regressions cover the fix. Intermediate `414f6f05f99c4b0384dac4cec3eac66a` is preserved; subsequent review tightened exported-schema semantics and audit provenance without erasing evidence. The final technical re-review approved the fixture-only implementation. @caldeirav subsequently reported that the human walkthrough matched and explicitly accepted this block; block-02 sign-off was not reused. Recording-time pending statuses remain historical, with subsequent acceptance attached separately.
