"""Export reusable JSON Schemas; no providers, tracking server or tool execution."""
import argparse
import hashlib
import json
from pathlib import Path

from src.banking_contracts import CONTRACT_VERSION
from src.banking_contracts.models import (ActionProposal, BindingCommitment, BoundAction, Decision, ErrorReport,
    ExecutionReceipt, FixtureDecision, PolicyProfile, TrustedContext)
from src.banking_contracts.tools import AGENTDOJO_COMMIT, ToolCatalog

MODELS = (ActionProposal, BindingCommitment, BoundAction, Decision, ErrorReport, ExecutionReceipt,
          FixtureDecision, PolicyProfile, TrustedContext)


def export_schemas(catalog=None):
    catalog = catalog or ToolCatalog.from_pinned_agentdojo()
    tools = catalog.schemas()
    # The generic DTO frames the request; this schema also binds its selector to
    # the reused strict argument model. Consumers must still validate authority.
    proposal = {"title": "BankingActionWithToolArguments", "allOf": [ActionProposal.model_json_schema(),
        {"oneOf": [{"properties": {"tool_name": {"const": name}, "arguments": info["arguments"]},
                    "required": ["tool_name", "arguments"]} for name, info in tools.items()]}]}
    return dict(contract_version=CONTRACT_VERSION, upstream_commit=AGENTDOJO_COMMIT,
        tool_classifications={name: info["classification"] for name, info in tools.items()},
        models={model.__name__: model.model_json_schema() for model in MODELS},
        action_with_tool_arguments=proposal, tool_arguments=tools,
        validation_requirements=dict(json_schema="Shape and expressible outcome conditionals; enforce formats where applicable",
            runtime="Also require model validators and x-required-runtime-checks: ordering/equality, canonicalization, limits, authority, freshness and keyed binding"),
        authority_warning="DTO validation/digests do not authenticate callers or authorize financial effects; fixtures only.")


def write_schemas(directory, catalog=None):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    bundle = export_schemas(catalog)
    path = directory / "banking-actions-v1.json"
    data = json.dumps(bundle, sort_keys=True, indent=2).encode()+b"\n"
    path.write_bytes(data)
    return path, hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=".infra/banking-contracts-03a/schemas")
    args = parser.parse_args()
    path, checksum = write_schemas(args.output)
    print(json.dumps(dict(path=str(path), sha256=checksum)))


if __name__ == "__main__": main()
