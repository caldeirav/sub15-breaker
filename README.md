# BreakerSubstrate

Research scaffold for evaluating shell-tool verification with LangGraph, agentgateway, a sequence-classifier sidecar, MLflow, and Gemini. See [the specification](specs/001-breaker.md) for the evaluation and safety contract.

**Status: not a deployable safety boundary yet.** This repository does not contain trained safety weights, a sandboxed executor, a reset service, or an Actor termination integration. The Kubernetes files require site-specific images and existing controllers; the gateway hook has not been validated against a running cluster. Do not connect it to a real or privileged executor. A 403 stops that request; it does **not** terminate an Actor or undo prior mutations. Configure network isolation so the executor cannot be reached except through an authenticated gateway, and independently verify that it works.

## Setup

1. Install [uv](https://docs.astral.sh/uv/getting-started/installation/) (0.8.22 or newer), then run `uv python install` and `uv sync --locked` from the repository root. uv manages Python (3.12 by default via `.python-version`), the local `.venv`, and all Python dependencies, including the default `dev` group. Python 3.11–3.13 is supported; no system Python or manual virtualenv activation is required.
2. Copy `.env.example` to `.env`. Start LM Studio with a tool-capable model and Responses API at `http://localhost:1234/v1`. Set `LM_STUDIO_MODEL` and `GEMINI_API_KEY`.
3. Start MLflow with `uv run --locked mlflow server --host 127.0.0.1 --port 5001 --backend-store-uri sqlite:///mlflow.db`. The example sets `MLFLOW_TRACKING_URI=http://localhost:5001`; absent the variable, the Python tools fall back to `sqlite:///mlflow.db`. Load `.env` or export variables when running the sidecar.
4. Run `scripts/check_env.sh`. It checks the uv lockfile and synchronized environment, tools, Podman connectivity, LM Studio, MLflow, and `.env`.

### Dependency workflow

`pyproject.toml` declares dependencies; `uv.lock` pins their resolved versions across supported Python versions and platforms. Commit both files and `.python-version`. Do not install project packages with pip, Poetry, Conda, or ad hoc `uv pip install` commands, or maintain a separate requirements file.

- Add/remove runtime packages: `uv add PACKAGE` / `uv remove PACKAGE`.
- Add/remove development tools: `uv add --dev PACKAGE` / `uv remove --dev PACKAGE`.
- Upgrade deliberately: `uv lock --upgrade-package PACKAGE` (or `uv lock --upgrade` for all), then `uv sync --locked` and run tests.
- After manually editing dependency declarations: `uv lock`, then `uv sync --locked`; review and commit the lockfile changes.
- Validate without changing the lockfile: `uv lock --check`; check the local environment with `uv sync --locked --check`.
- For deployment, install with `uv sync --locked --no-dev --no-editable`. Start pre-synchronized containers with `uv run --no-sync --no-dev ...` so startup does not resolve or download dependencies.

All local Python commands below use `uv run --locked` to refuse implicit lockfile updates. uv does **not** install system infrastructure: install Podman, Kind, kubectl, the `kubectl-ate` plugin, and curl separately, and provision LM Studio and the cluster controllers as described below. Model weights and API credentials are external assets, not Python dependencies.

## Classifier and calibration

Fine-tune a compatible Hugging Face binary sequence-classification model (e.g. MiniLM or DeBERTa) on representative safety labels, with label 1 meaning unsafe. The generic MS MARCO relevance checkpoint is **not** a safety classifier. Supply its saved directory as `RISK_MODEL_PATH`. Collect two logits and a binary label per example in a held-out calibration JSONL, fit the temperature using `uv run --locked python -m src.eval.calibrate heldout.jsonl`, and set `RISK_TEMPERATURE` to the resulting positive value. Do not reuse calibration or training examples as the evaluation set. Validate label semantics, calibration, long-input rejection, and distribution shift independently. The provided synthetic suite is for evaluation, not adequate training data.

Run `uv run --locked uvicorn src.gateway.decision_sidecar:app --port 8000`. `POST /score` returns risk, trip, and local inference latency; `POST /authorize` returns 403 at risk >= 0.70 and 503 on model failure. Both accept only `{"command":"..."}`. The classifier uses one forward pass and no generation; it rejects input exceeding the model context rather than authorizing a truncated command. Temperature scaling does not itself prove calibration. The 15 ms target is not guaranteed and must be measured on the intended hardware, including gateway/network overhead.

## Infrastructure (integration work required)

Build the uv-managed sidecar base with `podman build -f Dockerfile.sidecar -t breaker-sidecar:base .`. It installs locked runtime dependencies without dev tools, using uv 0.8.22 and Python 3.12. Derive your deployment image from this base and copy your trained model directory to `/model`; the base intentionally contains no model. The manifest expects uv and the synchronized project at `/app` and runs without dependency synchronization or downloads at startup. Publish/load the final image into your cluster and replace the sidecar image placeholder. This does not build or manage the separately supplied isolated-executor image.

`scripts/setup_infra.sh` requires uv and validates `uv.lock` before any cluster changes; it does not install local Python packages. Run `uv sync --locked` yourself for local tools. A missing or stale lockfile must be resolved and committed before provisioning.

`scripts/setup_infra.sh` creates a named Kind cluster on Podman if needed and applies the manifests only after checking for existing Substrate, Gateway API and agentgateway CRDs. Install their matching controllers separately in that cluster first. Substrate's `ActorTemplate` is an ATE API resource, not a Kubernetes CRD; the script uses `kubectl ate create actor-template` and requires a pre-existing ATE space and sandbox configuration. Replace image placeholders in `k8s/workerpool.yaml`, `k8s/actor-template.yaml`, and `k8s/decision-sidecar.yaml`; create the `risk-calibration` secret with key `temperature` and include the trained model at `/model` in the sidecar image. Provide an isolated executor Service named `isolated-executor` implementing `POST /execute` with the same command JSON, and a separately authenticated sandbox-reset service. There is no executor in this repository. The script does not install controllers or create the ATE space, and it does not change the current Kubernetes context.

`k8s/agentgateway-hook.yaml` demonstrates a fail-closed HTTP external-authorization policy, buffering the full request before forwarding. Validate its CRD schema, routing, policy acceptance, body integrity, bypass prevention, readiness, failure handling, and containment against your deployed agentgateway version before use. It applies to the `/execute` HTTP route only, not arbitrary MCP tool calls. It does not halt an Actor. Add an authenticated and independently tested Actor-stop mechanism if that is required.

## Benchmark and dashboard

Provision **two distinct** isolated gateway routes: mode A uses generative verification, mode B uses the sidecar. The included route is for B; a separately configured A route is still required. Set `AGENTGATEWAY_URL_A`, `AGENTGATEWAY_URL_B`, and `EVAL_RESET_URL`. The reset endpoint must restore a fresh isolated sandbox on each POST; the runner calls it before every trial and records failures. Both routes must enforce their intended policies and forbid direct access to the executor; this project cannot establish that isolation for you. Do not run the synthetic destructive or network cases outside a disposable sandbox with restricted egress.

Run `uv run --locked python -m src.eval.runner`, then `uv run --locked streamlit run src/dashboard/app.py`. The runner downloads `epinnock/intercode-nl2bash-curated` and merges `data/golden_eval_suite.jsonl`, sends each task through each mode, requests a Gemini 2.5 Flash judgment, and records results and measured decision latency to MLflow. Generative latency is measured, not forced to exceed 1,500 ms; mode B performs an additional score request before dispatch, and its actual gateway independently rechecks authorization. Provisioning, model training, and a real end-to-end benchmark are outside the scaffold. Gemini's judgment is not ground truth. ECE uses only independently labeled synthetic cases whose **exact reference command** was actually proposed, not unlabeled public tasks or invented labels. For meaningful calibration results, evaluate a sufficiently large held-out labeled command set separately; the tiny suite is illustrative.

## Tests

`uv run --locked python -m pytest -q`. Development dependencies are included by default. Unit tests use mocks and do not prove integration, containment, model quality, or latency.
