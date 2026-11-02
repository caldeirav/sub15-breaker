# Demo review API v1

Implementation: `src/benchmark/review_backend.py`; backend delivery #59.
Visualization #60 is **planned only**. This server is a read-only adapter over
immutable saved evidence, not a model runner, banking service or general file API.

## Build and serve

An operator supplies an allowlist JSON array of objects with `id`, `directory`
(native run bundle) and `report` (qualified or incomplete report JSON). Source
report/record hashes are checked against the immutable ledger; `review.json`
contains sanitized normalized data, and private `manifest.json` binds its sources.
The generated `summary.md`/`summary.html` form the consolidated review package,
not a visualization application. Do not overwrite an existing bundle.

```bash
uv run --locked python -m src.benchmark.review_backend \
  --sources APPROVED_SOURCES_JSON --output NEW_REVIEW_BUNDLE_DIRECTORY
uv run --locked python -m src.benchmark.review_backend \
  --serve NEW_REVIEW_BUNDLE_DIRECTORY --port 8088 \
  --token-file PRIVATE_READ_TOKEN_FILE
```

The service binds **127.0.0.1 only**, with at most16 request connections and bounded
socket reads. The read token is a new limited-purpose token, not a provider,
platform or store credential; its file must be private (0600). No credentials or
raw bank state/prompts/model output are exported. Only numeric/boolean state
changes are shown directly; other values are replaced by redacted digests.
No permissive CORS, live dispatch or automatic provider/cluster request is added.
Future UI should use a same-origin server adapter, not infrastructure credentials.

## Endpoints

Every request requires `Authorization: Bearer READ_TOKEN` and a localhost Host.
Responses are JSON with `Cache-Control: no-store` and no model side effects.

| GET endpoint | Response |
| --- | --- |
| `/api/v1/readiness` | Bundle verified; mode=`saved_replay`; current store=`not_probed`; live dispatch=false |
| `/api/v1/accounting` | Durable-ledger snapshot totals/cost including holds and prefix hash; not an invoice or new allocation |
| `/api/v1/cases` | Original D01–D05 definitions, expected decision and producer kind |
| `/api/v1/runs` | Run summaries: saved phase, completeness/readiness, verdict and limitations |
| `/api/v1/runs/{id}` | Run metadata and normalized results |
| `/api/v1/runs/{id}/results` | Cases, expected/observed decisions, original utility, action/receipt summaries, sanitized state diffs, coverage, counters, telemetry status, accuracy/performance and trace/run links |
| `/api/v1/runs/{id}/events?after=0&limit=100` | Ordered logical replay events, at most200/page, monotonic `sequence`, nullable `next_after` |

Write methods return405; unauthorized host/token401; unknown IDs/paths404; bad
pagination400. No endpoint accepts a filesystem path, shell command, model prompt,
ticket capability or execution request. Starting/cancelling a live run is out of
scope and requires a separately approved dispatch/auth/allocation design.

## Contract and interpretation

Top-level schema is **`demo-review-v1`**. Schema changes need a new version or a
backward-compatible optional field. `mode=saved_replay`, `live_dispatch_supported=false`
and `inference_on_read=false` are explicit. A future client must reject unknown
schema versions rather than guess the meaning of a missing field.

- A run has `id`, `phase`, `complete`, `all_ready`, `owner_acceptance`, `cases`,
  `curated_accuracy`, `performance`, `external_harness_verdict` and `limitations`.
- Each declared native case is present, even if `not_run` or `setup_failed`.
  Missing decisions/counters/timers are null or explicitly unobserved, not zero.
  Scripted/fault controls are distinct from genuine acting-agent workflows.
- Case `ready` cannot inherit an original green flag when logical tool attempts
  lack dispatch coverage, telemetry is incomplete or cleanup failed. The original
  recorded flag is retained separately. Utility=false on a deny/error control
  is not a failed banking workflow or a model-accuracy sample.
- Events have `sequence`, `case_id`, `stage`, `timestamp=null` and
  `time_basis=logical_order_not_wall_clock`. They reconstruct causal stages from
  saved records; they are **not fabricated timestamps or a measured live stream**.
  Guard, admission, Actor result, late-result/cancellation and terminal stages
  retain available evidence. Open MLflow run/trace links for authoritative spans.
- Timers use explicit ns fields: `classifier_core_ns`, `review_ns`, `claim_ns`.
  They have different boundaries.15ms targets the classifier core, not claims;
  null means unrecorded. Aggregate paired/native values remain separate.
- Capacity snapshots are labelled recorded-at-run-start, not current live health.
  The banking service separately exposes authenticated read-only `/capacity`;
  it is not proxied to a browser by this replay API.
- `manifest.json` and all original source files remain local/operator-private.
  Server startup verifies payload/source hashes and never silently serves a
  tampered bundle. Source artifacts must be retained for provenance checks.

Opening, paging, replaying, exporting or reading this package issues **zero model,
tool or judge calls**. The package preserves historical nd4 failures/negative
review and nd6 capacity failure alongside fresh evidence. It does not close owner
acceptance #45/#48 or defer/hide quality #55, performance #13 or held-out work #56.

## Planned visualization PR (#60)

Map cases→five cards, runs→saved-run picker, events→ordered enforcement timeline,
results→expected/observed/utility/coverage/receipt/state-diff panels. Show paired
accuracy denominators and separate latency boundaries, plus MLflow links and
persistent limitations. Fixture-test success, block, error, cancellation, partial
coverage, unstarted cases and missing telemetry; verify accessibility and zero
inference on load/navigation. No frontend implementation or live-run buttons are
part of the backend PR.
