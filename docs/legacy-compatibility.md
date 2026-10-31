# Legacy compatibility: not the banking architecture

These files remain because they contain earlier research scaffolding and regression coverage. They are **not** the supported banking entry point, golden environment, calibrated banking model or complete evidence UI. Their removal/migration is scoped under #24/#10/#12, not performed by a documentation change.

| Path | What it actually represents |
| --- | --- |
| `src/agent/graph.py` | Earlier command-based LangGraph agent, with agent-local generative review and duplicate classifier scoring on allowed actions |
| `src/eval/dataset_loader.py`, `data/golden_eval_suite.jsonl` | Earlier command/reference examples; not executable banking tasks or banking policy labels |
| `src/eval/runner.py` | Earlier paired command runner using external reset routes and a raw Google SDK grader; not the accepted native-judge banking harness |
| `src/gateway/decision_sidecar.py` | Command-only binary classifier prototype; no banking intent/state input or released safety artifact |
| `src/eval/calibrate.py`, `src/eval/metrics.py` | Scalar temperature/NLL and calibration utilities; not a released banking calibration pipeline or sufficient labeled evaluation set |
| `src/dashboard/app.py` | Earlier Streamlit reader for command-run artifacts; use MLflow traces/assessments for banking |
| `Dockerfile.sidecar`, `k8s/decision-sidecar.yaml`, `k8s/agentgateway-hook.yaml`, `k8s/actor-template.yaml` | Research placeholders/prototype workload contracts; not deployable banking admission or an Actor-hosted banking service |

Do not use a generic relevance checkpoint or command-only weights as the banking risk verifier. The prototype's threshold and environment settings are not an approved banking operating point. A successful legacy `/health`, graph stop, denial or chart installation is not evidence of banking authorization, Actor termination or containment.

The accepted [infrastructure fixture](infra.md) is separate: its `command` field carries fixed, non-executing sentinels to test transport/authentication. It does not accept arbitrary agent actions or supply the new banking envelope.

Historical instructions and dataset comparisons are available in [the pre-cleanup revision](https://github.com/caldeirav/sub15-breaker/tree/1e32c54eec0cfe060013487789924baa57470894). They are not current setup recommendations. No destructive command examples should be executed on the host or privileged workloads.

For current use, start with [the banking runbook](banking-feasibility.md), [golden environment](golden-data.md) and [project scope](project-scope.md). Block 03a will define the new contract **after owner requirements clarification**; it does not silently reinterpret any legacy payload as a banking authorization.
