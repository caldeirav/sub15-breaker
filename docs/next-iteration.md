# Remaining blocks and recommended next iteration

Block 02's **local banking evaluation harness** was accepted by @caldeirav and merged in [PR #26](https://github.com/caldeirav/sub15-breaker/pull/26) on 2026-10-31. This does not accept a deployed gateway/Actor path, risk model, calibration, agent quality target or latency claim. Preserve the trace/score contract and reuse [AgentDojo's golden environment](golden-data.md). Do not build a generic shell executor or another financial corpus.

## Recommended next PR: block 03a, canonical banking action and trusted context

Focus on **#21 + #9**, with the interface portions of #19/#22/#23. Define the contract before hosting tools or training a model; otherwise admission, mutation and model input will bind different facts.

**Status: implemented record-only and accepted by @caldeirav on 2026-10-31.** The owner selected contracts+fixtures without live integration, exact decimal strings, service-owned structural policy fixtures, all 11 tool schemas and private-keyed HMAC commitments. See [the implementation/evidence](banking-contracts-03a.md). No HTTP service, actual authentication, financial approval, Actor or model integration is delivered. Later blocks require their own acceptance.

### Clarification record (completed before coding)

- Deliver schemas/context-resolver/record-only fixtures alone, or also opt-in integration with the accepted live pilot? A real HTTP service, gateway policy or Actor deployment is not implied.
- Choose exact finite money representation, precision and currency/unit assumptions at the new boundary, with an explicit compatibility adapter for existing upstream float amounts. Do not silently round or infer currency from an IBAN.
- Define the trusted context/policy fixture source and which facts may authorize an action. User intent is distinct from untrusted invoice text; hidden benchmark expected answers must not become guard inputs.
- Confirm tool coverage and initial policy depth: structural/capability limits versus financial authorization rules. A digest/binding fixture is not an authenticated admission service or durable idempotency store.

The owner chose the narrow recommended options. Financial authorization, real key management/authentication, durable state and live integration remain outside this block; do not add guessed rules or alter accepted evaluation behavior. Additional scope requires fresh clarification.

### Deliverables

1. Versioned typed action/context, decision, execution-receipt and error schemas. Cover tool name/arguments, action/idempotency ID, principal/trial/Actor generation, trusted intent/policy/input version, expected state version, deadline and canonical action/context digests.
2. A small trusted-context resolver fixture: principal/intent/policy/state ownership is service-controlled. Distinguish authenticated user intent from untrusted invoice/tool text and derived observations. Never send evaluator solutions, checker answers or attacker goals to the acting model or verifier, or accept an agent's self-asserted safety proposition.
3. Deterministic schema/capability/size/amount constraints and explicit allow/deny/error/unknown semantics. Specify finite money representation and adapter boundaries without silently changing upstream benchmark float semantics. Both read and write tools are in scope.
4. Admission-to-receipt binding and idempotency/state-version semantics, including stale generation, changed payload, uncertain write outcomes and reset invalidation. Design these now; durable transactional implementation belongs to 03b/04.
5. MLflow context propagation/score ownership fixtures. Demonstrate a harmless accepted action, a rejected spoof/stale action and their exact source/context/digest/receipt links with CODE annotations. Use stub decisions; do not claim a learned guard or real Actor boundary.

### Acceptance

- Offline tests reject duplicate/ambiguous JSON, unknown fields/tools, malformed/nonfinite/overflow values, forged intent/policy/principal, stale state/generation and altered action/context binding. Missing data is not silently treated as safe or truncated.
- Fixtures exercise legitimate actions and benign near-misses, not only deny-everything behavior. This is contract-test data, not a new financial benchmark corpus or calibrated action-label set.
- Independent review plus owner inspection of the schemas, authority map and linked MLflow fixtures; regression coverage and updated runbook; one scoped PR before runtime implementation.
- No paid model calls, real payment credentials, new safety training, arbitrary agent access or cluster changes are required for this slice.

**Exit condition:** one canonical contract can be consumed by gateway admission, the Actor tool service, A/B verifiers and the evaluator without caller-controlled authority or hidden golden-answer leakage. Do not proceed just because the types serialize successfully.

## Remaining dependency sequence

| Block | Outcome | Issues |
| --- | --- | --- |
| **03a — next** | Canonical action/trusted-context/policy/trace and transaction interfaces. | #21, #9; interfaces #19/#22/#23 |
| **03b** | Actual gVisor Actor-hosted synthetic tool service, isolated state, authenticated reset/cleanup, atomic versions, idempotency and uncertain-write reconciliation. | #1, #23; #3/#10/#22 |
| **04** | Authenticated fail-closed gateway, exact action/Actor/state binding, no bypass/replay; one authoritative decision. Use deterministic fixture verifiers first. | #4, #6; #21/#9/#23 |
| **05** | Durable generation-scoped latch, acknowledged stop and authorized recovery; stop is not rollback. | #7 |
| **06** | Freeze a small eligible upstream task/policy slice and adversarial cases; separate reviewed action labels and train/calibration/test groups. | #15, #16, #19; reuse resolved #20 |
| **07a / 07b** | Train/release a genuine banking action-context risk artifact; independently calibrate and freeze its operating point. | #2, #5; #9/#21 |
| **08** | Supported banking agent through the real boundary; same-action replay and full-agent A/B with complete MLflow evidence and optional native Gemini judging. | #24, #6, #8, #3/#22 |
| **09** | Role-specific hardened images/packages, CLI/doctor/dry-run and a reproducible clean-checkout demonstration. | #10, #12, #24 |
| **10** | Matched quality/availability benchmark of complete authorization latency, warm/cold/tails/errors and narrowly supported release claims. | #11; accepted #2/#5/#8 |
| **Optional** | Acceleration/export/quantization or additional domains, only after baseline parity and quality evidence. | #13 |

Schema/policy design and packaging tests can be prepared early; the table gives completion dependencies, not permission to skip each block's acceptance. **#3/#22 evidence and #17 tests/independent review/human acceptance/docs/PR gates apply throughout.** Preserve the distinction between harness correctness, agent utility, policy discrimination, calibrated risk, isolation, stop and performance.

## Separate quality follow-up

#25 remains open and **nonblocking for the harness**. If prioritized later, investigate schedule retrieval before premature rent clarification, with legitimate-ambiguity controls and no evaluator-answer leakage. Predeclare any model-quality comparison/repeats before paid calls; report all outcomes rather than retrying for a preferred win rate. It should not displace the action/context boundary as the recommended next architectural iteration.
