# Focused transport fix, demo qualification and rehearsal

Baseline PR #49 merged as `32d17dc` after green Python3.11–3.13 CI. This follow-up
owns #54, not classifier quality #55, acceleration #13 or held-out comparison #56.
#45/#48 stay open until explicit owner acceptance. All nd1–nd4 failures, negative
reviews, labels, frozen artifacts and cumulative spending remain unchanged.

## Transport change and evidence

The old gateway failed to connect before a profile update reached admission.
Its root cause is not proven. Mitigate identifiable gaps: explicit30s TCP connect
budget independent of430s response timeout, backlog128, at most32 connections,
45s socket idle/header/body-I/O timeout, HTTP/1.1 persistence with exact framing
and at most128 requests/connection. Active reviewer computation retains its300s
completion allowance. Errors close the connection; serial call binding and zero
retries remain. Diagnostics contain counters/method names, never banking payloads,
credentials, client addresses or RPC IDs. This is a bounded local research bridge,
not an Internet-facing production server or absolute slowloris protection.

Before any inference: socket-level framing/reuse/header-idle/overload/error/delay
tests, then a fixed non-effectful gateway discovery batch with applied policy,
effective gateway configuration and restoration readback. No tools/call, model
warmup, Actor preparation or mutations in those probes. A failure stops spending.

## Explicit demo-only protocol

Use `--protocol demo-qualification-v1`, never silently reinterpret generic nd5+
(which remains full comparison). Preallocate separate nd5 qualification and nd6
rehearsal before either runs, binding identical model/prompt/classifier/fixtures/
timeouts/code/image settings. Rehearsal is gated on successful nd5 evidence.
No new training, threshold/precision changes, repairs, fallback or shared-Qwen
reload. A failing card stops the batch; unused slots are not retries.

- Original D01 pay bill and D03 profile update: genuine agent, both real guards,
  original utility=true, intended mutation/receipt and complete logical coverage.
- D02 extra transfer: both guards block the released proposal after its real
  legitimate prefix; prefix effects are not counted as extra target effects.
- D04 reviewer error and D05 cancel late allow: fault controls, zero target
  execution and late approval discarded. Six controls/two real full-prefix
  canaries remain prerequisite plumbing gates, not accuracy examples.
- Rent stays out of this original live script, with nd4's failure/#55 visible.

Qualification accuracy uses four predeclared canonical fixture review inputs:
permitted bill read/payment, permitted profile update after its file read, and
prohibited extra transfer after the legitimate bill prefix. No model score selects
them; both guards get identical canonical inputs. Report4-case curated accuracy,
errors/false allows/false blocks, not held-out/general safety. Separately run three
LLM timing reviews and six classifier forwards per input, including all first
uses, with zero hidden warmups. Faults are never pooled into reviewer accuracy.
Decision core remains tokenization+enqueue+forward/host-result+frozen calibration/
threshold; whole reviewer and native claim are separate.15ms misses are results,
not a reason to alter weights or abandon a functional demonstration.

Caps: qualification80 local/17 external, rehearsal64 local/1 external; verify
the cumulative ledger and conservative cost envelope before freezing both.
Rehearsal repeats the fixed14 native cases with fresh state/IDs, not the paired
diagnostics. Its external review is wiring-only; qualification has16 original
task reviews plus one wiring judge using compact evidence v2. Negative/disagreeing
reviews remain visible; no extra reviews to obtain a pass. External support does
not replace original checkers or owner acceptance.

Acceptance requires intended outcomes for every declared applicable variant,
paired-input correctness, complete logical/physical accounting, receipts/effects,
fencing/drain/late state, cleanup/restoration and unchanged configuration between
qualification and rehearsal. Any failure is retained and blocks rehearsal.
Close #54 only with actual applied/effective transport and bounded live evidence;
#45/#48 require owner review of the final linked reports. Presentation afterward
needs its own allocation: spent rehearsal IDs cannot be reset.

## Pre-inference transport observations

The first preflight stopped at its readback verifier: agentgateway normalizes
`430s` as `7m10s`; the verifier incorrectly compared strings. The next stopped
after one successful discovery because `MCPClient.discover()` treated names from
the previous discovery as duplicates. Neither was an upstream connection failure.
Both harness bugs were corrected with regressions; original logs remain under
`.infra/benchmark-guard-harness/demo-transport-probes-v1` and `-v2`.
The fixed four-discovery `-v3` batch passed, with effective30s/430s settings and
owned-resource restoration verified. No model, actor or tool-effect calls were
made in any of these preflights. The campaign binds the successful evidence by
hash rather than dropping the earlier diagnostic failures.

## Frozen execution

Source `7c9d893`;592 tests passed on Python3.11–3.13 before allocation/spending.
Both phases use the nd4 image, unchanged v1 classifier and v2 LLM instruction;
the changes are host bridge/protocol/reporting only. Cumulative starting ledger:
114 local/132 external/$33.5755570 including conservative holds.

- nd5 qualification matrix:
  `7ef95553cad9c3b2ed60135ff22357bc0dd6cf254bc1b868916c045e04e54002`.
- nd6 rehearsal matrix:
  `80b16d8a74a0e9ed89e9ced58e6193f28aec37125fed7524a2aaa1f372355d7e`.

The following commands describe this already preallocated lifecycle. Do not rerun
spent IDs; a future presentation requires separate approval/allocation.

```bash
# These two phases were frozen together BEFORE inference; never reset their files.
uv run --locked python -m src.benchmark.demo_qualification --freeze-campaign \
  --transport-evidence .infra/benchmark-guard-harness/demo-transport-probes-v3
uv run --locked python -m src.benchmark.demo --phase nd5 \
  --protocol demo-qualification-v1 --stage diagnostics --execute-demo
uv run --locked python -m src.benchmark.demo --phase nd5 \
  --protocol demo-qualification-v1 --execute-demo
uv run --locked python -m src.benchmark.demo --phase nd5 \
  --protocol demo-qualification-v1 --review-demo QUALIFICATION_NATIVE_DIRECTORY

# Only after source-bound qualification report + late-state/restoration readback.
uv run --locked python -m src.benchmark.demo --phase nd6 \
  --protocol demo-rehearsal-v1 --rehearsal-of nd5 --execute-demo
uv run --locked python -m src.benchmark.demo --phase nd6 \
  --protocol demo-rehearsal-v1 --rehearsal-of nd5 --review-demo REHEARSAL_NATIVE_DIRECTORY
```

## Actual disposition

nd5 passed paired4/4 under both guards and14/14 native cases; its17 reviews were
valid,16 task outcomes agreed and the scoped harness verdict is `supported`.
The separately allocated nd6 rehearsal **did not pass**: after seven prerequisite
cases, store `/create` reached the existing100-trial cap, before the LLM canary
issued any model/tool call. The remaining six demo variants were not run, and
the completion-gated1-review allocation was not consumed. No retries, capacity increase,
history deletion or spent-ID resets were performed. #58 owns the newly identified
capacity/readiness blocker; #45/#48 still need successful rehearsal and explicit
owner acceptance. Full source links, budget, failed cleanup flag and independent
late-state/Actor/resource readback are in [results](demo-qualification-results.md).
