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
