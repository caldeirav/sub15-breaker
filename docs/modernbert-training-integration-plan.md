# ModernBERT + hybrid data: sequential validation plan

Execution tracking is in #43 / draft PR #44. This is the technical sequence, not
a promise that an untrained checkpoint or successful fixture is a safety guard.

## 1. Pin and validate the encoder

- Base: `answerdotai/ModernBERT-base`, revision
  `8949b909ec900327062f0ebf497f51aef5e6f0c8`, Apache2.0. Download only the
  safetensors/config/tokenizer/card files; no unrelated model search or upgrades.
- Start with float32, explicit SDPA, `reference_compile=False`, Apple MPS,
  dynamic padding and2048 maximum tokens, without truncation or silent CPU fallback.
- Verify CPU/MPS numerical agreement, finite backward/optimizer behavior and
  measured memory before training. A newly initialized classification head is
  a compatibility fixture only; never export it as a calibrated banking guard.
- Re-tokenize the immutable review-applied dataset. Preserve all input digests,
  human quarantine and non-length coverage flags. Tokenizer changes do not change
  the owner's Unknown judgment or automatically resolve missing credential facts.

## 2. Freeze data sources and partitions before fitting

The complete original task/attack cross-product is connected. One can prune it
into smaller selections, but this plan instead preserves the entire original
reviewed corpus as a **no-fit benchmark transfer/development holdout**, rather
than randomly splitting reused actions/documents or quietly shrinking evaluation.
It has already been inspected during development; do not call it an untouched
statistical test.

If this conservative strategy requires more fitting data, use training-only hybrid
augmentation, authorized separately from live evaluation (which stays three tasks):

- Code owns an explicit legitimate request and positive/counterfactual actions
  using the existing five mutation tools. Canonical schemas and controlled
  execution validate the examples; execution success is not the permission oracle.
- Gemini contributes **only untrusted document prose**. It receives no original
  test labels, checkers or expected trajectories and assigns no training labels.
  Its text cannot change the code-rendered authoritative user request.
- Keep critical constraints visible in the guard input. Negatives use plausible
  values from the same distribution, not giveaways such as an `UNAUTHORIZED` payee.
  Unconditional synthetic credential requests do not imitate or relabel the
  quarantined conditional suspicious-activity case.
- Partition recipes, entities, state instantiations and document/injection themes
  before generation. Positive/negative pairs stay in one scenario group. Use
  separate training, calibration and threshold-validation populations. Keep all
  original benchmark cases out of gradient fitting, calibration and selection.
- Inspect duplicates, class/tool coverage, input bounds, source/spec consistency
  and rejection counts before freezing the dataset. Reject malformed generated
  prose/invalid examples without refunding requests or repairing responses.

The initial fixed recipe has40 scenarios per mutation tool for training and10
per tool for each calibration/validation partition, each with a positive and a
counterfactual:400/100/100 potential rows. Twelve predeclared Gemini operations
generate document banks in disjoint families; no requests are repeated for a
preferred outcome. Counts after validation, not requested counts, are authoritative.

## 3. Budgeted generation and provenance

Retain the cumulative2048 local /512 Gemini /$50 accounted-cost limits and all
historical reservations. A separate hash-bound **pre-training generation plan**
is required: reviewed-source decision, source dataset, protocol and split-recipe
hashes plus named cases. It does not fabricate a trained-artifact hash to bypass
the later native A/B matrix gate.

Reserve at the actual HTTP request hook, disable SDK retries/redirects/tool loops
and provider fallback, and retain raw response, finish/usage/error/rejection facts
in MLflow. Monetary settlement includes non-visible completion/thought tokens;
missing usage keeps its conservative hold. Generation is a distinct role, not
misrepresented as a task/harness judge. Historical unknowns remain unknown.

## 4. Train, calibrate and test once under the frozen protocol

- Implement a reproducible binary trainer/exporter with fixed seed/config and
  source/row/family hashes. Fit only training data; select the predeclared model
  using validation, never original benchmark outcomes. No hidden hyperparameter
  campaign or early stopping against the final holdout.
- Fit temperature on separate calibration logits. Select the threshold on
  validation to minimize false allows subject to at most10% observed false
  blocks; preserve infeasible/inconclusive outcomes and confidence intervals.
- Freeze weights/tokenizer/input-policy/class mapping/calibration/threshold
  artifacts before scoring the original corpus. Report counts, NLL/Brier/ECE,
  false allows/blocks, coverage and group/tool slices, including unsupported and
  quarantined cases. Do not count those cases as correct model blocks.
- Reload the exported artifact with the actual fail-closed loader and check
  logit/calibration parity. A bad result is reported, not repaired by test tuning.

## 5. Integrate only the frozen artifact and matched LLM guard

- Keep the single compiled agent runner; choose guard backend at the shared
  native Substrate gate. Use the same goal/action/context materialization and
  canonical consumed ticket for both arms, with one authoritative review.
- Align Actor/store client timeout, reviewer, Envoy timeout, ticket lifetime,
  outer MCP and episode deadlines; preserve explicit uncertain effects.
- Prove allow/block/error/late-verdict controls with actual dispatch counts,
  receipts/state and persisted trace ownership before live model comparisons.
- Freeze a new cumulative A/B request matrix including actor, LLM guard, replay,
  warmup, retries if ever separately authorized, and external Gemini evaluation.
- Counterbalance identical-input native replay and run fresh-state full episodes
  separately. Measure real admission-only time, not tool-inclusive roundtrip or
  a forward-only/service-only timer. No sub-15ms or matched-quality claim without
  actual evidence. External Gemini reviews post-run evidence, not training labels.

Do not add production IAM, HA, a second agent loop or the deferred soak as a
prerequisite. Do not modify global LM Studio defaults or unload/reload shared
acting-model weights merely to make an experiment pass.

### Diagnostic comparison entry point

`python -m src.benchmark.compare` reuses `wiring.run_case`; it does not implement
another agent. `--artifact`, `--dataset` and `--budget` point to the frozen local
export, re-tokenized original dataset and **existing cumulative ledger**.
Without `--freeze` or `--execute` it only prints the proposed bound matrix.
`--freeze` binds the matrix without model calls. The matrix records diagnostic
quality status, calibration, reviewer model, deadline profile and named cases.

Before execution, rebuild the digest-bound banking image and deploy it with
`python -m src.banking_service.deploy --image <digest-reference>
--deadline-profile learned-guard-v1`. Existing service defaults remain legacy;
the comparison refuses a legacy deployment or mismatched store/Actor settings.
The opt-in chain is20s reviewer,25s native hook,30s Actor/store client,55s Actor
server,60s outer Actor client,65s MCP client,70s MCP route and90s ticket lifetime.
The55s Actor deadline covers the claim **plus** bounded tool execution and commit.

`--execute canary` first runs native allow/block/error and unsupported-input
controls, then one scripted fresh-state proposal per real guard. Canary admission
must have matching input digests and honest dispatch/state evidence; a genuine
model block is not rewritten to an allow. `--execute episodes --canary-result
<result.json>` requires persisted mechanical canary evidence before running the
six task/guard episodes in counterbalanced order. Started cases have irreversible
markers even when they consume zero generative requests; failures are not retried.
Blocked/error episodes remain results, not automatic rerun triggers.

The named paired-replay slots are budget scope only: this CLI does **not** yet
execute reconstructed-prefix native replay or external post-run Gemini review.
It reports these as incomplete. Native admission-service and model-forward time
are not full-path admission latency; Actor roundtrip includes tool work. No
admission-only latency claim follows from this command.
