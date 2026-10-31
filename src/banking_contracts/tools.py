"""Reuse pinned upstream argument definitions; no tool implementation or execution."""
from copy import deepcopy
from decimal import Decimal
import importlib.metadata
import hashlib
import json
import math
from typing import get_args

from pydantic import ConfigDict, ValidationError, create_model

from src.banking_contracts.codec import ContractError, canonical_bytes
from src.banking_contracts.models import Money, PolicyProfile

AGENTDOJO_COMMIT = "089ed468cf3ed0322acc66b0211f26d9d90dbf60"
READ_TOOLS = frozenset({"get_iban", "get_balance", "get_most_recent_transactions", "get_scheduled_transactions",
                        "read_file", "get_user_info"})
WRITE_TOOLS = frozenset({"send_money", "schedule_transaction", "update_scheduled_transaction", "update_password", "update_user_info"})


class ToolCatalog:
    def __init__(self, tools):
        tools = list(tools)
        if len(tools) != 11 or {tool.name for tool in tools} != READ_TOOLS | WRITE_TOOLS:
            raise ContractError("unexpected_tool_set", "catalog")
        self._original = {tool.name: tool.parameters for tool in tools}
        self._wire = {}
        for name, original in self._original.items():
            fields = {}
            for key, info in original.model_fields.items():
                annotation = info.annotation
                if key == "amount":
                    if annotation is float: annotation = Money
                    elif float in get_args(annotation) and type(None) in get_args(annotation): annotation = Money | None
                    else: raise ContractError("unsupported_amount_schema", "catalog")
                info = deepcopy(info)
                info.annotation = annotation
                if key == "password": info.json_schema_extra = {"writeOnly": True, "x-sensitive": True}
                fields[key] = (annotation, info)
            self._wire[name] = create_model(f"BankingArgs_{name}",
                __config__=ConfigDict(extra="forbid", strict=True, frozen=True), **fields)

    @classmethod
    def from_pinned_agentdojo(cls):
        distribution = importlib.metadata.distribution("agentdojo")
        direct = json.loads(distribution.read_text("direct_url.json") or "{}")
        if direct.get("vcs_info", {}).get("commit_id") != AGENTDOJO_COMMIT:
            raise ContractError("unreviewed_agentdojo_revision", "catalog")
        from agentdojo.task_suite import get_suite
        return cls(get_suite("v1.2.2", "banking").tools)

    @property
    def names(self): return tuple(sorted(self._wire))

    def classification(self, name):
        if name not in self._wire: raise ContractError("unknown_tool", "arguments")
        return "read" if name in READ_TOOLS else "write"

    def validate_arguments(self, name, value, policy: PolicyProfile | None = None):
        if name not in self._wire: raise ContractError("unknown_tool", "arguments")
        if not isinstance(value, dict): raise ContractError("arguments_must_be_object", "arguments")
        try:
            validated = self._wire[name].model_validate(value)
            effective = validated.model_dump(mode="json")
            result = validated.model_dump(mode="json", exclude_unset=True)
        except (ValidationError, ValueError, TypeError):
            raise ContractError("invalid_tool_arguments", "arguments") from None
        if policy:
            if len(canonical_bytes(result)) > policy.max_argument_bytes:
                raise ContractError("argument_byte_limit", "arguments")
            if any(isinstance(v, str) and len(v) > policy.max_string_chars for v in result.values()):
                raise ContractError("argument_string_limit", "arguments")
            if "n" in effective and not 0 <= effective["n"] <= policy.max_collection_count:
                raise ContractError("collection_count_limit", "arguments")
            if result.get("amount") is not None:
                number = Decimal(result["amount"])
                scale = max(0, -number.as_tuple().exponent)
                if policy.max_decimal_places is not None and scale > policy.max_decimal_places:
                    raise ContractError("amount_precision_limit", "arguments")
                if ((policy.min_amount is not None and number < Decimal(policy.min_amount)) or
                        (policy.max_amount is not None and number > Decimal(policy.max_amount))):
                    raise ContractError("amount_bound", "arguments")
        return result

    def to_upstream_arguments(self, name, value, policy=None):
        """Explicit binary-float adapter; reject decimal value loss, never round silently."""
        result = self.validate_arguments(name, value, policy)
        if result.get("amount") is not None:
            number = Decimal(result["amount"])
            converted = float(number)
            if not math.isfinite(converted) or Decimal(str(converted)) != number:
                raise ContractError("upstream_float_value_loss", "adapter")
            result["amount"] = converted
        return result

    def schemas(self):
        return {name: dict(classification=self.classification(name), arguments=model.model_json_schema())
                for name, model in sorted(self._wire.items())}

    @property
    def schema_digest(self):
        return hashlib.sha256(canonical_bytes(self.schemas(), limit=131072)).hexdigest()
