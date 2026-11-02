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
    commit: int | None = None
    model: int = 45
    episode: int = 480


LEGACY=Deadlines("legacy",20,25,15,45,40,50,60,30)
LEARNED=Deadlines("learned-guard-v1",20,25,30,55,60,65,70,90)
DEMO=Deadlines("native-demo-v1",20,25,35,65,70,80,85,90,5)
MEASURE=Deadlines("native-measure-v2",300,330,350,390,410,450,470,900,10,300,3600)


def profile(name="legacy"):
    if name=="legacy":return LEGACY
    if name==LEARNED.name:return LEARNED
    if name==DEMO.name:return DEMO
    if name==MEASURE.name:return MEASURE
    raise ValueError("unknown_banking_deadline_profile")
