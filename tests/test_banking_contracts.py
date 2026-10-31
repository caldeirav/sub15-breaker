"""03a contracts: no model/provider calls, banking execution or tracking server."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace

from pydantic import ValidationError
from jsonschema import Draft202012Validator
import pytest

from src.banking_contracts.authority import FixtureRecorder, FixtureRegistry, issue_fixture_decision
from src.banking_contracts.codec import ContractError, canonical_bytes, parse_object, public_view
from src.banking_contracts.fixtures import (argument_examples, audit_fixture_results, case_plans,
    context_fixture, run_case, validate_case_matrix)
from src.banking_contracts.models import ActionProposal, Decision, ExecutionReceipt, PolicyProfile, TrustedContext
from src.banking_contracts.schemas import export_schemas, write_schemas
from src.banking_contracts.tools import READ_TOOLS, WRITE_TOOLS, ToolCatalog

NOW = datetime(2026, 10, 31, tzinfo=timezone.utc)
CALLER = dict(principal_id="fixture-principal", interaction_id="fixture-interaction", now=NOW)


@pytest.fixture(scope="module")
def catalog(): return ToolCatalog.from_pinned_agentdojo()


@pytest.fixture
def world(catalog):
    context = context_fixture(NOW, allowed_tools=catalog.names)
    registry = FixtureRegistry([context], catalog, binding_key=b"k"*32, key_ref="test-key-v1")
    return registry, FixtureRecorder(registry), context


def proposal(tool="get_balance", arguments=None, **changes):
    value = dict(action_id="action-1", idempotency_key="idem-1", expected_context_version=1,
                 expected_actor_generation=1, expected_state_version=7, tool_name=tool,
                 arguments={} if arguments is None else arguments)
    return ActionProposal(**dict(value, **changes))


@pytest.mark.parametrize("name", sorted(READ_TOOLS | WRITE_TOOLS))
def test_all_eleven_tool_schemas_are_reused_and_strict(catalog, name):
    args = argument_examples()[name]
    checked = catalog.validate_arguments(name, args)
    assert set(checked) == set(args)
    assert catalog.classification(name) == ("read" if name in READ_TOOLS else "write")
    schema = catalog.schemas()[name]["arguments"]
    assert schema["additionalProperties"] is False
    with pytest.raises(ContractError, match="invalid_tool_arguments"):
        catalog.validate_arguments(name, dict(args, unexpected="not-allowed"))


def test_generated_schema_bundle_has_tool_discriminators_and_is_deterministic(catalog, tmp_path):
    bundle = export_schemas(catalog)
    assert len(bundle["tool_arguments"]) == 11
    assert len(bundle["action_with_tool_arguments"]["allOf"][1]["oneOf"]) == 11
    assert {"ActionProposal", "TrustedContext", "Decision", "ExecutionReceipt", "ErrorReport"} <= bundle["models"].keys()
    assert bundle["tool_arguments"]["update_password"]["arguments"]["properties"]["password"]["writeOnly"]
    path, digest = write_schemas(tmp_path, catalog)
    first = path.read_bytes()
    assert write_schemas(tmp_path, catalog)[1] == digest and path.read_bytes() == first
    for model in bundle["models"].values(): Draft202012Validator.check_schema(model)
    Draft202012Validator.check_schema(bundle["action_with_tool_arguments"])
    validator = Draft202012Validator(bundle["action_with_tool_arguments"])
    for name, args in argument_examples().items():
        validator.validate(proposal(name, args).model_dump(mode="json"))


@pytest.mark.parametrize("body,code", [
    (b'{"action_id":"a","action_id":"b"}', "duplicate_json_key"),
    (b'{"arguments":{"n":1,"n":2}}', "duplicate_json_key"),
    (b'{"x":NaN}', "nonfinite_json_number"), (b'{"x":Infinity}', "nonfinite_json_number"),
    (b'{"x":1e9999}', "noncanonical_value"), (b'[]', "expected_json_object"),
    (b'{broken', "invalid_json"), (b'\xff', "invalid_json"), (b'x'*16385, "invalid_body_size"),
    (b'{"x":"\\ud800"}', "noncanonical_value"),
])
def test_json_rejects_ambiguity_nonfinite_unicode_and_size(body, code):
    with pytest.raises(ContractError, match=code): parse_object(body)


def test_json_order_is_canonical_but_unicode_is_not_silently_normalized():
    assert canonical_bytes(parse_object(b'{"b":2,"a":1}')) == b'{"a":1,"b":2}'
    assert canonical_bytes(dict(text="Caf\u00e9")) != canonical_bytes(dict(text="Cafe\u0301"))


def test_proposal_wire_version_is_not_confused_with_bundle_version(world):
    registry, _, _ = world
    raw = proposal().model_dump(mode="json")
    assert registry.parse_proposal(canonical_bytes(raw)) == proposal()
    raw["schema_version"] = "banking-actions-v1"  # family/bundle version, not ActionProposal's version
    with pytest.raises(ContractError, match="invalid_action_schema"):
        registry.parse_proposal(canonical_bytes(raw))


@pytest.mark.parametrize("value", [12.3, True, "NaN", "Infinity", "1e2", "01.20", "+1.20", " 1.20", "1." , "9"*129])
def test_money_is_an_exact_bounded_string_not_a_float_or_rounding_rule(catalog, value):
    with pytest.raises(ContractError):
        catalog.validate_arguments("send_money", dict(argument_examples()["send_money"], amount=value))


def test_money_normalization_float_adapter_and_precision_profile(catalog, world):
    registry, _, context = world
    args = dict(argument_examples()["send_money"], amount="12.3000")
    bound = registry.bind(proposal("send_money", args), **CALLER)
    assert bound.proposal.arguments["amount"] == "12.3" and args["amount"] == "12.3000"
    assert catalog.to_upstream_arguments("send_money", args)["amount"] == 12.3
    equivalent = registry.bind(proposal("send_money", dict(args, amount="12.3")), **CALLER)
    assert equivalent.binding == bound.binding
    for amount in ("12.345", "10000000000000001"):
        with pytest.raises(ContractError): catalog.validate_arguments("send_money", dict(args, amount=amount), context.policy)
    with pytest.raises(ContractError, match="upstream_float_value_loss"):
        catalog.to_upstream_arguments("send_money", dict(args, amount="9007199254740993"))
    # No ambient Decimal precision loss, and no implicit currency from the recipient.
    exact = catalog.validate_arguments("send_money", dict(args, amount="123456789012345678901234567890.123456789"))
    assert exact["amount"] == "123456789012345678901234567890.123456789"
    assert context.policy.currency is None and context.policy.amount_unit == "benchmark-native"


def test_optional_arguments_and_default_resource_limits_are_not_bypassed(catalog, world):
    _, _, context = world
    assert catalog.validate_arguments("update_scheduled_transaction", dict(id=7)) == dict(id=7)
    assert catalog.to_upstream_arguments("update_scheduled_transaction", dict(id=7, amount=None))["amount"] is None
    policy = context.policy.model_copy(update={"max_collection_count": 3})
    with pytest.raises(ContractError, match="collection_count_limit"):
        catalog.validate_arguments("get_most_recent_transactions", {}, policy)  # upstream default is100
    for value in (True, 1.0, "1"):
        with pytest.raises(ContractError): catalog.validate_arguments("get_most_recent_transactions", dict(n=value))
    assert catalog.validate_arguments("get_most_recent_transactions", dict(n=3), policy) == dict(n=3)


@pytest.mark.parametrize("extra", ["principal_id", "actor_id", "policy", "user_request", "expires_at", "allow", "risk"])
def test_agent_cannot_assert_authority_or_verdict_in_proposal(world, extra):
    registry, _, _ = world
    body = dict(proposal().model_dump(mode="json"), **{extra: "CANARY-PRIVATE-INPUT"})
    with pytest.raises(ContractError) as error: registry.parse_proposal(canonical_bytes(body))
    assert error.value.code == "invalid_action_schema"
    assert "CANARY" not in str(error.value) and "CANARY" not in json.dumps(error.value.report())


@pytest.mark.parametrize("field", ["expected_actor_generation", "expected_state_version", "expected_context_version"])
@pytest.mark.parametrize("value", [-1, True, 1.0, "1", 2**63])
def test_versions_are_strict_bounded_integers(field, value):
    with pytest.raises(ValidationError): proposal(**{field: value})


@pytest.mark.parametrize("changes,code", [
    ({"expected_state_version": 6}, "stale_state"),
    ({"expected_actor_generation": 0}, "stale_actor_generation"),
    ({"expected_context_version": 0}, "stale_context"),
])
def test_stale_proposal_does_not_bind(world, changes, code):
    registry, _, _ = world
    with pytest.raises(ContractError, match=code): registry.bind(proposal(**changes), **CALLER)


def test_trusted_lookup_expiry_and_context_snapshot(world):
    registry, _, context = world
    with pytest.raises(ContractError, match="unknown_trusted_context"):
        registry.bind(proposal(), **dict(CALLER, principal_id="other-principal"))
    with pytest.raises(ContractError, match="context_expired"):
        registry.bind(proposal(), **dict(CALLER, now=context.expires_at))
    with pytest.raises(ContractError, match="invalid_trusted_clock"):
        registry.bind(proposal(), **dict(CALLER, now=NOW.replace(tzinfo=None)))
    forged = context.model_copy(update={"principal_id": "other-principal"})
    bound = registry.bind(proposal(), **CALLER)
    with pytest.raises(ContractError, match="trusted_context_mismatch"):
        registry.verify(bound.model_copy(update={"context": forged}), **CALLER)


def test_body_mutation_catalog_and_private_key_binding(world, catalog):
    registry, _, context = world
    original = proposal("update_user_info", dict(city="Fixture City"))
    bound = registry.bind(original, **CALLER)
    original.arguments["city"] = "Changed after binding"
    assert bound.proposal.arguments["city"] == "Fixture City"
    modified = bound.model_copy(deep=True)
    modified.proposal.arguments["city"] = "Tampered City"
    with pytest.raises(ContractError, match="binding_mismatch"): registry.verify(modified, **CALLER)
    with pytest.raises(ContractError, match="tool_catalog_mismatch"):
        registry.verify(bound.model_copy(update={"tool_catalog_digest": "0"*64}), **CALLER)
    other = FixtureRegistry([context], catalog, binding_key=b"z"*32, key_ref="test-key-v1")
    with pytest.raises(ContractError, match="binding_mismatch"): other.verify(bound, **CALLER)
    with pytest.raises(ContractError, match="nonfixture_action_not_supported"):
        registry.verify(bound.model_copy(update={"fixture_only": False}), **CALLER)


def test_sensitive_payloads_have_keyed_commitments_and_safe_export(world):
    registry, _, context = world
    secret = "PASSWORD-PRIVATE-CANARY"
    bound = registry.bind(proposal("update_password", dict(password=secret)), **CALLER)
    other = registry.bind(proposal("update_password", dict(password=secret+"changed")), **CALLER)
    assert bound.binding != other.binding
    assert secret not in repr(bound) and secret not in json.dumps(public_view(bound))
    assert bound.binding.algorithm == "hmac-sha256" and bound.binding.profile_id == "fixture-binding-v1"
    assert "user_request" in public_view(bound)["context"]
    assert public_view(bound)["context"]["user_request"] == "[WITHHELD]"
    exported = public_view(bound)
    assert "_key" not in exported and "binding_key" not in exported
    assert (b"k"*32).decode() not in json.dumps(exported)  # public key_ref/idempotency_key are not key material


@pytest.mark.parametrize("status,tools,tool,expected", [
    ("active", ("get_balance",), "get_balance", "allow"),
    ("active", ("get_balance",), "get_user_info", "deny"),
    ("needs_review", ("get_balance",), "get_balance", "unknown"),
    ("unavailable", ("get_balance",), "get_balance", "error"),
])
def test_every_nonallow_fixture_decision_blocks_recording(catalog, status, tools, tool, expected):
    context = context_fixture(NOW, policy_status=status, allowed_tools=tools)
    registry = FixtureRegistry([context], catalog)
    recorder = FixtureRecorder(registry)
    bound = registry.bind(proposal(tool), **CALLER)
    decision = issue_fixture_decision(registry, bound, **CALLER)
    receipt, _ = recorder.record(bound, decision, **CALLER)
    assert decision.verdict == expected and decision.financial_authorization is False
    assert receipt.fixture_only and receipt.executed is False
    assert receipt.status == ("recorded_only" if expected == "allow" else "not_executed")
    assert recorder.record_count == (1 if expected == "allow" else 0)


def test_recorder_is_idempotent_but_not_an_executor(world):
    registry, recorder, _ = world
    bound = registry.bind(proposal(), **CALLER)
    decision = issue_fixture_decision(registry, bound, **CALLER)
    first, replay = recorder.record(bound, decision, **CALLER)
    again, replay2 = recorder.record(bound, decision, **CALLER)
    assert first == again and not replay and replay2 and recorder.record_count == 1
    assert first.executed is False and first.state_version_after == first.state_version_before
    changed = registry.bind(proposal("get_user_info"), **CALLER)
    with pytest.raises(ContractError, match="action_id_conflict"):
        recorder.record(changed, issue_fixture_decision(registry, changed, **CALLER), **CALLER)
    reused = registry.bind(proposal(action_id="other-action"), **CALLER)
    with pytest.raises(ContractError, match="idempotency_key_conflict"):
        recorder.record(reused, issue_fixture_decision(registry, reused, **CALLER), **CALLER)


def test_concurrent_records_and_capacity_are_bounded(world):
    registry, recorder, _ = world
    bound = registry.bind(proposal(), **CALLER)
    decision = issue_fixture_decision(registry, bound, **CALLER)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: recorder.record(bound, decision, **CALLER), range(20)))
    assert recorder.record_count == 1 and sum(not replay for _, replay in results) == 1
    small = FixtureRecorder(registry, max_records=1)
    small.record(bound, decision, **CALLER)
    next_action = registry.bind(proposal(action_id="second", idempotency_key="second"), **CALLER)
    with pytest.raises(ContractError, match="fixture_capacity"):
        small.record(next_action, issue_fixture_decision(registry, next_action, **CALLER), **CALLER)


def test_changed_generation_and_forged_decision_cannot_record(world, catalog):
    registry, recorder, context = world
    bound = registry.bind(proposal(), **CALLER)
    decision = issue_fixture_decision(registry, bound, **CALLER)
    with pytest.raises(ContractError, match="decision_binding_mismatch"):
        recorder.record(bound, decision.model_copy(update={"verdict": "deny"}), **CALLER)
    reset = FixtureRegistry([context.model_copy(update={"actor_generation": 2})], catalog)
    with pytest.raises(ContractError, match="stale_actor_generation"):
        FixtureRecorder(reset).record(bound, decision, **CALLER)
    assert recorder.record_count == 0


def test_receipts_cannot_turn_uncertainty_or_fixture_into_execution(world):
    registry, recorder, _ = world
    bound = registry.bind(proposal(), **CALLER)
    receipt, _ = recorder.record(bound, issue_fixture_decision(registry, bound, **CALLER), **CALLER)
    value = receipt.model_dump(mode="python")
    for changes in (dict(status="executed", executed=True), dict(status="unknown", executed=False),
                    dict(state_version_after=6), dict(status="executed", fixture_only=False, executed=True, evidence_id=None)):
        with pytest.raises(ValidationError): ExecutionReceipt.model_validate(dict(value, **changes))
    unknown = ExecutionReceipt.model_validate(dict(value, status="unknown", fixture_only=False,
        executed=None, state_version_after=None, evidence_id=None))
    assert unknown.executed is None


@pytest.mark.parametrize("changes", [
    dict(status="unknown", fixture_only=False, executed=False, state_version_after=None),
    dict(status="error", fixture_only=False, executed=False, state_version_after=None),
    dict(status="executed", fixture_only=True, executed=True, evidence_id=None),
    dict(status="executed", fixture_only=False, executed=True, evidence_id=None),
    dict(status="executed", fixture_only=False, executed=True, state_version_after=None),
    dict(status="recorded_only", fixture_only=False, executed=False),
    dict(status="not_executed", fixture_only=False, executed=True),
])
def test_published_receipt_schema_and_python_both_reject_false_outcomes(world, changes):
    registry, recorder, _ = world
    bound = registry.bind(proposal(), **CALLER)
    receipt, _ = recorder.record(bound, issue_fixture_decision(registry, bound, **CALLER), **CALLER)
    value = dict(receipt.model_dump(mode="json"), **changes)
    assert list(Draft202012Validator(ExecutionReceipt.model_json_schema()).iter_errors(value))
    with pytest.raises(ValidationError): ExecutionReceipt.model_validate(value)


def test_schema_declares_runtime_cross_field_checks_and_valid_outcomes(world):
    registry, recorder, _ = world
    bound = registry.bind(proposal(), **CALLER)
    receipt, _ = recorder.record(bound, issue_fixture_decision(registry, bound, **CALLER), **CALLER)
    schema = ExecutionReceipt.model_json_schema()
    validator = Draft202012Validator(schema)
    validator.validate(receipt.model_dump(mode="json"))
    unknown = dict(receipt.model_dump(mode="json"), status="unknown", fixture_only=False, executed=None,
                   state_version_after=None, evidence_id=None)
    validator.validate(unknown)
    assert "x-required-runtime-checks" in schema
    # Dynamic value comparisons cannot be expressed by standard JSON Schema.
    wrong_version = dict(receipt.model_dump(mode="json"), state_version_after=8)
    validator.validate(wrong_version)
    with pytest.raises(ValidationError): ExecutionReceipt.model_validate(wrong_version)


def test_profile_and_contracts_reject_unknown_versions_and_bad_owner_config(catalog):
    with pytest.raises(ValidationError): proposal(schema_version="banking-action-v999")
    with pytest.raises(ValidationError): PolicyProfile(policy_id="p", policy_version=1, allowed_tools=("get_balance", "get_balance"))
    with pytest.raises(ValidationError): PolicyProfile(policy_id="p", policy_version=1, allowed_tools=(), min_amount="2", max_amount="1")
    context = context_fixture(NOW, allowed_tools=catalog.names)
    with pytest.raises(ContractError, match="duplicate_trusted_context"): FixtureRegistry([context, context], catalog)
    with pytest.raises(ContractError, match="fixture_key_too_short"): FixtureRegistry([context], catalog, binding_key=b"weak")
    with pytest.raises(ContractError, match="nonfixture_authority_not_supported"):
        FixtureRegistry([context.model_copy(update={"authority_kind": "service-owned"})], catalog)
    assert len({p["case_id"] for p in case_plans()}) == len(case_plans())


def test_every_declared_fixture_runs_full_wire_path_and_persisted_scores(monkeypatch, catalog):
    traces, stack = {}, []
    class Span:
        def set_inputs(self, value): self.inputs = deepcopy(value)
        def set_outputs(self, value): self.outputs = deepcopy(value)
    @contextmanager
    def start_span(name, span_type):
        span = Span()
        span.trace_id = stack[0].trace_id if stack else f"tr-fixture-{len(traces)}"
        span.span_id = f"span-{len(traces.setdefault(span.trace_id, []))}"
        span.parent_id = stack[-1].span_id if stack else None
        span.name, span.span_type = name, span_type
        traces[span.trace_id].append(span)
        stack.append(span)
        try: yield span
        finally: stack.pop()
    feedback = {}
    def log_feedback(**kw):
        feedback.setdefault(kw["trace_id"], []).append(SimpleNamespace(name=kw["name"], value=kw["value"],
            error=None, span_id=None, source=kw["source"]))
    monkeypatch.setattr("mlflow.start_span", start_span)
    monkeypatch.setattr("mlflow.log_feedback", log_feedback)
    results = [run_case(plan, NOW, catalog) for plan in case_plans()]
    assert len(results) == 26 and all(r["passed"] for r in results), results
    snapshots = {key: SimpleNamespace(info=SimpleNamespace(assessments=feedback[key],
        trace_metadata={"mlflow.sourceRun": "unit-run"}), data=SimpleNamespace(spans=spans)) for key, spans in traces.items()}
    assert all(row["passed"] for row in audit_fixture_results(results, "unit-run", snapshots.get))
    damaged = deepcopy(snapshots)
    damaged[results[0]["trace_id"]].info.assessments[0].value = False
    assert not all(row["passed"] for row in audit_fixture_results(results, "unit-run", damaged.get))
    assert not all(row["passed"] for row in audit_fixture_results(results, "wrong-run", snapshots.get))
    wrong_issuer = deepcopy(snapshots)
    for trace in wrong_issuer.values():
        for assessment in trace.info.assessments:
            assessment.source = SimpleNamespace(source_type="HUMAN", source_id="wrong-owner")
    assert not any(row["passed"] for row in audit_fixture_results(results, "unit-run", wrong_issuer.get))
    duplicate = deepcopy(snapshots)
    duplicate[results[0]["trace_id"]].info.assessments.append(deepcopy(duplicate[results[0]["trace_id"]].info.assessments[0]))
    assert not audit_fixture_results(results, "unit-run", duplicate.get)[0]["passed"]


def test_fixture_matrix_does_not_pass_when_empty_missing_or_duplicated():
    plans = case_plans()
    validate_case_matrix(plans)
    for broken in ([], plans[:-1], plans+[deepcopy(plans[0])]):
        with pytest.raises(ContractError, match="fixture_case_matrix_mismatch"): validate_case_matrix(broken)
