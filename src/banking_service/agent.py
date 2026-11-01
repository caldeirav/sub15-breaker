"""Opt-in Actor-backed adapter; the accepted in-memory pipeline is unchanged."""
from copy import deepcopy
import json
from types import SimpleNamespace
from uuid import uuid4

import httpx
import mlflow

from src.banking_contracts.codec import ContractError
from src.banking_contracts.tools import ToolCatalog
from src.banking_service.http import RuntimeClient
from src.feasibility.banking import BankingTrial, serializable


def canonical_suite_view(suite):
    schemas=ToolCatalog.from_pinned_agentdojo().schemas()
    return SimpleNamespace(tools=[SimpleNamespace(name=t.name,description=t.description,
        parameters=SimpleNamespace(model_json_schema=lambda name=t.name:deepcopy(schemas[name]["arguments"]))) for t in suite.tools])


class DurableModelClient:
    """Persist model attempts/results before returning them to the agent loop."""
    def __init__(self, client, store, trial_id):
        self.client, self.store, self.trial_id = client, store, trial_id
        self.responses = self

    def with_options(self, **options):
        return DurableModelClient(self.client.with_options(**options), self.store, self.trial_id)

    def create(self, **request):
        call_id = uuid4().hex
        self.store.call("/client-event", dict(trial_id=self.trial_id, kind="model_attempt",
            payload=serializable(dict(call_id=call_id, request=request))))
        try:
            response = self.client.responses.create(**request)
        except Exception as exc:
            self.store.call("/client-event", dict(trial_id=self.trial_id, kind="model_error",
                payload=dict(call_id=call_id, error=type(exc).__name__)))
            raise RuntimeError(type(exc).__name__) from None
        self.store.call("/client-event", dict(trial_id=self.trial_id, kind="model_result",
            payload=serializable(dict(call_id=call_id, response=response.model_dump(mode="json")))))
        return response


class ActorBankingTrial(BankingTrial):
    def __init__(self, suite, task_id, case_id, store, actor_url, authorization):
        super().__init__(suite, task_id, case_id)
        self.store, self.actor = store, RuntimeClient(actor_url, authorization, timeout=20)
        self.remote_trial_id = case_id
        # Reuse the existing bounded pipeline with canonical schemas. This does
        # not alter the original suite or invoke its local FunctionsRuntime.
        self.suite=canonical_suite_view(suite)
        snapshot = store.call("/snapshot", dict(trial_id=case_id))
        self.environment = type(self.environment).model_validate(snapshot["state"])
        self.initial = self.environment.model_copy(deep=True)

    def execute(self, tool, arguments, call_id=None, require_call_id=False):
        if self.status in {"execution_unknown","runtime_error"}:
            raise RuntimeError("Actor trial is stopped pending reconciliation")
        with mlflow.start_span(name=tool, span_type="TOOL") as span:
            span.set_inputs(serializable(dict(tool=tool, arguments=arguments, call_id=call_id,
                execution_backend="substrate-gvisor", trial_id=self.remote_trial_id)))
            committed = None
            stop = False
            try:
                if isinstance(arguments, str):
                    from src.banking_contracts.codec import parse_object
                    arguments = parse_object(arguments.encode())
                if require_call_id and not call_id: raise ContractError("missing_call_id", "adapter")
                snapshot = self.store.call("/snapshot", dict(trial_id=self.remote_trial_id))
                proposal = dict(schema_version="banking-action-v1", action_id="action-"+uuid4().hex,
                    idempotency_key="idempotency-"+uuid4().hex, tool_name=tool, arguments=arguments,
                    expected_context_version=snapshot["context"]["context_version"],
                    expected_actor_generation=snapshot["generation"], expected_state_version=snapshot["state_version"])
                try:
                    prepared = self.store.call("/prepare", dict(trial_id=self.remote_trial_id, proposal=proposal))
                except httpx.TransportError:
                    # No second prepare and no new action identity. Lookup is a
                    # read-only reconciliation of the exact original proposal.
                    prepared = self.store.call("/reconcile", dict(trial_id=self.remote_trial_id,proposal=proposal))
                if prepared["status"]=="completed":
                    result=prepared
                elif prepared["status"]=="prepared":
                    try: result = self.actor.call("/execute", dict(ticket=prepared["ticket"]))
                    except (httpx.TransportError,ContractError):
                        result=self.store.call("/status",dict(trial_id=self.remote_trial_id,ticket=prepared["ticket"]))
                else: raise ContractError("execution_outcome_unknown","adapter")
                if result["status"] != "completed": raise ContractError("execution_outcome_unknown", "adapter")
                committed = result["result"]
                output, error, receipt = committed["output"], committed["error"], committed["receipt"]
                snapshot = self.store.call("/snapshot", dict(trial_id=self.remote_trial_id))
                self.environment = type(self.environment).model_validate(snapshot["state"])
            except (ContractError, httpx.TransportError) as exc:
                error = getattr(exc, "code", "execution_outcome_unknown")
                output, receipt = (committed["output"],committed["receipt"]) if committed else (None,None)
                self.status = "execution_unknown" if committed is None else "runtime_error"
                stop = True
            record = dict(evidence_id=f"{self.case_id}/action-{len(self.records)}", tool=tool,
                arguments=serializable(arguments), output=serializable(output), error=error, span_id=span.span_id,
                state_changed=committed["state_changed"] if committed else None,
                before_state_hash=committed["before_fingerprint"] if committed else None,
                after_state=serializable(self.environment), execution_receipt=serializable(receipt),
                execution_backend="substrate-gvisor")
            self.records.append(record)
            if error: self.errors.append(error)
            span.set_outputs(record)
            if stop:
                self.store.call("/client-event",dict(trial_id=self.remote_trial_id,kind="transport_unknown",
                    payload=dict(error=error,call_id=call_id,known_receipt=serializable(receipt))))
                raise RuntimeError("Actor result requires reconciliation; trial stopped")
            return record
