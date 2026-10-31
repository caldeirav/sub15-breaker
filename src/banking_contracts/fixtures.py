"""Harmless CODE contract fixtures: no banking tools, models, gateway or Actors."""
import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets

from dotenv import load_dotenv
import mlflow

from src.banking_contracts import CONTRACT_VERSION
from src.banking_contracts.authority import FixtureRecorder, FixtureRegistry, issue_fixture_decision
from src.banking_contracts.codec import ContractError, canonical_bytes, public_view
from src.banking_contracts.models import ActionProposal, PolicyProfile, TrustedContext
from src.banking_contracts.schemas import write_schemas
from src.banking_contracts.tools import READ_TOOLS, WRITE_TOOLS, ToolCatalog

ROOT = Path(__file__).resolve().parents[2]
SCORE_FIELDS = ("passed", "proposal_parsed", "context_bound", "outcome", "receipt_recorded", "executed", "replayed", "record_count")
EXPECTED_CASE_IDS = frozenset({"valid_"+name for name in READ_TOOLS | WRITE_TOOLS} | {
    "spoofed_authority", "stale_state", "stale_generation", "wrong_caller", "expired", "duplicate_json", "decision_tamper",
    "capability_denied", "policy_unknown", "policy_unavailable", "tampered_action", "changed_idempotent_payload",
    "idempotent_replay", "invalid_money", "float_adapter_loss"})


def validate_case_matrix(plans):
    if Counter(p["case_id"] for p in plans) != Counter({name: 1 for name in EXPECTED_CASE_IDS}):
        raise ContractError("fixture_case_matrix_mismatch", "protocol")


def context_fixture(now, *, policy_status="active", allowed_tools=None):
    """Developer-authored authority fixture. Does not read golden task/checker data."""
    catalog_names = ToolCatalog.from_pinned_agentdojo().names if allowed_tools is None else allowed_tools
    return TrustedContext(context_version=1, principal_id="fixture-principal", interaction_id="fixture-interaction",
        trial_id="fixture-trial", actor_id="fixture-actor", actor_generation=1, state_version=7,
        intent_id="fixture-intent", intent_version=1, user_request="Record a synthetic contract example only.",
        policy=PolicyProfile(policy_id="fixture-structural-policy", policy_version=1,
            allowed_tools=tuple(catalog_names), status=policy_status, max_decimal_places=2,
            min_amount="0", max_amount="10000000000000000"), expires_at=now+timedelta(minutes=5))


def argument_examples():
    money = dict(recipient="FIXTURE-RECIPIENT", amount="12.30", subject="Fixture only", date="2026-10-31")
    return dict(get_iban={}, get_balance={}, get_most_recent_transactions=dict(n=3),
        get_scheduled_transactions={}, read_file=dict(file_path="fixture-invoice.txt"), get_user_info={},
        send_money=money, schedule_transaction=dict(money, recurring=False),
        update_scheduled_transaction=dict(id=42, amount="12.34"),
        update_password=dict(password=secrets.token_urlsafe(24)),
        update_user_info=dict(street="Fixture Street 1", city="Fixture City"))


def case_plans():
    plans = [dict(case_id=f"valid_{name}", tool=name, arguments=args, expected="allow", records=1)
             for name, args in argument_examples().items()]
    plans += [dict(case_id=name, tool="get_balance", arguments={}, expected="error", error=error, records=0)
        for name, error in (("spoofed_authority", "invalid_action_schema"), ("stale_state", "stale_state"),
            ("stale_generation", "stale_actor_generation"), ("wrong_caller", "unknown_trusted_context"),
            ("expired", "context_expired"), ("duplicate_json", "duplicate_json_key"),
            ("decision_tamper", "decision_binding_mismatch"))]
    plans += [dict(case_id="capability_denied", tool="update_user_info", arguments=dict(city="Fixture City"),
                  expected="deny", records=0),
        dict(case_id="policy_unknown", tool="get_balance", arguments={}, expected="unknown", records=0),
        dict(case_id="policy_unavailable", tool="get_balance", arguments={}, expected="error", records=0),
        dict(case_id="tampered_action", tool="send_money", arguments=argument_examples()["send_money"],
             expected="error", error="binding_mismatch", records=0),
        dict(case_id="changed_idempotent_payload", tool="update_user_info", arguments=dict(city="Fixture City"),
             expected="error", error="action_id_conflict", records=1),
        dict(case_id="idempotent_replay", tool="get_balance", arguments={}, expected="allow", records=1),
        dict(case_id="invalid_money", tool="send_money", arguments=dict(argument_examples()["send_money"], amount="NaN"),
             expected="error", error="invalid_tool_arguments", records=0),
        dict(case_id="float_adapter_loss", tool="send_money", arguments=dict(argument_examples()["send_money"], amount="9007199254740993"),
             expected="error", error="upstream_float_value_loss", records=0)]
    return plans


def run_case(plan, now, catalog):
    name = plan["case_id"]
    context = context_fixture(now, policy_status={"policy_unknown": "needs_review", "policy_unavailable": "unavailable"}.get(name, "active"),
        allowed_tools=("get_balance",) if name == "capability_denied" else catalog.names)
    registry = FixtureRegistry([context], catalog, key_ref="fixture-key-"+name)
    recorder = FixtureRecorder(registry)
    caller = dict(principal_id="fixture-principal", interaction_id="fixture-interaction", now=now)
    proposal = dict(schema_version=ActionProposal.model_fields["schema_version"].default,
        action_id="action-"+name, idempotency_key="idempotency-"+name,
        expected_context_version=1, expected_actor_generation=1, expected_state_version=7,
        tool_name=plan["tool"], arguments=deepcopy(plan["arguments"]))
    if name == "spoofed_authority": proposal["principal_id"] = "forged-principal"
    if name == "stale_state": proposal["expected_state_version"] = 6
    if name == "stale_generation": proposal["expected_actor_generation"] = 0
    if name == "wrong_caller": caller["principal_id"] = "unregistered-principal"
    if name == "expired": caller["now"] = now+timedelta(minutes=6)
    body = canonical_bytes(proposal)
    if name == "duplicate_json": body = body[:-1]+b',"action_id":"duplicate"}'
    result = dict(case_id=name, fixture_only=True, proposal_parsed=False, context_bound=False,
                  outcome=None, error_code=None, receipt_recorded=False, executed=False, replayed=False)
    with mlflow.start_span(name=name, span_type="CHAIN") as root:
        result["trace_id"] = root.trace_id
        root.set_inputs(dict(case_id=name, fixture_only=True, body_bytes=len(body), tool_name=plan["tool"],
            expected=plan["expected"], expected_error=plan.get("error"), trusted_context=public_view(context),
            clock_kind="controlled-fixture", effective_now=caller["now"].isoformat()))
        try:
            with mlflow.start_span(name="parse_proposal", span_type="CHAIN") as span:
                parsed = registry.parse_proposal(body)
                result["proposal_parsed"] = True
                span.set_outputs(public_view(parsed))
            with mlflow.start_span(name="resolve_validate_bind", span_type="CHAIN") as span:
                bound = registry.bind(parsed, **caller)
                result["context_bound"] = True
                span.set_outputs(public_view(bound))
            if name == "float_adapter_loss":
                with mlflow.start_span(name="explicit_float_adapter", span_type="CHAIN"):
                    catalog.to_upstream_arguments(bound.proposal.tool_name, bound.proposal.arguments, context.policy)
            with mlflow.start_span(name="fixture_structural_decision", span_type="CHAIN") as span:
                decision = issue_fixture_decision(registry, bound, **caller)
                span.set_outputs(public_view(decision))
            if name == "tampered_action": bound.proposal.arguments["subject"] = "Changed fixture subject"
            if name == "decision_tamper": decision = decision.model_copy(update={"verdict": "deny"})
            with mlflow.start_span(name="record_only_receipt", span_type="CHAIN") as span:
                receipt, replayed = recorder.record(bound, decision, **caller)
                result.update(outcome=decision.verdict, receipt_recorded=receipt.status == "recorded_only",
                              replayed=replayed, executed=receipt.executed)
                span.set_outputs(public_view(dict(receipt=receipt, replayed=replayed)))
            if name in {"idempotent_replay", "changed_idempotent_payload"}:
                if name == "changed_idempotent_payload":
                    changed = parsed.model_copy(update={"arguments": dict(city="Other Fixture City")})
                    bound = registry.bind(changed, **caller)
                    decision = issue_fixture_decision(registry, bound, **caller)
                with mlflow.start_span(name="repeat_record_attempt", span_type="CHAIN") as span:
                    repeated, replayed = recorder.record(bound, decision, **caller)
                    result["replayed"] = replayed
                    result["executed"] = repeated.executed
                    span.set_outputs(public_view(dict(receipt=repeated, replayed=replayed)))
        except ContractError as exc:
            result.update(outcome="error", error_code=exc.code, error=exc.report())
        result["record_count"] = recorder.record_count
        result["passed"] = (result["outcome"] == plan["expected"] and result["error_code"] == plan.get("error") and
                            result["record_count"] == plan["records"] and result["executed"] is False and
                            (name != "idempotent_replay" or result["replayed"]))
        root.set_outputs(public_view(result))
    source = mlflow.entities.AssessmentSource(source_type="CODE", source_id="banking-contract-fixtures-v1")
    for field in SCORE_FIELDS:
        mlflow.log_feedback(trace_id=result["trace_id"], name=f"contract/{field}", value=result[field], source=source)
    if result["error_code"]:
        mlflow.log_feedback(trace_id=result["trace_id"], name="contract/error_code", value=result["error_code"], source=source)
    return result


def audit_fixture_results(results, run_id, get_trace=None):
    """Verify values/ownership, not merely the presence of a pass column."""
    get_trace = get_trace or mlflow.get_trace
    audit = []
    seen = set()
    for result in results:
        trace = get_trace(result["trace_id"])
        if trace is None:
            audit.append(dict(trace_id=result["trace_id"], passed=False, error="missing_trace"))
            continue
        expected_scores = {f"contract/{name}": result[name] for name in SCORE_FIELDS}
        if result["error_code"] is not None: expected_scores["contract/error_code"] = result["error_code"]
        owned_scores = not any(a.span_id is None and a.name.startswith("contract/") and a.name not in expected_scores
                               for a in trace.info.assessments)
        for name, expected in expected_scores.items():
            matching = [a for a in trace.info.assessments if a.name == name and a.span_id is None]
            if len(matching) != 1:
                owned_scores = False
                continue
            value = matching[0]
            source = value.source
            if (value.error is not None or source is None or source.source_type != "CODE" or
                    source.source_id != "banking-contract-fixtures-v1" or value.value != expected):
                owned_scores = False
        unique = result["trace_id"] not in seen
        seen.add(result["trace_id"])
        spans = trace.data.spans
        audit.append(dict(trace_id=result["trace_id"], passed=unique and bool(spans) and
            trace.info.trace_metadata.get("mlflow.sourceRun") == run_id and
            owned_scores and
            not any(s.span_type in {"LLM", "CHAT_MODEL", "TOOL", "AGENT"} for s in spans) and
            any(s.parent_id is None and s.outputs == result for s in spans)))
    return audit


def run_fixtures():
    load_dotenv(ROOT/".env")
    mlflow.set_tracking_uri(os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5001"))
    mlflow.set_experiment("breaker-banking-contracts-03a")
    os.environ["MLFLOW_ENABLE_ASYNC_TRACE_LOGGING"] = "false"
    os.environ["MLFLOW_TRACE_SAMPLING_RATIO"] = "1"
    os.environ.setdefault("MLFLOW_HTTP_REQUEST_TIMEOUT", "10")
    os.environ.setdefault("MLFLOW_HTTP_REQUEST_MAX_RETRIES", "1")
    catalog, plans = ToolCatalog.from_pinned_agentdojo(), case_plans()
    validate_case_matrix(plans)
    with mlflow.start_run(run_name="block03a-record-only-contract-fixtures") as run:
        mlflow.set_tags(dict(block="03a", fixture_only="true", new_model_calls="0", banking_tool_calls="0",
                            human_acceptance="pending", financial_authorization="false"))
        mlflow.log_dict(dict(contract_version=CONTRACT_VERSION, cases=[{k: v for k, v in p.items() if k != "arguments"} for p in plans],
            tools=list(catalog.names), tool_catalog_digest=catalog.schema_digest, decision_kind="structural-fixture-only",
            commitments="HMAC-SHA-256; private fixture key never exported", financial_authorization=False,
            clock_kind="controlled-fixture", no_banking_state_mutation=True,
            clarification="Owner approved contracts+fixtures, decimal strings, structural registry policy, all11 tools, keyed bindings"), "protocol.json")
        path, checksum = write_schemas(ROOT/".infra/banking-contracts-03a/schemas", catalog)
        mlflow.log_artifact(str(path), "schemas")
        mlflow.log_param("schema_bundle_sha256", checksum)
        source_hashes = {}
        for source in sorted((ROOT/"src/banking_contracts").glob("*.py")):
            mlflow.log_artifact(str(source), "implementation")
            source_hashes[source.name] = hashlib.sha256(source.read_bytes()).hexdigest()
        mlflow.log_dict(source_hashes, "implementation/source-sha256.json")
        now = datetime.now(timezone.utc)
        results = [run_case(plan, now, catalog) for plan in plans]
        audit = audit_fixture_results(results, run.info.run_id)
        summary = dict(run_id=run.info.run_id, experiment_id=run.info.experiment_id, contract_version=CONTRACT_VERSION,
            fixture_only=True, cases=len(results), passed=all(r["passed"] for r in results) and all(r["passed"] for r in audit),
            new_model_calls=0, banking_tool_calls=0, real_executions=0, human_acceptance="pending", results=results)
        mlflow.log_dict(summary, "summary.json")
        mlflow.log_dict(audit, "audit/trace-score-readback.json")
        mlflow.set_tag("fixture_status", "passed" if summary["passed"] else "review_required")
        if not summary["passed"]: mlflow.end_run(status="FAILED")
        print(json.dumps(summary, indent=2))
        return summary


if __name__ == "__main__":
    raise SystemExit(0 if run_fixtures()["passed"] else 1)
