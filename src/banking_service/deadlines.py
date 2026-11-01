"""Opt-in benchmark deadlines; legacy service behavior remains the default."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Deadlines:
    name: str
    reviewer: int
    native_hook: int
    actor_store: int
    actor_server: int
    actor_client: int
    mcp_client: int
    mcp_route: int
    ticket: int


LEGACY=Deadlines("legacy",20,25,15,45,40,50,60,30)
LEARNED=Deadlines("learned-guard-v1",20,25,30,55,60,65,70,90)


def profile(name="legacy"):
    if name=="legacy":return LEGACY
    if name==LEARNED.name:return LEARNED
    raise ValueError("unknown_banking_deadline_profile")
