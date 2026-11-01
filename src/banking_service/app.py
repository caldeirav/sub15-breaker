"""Authenticated durable-store and Actor entry points for controlled validation."""
import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re

from src.banking_contracts.codec import ContractError
from src.banking_contracts.models import PolicyProfile, TrustedContext
from src.banking_contracts.tools import ToolCatalog
from src.banking_service.auth import IdentityVerifier
from src.banking_service.http import BoundedServer, RuntimeClient, fields
from src.banking_service.store import StateStore
from src.banking_service.upstream import bounded_evaluate, environment_model, initial_state


class StoreApplication:
    def __init__(self, store, identities):
        self.store, self.identities = store, identities

    def __call__(self, path, body, authorization):
        match=re.fullmatch(r"/claim/([0-9a-f]{32})",path)
        if match:
            # Header-only native ext_proc reviews this immutable ticket. There
            # is no second body ticket/action that could differ from the review.
            identity=self.identities.actor(authorization)
            fields(body,())
            return self.store.claim(match[1],identity.name,identity.uid)
        if path in {"/claim", "/commit"}:
            identity = self.identities.actor(authorization)
            if path == "/claim":
                fields(body, ("ticket",))
                return self.store.claim(body["ticket"], identity.name, identity.uid)
            fields(body, ("ticket", "state", "output", "error"))
            state = environment_model().model_validate(body["state"]).model_dump(mode="json")
            return self.store.commit(body["ticket"], identity.name, identity.uid, state, body["output"], body["error"])
        principal = self.identities.driver(authorization)
        if path == "/create":
            fields(body, ("trial_id", "actor_id", "actor_uid", "user_request"))
            context = TrustedContext(context_version=1, principal_id=principal, interaction_id=body["trial_id"],
                trial_id=body["trial_id"], actor_id=body["actor_id"], actor_generation=1, state_version=0,
                intent_id=body["trial_id"], intent_version=1, user_request=body["user_request"],
                policy=PolicyProfile(policy_id="controlled-validation-tools", policy_version=1,
                    allowed_tools=tuple(self.store.catalog.names)),
                expires_at=datetime.now(timezone.utc)+timedelta(hours=1), authority_kind="service-owned")
            return self.store.create(context, body["actor_uid"], initial_state())
        if path == "/snapshot":
            fields(body, ("trial_id",))
            return self.store.snapshot(body["trial_id"], principal)
        if path == "/prepare":
            fields(body, ("trial_id", "proposal"))
            return self.store.prepare(body["trial_id"], principal, body["proposal"])
        if path == "/status":
            fields(body, ("trial_id", "ticket"))
            return self.store.status(body["trial_id"], principal, body["ticket"])
        if path == "/reconcile":
            fields(body,("trial_id","proposal"))
            return self.store.reconcile(body["trial_id"],principal,body["proposal"])
        if path == "/fence":
            fields(body, ("trial_id",))
            self.store.fence(body["trial_id"], principal)
            return dict(fenced=True)
        if path == "/replace":
            fields(body, ("trial_id", "actor_id", "actor_uid"))
            return self.store.replace(body["trial_id"], principal, body["actor_id"], body["actor_uid"])
        if path == "/events":
            fields(body, ())
            return dict(events=self.store.events())
        if path == "/trial-events":
            fields(body,("trial_id",))
            return dict(events=self.store.trial_events(body["trial_id"],principal))
        if path == "/acknowledge":
            fields(body, ("event_id",))
            self.store.acknowledge(body["event_id"])
            return dict(acknowledged=True)
        if path == "/client-event":
            fields(body, ("trial_id", "kind", "payload"))
            return self.store.client_event(body["trial_id"], principal, body["kind"], body["payload"])
        raise ContractError("unknown_runtime_route", "transport")


class ActorApplication:
    def __init__(self, store, identities, runtime_mounts=(),fault_stage=None,benchmark_claim_path=False):
        self.store, self.identities = store, identities
        self.runtime_mounts=runtime_mounts
        if fault_stage not in {None,"after_claim","after_commit"}:raise ValueError("unsupported_validation_fault")
        self.fault_stage=fault_stage
        self.benchmark_claim_path=benchmark_claim_path

    def __call__(self, path, body, authorization):
        self.identities.driver(authorization)
        if path == "/probe":
            fields(body, ())
            from src.banking_service.security import identity
            return dict(**identity(),
                ambient_kubernetes_token=Path("/var/run/secrets/kubernetes.io/serviceaccount/token").exists(),
                environment_keys=sorted(os.environ),mounts=list(self.runtime_mounts))
        if path != "/execute": raise ContractError("unknown_runtime_route", "transport")
        fields(body, ("ticket",))
        if self.benchmark_claim_path:
            if not isinstance(body["ticket"],str) or not re.fullmatch(r"[0-9a-f]{32}",body["ticket"]):
                raise ContractError("invalid_benchmark_ticket","transport")
            work=self.store.call("/claim/"+body["ticket"],{})
        else:
            work = self.store.call("/claim", body)
        if work["status"] == "completed": return work
        # Immutable validation-template setting, never a request/model argument.
        if self.fault_stage=="after_claim":os._exit(70)
        result = bounded_evaluate(work["proposal"], work["state"])
        committed=self.store.call("/commit", dict(ticket=body["ticket"], **result))
        if self.fault_stage=="after_commit":os._exit(71)
        return committed


def main(runtime_mounts=()):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("role", choices=("store", "actor"))
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    identities = (IdentityVerifier(json.loads(os.environ["BANKING_IDENTITY_JSON"]))
        if "BANKING_IDENTITY_JSON" in os.environ else IdentityVerifier.from_file(os.environ["BANKING_IDENTITY_CONFIG"]))
    if args.role == "store":
        store = StateStore(os.environ["BANKING_STORE_PATH"], Path(os.environ["BANKING_KEY_FILE"]).read_bytes())
        application = StoreApplication(store, identities)
    else:
        application = ActorApplication(RuntimeClient(os.environ["BANKING_STORE_URL"], "Bearer inject-actor-jwt"), identities,
            runtime_mounts,os.getenv("BANKING_VALIDATION_FAULT_STAGE"),os.getenv("BANKING_BENCHMARK_CLAIM_PATH")=="1")
    with BoundedServer(("0.0.0.0", args.port), application) as server:
        server.serve_forever()


if __name__ == "__main__": main()
