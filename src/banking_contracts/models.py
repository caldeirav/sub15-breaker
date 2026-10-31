"""Shared typed schemas. Validating a DTO does NOT authenticate its issuer."""
from datetime import datetime, timezone
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import (AfterValidator, BaseModel, BeforeValidator, ConfigDict,
                      Field, model_validator)

ToolName = Literal["get_iban", "send_money", "schedule_transaction", "update_scheduled_transaction",
    "get_balance", "get_most_recent_transactions", "get_scheduled_transactions", "read_file",
    "get_user_info", "update_password", "update_user_info"]
OpaqueId = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")]
Version = Annotated[int, Field(ge=0, le=2**63 - 1)]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


def normalize_money(value):
    # Decimal construction and fixed formatting are exact; normalize() could round
    # under the ambient Decimal context and is deliberately not used.
    number = Decimal(value)
    if not number.is_finite(): raise ValueError("nonfinite_money")
    text = format(number, "f")
    if "." in text: text = text.rstrip("0").rstrip(".")
    return "0" if number == 0 else text


Money = Annotated[str, Field(min_length=1, max_length=128,
    pattern=r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$"), AfterValidator(normalize_money)]


def utc(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("aware_datetime_required")
    return value.astimezone(timezone.utc)


UTCDateTime = Annotated[datetime, BeforeValidator(utc)]


class ContractModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True, validate_default=True)


class PolicyProfile(ContractModel):
    schema_version: Literal["banking-policy-v1"] = "banking-policy-v1"
    policy_id: OpaqueId
    policy_version: Version
    allowed_tools: Annotated[tuple[ToolName, ...], BeforeValidator(lambda v: tuple(v) if isinstance(v, list) else v),
                             Field(json_schema_extra={"uniqueItems": True})]
    status: Literal["active", "needs_review", "unavailable"] = "active"
    amount_unit: OpaqueId = "benchmark-native"
    currency: Annotated[str, Field(pattern=r"^[A-Z]{3}$")] | None = None
    max_decimal_places: Annotated[int, Field(ge=0, le=128)] | None = None
    min_amount: Money | None = None
    max_amount: Money | None = None
    max_argument_bytes: Annotated[int, Field(gt=0, le=8192)] = 8192
    max_string_chars: Annotated[int, Field(gt=0, le=4096)] = 4096
    max_collection_count: Annotated[int, Field(ge=0, le=10000)] = 1000

    @model_validator(mode="after")
    def validate_profile(self):
        if len(set(self.allowed_tools)) != len(self.allowed_tools): raise ValueError("duplicate_capability")
        if self.min_amount is not None and self.max_amount is not None and Decimal(self.min_amount) > Decimal(self.max_amount):
            raise ValueError("invalid_amount_bounds")
        return self


class TrustedContext(ContractModel):
    schema_version: Literal["banking-context-v1"] = "banking-context-v1"
    context_version: Version
    principal_id: OpaqueId
    interaction_id: OpaqueId
    trial_id: OpaqueId
    actor_id: OpaqueId
    actor_generation: Version
    state_version: Version
    intent_id: OpaqueId
    intent_version: Version
    user_request: Annotated[str, Field(min_length=1, max_length=4096, repr=False)]
    policy: PolicyProfile
    expires_at: UTCDateTime
    authority_kind: Literal["service-owned", "service-owned-fixture"] = "service-owned-fixture"


class ActionProposal(ContractModel):
    schema_version: Literal["banking-action-v1"] = "banking-action-v1"
    action_id: OpaqueId
    idempotency_key: OpaqueId
    expected_context_version: Version
    expected_actor_generation: Version
    expected_state_version: Version
    tool_name: ToolName
    arguments: dict[str, Any] = Field(repr=False)


class BindingCommitment(ContractModel):
    schema_version: Literal["banking-binding-v1"] = "banking-binding-v1"
    algorithm: Literal["hmac-sha256"] = "hmac-sha256"
    profile_id: OpaqueId = "fixture-binding-v1"
    key_ref: OpaqueId
    action_digest: Digest
    context_digest: Digest
    bound_digest: Digest


class BoundAction(ContractModel):
    schema_version: Literal["banking-bound-action-v1"] = "banking-bound-action-v1"
    verifier_input_version: Literal["banking-verifier-input-v1"] = "banking-verifier-input-v1"
    proposal: ActionProposal
    context: TrustedContext
    tool_catalog_digest: Digest
    binding: BindingCommitment
    fixture_only: bool = True


def decision_schema(schema):
    schema["allOf"] = [
        {"if": {"properties": {"decision_scope": {"const": "structural_fixture"}}, "required": ["decision_scope"]},
         "then": {"properties": {"fixture_only": {"const": True}}}},
        {"if": {"properties": {"decision_scope": {"const": "admission"}}, "required": ["decision_scope"]},
         "then": {"properties": {"fixture_only": {"const": False}}}}]
    schema["x-required-runtime-checks"] = ["issued_at < expires_at", "trusted issuer/context and keyed binding validation"]


class Decision(ContractModel):
    """Shared shape; an admission decision still needs a real authenticated issuer."""
    model_config = ConfigDict(json_schema_extra=decision_schema)
    schema_version: Literal["banking-decision-v1"] = "banking-decision-v1"
    decision_id: OpaqueId
    action_id: OpaqueId
    binding: BindingCommitment
    verdict: Literal["allow", "deny", "error", "unknown"]
    reason_code: OpaqueId
    verifier_id: OpaqueId
    decision_scope: Literal["structural_fixture", "admission"]
    issued_at: UTCDateTime
    expires_at: UTCDateTime
    fixture_only: bool
    financial_authorization: Literal[False] = False

    @model_validator(mode="after")
    def validate_times(self):
        if self.issued_at >= self.expires_at: raise ValueError("invalid_decision_deadline")
        if self.decision_scope == "structural_fixture" and not self.fixture_only:
            raise ValueError("fixture_scope_required")
        if self.decision_scope == "admission" and self.fixture_only:
            raise ValueError("admission_is_not_fixture_scope")
        return self


class FixtureDecision(Decision):
    schema_version: Literal["banking-decision-v1"] = "banking-decision-v1"
    verifier_id: Literal["structural-fixture-v1"] = "structural-fixture-v1"
    decision_scope: Literal["structural_fixture"] = "structural_fixture"
    fixture_only: Literal[True] = True


def receipt_schema(schema):
    def when(field, value, properties):
        return {"if": {"properties": {field: {"const": value}}, "required": [field]},
                "then": {"properties": properties}}
    schema["allOf"] = [
        when("fixture_only", True, {"executed": {"const": False}}),
        when("status", "recorded_only", {"fixture_only": {"const": True}, "executed": {"const": False},
                                         "state_version_after": {"type": "integer"}}),
        when("status", "not_executed", {"executed": {"const": False}}),
        when("status", "executed", {"fixture_only": {"const": False}, "executed": {"const": True},
                                    "evidence_id": {"type": "string"}, "state_version_after": {"type": "integer"}}),
        when("status", "unknown", {"executed": {"type": "null"}, "state_version_after": {"type": "null"}}),
        when("status", "error", {"executed": {"type": "null"}, "state_version_after": {"type": "null"}})]
    # Standard JSON Schema cannot compare two arbitrary property values. These
    # remain explicitly normative Python/protocol checks, never silent promises.
    schema["x-required-runtime-checks"] = [
        "state_version_after >= state_version_before when after is known",
        "recorded_only requires state_version_after == state_version_before",
        "receipt issuer/evidence existence and keyed action/context/decision binding"]


class ExecutionReceipt(ContractModel):
    """A shape for future outcomes, not evidence that a real execution occurred."""
    model_config = ConfigDict(json_schema_extra=receipt_schema)
    schema_version: Literal["banking-receipt-v1"] = "banking-receipt-v1"
    receipt_id: OpaqueId
    action_id: OpaqueId
    decision_id: OpaqueId
    binding: BindingCommitment
    principal_id: OpaqueId
    trial_id: OpaqueId
    actor_id: OpaqueId
    actor_generation: Version
    state_version_before: Version
    state_version_after: Version | None
    status: Literal["recorded_only", "not_executed", "executed", "unknown", "error"]
    executed: bool | None
    evidence_id: OpaqueId | None
    recorded_at: UTCDateTime
    fixture_only: bool

    @model_validator(mode="after")
    def validate_outcome(self):
        if self.fixture_only and self.executed is not False: raise ValueError("fixture_cannot_execute")
        if self.status == "recorded_only" and (not self.fixture_only or self.executed is not False or
                self.state_version_after != self.state_version_before): raise ValueError("invalid_record_only_receipt")
        if self.status == "not_executed" and self.executed is not False: raise ValueError("invalid_nonexecution_receipt")
        if self.status == "executed" and (self.fixture_only or self.executed is not True or self.evidence_id is None or
                self.state_version_after is None): raise ValueError("execution_evidence_required")
        if self.status in {"unknown", "error"} and (self.executed is not None or self.state_version_after is not None):
            raise ValueError("uncertain_execution_cannot_be_false")
        if self.state_version_after is not None and self.state_version_after < self.state_version_before:
            raise ValueError("state_version_regression")
        return self


class ErrorReport(ContractModel):
    schema_version: Literal["banking-error-v1"] = "banking-error-v1"
    code: OpaqueId
    stage: OpaqueId
    retryable: Literal[False] = False
    fixture_only: Literal[True] = True
