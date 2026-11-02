# Documentation

Start with the [project overview and local quick start](../README.md).
These guides describe implemented behavior, not an old sprint plan.

| Guide | Details |
| --- | --- |
| [System and harness architecture](architecture.md) | Component roles, Substrate versus agentgateway, authority, tickets, transactions, isolation and technical decisions |
| [Agent flow](agent-flow.md) | Compiled graph, messages, tool sequence, native review, cancellation and failure semantics |
| [Model and calibration](model.md) | Shared review input, labels, training populations, frozen artifact, risk calculation, LLM protocol and research limits |
| [Testing and validation](validation.md) | AgentDojo data/checkers, metrics, controls, MLflow ownership, offline tests and full live A/B procedure |
| [Local infrastructure](infra.md) | Prerequisites, versions, owned-stack setup, artifact handoff, credentials, checks and teardown |
| [Demo guide](demo.md) | Live five-card UI, sequential paired runs, real-time observations, golden/timing panels, operator allocations, prerequisites and separate saved-review API |
| [Latest demo results — nd11/nd12](results/demo-nd11-nd12.md) | Versioned protocol, golden accuracy, measured performance, startup appendix, costs and evidence IDs |

## Documentation and evidence policy

Only the latest demo campaign has a results page here. Superseded development
plans, duplicate reports and old block-status pages are removed from current
navigation. Still-relevant design, procedures and limitations are consolidated
into the topic guides; this is not a claim that old failures were repaired.

Historical acceptance JSON, review/checklist records and seven byte-preserved
protocol/rubric assets moved to [the validation archive](../validation/archive/README.md).
The [pre-consolidation docs at revision 394b165](https://github.com/caldeirav/sub15-breaker/tree/394b16518cf0b090d873562715190dbf92c1e4d0/docs)
retain every earlier page. Raw local evidence, MLflow runs, model/data manifests,
review exports and ledgers remain untouched. Archive statements/paths describe
their recording revision; they are not present-day setup instructions.

New results must use a new versioned filename and identify their frozen source,
protocol and data. Never overwrite measured source artifacts, old failed statuses,
negative reviews, quarantined labels or human attestations. Infrastructure health,
CODE tests, Gemini support and independent agent review are **not human sign-off**.
Final owner/process review is tracked in [#17](https://github.com/caldeirav/sub15-breaker/issues/17);
the [roadmap](https://github.com/caldeirav/sub15-breaker/issues/14) owns the backlog.
