"""Service-owned in-memory fixtures, NOT authentication or financial authorization."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import hmac
import secrets
from threading import Lock
from uuid import uuid4

from pydantic import ValidationError

from src.banking_contracts.codec import ContractError, canonical_bytes, parse_object
from src.banking_contracts.models import (ActionProposal, BindingCommitment, BoundAction,
    ExecutionReceipt, FixtureDecision, TrustedContext, utc)
from src.banking_contracts.tools import ToolCatalog


def clock(value=None):
    try:
        return utc(datetime.now(timezone.utc) if value is None else value)
    except (ValueError, TypeError):
        raise ContractError("invalid_trusted_clock", "context") from None


class FixtureRegistry:
    """The caller principal is supplied by a TRUSTED adapter, never request JSON.

    This fixture cannot authenticate that adapter or a network caller. It resolves
    authority from its own immutable snapshot and rechecks it at record time.
    """
    def __init__(self, contexts, catalog=None, *, binding_key=None, key_ref="fixture-key-v1"):
        self.catalog = catalog or ToolCatalog.from_pinned_agentdojo()
        self._contexts = {}
        for value in contexts:
            context = TrustedContext.model_validate(value.model_dump(mode="python") if isinstance(value, TrustedContext) else value)
            if context.authority_kind != "service-owned-fixture":
                raise ContractError("nonfixture_authority_not_supported", "context")
            key = context.principal_id, context.interaction_id
            if key in self._contexts: raise ContractError("duplicate_trusted_context", "context")
            self._contexts[key] = context
        if binding_key is not None and (not isinstance(binding_key, bytes) or len(binding_key) < 32):
            raise ContractError("fixture_key_too_short", "binding")
        self._key = binding_key or secrets.token_bytes(32)
        self.key_ref = key_ref

    def resolve(self, *, principal_id, interaction_id, now=None):
        context = self._contexts.get((principal_id, interaction_id))
        if context is None: raise ContractError("unknown_trusted_context", "context")
        if clock(now) >= context.expires_at: raise ContractError("context_expired", "context")
        return context.model_copy(deep=True)

    def parse_proposal(self, body):
        try:
            return ActionProposal.model_validate(parse_object(body))
        except ContractError:
            raise
        except (ValidationError, ValueError, TypeError):
            raise ContractError("invalid_action_schema", "parse") from None

    def _commit(self, domain, value):
        return hmac.new(self._key, domain.encode()+b"\0"+canonical_bytes(value), hashlib.sha256).hexdigest()

    def bind(self, proposal, *, principal_id, interaction_id, now=None):
        try:
            # Revalidate model_copy/nested mutations; frozen DTOs are not deep authority.
            proposal = ActionProposal.model_validate(proposal.model_dump(mode="python"))
        except (ValidationError, ValueError, TypeError, AttributeError):
            raise ContractError("invalid_action_schema", "binding") from None
        context = self.resolve(principal_id=principal_id, interaction_id=interaction_id, now=now)
        if proposal.expected_context_version != context.context_version:
            raise ContractError("stale_context", "context")
        if proposal.expected_actor_generation != context.actor_generation:
            raise ContractError("stale_actor_generation", "context")
        if proposal.expected_state_version != context.state_version:
            raise ContractError("stale_state", "context")
        arguments = self.catalog.validate_arguments(proposal.tool_name, proposal.arguments, context.policy)
        normalized = proposal.model_copy(update={"arguments": deepcopy(arguments)})
        action_digest, context_digest = self._commit("action-v1", normalized), self._commit("context-v1", context)
        try:
            binding = BindingCommitment(key_ref=self.key_ref, action_digest=action_digest, context_digest=context_digest,
                bound_digest=self._commit("binding-v1", dict(key_ref=self.key_ref, action=action_digest, context=context_digest,
                    profile_id="fixture-binding-v1", tool_catalog=self.catalog.schema_digest,
                    input_version="banking-verifier-input-v1")))
        except ValidationError:
            raise ContractError("invalid_binding_profile", "binding") from None
        value = BoundAction(proposal=normalized, context=context, tool_catalog_digest=self.catalog.schema_digest, binding=binding)
        canonical_bytes(value)
        return value

    def verify(self, action, *, principal_id, interaction_id, now=None):
        try:
            action = BoundAction.model_validate(action.model_dump(mode="python"))
        except (ValidationError, ValueError, TypeError, AttributeError):
            raise ContractError("invalid_bound_action", "binding") from None
        expected = self.bind(action.proposal, principal_id=principal_id, interaction_id=interaction_id, now=now)
        if action.fixture_only is not True:
            raise ContractError("nonfixture_action_not_supported", "binding")
        if not hmac.compare_digest(action.tool_catalog_digest, expected.tool_catalog_digest):
            raise ContractError("tool_catalog_mismatch", "binding")
        if canonical_bytes(action.context) != canonical_bytes(expected.context):
            raise ContractError("trusted_context_mismatch", "binding")
        for name in ("key_ref", "algorithm", "profile_id", "action_digest", "context_digest", "bound_digest"):
            if not hmac.compare_digest(getattr(action.binding, name), getattr(expected.binding, name)):
                raise ContractError("binding_mismatch", "binding")
        return expected


def fixture_verdict(action):
    """Structural/capability fixture only; user intent is NOT deemed financially safe."""
    if action.context.policy.status == "needs_review": return "unknown", "fixture_policy_needs_review"
    if action.context.policy.status == "unavailable": return "error", "fixture_policy_unavailable"
    if action.proposal.tool_name not in action.context.policy.allowed_tools: return "deny", "fixture_capability_denied"
    return "allow", "fixture_structural_pass"


def issue_fixture_decision(registry, action, *, principal_id, interaction_id, now=None):
    action = registry.verify(action, principal_id=principal_id, interaction_id=interaction_id, now=now)
    verdict, reason = fixture_verdict(action)
    return FixtureDecision(decision_id=uuid4().hex, action_id=action.proposal.action_id,
        binding=action.binding, verdict=verdict, reason_code=reason,
        issued_at=clock(now), expires_at=action.context.expires_at)


class FixtureRecorder:
    """Bounded process-local idempotent ledger. Executes ZERO banking tools.

    Not durable state, transactional mutation, exactly-once execution or a signed
    authorization protocol. Every record attempt revalidates current authority.
    """
    def __init__(self, registry, max_records=1000):
        if type(max_records) is not int or not 1 <= max_records <= 10000:
            raise ContractError("invalid_fixture_capacity", "record")
        self.registry, self.max_records = registry, max_records
        self._records, self._idempotency = {}, {}
        self._lock = Lock()

    @property
    def record_count(self):
        with self._lock: return len(self._records)

    def record(self, action, decision, *, principal_id, interaction_id, now=None):
        action = self.registry.verify(action, principal_id=principal_id, interaction_id=interaction_id, now=now)
        try:
            decision = FixtureDecision.model_validate(decision.model_dump(mode="python"))
        except (ValidationError, ValueError, TypeError, AttributeError):
            raise ContractError("invalid_fixture_decision", "record") from None
        current = clock(now)
        expected_verdict, expected_reason = fixture_verdict(action)
        if (decision.action_id != action.proposal.action_id or decision.binding != action.binding or
                decision.expires_at != action.context.expires_at or not decision.issued_at <= current < decision.expires_at or
                decision.verdict != expected_verdict or decision.reason_code != expected_reason):
            raise ContractError("decision_binding_mismatch", "record")
        context, proposal = action.context, action.proposal
        prefix = (context.principal_id, context.trial_id, context.actor_id, context.actor_generation)
        action_key, idempotency_key = (*prefix, proposal.action_id), (*prefix, proposal.idempotency_key)
        def receipt(status):
            return ExecutionReceipt(receipt_id=uuid4().hex, action_id=proposal.action_id, decision_id=decision.decision_id,
                binding=action.binding, principal_id=context.principal_id, trial_id=context.trial_id,
                actor_id=context.actor_id, actor_generation=context.actor_generation,
                state_version_before=context.state_version, state_version_after=context.state_version,
                status=status, executed=False, evidence_id="fixture-record-"+uuid4().hex,
                recorded_at=current, fixture_only=True)
        if decision.verdict != "allow": return receipt("not_executed"), False
        with self._lock:
            # Recheck time after queueing; this is still only a local recording, not
            # transactional bank-state admission or an authenticated transport.
            current = clock(now)
            self.registry.verify(action, principal_id=principal_id, interaction_id=interaction_id, now=current)
            if not decision.issued_at <= current < decision.expires_at:
                raise ContractError("decision_expired", "record")
            old = self._records.get(action_key)
            existing = self._idempotency.get(idempotency_key)
            if old is not None:
                if old.binding != action.binding or existing != action_key:
                    raise ContractError("action_id_conflict", "record")
                return old, True
            if existing is not None: raise ContractError("idempotency_key_conflict", "record")
            if len(self._records) >= self.max_records: raise ContractError("fixture_capacity", "record")
            value = receipt("recorded_only")
            self._records[action_key], self._idempotency[idempotency_key] = value, action_key
            return value, False
