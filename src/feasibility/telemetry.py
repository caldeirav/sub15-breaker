"""Persisted trace readback and scalar-score export; no provider calls."""
import mlflow

from src.feasibility.banking import SOURCE, digest
from src.feasibility.judges import provenance_choices, review_score_values
from src.feasibility.metrics_contract import CONTRACT_VERSION, review_payload


def log_case_scores(record):
    for name, value in {"execution/model_attempts": record["model_attempts"],
                        "execution/tool_attempts": len(record["evidence"]["actions"])}.items():
        mlflow.log_feedback(trace_id=record["trace_id"], name=name, value=value, source=SOURCE)
    for action in record["evidence"]["actions"]:
        for key, value in {"execution_error": bool(action["error"]), "state_changed": action["state_changed"]}.items():
            mlflow.log_feedback(trace_id=record["trace_id"], span_id=action["span_id"],
                name=f"tool/{key}", value=value, source=SOURCE)


def scalar_scores(trace):
    return {a.name: a.value for a in trace.info.assessments
            if a.span_id is None and a.error is None and isinstance(a.value, (bool, int, float, str))}


def audit_traces(records, reviews, get_trace=None):
    """Missing/duplicate spans or missing/wrong score columns fail the evidence gate."""
    mlflow.flush_trace_async_logging()
    get_trace = get_trace or mlflow.get_trace
    errors, rows = [], []
    cache = {}

    def fetch(trace_id):
        if trace_id not in cache:
            cache[trace_id] = get_trace(trace_id)
        return cache[trace_id]

    def retrieve(trace_id, kind):
        trace = fetch(trace_id)
        if trace is None or not trace.data.spans:
            errors.append(f"{trace_id}: missing {kind} trace")
            return None
        rows.append(dict(trace_id=trace_id, kind=kind, scores=scalar_scores(trace)))
        return trace

    for record in records:
        trace = retrieve(record["trace_id"], "case")
        if trace is None:
            continue
        scores = scalar_scores(trace)
        spans = trace.data.spans
        tools = [s for s in spans if s.span_type == "TOOL"]
        models = [s for s in spans if s.span_type == "CHAT_MODEL"]
        rows[-1].update(case_id=record["case_id"], trial_run_id=record["child_run_id"],
                        model_spans=len(models), tool_spans=len(tools))
        if len(tools) != len(record["evidence"]["actions"]) or len(models) != record["model_attempts"]:
            errors.append(f"{record['trace_id']}: model/tool attempt counts differ")
        if trace.info.trace_metadata.get("mlflow.sourceRun") != record["child_run_id"]:
            errors.append(f"{record['trace_id']}: wrong trial run association")
        roots = [s for s in spans if s.parent_id is None]
        if len(roots) != 1 or roots[0].outputs != record["evidence"]:
            errors.append(f"{record['trace_id']}: root evidence differs")
        actions = record["evidence"]["actions"]
        action_spans = [a["span_id"] for a in actions]
        if (len(set(action_spans)) != len(action_spans) or set(action_spans) != {s.span_id for s in tools}
                or len({a["evidence_id"] for a in actions}) != len(actions)):
            errors.append(f"{record['trace_id']}: actions/tool spans are not a unique bijection")
        for action in record["evidence"]["actions"]:
            matches = [s for s in tools if s.span_id == action["span_id"] and s.outputs == action]
            expected_tool = {"tool/execution_error": bool(action["error"]), "tool/state_changed": action["state_changed"]}
            actual = {a.name: a.value for a in trace.info.assessments if a.span_id == action["span_id"] and a.error is None}
            if len(matches) != 1 or any(k not in actual or actual[k] != v for k, v in expected_tool.items()):
                errors.append(f"{record['trace_id']}: tool evidence/assessments missing")
        model_calls = record["evidence"].get("model_calls", [])
        model_ids = [call["span_id"] for call in model_calls]
        if (len(model_calls) != record["model_attempts"] or len(set(model_ids)) != len(model_ids)
                or set(model_ids) != {s.span_id for s in models}):
            errors.append(f"{record['trace_id']}: model attempt ledger differs")
        for call in model_calls:
            matches = [s for s in models if s.span_id == call["span_id"]]
            if len(matches) != 1:
                continue
            model_span = matches[0]
            inputs, outputs = model_span.inputs or {}, model_span.outputs or {}
            if (not isinstance(inputs, dict) or not isinstance(outputs, dict)
                    or not {"model", "input", "tools", "instructions", "max_output_tokens"} <= inputs.keys()
                    or "status" not in outputs or inputs.get("model") != call["requested_model"]
                    or model_span.attributes.get("mlflow.llm.model") != call["requested_model"]
                    or digest(inputs) != call["input_digest"] or digest(outputs) != call["output_digest"]):
                errors.append(f"{record['trace_id']}: model request/response/provenance differs")
        expected = {f"oracle/{k}": record["measured"][k] for k in
                    ("utility", "selected_attack_goal_reached", "state_changed", "execution_error")}
        expected.update({"execution/status": record["measured"]["status"],
            "execution/completed": record["measured"]["status"] == "completed" and not record["measured"]["execution_error"],
            "execution/model_attempts": record["model_attempts"], "execution/tool_attempts": len(tools)})
        if record["measured"].get("metric_contract_version") == CONTRACT_VERSION:
            expected["metrics/contract_version"] = CONTRACT_VERSION
            expected["effects/declared_goal_known"] = record["measured"]["declared_goal_reached"] is not None
            for name in ("observed_attacker_transfer_count", "forbidden_recipient_transfer", "declared_goal_reached",
                         "normalized_utility_parity", "normalized_attack_parity"):
                if record["measured"][name] is not None:
                    expected[f"effects/{name}"] = record["measured"][name]
        if any(k not in scores or scores[k] != v for k, v in expected.items()):
            errors.append(f"{record['trace_id']}: case scalar assessments missing/different")
    targets = {r["case_id"]: r for r in records}
    for result in reviews:
        trace = retrieve(result["judge_trace_id"], "judge")
        if trace is None:
            continue
        record = targets[result["case_id"]]
        spans = trace.data.spans
        rows[-1].update(case_id=result["case_id"], trial_run_id=record["child_run_id"],
                        target_trace_id=record["trace_id"], criterion=result["criterion"], model_spans=1, tool_spans=0)
        review_spans = [s for s in spans if s.span_type == "LLM" and
            (s.inputs or {}).get("target_trace_id") == record["trace_id"] and
            (s.inputs or {}).get("criterion") == result["criterion"]]
        if len(review_spans) != 1 or review_spans[0].outputs != {k: v for k, v in result.items() if k != "case_id"}:
            errors.append(f"{result['judge_trace_id']}: judge invocation/link/output differs")
        elif (not (review_spans[0].inputs or {}).get("model")
                or not (review_spans[0].inputs or {}).get("instructions")
                or "inference_params" not in review_spans[0].inputs
                or review_spans[0].attributes.get("mlflow.llm.model") != review_spans[0].inputs["model"]):
            errors.append(f"{result['judge_trace_id']}: judge model/config provenance missing")
        if len(review_spans) == 1:
            inputs, projected, reference = review_payload(record, result["criterion"])
            actual_inputs = review_spans[0].inputs
            if (actual_inputs.get("inputs") != inputs or actual_inputs.get("outputs") != projected
                    or actual_inputs.get("expectations") != reference):
                errors.append(f"{result['judge_trace_id']}: normalized projection/rule differs or oracle leaked")
            if (review_spans[0].attributes.get("judge.native") and
                    actual_inputs.get("feedback_choices") != provenance_choices(projected, reference)):
                errors.append(f"{result['judge_trace_id']}: native provenance schema differs")
        scores = scalar_scores(trace)
        expected = review_score_values(result)
        target_trace = fetch(record["trace_id"])
        target_scores = scalar_scores(target_trace) if target_trace else {}
        if any(scores.get(f"judge/{k}") != v or target_scores.get(f"{result['judge']}/{k}") != v for k, v in expected.items()):
            errors.append(f"{result['judge_trace_id']}: review/target scalar assessments missing/different")
        if trace.info.trace_metadata.get("mlflow.sourceRun") != record["child_run_id"]:
            errors.append(f"{result['judge_trace_id']}: wrong trial run association")
    return dict(passed=not errors, errors=errors, traces=rows)
