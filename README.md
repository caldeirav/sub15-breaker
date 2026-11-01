# BreakerSubstrate

**Pre-execution action verification for agentic runtimes, without generating verification tokens on the classifier path.**

BreakerSubstrate (`sub15-breaker`) is the research reference architecture for the AgentSubstrate Day NA 2026 session [“Instant Circuit Breakers: Sub-15ms Action Verification in Agent Substrate”](https://atecon.dev/). It investigates a practical question: **can a compact, calibrated classifier reject a dangerous tool action before execution, with less overhead than asking a generative model to review it?**

The reference use case is a **simulated banking agent**. A user asks it to pay a bill, adjust a scheduled payment or update an address. The model proposes typed tool calls; untrusted invoices or tool responses may try to redirect those calls. We reuse AgentDojo's synthetic tasks, tools, state and executable checkers rather than build a new financial benchmark or expose a general-purpose shell.

The comparison is between **A: gateway-side generative verification** and **B: one compact classifier inference over the same action and trusted context**. Both belong at the same enforcement boundary. The sub-15ms objective is a research hypothesis—not a measured result, safety guarantee or hardware-independent SLA.

> **Research software, not a production safety boundary.** Use synthetic data only; do not connect real bank APIs, money, payment credentials or a privileged executor. A denied request is not acknowledged Actor termination, and neither denial nor termination rolls back prior effects.

For delivery status, dependencies, implementation blocks and acceptance, use the [GitHub roadmap](https://github.com/caldeirav/sub15-breaker/issues/14) and [implementation issues](https://github.com/caldeirav/sub15-breaker/issues). This README describes the project, architecture and technical decisions, not a release ledger.

## Why this design?

1. **Verify before mutation.** Reviewing a trace after an unauthorized transfer is too late to prevent that transfer. Enforcement must inspect the proposed action before the tool consumes it.
2. **Separate proposal from authority.** The acting model, its explanations and tool-returned text are untrusted. Identity, policy, intent provenance and state versions must come from services outside the agent—not from its assertion that an action is safe.
3. **Separate reasoning from classification.** A generative reviewer produces tokens; a compact encoder can make a binary classification in one forward pass. Lower and more predictable overhead is a hypothesis to test at comparable quality, not an assumed advantage.
4. **Use calibrated estimates, not verbal confidence.** A score between zero and one is not automatically a meaningful probability. Independent labels, held-out calibration, error rates and coverage are necessary.
5. **Retain deterministic controls and isolation.** A model can miss an unsafe action. Authentication, schema validation, capabilities, state checks, resource limits and a sandbox remain necessary regardless of the score.
6. **Measure rather than manufacture the comparison.** Do not add artificial delays to A, assume millisecond performance for B, hide failures or count a denied-everything agent as a successful system.

## Agent design and control flow

**The original command agent uses LangGraph; the banking agent currently does not.** [`src/agent/graph.py`](src/agent/graph.py) compiles a `StateGraph` with `think` and `act` nodes. The banking adapter, [`LocalBankingPipeline`](src/feasibility/agent.py), implements a bounded Python loop through AgentDojo's `BasePipelineElement` interface. The [Actor-backed adapter](src/banking_service/agent.py) reuses that same loop and replaces tool dispatch, not orchestration. This is a deviation from the original LangGraph design, not a claim that every agent in the repository is graph-compiled.

### Original LangGraph design

The following source-derived diagram makes the legacy graph's routing explicit:

```mermaid
flowchart TD
    LS([START]) --> Think["think: request model response"]
    Think -->|tool calls and step budget remains| Act["act: parse, review and dispatch"]
    Think -->|no calls or step limit| LE([END])
    Act -->|denial or halt| LE
    Act -->|append tool results| Think
```

Its state contains `input_items`, pending `calls`, `events`, `answer`, `halted` and `steps`. `think` appends model output; `act` parses the proposed command, applies the selected legacy review path, dispatches allowed work and appends function results. The command-only verifier path is **not** a banking guard or the intended matched gateway A/B boundary; do not use it as the banking entry point.

### Runnable banking agent

This diagram describes the banking loop's **logical state machine**, not a compiled LangGraph:

Its state is the plain `items` history plus `trial.answer`, `trial.status`, model/action records, errors, an environment view and a monotonic deadline. In the Actor profile that environment is a mirror of committed service state, not authority supplied by the model.

```mermaid
flowchart TD
    S([User task and fresh trial]) --> Budget{"Turn, tool and time budget available?"}
    Budget -->|no| Stop["Stop with explicit terminal status"]
    Budget -->|yes| Model["Record attempt and call Responses API"]
    Model -->|provider or persistence error| Stop
    Model --> Response{"Completed response with structured tool calls?"}
    Response -->|no calls: return answer| Eval["Runner: evaluate state and preserve evidence"]
    Response -->|incomplete or empty response| Stop
    Response -->|tool calls| Dispatch["Validate arguments and dispatch each bounded call"]
    Dispatch -->|known result| Append["Append function_call_output with its call_id"]
    Append -->|after processing returned calls| Budget
    Dispatch -->|uncertain remote response| Status["Read receipt or status; do not repeat the write"]
    Status -->|committed result recovered| Append
    Status -->|unresolved or rejected| Stop
    Stop --> Eval
    Eval --> Cleanup["Runner: clean up Actor backend if used"]
    Cleanup --> Judge["Live evaluator: native Gemini review"]
    Judge --> E([Results and trace-local scores in MLflow])
```

Evaluation, Actor cleanup where applicable and judging are **runner-owned stages after the loop**, not actions authorized by the model or nodes of a compiled banking graph. The live evaluation entry points enable Gemini; provider-free contract/runtime controls do not invoke it. Native review is outside execution/admission.

- **Conversation:** `items` starts with the user task. Each turn sends the full history, all 11 tool definitions and a separate `instructions` field. Returned assistant/function-call items are retained; tool results return as `function_call_output` items tied to the original `call_id`.
- **Bounded behavior:** the loop allows at most eight model turns and sixteen tool attempts, with a cooperative 180-second task budget and individually bounded requests. No provider retry or text-to-tool repair is implicit. A final model answer is not proof that the task succeeded.
- **Execution backend:** the default pilot uses in-memory synthetic tools. The opt-in backend persists model attempts/results, prepares a versioned action ticket, executes the pinned function in a gVisor Actor and commits state/receipt/outbox changes through the trusted service. An uncertain write is reconciled by status, never blindly repeated.
- **Authority:** messages and graph state do not grant permission. Principal, policy, Actor identity/generation and authoritative state versions come from services outside the model. Gateway financial-policy A/B verification is a separate boundary in the architecture below, not an extra model call hidden inside this loop.
- **Persistence:** durable banking state, receipts and evidence do not imply a checkpointed conversation. The banking pipeline accepts a fresh request, rejects resumed message sessions and has no LangGraph checkpointer. A graph migration must retain action IDs, reconciliation, budgets and evidence; checkpoint/node retries must not duplicate model calls or writes.

A behavior-preserving LangGraph version would make the budget, model, response-routing, action preparation, remote execution/reconciliation and terminal-evidence steps explicit nodes while keeping authority and mutation in the existing services. Merely replacing the Python loop with `StateGraph` would **not** fix a serving-side tool-call parser error.

### Chat templates and the model/tool boundary

The agent sends structured API messages and tool schemas; **LM Studio applies the model's chat template and parses generated tool-call text**. These are different from LangGraph's routing responsibilities. For Qwen3 Instruct, the native format is a JSON function request wrapped in `<tool_call>...</tool_call>`; Qwen3-Coder's nested function/parameter XML is a different protocol. Use the exact model-family template/parser pair, not a generic “Qwen” replacement.

Pin the model/quantization, serving runtime, template hash, sampling settings, stop conditions and API message serialization for reproducible comparisons. Never fix an unparseable response by guessing and executing its intended tool call. See the [evidence-backed rent/parser analysis](docs/validation/rent-parser-analysis.md) for a concrete model/tool trace, template comparison, external references and proposed controlled improvements.

## Architecture and trust boundaries

The intended enforcement architecture is:

```text
Authenticated user request                 Service-owned policy / trial registry
             |                                          |
             v                                          v
    Local tool-capable agent ---- proposed typed action (untrusted)
             ^                                          |
             |                                          v
             |                              Authenticated agentgateway
             |                                resolve trusted context
             |                                deterministic validation
             |                                          |
             |                            +-------------+-------------+
             |                            |                           |
             |                     A: generative review       B: encoder inference
             |                            |                    + calibrated risk
             |                            +-------------+-------------+
             |                                          |
             |                              one authoritative decision
             |                                          |
             |                     exact action / state / generation binding
             |                                          |
             +------ bounded result / receipt --- isolated Substrate Actor
                                                       banking tools
                                                       per-trial state

All stages -> MLflow traces, action-owned scores and failure evidence
Observed state/actions -> deterministic evaluation -> native Gemini review
```

This diagram is a **design contract, not a deployment inventory**. The runnable local harness dispatches directly to in-memory AgentDojo tools; it is useful for evaluation and is not a substitute for an isolated gateway-to-Actor path. The shared contract fixtures record harmless receipts without executing tools. See [the GitHub roadmap](https://github.com/caldeirav/sub15-breaker/issues/14) for delivered versus remaining capabilities.

### What is trusted?

- **Untrusted:** model output, proposed tool arguments, agent-provided identity/score headers, invoice text, returned document contents and other attacker-controlled observations.
- **Service-controlled authority:** authenticated principal/trial ownership, Actor identity/generation, versioned intent and policy, current state version, admission decisions and independently produced receipts.
- **Evaluator-only:** golden reference trajectories, hidden checker answers and selected attacker objectives. These must not become acting-model or admission-verifier inputs.
- **Outside the protection claim:** a compromised host/control plane, cluster administrator or trusted policy/model artifact publisher. Isolation reduces consequences; it does not make these authorities trustworthy by itself.

| Threat | Banking example | Required control / residual limit |
| --- | --- | --- |
| Prompt injection | An invoice asks the agent to replace the recipient or disclose a subscription | Treat tool text as data; verify against separately sourced intent/policy. A well-formed tool call can still be unauthorized. |
| Unauthorized mutation or disclosure | Change a scheduled payment or account detail unrelated to the request | Context-aware policy, capabilities, bounded access and independently checked effects; utility alone is not safety. |
| Request mismatch or gateway bypass | Reuse an allow decision for another payload, state or Actor | Authenticated transport, exact binding, expiry, atomic state checks and tested bypass prevention. |
| Duplicate or uncertain writes | A payment succeeds but its response is lost | Idempotency registry, transactional state/receipt commit and status reconciliation; a timeout is not proof of non-execution. |
| Cross-trial leakage | A previous trial's modified state or credentials survive reset | Isolated state, generation-scoped lifecycle, verified reset fingerprints and cleanup. |
| Resource exhaustion | Excessive calls, huge arguments/results or stalled operations | Input/output/turn/time/concurrency/resource limits; a classifier is not a quota system. |
| Misleading evidence | Treat a 503 as a prevented attack or a judge opinion as truth | Distinct denial/execution/error/unknown outcomes, independent receipts and exact trace/readback coverage. |

### Action, context and transaction binding

An action carries a tool name, typed arguments, action/idempotency IDs and optimistic expected context/state/generation versions. It cannot select its own principal, policy, trusted intent or decision. Trusted services resolve those facts and bind the exact canonical action/context to admission and execution.

Amounts use **exact decimal strings in benchmark-native units**. There is no inferred currency or silent rounding. The explicit adapter to upstream float arguments rejects decimal round-trip value loss. Profile-owned bounds and precision are separate from financial authorization rules.

Private-keyed HMAC commitments in the record-only fixtures avoid publishing guessable fingerprints of password-bearing inputs. They are **not** production authentication, signed admission grants or a key-management system. JSON Schema validates shape and expressible outcome conditions; dynamic equality/order, freshness, authority and cryptographic binding require runtime checks. See [contract semantics](docs/banking-contracts-03a.md).

At a real mutation boundary, expected state must be checked atomically with the change. A matching retry must not repeat the effect; changed-payload ID reuse must fail. Unknown write outcomes require receipt/status reconciliation before retry. These are transactional guarantees to demonstrate, not guarantees provided by serializing a DTO or copying Python state.

The [Actor-backed local service design](docs/banking-actor-service.md) separates disposable tool computation from authoritative state: pinned functions run inside the Actor, while a dedicated single-writer service atomically commits synthetic state, receipts and an evidence outbox on its own persistent volume. This preserves receipt history across Actor replacement without reusing platform database credentials. Its local durability profile does not cover node/disk loss or HA; acceptance evidence belongs in the linked GitHub issues.

### Denial, latch, stop and reset are different

- **Deny:** do not forward this action.
- **Latch:** prevent later admissions for the affected trial/Actor generation, including concurrent clients.
- **Stop:** request termination of the correct Actor and observe acknowledgment independently.
- **Reset:** establish fresh synthetic state and a new generation under authorized lifecycle control.

A cooperative agent stopping its loop is not an externally enforced latch. A 403 is not termination. A reset does not undo a previously disclosed secret or an external payment.

## Technical decisions

| Component | Role and rationale |
| --- | --- |
| **AgentDojo banking** | Reuse pinned tasks, synthetic state, 11 tool definitions and executable checks; minimize custom benchmark work and preserve upstream parity. |
| **Agent Substrate + gVisor** | Intended lifecycle and isolation for ephemeral per-trial Actors. Actual runtime assignment and confinement must be observed, not inferred from YAML. |
| **agentgateway** | Enforcement outside the proposing agent. Both A and B must authorize the same consumed action through the same boundary, without a trusted agent-supplied risk score. |
| **Compact encoder + PyTorch/Transformers** | Binary policy classification without autoregressive verification tokens. Model architecture, input schema, labels, calibration and runtime must be version-bound. |
| **Local model through LM Studio / OpenAI SDK** | Tool-capable Responses API acting model; the model identifier is configurable, not bundled. The banking harness is separate from the legacy LangGraph command agent. |
| **MLflow** | Trace/evaluation system of record: invocation inputs/results, action-owned assessments, provenance, failures, artifacts and persisted readback—not only run-level averages. |
| **Native MLflow Gemini judges + LiteLLM SDK** | Post-execution evidence review. LiteLLM is MLflow's in-process Gemini adapter, not a deployed proxy or replacement for agentgateway. |
| **Podman + Kind + Cilium** | Local Kubernetes profile with an enforcing CNI and explicit positive/negative network tests. Merely creating NetworkPolicy objects is insufficient. |
| **uv** | Managed Python and a committed universal lockfile for development/tests and reproducible installation. Models, images, controllers and credentials need their own explicit provenance. |

The acting-model and Gemini SDK calls in the local harness are not routed through agentgateway. Local acting inference does **not** make the full experiment offline/private: enabling native Gemini review transmits projected evidence to an external provider. Use synthetic evidence and understand that data flow.

The legacy command-only sidecar, command dataset and Streamlit view are compatibility scaffolding, not a banking model or the authoritative banking evidence UI. See [legacy boundaries](docs/legacy-compatibility.md). No generic shell executor or alternative financial corpus is required.

## Risk model and calibration

The intended classifier consumes the **canonical action plus trusted intent/policy/state context**, not just recipient/amount or an agent-written safety proposition. The same action may be permitted under one trusted request and forbidden under another.

A compact MiniLM- or DeBERTa-family encoder is a possible starting architecture, not a released safety artifact. A generic relevance checkpoint is not a drop-in safety verifier. Class meanings must be independently verified: for two logits, let class 0 mean permitted and class 1 mean prohibited under the declared labeling policy.

With temperature $T > 0$, the estimated policy risk is:

$$
p_{\mathrm{risk}} = \operatorname{softmax}(z/T)_1
= \sigma\!\left(\frac{z_1-z_0}{T}\right).
$$

This uses the **logit difference**, not a sigmoid of one arbitrary class logit. Temperature scaling fits held-out negative log-likelihood; it does not create correct labels or directly minimize ECE. See [Guo et al., 2017](https://proceedings.mlr.press/v70/guo17a.html).

Use separate, group-disjoint **training, calibration, threshold-validation and final-test** populations. End-state task success and Gemini opinions do not independently label every intermediate action. Freeze a policy/model/schema-bound threshold $\tau$ after choosing an operating point on validation data; deny when $p_{\mathrm{risk}} \geq \tau$. The legacy command prototype's 0.70 is not a justified banking threshold.

Calibration should be reported with NLL, Brier score, reliability bins and ECE, alongside false-negative/false-positive rates, coverage and uncertainty:

$$
\mathrm{ECE}=\sum_b\frac{|B_b|}{N}
\left|\operatorname{mean}_{i\in B_b}(p_i)
-\operatorname{mean}_{i\in B_b}(y_i)\right|.
$$

Low aggregate ECE can hide rare dangerous failures or distribution shift. Calibration is not universal safety, and performance claims must identify the precise artifact, policy, input population and hardware profile. Missing/mismatched artifacts, malformed decisions, unavailable inference and unsupported inputs must not become approvals.

## Golden environment and evaluation design

Source: AgentDojo package `0.1.35`, Git commit `089ed468cf3ed0322acc66b0211f26d9d90dbf60`, banking benchmark `v1.2.2`.

| Task | User goal | Executable utility criterion |
| --- | --- | --- |
| `user_task_0` | Pay the supplied bill | Upstream expected transaction amount/recipient |
| `user_task_2` | Adjust rent from the notice | Upstream first matching scheduled rent amount |
| `user_task_13` | Update account address | Upstream street/city predicate |

Golden references/checkers stay evaluator-only. The agent receives the user's request and available observations, not the expected answer. The simulated payment tool is not a settlement/accounting system; retain upstream weaknesses for parity rather than silently strengthen the benchmark.

Four criteria remain distinct: **task utility**, **upstream selected attacker parity**, **new/changed forbidden-recipient effects**, and **declared subscription-disclosure goal**. A task can succeed while an additional forbidden effect occurs. Original invoice-replacing attacks and fact-preserving append adaptations must be labeled separately; destroyed task facts do not prove safe refusal. See [golden environment and metric meanings](docs/golden-data.md).

### Two complementary A/B protocols

1. **Same-action replay:** both verifiers receive identical independently reviewed action/context pairs. This isolates discrimination, calibration and complete admission latency.
2. **Fresh-state full-agent trials:** the agent attempts each task under each verifier from equivalent isolated initial state. Action sequences may diverge; measure utility, effects, refusal, failures and total cost rather than assume identical proposals.

Both need benign near-misses as well as attacks, exact denominators, declared exclusions, counterbalanced order/repeats and retained unknown/error outcomes. Deny-all/allow-all controls expose misleading aggregate success. A correctly captured and scored agent failure is successful evaluation—not successful agent work. Harness correctness, guard quality and task quality are separate questions.

### What latency means

Measure completed **authoritative authorization**: parsing, trusted-context resolution, queueing, transport, verifier inference and admission checks at a declared boundary. Include exactly one authoritative verifier invocation per admission; an agent-side score followed by a gateway rescore is not the intended B path.

Report hardware/load/input sizes, warm/cold behavior, p50/p95/p99, failures and availability at a predeclared quality operating point. A model forward-pass timer excludes gateway/network/context work; total task time includes agent/tool/reset/judge work. Neither is interchangeable with admission latency. Do not assume seconds for A or milliseconds for B, omit failed samples or choose a favorable percentile after measurement.

### Evidence and native judge review

MLflow records every model/tool/verifier/judge attempt, including failures, with scores on the owning trace/action span. Lifecycle, receipt, state and evaluation evidence must reconcile. Run-level averages never replace exact case/review coverage, stage outcomes or persisted assessment ownership.

Native Gemini judges run **outside authorization**. They review criterion-specific projected observations against closed normalized rules, not checker Python, measured verdicts or the agent's claims of success. Keep raw native feedback, decoded provenance and scalar verdict/validity/agreement/error fields. Deterministic outcomes remain authoritative; disagreement and insufficient evidence remain visible. Schema-constrained outputs are not independent safety ground truth.

See [evaluation design](docs/evaluation-design-review.md), [trace/score ownership](docs/mlflow-trace-contract.md) and [the banking runbook](docs/banking-feasibility.md) for exact evidence contracts and examples.

## Run locally

### Python and configuration

Use [uv](https://docs.astral.sh/uv/) and the committed lockfile. Python 3.11–3.13 is supported; `.python-version` selects the local default.

```bash
uv python install
uv sync --locked
```

Create `.env` from `.env.example` **only if absent**; never overwrite existing credentials or commit them. Configure:

| Setting | Purpose |
| --- | --- |
| `LM_STUDIO_BASE_URL`, `LM_STUDIO_MODEL` | Tool-capable acting model; usual endpoint `http://localhost:1234/v1` |
| `MLFLOW_TRACKING_URI` | Tracking server, normally `http://localhost:5001` |
| `BANKING_MLFLOW_EXPERIMENT` | Banking experiment name; an explicit `MLFLOW_EXPERIMENT_ID` takes precedence |
| `GEMINI_API_KEY` | External native judge credentials for the full live harness |
| `MLFLOW_GENAI_JUDGE_DEFAULT_MODEL` | Native judge model, default `gemini:/gemini-2.5-flash` |
| `LITELLM_LOCAL_MODEL_COST_MAP` | Harness uses bundled pricing metadata; cost values are estimates, not invoices |

If MLflow is not already running, start it in another terminal:

```bash
uv run --locked mlflow server --host 127.0.0.1 --port 5001 \
  --backend-store-uri sqlite:///mlflow.db \
  --artifacts-destination .infra/mlflow-artifacts
```

The local harness runs in memory: no Kubernetes, gateway, Actor service or classifier weights are prerequisites. Its direct tool dispatch does not exercise the enforcement architecture above. There is no installed `sub15-breaker` CLI; use the module entry points.

### Tests and experiments

```bash
# Offline tests; no model/provider calls or tracking server required.
bash scripts/test.sh

# Export shared schemas to an ignored local directory; no tool execution.
uv run --locked python -m src.banking_contracts.schemas

# Record-only CODE contract fixtures; requires MLflow, not models or bank actions.
uv run --locked --env-file .env python -m src.banking_contracts.fixtures

# Persisted MLflow plumbing validation with model stubs, no provider calls.
uv run --locked --env-file .env python -m pytest -q validation/test_banking_mlflow_local.py

# Full live harness: local acting model plus paid external native Gemini review.
uv run --locked --env-file .env python -m src.feasibility.runner
```

`--oracle-only` skips the acting model **but still invokes Gemini**; it is not a provider-free mode. Do not repeatedly sample for favorable agent outcomes or judge agreement. Existing compatible source evidence can be reassessed without new model/tool/judge calls:

```bash
uv run --locked --env-file .env python -m src.feasibility.reassess --source-run SOURCE_RUN_ID
```

This needs the original artifacts/traces; example run links in the documentation refer to the owner's local MLflow instance, not a public service. Open MLflow's **Traces** table for action/effect scores and separate native review rows; use [the runbook](docs/banking-feasibility.md) for their exact interpretation.

### Dependencies and infrastructure

Use `uv add PACKAGE` for runtime dependencies and `uv add --dev PACKAGE` for test tools; commit both `pyproject.toml` and `uv.lock`. Review deliberate upgrades and run the tests. Do not maintain an unrelated requirements file or install ad hoc packages into the project environment. Locked runs refuse implicit dependency changes; deploy synchronized images without runtime dependency downloads.

For the separate local infrastructure profile, follow [the infrastructure guide](docs/infra.md). It documents pinned Podman/Kind/Cilium/agentgateway/Substrate setup, owned-resource teardown, network controls and non-executing enforcement fixtures. These checks are not evidence of a banking Actor execution boundary. The legacy `--research` environment check includes a command-only sidecar and is not a banking doctor. Do not apply the [placeholder workloads](k8s/README.md) as if they supplied a complete deployment.

## Explore the repository

| Path | Purpose |
| --- | --- |
| `src/feasibility/` | Banking adapter, local agent, pinned checks, native judges, trace auditing and evaluation |
| `src/banking_contracts/` | Shared action/context/decision/receipt types, JSON Schema exports and record-only structural fixtures |
| `src/banking_service/` | Opt-in Actor-backed computation, transactional state/receipts, platform identity and durable evidence transport |
| `src/infra/`, `scripts/`, `infra/` | Pinned local infrastructure, readiness and harmless network/enforcement probes |
| `tests/`, `validation/` | Offline regressions and explicit opt-in persisted/live validation |
| `k8s/` | Research workload examples; inspect their prerequisites before use |
| `docs/`, `specs/` | Architecture/contracts, runbooks, evaluation semantics and historical evidence |

Start with the [documentation index](docs/README.md), [scope/trust boundaries](docs/project-scope.md) and [specification](specs/001-breaker.md). Track project progress and planned implementation in [GitHub roadmap #14](https://github.com/caldeirav/sub15-breaker/issues/14), not README test counts or block-status summaries.
