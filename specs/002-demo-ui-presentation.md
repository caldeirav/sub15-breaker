# Demo UI presentation specification: use-case context, decision-model I/O and component flow (`demo-ui-presentation-v1`)

Status: **implemented** on `feat/demo-ui-presentation` (issues
[#70](https://github.com/caldeirav/sub15-breaker/issues/70),
[#71](https://github.com/caldeirav/sub15-breaker/issues/71) and
[#72](https://github.com/caldeirav/sub15-breaker/issues/72)); offline suite and
the offline browser fixture checks are updated with it. Live-browser and
owner validation remain recorded per issue before closure, per #17.

## Objective

Make the live five-card UI self-explanatory for a presentation audience:

1. Show the **use-case being tested** (task prompt, relevant synthetic state,
   producer type) and its **expected outcome** before/while a card runs.
2. Show the **input and output of each decision model** — the encoder
   classifier and the LLM reviewer — at the native pre-execution boundary.
3. Show the **final outcome of the run** clearly, including a paired
   per-action comparison between the two routes.
4. Make the **roles of agentgateway and Agent Substrate** (and the other
   components) visible in the execution flow while a run streams.

Presentation clarity only. No new inference pathway, protocol, guard decision,
admission semantics, budget/allocation behavior, external-review semantics or
saved-replay change is introduced by this specification.

## Audience and display philosophy

Primary audience is a **live presentation**: large, unambiguous outcome
statements first; dense evidence behind expanders. Progressive disclosure —
context and verdicts at a glance, decision-model I/O and component detail on
demand. The UI remains operator-inspectable, but inspection density never
displaces the presentation reading order.

## Non-goals and invariants

- **No behavior change** to guards, admission, calibration, event whitelisting
  for live SSE events, budgets, Gemini review, idempotency or cleanup. The UI
  stays read-only except the existing explicit Run POST.
- **Privacy model unchanged in kind**: live events stay terse and whitelisted
  (`EVENT_FIELDS`, ≤4096 bytes); all richer data added by this specification
  appears only in **post-run `public.json` summaries** and **read-only
  pre-run context endpoints**, built from Mask/`public_view`-sanitized
  synthetic values. No credentials, ticket capabilities, unmasked complete
  bank state or raw exception text ever reach the browser. Rendered values are
  text-only and escaped; no HTML injection surface.
- **No model-accuracy claims added**: D02 remains scripted released
  attack-proposal evidence; D04/D05 remain declared fault controls with no
  real reviewer model I/O (panels must show not-applicable, never zero).
  Golden labels appear only where a frozen action digest is actually covered.
- **Timing honesty preserved**: no additive nested timers, no fabricated
  gateway internals, startup/priming and Gemini remain outside guard timing.
- **Stack constraints**: no Node/npm build, no CDN or inline scripts; CSP
  unchanged (`script-src 'self'`). Diagrams are inline SVG/CSS only.
- **Restart discipline**: runtime-source changes (guard-record retention,
  bridge evidence retention, card-context derivation) require the documented
  graceful server restart; `check_execution_source` semantics are unchanged.
  Browser-only files remain excluded from the execution-source hash.
- **Evidence binding**: card context is served from pinned plan/adapter data
  with recorded digests, not free-floating copies that can drift. Curated
  per-card expectation text lives in hashed runtime source
  (`src/demo_ui/protocol.py`), not only in browser JS.

## Design

### 1. Use-case context and expected outcome (issue #70)

**Backend-served card context.** New auth-gated read-only endpoint
(`GET /api/live/cards`, session cookie like `/api/live/status`; never accepts
card parameters that could select execution) returns, per card D01–D05:

- identity: card id, title, kind, producer (`acting_model`,
  `scripted_released_attack`, fault-control mode), task id;
- the **public task prompt** (the pinned AgentDojo `user_request` the agent
  actually receives);
- a **masked, bounded view of relevant initial synthetic state** (e.g. account
  balance and the scheduled bill for D01; the supplied address file for D03),
  rendered through the existing Mask/`public_view` machinery;
- the **tool inventory** exposed to the agent (names + one-line descriptions
  from the pinned catalog);
- for D02, the **released attack proposal** (the scripted extra transfer from
  the pinned fixtures), clearly labelled untrusted synthetic attack data;
- for D04/D05, the **declared fault** (reviewer error / late-allow
  cancellation) and the explicit statement that no real reviewer model I/O
  occurs;
- **structured expected outcome**: expected effective decision per route,
  target effect/receipt/state invariants, the original utility criterion and
  its upstream checker reference — derived from the same declarations that
  `make_pair`/`make_card` evaluate, not new parallel truth.

Derivation is read-only (no inference, no trial creation), happens once at
server start or first request, is cached, and its digest is recorded in the
session evidence directory. The static JS card strings remain only as a
fallback if the endpoint fails; the panel states when it is showing fallback.

**Scenario panel.** The selected card view renders: what the user asks for
(actual prompt), what state the agent starts from (masked view), what the
agent may do (tools), what is expected to happen (structured outcome), and
what would violate it (the negative expectation, e.g. zero additional
transfer in D02).

### 2. Decision-model input/output (issue #70)

**Runtime retention (small, bounded, no behavior change).** The guard result
record additionally retains: for the LLM reviewer, the **raw verdict text**
(the `{"allow": true|false}` JSON actually parsed, ≤256 chars, plus
`prompt_version`); for the classifier, the **unsafe logit**, frozen
`temperature` and `threshold` alongside the existing calibrated risk. The
bridge additionally retains the **masked review input** (the projected
`ReviewInput` fields: goal, policy id/text, tool, arguments, untrusted
observations, state view, token count, `input_digest`) in each action's
evidence record, bounded (unsupported/oversized projections already fail
closed with issues listed). Everything already Mask-sanitized by the existing
`ReviewBuilder`/`Mask` path; persisted in MLflow traces as today.

**Summary enrichment.** `summarize()` exposes these per action in
`public.json` lane summaries, alongside existing fields.

**UI.** Each lane's per-action expander becomes a **"Decision review"**
section: the exact input the reviewer received, rendered field-by-field
(observations/state behind sub-expanders when long), with the input digest and
token count; then the reviewer's output — classifier: decision, calibrated
risk vs frozen threshold (with logit and temperature), core vs whole-review
latency; LLM: decision, raw verdict JSON, whole-review latency, prompt
version. An affordance marks when both routes reviewed the **identical input
digest**. D02 shows real reviewer I/O over the scripted prefix with the
producer labelled; D04/D05 show the declared fault and "not applicable"
instead of model I/O. Live SSE events remain unchanged.

### 3. Paired final outcome summary (issue #72)

- **Verdict banner per lane**: status chip (pass / fail / not completed),
  expected vs observed effective decision, executed/blocked/error action
  counts, utility, effects/receipts verified, telemetry/cleanup status.
- **Paired per-action comparison table** joined on `input_digest` where a
  frozen golden label exists: tool, short digest, classifier decision + core
  ms + risk, LLM decision + whole-review ms, golden label, per-lane outcome
  (executed/blocked) and receipt presence. Trajectory divergence (unmatched
  digests across routes) is stated explicitly — unmatched inputs never become
  a speedup or accuracy claim.
- **Card-level outcome statement**: one plain-language sentence per run,
  deterministically templated from structured fields (expected, observed,
  golden pass, effects), never free-form generation.

### 4. Component flow visualization (issue #71)

- **Per-route flow, retained:** each lane panel keeps its own component-flow
  ribbon — the components its execution traversed (agent loop, agentgateway
  model/MCP routes, Qwen server, bridge, state store, Substrate gVisor Actor,
  native Envoy claim gate, reviewer, MLflow) with traversal counts,
  accumulated live from observed events and retained after the run. A single
  shared chart is deliberately not used: it mixes routes and cannot retain
  per-route information.
- **Event tagging:** every timeline entry is tagged with the component that
  produced it from the explicit event-stage → component mapping; unknown
  stages are never assigned a component.
- **Role legend:** a collapsible legend on the routes heading explains each
  component's role with the transport vs execution/enforcement taxonomy —
  agentgateway is managed connectivity, **not** the sandbox or the claim gate;
  Agent Substrate owns ephemeral gVisor Actors and the native Envoy egress
  hook that gates the Actor's ticket claim. Links to `docs/architecture.md`.
- Highlights and tags reflect host-observed events and persisted gateway-span
  readback only; nothing fabricates remote internals or wall clocks.

### 5. Judge evaluations in the final evidence panel (issue #72 refinement)

- The post-run external review is surfaced per criterion and per route: what
  is evaluated (the versioned criterion rule), the golden data (pinned
  parameters and the CODE-oracle expected verdict), the judge's verdict,
  agreement with the golden expectation and a bounded judge rationale. D02
  (scripted) and D04/D05 (fault) producers show the scoped harness review
  only. Raw judge start/finish events are summarized by this table instead of
  the observation timeline. Deterministic payload re-derivation only; no
  extra inference, and the judge never overwrites CODE results.

## Acceptance (applies to each delivery block)

- Offline fixture tests (`tests/test_live_demo_ui.py`,
  `tests/test_live_observations.py`, `tests/test_live_protocol.py`) cover the
  new endpoint shape/masking/bounds, summary field presence, fault
  not-applicable paths, cross-lane digest join and secret-absence scans of
  `public.json` payloads.
- Browser fixture validation (`validation/run_ui_browser`, offline fixture;
  `--execute-live` remains opt-in) verifies rendering, expanders, live
  highlighting on synthetic events, responsive/keyboard/aria behavior and
  zero JavaScript errors for all five cards.
- `docs/demo.md` ("Interpret the display") and the affected guides are
  updated to match delivered behavior; limitations language is preserved.
- No new inference in any default path; MLflow trace/score ownership
  unaffected; process gates of #17 (independent review, manual validation
  records) apply per block as usual.
