# Services-ready demo retest and golden accuracy report — #65

Owner requested explicit readiness before demo/full-harness testing, investigation
of the284.743ms first classifier core, golden correctness for BOTH reviewers and
regenerated results without latency-attainment counts.

## Finding and serving change

Original weight loading was2648.374ms, outside the284.743ms decision timer. Its
forward/host-result stage was283.400ms; first-use device/runtime work is consistent
with this observation, not proven as a unique cause. The old arm-local lifetime
also reloaded the encoder during alternating accuracy arms.

New explicit `resident-primed-v1` serving keeps the SAME frozen encoder loaded
throughout a run. Load, fixed priming and all measured/native forwards run on one
owned worker, with MLflow context copied. Queue/handoff remains in whole-review
timing; actual tokenization/enqueue/forward/host-result/calibration remains core.
No verdict cache, batching, context truncation, precision/weights/calibration/
threshold change or shared-Qwen reload. Idle GPU clocks/queues can still cause
slow measured requests; do not promise uniformly short latency.

## Startup gate, separate from testing

Both modern demo and full-comparison paths use the shared startup gate. Verify
loaded/idle Qwen/context8192, tracking health, authenticated store/capacity, and
native-stage MCP catalog/real gVisor Actor identity path with no trial/tool action.
Run one reserved real acting-model tool-proposal protocol probe and one real LLM
reviewer protocol probe per process; generated proposals are NEVER executed.
Then run exactly2 classifier priming passes over frozen UNLABELLED review inputs,
requiring finite/bound inference, NOT a preferred allow/block decision. Preserve
all priming samples/cold load/first-use cost as startup, never accuracy or timed
test samples. No priming-until-fast loop. Resident services stay ready across arms.

Measurements retain EVERY after-startup sample, including the first and errors;
do not drop a slow sample. Services readiness is availability/protocol readiness,
not an accuracy certificate. Bad readiness stops before scored/native cases.
Per-case authenticated read-only readiness retains the existing bounded retry;
model reviews and banking actions still have zero retries.

## Golden accuracy and report changes

Freeze5 unique canonical golden actions: bill read/payment, unrelated extra
transfer after the legitimate prefix, profile read/update. Expected policy labels
and contexts come from pinned AgentDojo references/policy/effect evidence BEFORE
model calls. Labels/task/checker IDs never become guard features. Both real guards
get identical inputs; count errors/unknowns in coverage/unconditional accuracy.
Report per-action golden vs predicted, false allows/false blocks/errors, overall
unique-input denominator and per-use-case D01/D02/D03 (shared prefix overlaps,
never pool duplicates). D04/D05 are fail-closed mechanics, not accuracy samples.
Native workflow utility/receipt/effect correctness remains original golden CODE.
This is curated demo/development evidence, NOT a fresh held-out estimate.

New JSON/HTML/Markdown and read-only projections omit below15ms counters. Latency
distributions remain descriptive and startup is shown separately. Preserve earlier
reports/results as historical artifacts, linked not rewritten into warm results.
Classifier performance #13, rent quality #55 and held-out #56 remain separate;
no new full held-out inference or frontend work is authorized by this retest.

## Fresh fixed execution and caps

Preallocate nd11 qualification and nd12 rehearsal together, same source/image/
models/prompt/golden/serving profile. Qualification caps88 local/17 external;
rehearsal66 local/1 external. These INCLUDE6 real startup model calls total:
2 diagnostics +2 native qualification +2 native rehearsal. Classifier priming is
separately declared (2 passes per input/process); new demo has10 priming forwards
per process,30 total, excluded from scored/timed test denominators.

Append an exact18-review allowance scoped to nd11/nd12 from CURRENT spending;
keep old policies, ledgers/holds and global2048 local/512 external/$100 caps.
Explicitly release prior reservation while retaining used28-trial history; reserve
new42-trial/192-action/1200-event headroom without pruning/resetting DB/key/PVC.
Presentation headroom is not model authorization. Qualification5-pair/30-encoder/
15-LLM-timing +14 native/reviews gates ONE unchanged-config14-case rehearsal.
Any failed model/case is retained and stops, never resampled until green.

Acceptance: startup proofs, both reviewer golden correctness, original native
checkers/utility/receipts/effects, complete logical/physical counters, supported
allocated reviews, late state, cleanup/restoration and source-bound reports. #62
remains closed unless an actual regression appears; #45/#48 owner sign-off remains
separate. #60 visualization stays planning-only. Publish final reports/API with all
old failures/negative reviews intact.
