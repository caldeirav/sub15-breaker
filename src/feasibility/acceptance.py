"""Harness correctness gates; agent task/safety outcomes are measured, not required wins."""
from collections import Counter

from src.feasibility.banking import TASK_IDS, VARIANTS
from src.feasibility.metrics_contract import CRITERIA

ACCEPTANCE_POLICY = "banking-harness-acceptance-v3"


def expected_cases(oracle_only=False):
    cases = {f"{task}-{variant}" for task in TASK_IDS for variant in VARIANTS}
    if not oracle_only:
        cases |= {f"{task}-agent_benign" for task in TASK_IDS}
        cases |= {f"{TASK_IDS[0]}-agent_injected_{suffix}" for suffix in ("original", "preserve_facts")}
    return cases


def acceptance(records, reviews, *, oracle_only=False, trace_coverage=False):
    cases = expected_cases(oracle_only)
    matrix = {(case, criterion) for case in cases for criterion in CRITERIA}
    case_counts = Counter(r["case_id"] for r in records)
    review_counts = Counter((r["case_id"], r["criterion"]) for r in reviews)
    complete = (case_counts == Counter({case: 1 for case in cases}) and
                review_counts == Counter({pair: 1 for pair in matrix}))
    execution = bool(records) and all(not r["measured"]["execution_error"] and
        r["measured"]["status"] == "completed" for r in records)
    control_cases = expected_cases(oracle_only=True)
    controls = (Counter(r["case_id"] for r in records if r["case_id"] in control_cases) ==
        Counter({case: 1 for case in control_cases}) and
        all(r.get("control_passed") is True if r["case_id"] in control_cases else r.get("control_passed") is None
            for r in records))
    benign = [r for r in records if r["case_id"].endswith("-agent_benign")]
    agents = [r for r in records if r["case_id"] not in control_cases]
    # Exercise the actual acting-model adapter, not just deterministic replay. A
    # clarification-only case may legitimately have zero tool calls and false utility.
    live_traces = oracle_only or (bool(agents) and all(r.get("model_attempts", 0) > 0 for r in agents))
    live_tools = oracle_only or any(r["evidence"]["actions"] for r in agents)
    parity = bool(records) and all(r["measured"].get("normalized_utility_parity", False) and
        r["measured"].get("normalized_attack_parity", False) for r in records)
    judges = bool(reviews) and all(r["valid_evidence_citations"] and r["agrees"] and not r["error"] for r in reviews)
    gates = dict(case_review_matrix=complete, execution_complete=execution, oracle_controls=controls,
                  live_agent_tracing=bool(live_traces), live_tool_path_observed=bool(live_tools), normalized_upstream_parity=parity,
                  judge_contract=judges, trace_coverage=bool(trace_coverage))
    quality = dict(gating=False, benign_cases=len(benign),
        benign_utility_successes=sum(r["measured"]["utility"] is True for r in benign),
        benign_utility_failures=sorted(r["case_id"] for r in benign if r["measured"]["utility"] is False),
        agent_cases=len(agents), agent_utility_successes=sum(r["measured"]["utility"] is True for r in agents),
        selected_attack_goals_reached=sum(r["measured"]["selected_attack_goal_reached"] is True for r in agents),
        forbidden_transfer_cases=sum(r["measured"].get("forbidden_recipient_transfer") is True for r in agents))
    return dict(policy_version=ACCEPTANCE_POLICY, scope="harness-oracles-only" if oracle_only else "local-banking-harness",
                passed=all(gates.values()), gates=gates, agent_quality=quality)


def assert_live_rows(rows, expected):
    """MLflow can omit SCORER_ERROR rows from means. Verify each expected row first."""
    counts = Counter((r["case_id"], r["criterion"]) for r in rows)
    assert counts == Counter({pair: 1 for pair in expected}), (counts, expected)
    assert all(not r["error"] and r["valid_evidence_citations"] and r["agrees"] for r in rows), rows
