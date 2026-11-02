# End-to-end demo review backend plan

Owner authorized implementation of steps1–4 and **planning only** for visualization.
This is a stacked follow-up to PR #57, not authorization to merge that PR or record
owner acceptance. #58 owns capacity/readiness; #59 owns the review package/API;
#60 contains the separate planned visualization PR. #45/#48 remain owner gates.

## Ordered delivery and acceptance

1. Preserve the same SQLite PVC/key and hash all historical tables before/after
   deployment. Keep legacy trial limit100; explicitly configure bounded256 for
   this owned research deployment. Add authenticated read-only capacity and an
   exclusive durable campaign reservation covering42 trials (qualification14,
   rehearsal14, presentation headroom14),192 action slots and1200 evidence slots.
   Presentation headroom is **not** permission for presentation inference.
   Competing consumption fails closed; readiness precedes Actor/model allocation.
   Test exhaustion, reservation concurrency/restart, rollback and failed setup.
2. Append a scope-bound eight-operation external allowance amendment, retaining
   v4 policy/ledger/history and global2048 local/512 external/$100 caps. Freeze
   nd7 qualification80 local/17 external and nd8 rehearsal64 local/1 external
   together, on identical new image/configuration/source. No model/prompt/weights/
   threshold/precision changes or shared-Qwen reload; no retry until green.
   Fresh transport probes, paired correctness/timing, then14 native cases and17
   qualification reviews; complete source-bound report gates fresh14-case rehearsal
   and its one wiring review. Any failure is retained and stops the batch.
3. Generate JSON/HTML/Markdown review package: acceptance matrix, expected/observed
   decisions, original utility, receipts/effects/diffs, paired accuracy and error
   denominators, classifier-core/reviewer/native timings, trace links, counters,
   costs, hashes, late state and cleanup. Preserve nd4/nd6 failures/negative review.
4. Publish a versioned, read-only saved-replay backend for cases, runs, ordered
   events and results. Immutable allowlisted bundles, bounded pagination, sanitized
   fields and trace links, explicit missing telemetry and ordinal vs wall-clock
   timing. Local loopback service; no model/tool/judge calls, raw credentials,
   arbitrary file access, generic commands or live dispatch. Test HTTP/security
   and saved evidence end to end. Document the contract for a future UI.

Freeze all runtime/contract source before inference. Reporting-only derived fixes
must be identified if needed afterward. Run offline tests on Python3.11–3.13 and
CI. Close #58/#59 only on actual scoped evidence; leave #45/#48 for owner review.
Classifier quality #55, acceleration #13 and full held-out comparison #56 stay
separate.15ms targets classifier decision computation, not native claim latency.

## Visualization PR scope — planning only (#60)

Five-card selector and guard comparison, saved-run picker, ordered enforcement
timeline, expected/observed outcomes, state diff/receipt panel, accuracy/latency
summary, trace links and persistent limitations. Distinguish genuine agent vs
scripted/fault, saved replay vs live, blocked/error/unknown/cancelled vs success,
and observed dispatch coverage vs complete logical coverage. Use backend versioned
schemas, not raw MLflow/cluster credentials. No live buttons or frontend code in
this backend PR. Future UI acceptance includes accessibility, responsive layout,
fixtures for failures/missing data and E2E proof that replay issues zero inference.

## Frozen execution bindings

Source `b6386ae`;607 tests passed on Python3.11–3.13 before inference, with CI green.
Owned image:
`localhost:5002/breaker-banking@sha256:5c4386787c809563a6b2fd885f9c581562ac91f2359236fdf3674b9cee87a64b`.
Before/after history proofs verify the same PVC/key and all original metadata,
100 trial,189 action and577 unexported-event rows. Legacy default100 is unchanged;
the deployment explicitly selects256. An expired-token precheck stopped before
deployment mutation; its log is retained and scoped credentials were refreshed.

Fresh transport probes passed. The durable exclusive reservation is
`demo-review-nd7-nd8`:42 trials/192 actions/1200 evidence slots, with limits256/
1000/4000. Presentation headroom14 is reserved, **not authorized model spending**.
The additive allowance amendment is restricted to nd7/nd8, adding exactly8 reviews
without changing the v4 policy file, historical prefix or global caps.

- nd7 matrix: `198f0004905858cb5145adcb69ae91822040aa22ffe9b98d35faa4da559c4b14`.
- nd8 matrix: `8f3e44fadbd977d57ddd3bd14bd352c2cf968a71f2d17eeb2565e9ce1616505a`.

Both phases were frozen together before dispatch. Later results must retain every
failure/unknown and cannot reset IDs, replace the database or change the model.

## Execution disposition

nd7 paired4/4 both guards and14/14 native cases passed;17 valid reviews agreed on
16 task criteria and returned scoped harness support. nd8 **did not complete**:
the first control setup failed at Actor readiness with `invalid_runtime_json`,
before any model/tool dispatch. Capacity remained available; the trial was fenced,
Actor deleted and resources restored. #62 owns this distinct unresolved readiness
transport blocker. No retry, readiness bypass or extra inference was made.
The review package/API must preserve both the full qualification and this zero-case
rehearsal failure. #45/#48 remain open; visualization remains planning only.
