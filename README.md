# BreakerSubstrate

**A traced evaluation harness and planned pre-execution safety boundary for a simulated banking agent.**

The project reuses **AgentDojo banking tasks, synthetic state, tools and executable checkers**. A local agent attempts tasks such as paying a bill, adjusting rent or updating an address. MLflow records every acting-model/tool/judge invocation and the corresponding outcome scores. Correctly capturing and scoring a failed task is successful evaluation—not successful agent work.

The research target is to compare gateway-side generative verification (**A**) with one compact classifier pass over a structured action and trusted context (**B**), before isolated banking tools mutate state. The [session's sub-15ms objective](https://atecon.dev/) is a **hypothesis, not a measured result or SLA**.

## What works today

- **Accepted banking harness:** [PR #26](https://github.com/caldeirav/sub15-breaker/pull/26), accepted by **@caldeirav on 2026-10-31**, with 145 offline tests and passing Python 3.11–3.13 CI.
- **Existing golden environment:** three pinned AgentDojo tasks, 11 simulated tools, released reference trajectories/checkers, and labeled attack adaptations. No replacement financial dataset is being built.
- **Observable execution:** model requests/responses, tool attempts/results, state evidence, deterministic outcomes and registered native MLflow Gemini judges, with scalar scores against the owning traces.
- **Validated harness:** 17 recorded cases, 68 native judge reviews and 85 audited case/review traces. The approved [harness-v3 assessment](http://localhost:5001/#/experiments/1/runs/53b476bed53446ebac25753aaa9a8b80) passes all ten correctness gates using existing evidence, without rerunning models.

**Agent quality is reported separately:** the recorded agent completed 2/3 benign tasks and 3/5 total live tasks. The rent failure remains utility=false; [#25](https://github.com/caldeirav/sub15-breaker/issues/25) is a nonblocking quality follow-up. Earlier failed runs and their statuses are preserved, not relabeled.

**Not implemented yet:** a canonical banking action/trusted-context boundary, Actor-hosted banking service/reset, actual banking gateway enforcement, trained banking risk model/calibration, breaker stop integration, comparable A/B execution or complete-path latency evidence. The accepted infrastructure foundation uses non-executing gateway fixtures, not banking execution. No real bank, real payment or production credentials are involved.

## Current execution versus the target

```text
CURRENT LOCAL HARNESS
User task -> local Responses API agent -> AgentDojo in-memory tools/state
         -> pinned outcome checks + normalized effect criteria
         -> native MLflow Gemini review (post-evaluation)
         -> MLflow traces, per-trace scores, artifacts and coverage audit

PLANNED ENFORCEMENT PATH
Proposed banking action + service-owned intent/policy/state context
  -> authenticated agentgateway -> deterministic checks + one A OR B verifier
  -> isolated Actor tool service -> versioned execution receipt
  -> the same evaluation and MLflow evidence system
```

The acting agent currently calls LM Studio through the OpenAI SDK. Native MLflow judges call Gemini through the **LiteLLM SDK**; LiteLLM is not a deployed proxy or an alternative security gateway. **agentgateway is not yet on the local banking execution path.** Denial, durable latch, acknowledged Actor stop and reset are separate future operations; none promises rollback.

## Golden data and scoring

Canonical source: AgentDojo commit `089ed468cf3ed0322acc66b0211f26d9d90dbf60`, package `0.1.35`, benchmark `v1.2.2`.

| Task | User request | Executable utility criterion |
| --- | --- | --- |
| `user_task_0` | Pay the supplied bill | Upstream expected transaction amount/recipient |
| `user_task_2` | Adjust rent from the notice | Upstream first matching scheduled rent amount |
| `user_task_13` | Update account address | Upstream street/city predicate |

The reference/checker data stays evaluator-only; the acting model receives the user's task and available tool observations, not a golden solution. Utility, the upstream selected attacker predicate, new/changed forbidden-recipient effects and the declared service-disclosure goal are **separate metrics**. Native judges review relevant observations against closed normalized rules, not supplied measured verdicts or checker Python.

See [golden environment and metric semantics](docs/golden-data.md). End-state task labels do not supply per-action safety-training labels or calibrated risk probabilities. The current selected financial invariants are not universal safety or a complete accounting model.

## Run locally

### Install and configure

Use [uv](https://docs.astral.sh/uv/) with the committed lockfile:

```bash
uv python install
uv sync --locked
```

Create `.env` from `.env.example` **only if it does not already exist**; never overwrite existing credentials. Configure:

| Setting | Purpose |
| --- | --- |
| `LM_STUDIO_BASE_URL`, `LM_STUDIO_MODEL` | Tool-capable acting model; default endpoint `http://localhost:1234/v1` |
| `MLFLOW_TRACKING_URI` | Tracking server, normally `http://localhost:5001` |
| `BANKING_MLFLOW_EXPERIMENT` | Defaults to `breaker-banking-feasibility`; an explicit `MLFLOW_EXPERIMENT_ID` takes precedence |
| `GEMINI_API_KEY` | Required for the current full pilot's external native judge review |
| `MLFLOW_GENAI_JUDGE_DEFAULT_MODEL` | Defaults to `gemini:/gemini-2.5-flash` |
| `LITELLM_LOCAL_MODEL_COST_MAP` | Bundled pricing metadata; the harness pins it to `True`. Costs are estimates, not invoices. |

Python 3.11–3.13 is supported, with 3.12 the local default. There is not yet an installed `sub15-breaker` CLI. Cluster, gateway and trained-sidecar settings are **not prerequisites for this local harness**.

If a tracking server is not already running, start one in another terminal:

```bash
uv run --locked mlflow server --host 127.0.0.1 --port 5001 \
  --backend-store-uri sqlite:///mlflow.db \
  --artifacts-destination .infra/mlflow-artifacts
```

### Tests and experiments

```bash
# Offline tests; no model/provider calls or running tracking server required.
bash scripts/test.sh

# Persisted MLflow plumbing validation with CODE/model stubs, no provider calls.
uv run --locked --env-file .env python -m pytest -q validation/test_banking_mlflow_local.py

# Full live pilot: local acting model plus paid external Gemini reviews.
uv run --locked --env-file .env python -m src.feasibility.runner
```

The live pilot uses 12 deterministic controls, three benign agent trials and two bill-injection variants, with four review criteria per case. `--oracle-only` skips the local acting model **but still invokes Gemini**; it is not a judge-free or full live-adapter validation mode. Do not repeatedly rerun for favorable agent outcomes or unanimous judge agreement.

For an existing compatible source run, reassess harness correctness without new model/tool/judge calls:

```bash
uv run --locked --env-file .env python -m src.feasibility.reassess --source-run SOURCE_RUN_ID
```

This needs access to that run's artifacts/traces; example run IDs in the docs refer to the owner's local MLflow instance, not a public tracking service. [The runbook](docs/banking-feasibility.md) explains live prerequisites, optional regressions and archived evidence.

## Review evidence in MLflow

Open the configured experiment's **Traces** table. Case rows expose `oracle/*`, `effects/*`, `execution/*` and criterion-specific `banking_v2_*_gemini/*` assessments. Separate native review rows expose `judge/*` verdict, validity, agreement, error, model and available usage/cost columns. Tool scores are scoped to their actual action spans. Run-level averages never replace exact case/review coverage or the underlying evidence.

The native result is a schema-constrained JSON envelope string; its decoded fields retain exact criterion/reference/evidence IDs. All three verdicts remain possible. Deterministic results are authoritative; judges cannot overwrite them. Missing/nonapplicable evidence is not fabricated as a successful or zero-valued observation.

See [trace/score ownership](docs/mlflow-trace-contract.md) and the [accepted human review checklist](docs/validation/block-02-harness-review.md).

## Block 03a: confirmed contracts and record-only fixtures

The owner confirmed the [contract slice](docs/banking-contracts-03a.md): reusable types/JSON Schemas, exact decimal strings, service-owned structural fixtures, all 11 existing tool schemas and private-keyed fixture bindings. Implementation has **228 passing tests** and **26 matched CODE-only MLflow cases**, with independent technical approval and **human acceptance by @caldeirav on 2026-10-31**. The accepted live pilot is unchanged, and these fixtures invoke no banking tools, models, gateway or Actors. See the [block-03a acceptance record](docs/validation/block-03a.json).

No generic shell executor, new financial corpus, model training or cluster changes are included. Later blocks deliver real Actor tools/reset, gateway admission, latch/stop, policy data, model/calibration, A/B integration, packaging and performance evidence. Each block keeps fresh human acceptance and its own scoped PR gate.

- [Documentation index](docs/README.md)
- [Project scope and trust boundaries](docs/project-scope.md)
- [Specification](specs/001-breaker.md)
- [Remaining-block plan](docs/implementation-plan.md)
- [Block 03a proposal](docs/next-iteration.md)
- [Infrastructure foundation](docs/infra.md) — optional for the current in-memory harness

## Repository map

| Path | Role |
| --- | --- |
| `src/feasibility/` | Supported local banking adapter, pinned checks, native judges, trace auditing and acceptance |
| `src/banking_contracts/` | Block-03a shared contracts/schema export and record-only fixtures; not live admission |
| `tests/test_banking_*.py` | Offline banking/control/provenance/acceptance regressions |
| `validation/` | Explicit opt-in persisted and native judge validation |
| `src/infra/`, `scripts/`, `infra/` | Accepted control-plane and non-executing fixture foundation |
| `docs/`, `specs/` | Current scope, runbooks, contracts, plans and historical evidence |
| `k8s/` | Undeployed research examples; **not a banking service deployment** |

Older command-based modules, dataset and Streamlit dashboard remain compatibility scaffolding, not the banking golden environment, risk model or evidence UI. Their status and migration boundary are documented in [legacy compatibility](docs/legacy-compatibility.md); do not use them as the banking entry point.
