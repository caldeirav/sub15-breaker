"""Read-only presentation context for the five live cards.

Derives what a presenter needs to explain each use-case — the actual pinned
task prompt, a masked view of the initial synthetic state, the tool inventory,
the released attack proposal for D02 and the declared faults for D04/D05 —
from the pinned plan/adapter data. This module never dispatches work, creates
trials, calls models or touches the cluster; it only reads pinned assets and
applies the existing Mask/public_view sanitization.
"""
import json

from src.banking_contracts.codec import public_view
from src.benchmark.privacy import Mask
from src.demo_ui.protocol import CARD_CONTEXT, CARDS
from src.integrations.agentdojo.inventory import digest


def _masked_state(mask, environment):
    return public_view(mask(environment.model_dump(mode="json")))


def _documents(mask, environment, names):
    """Whole pinned file bodies, masked; untrusted text stays visibly untrusted."""
    files = environment.model_dump(mode="json").get("filesystem", {}).get("files", {})
    return {name: mask(files.get(name)) for name in names if name in files}


def _tools(adapter):
    return [dict(name=name, kind=adapter.catalog.classification(name)) for name in adapter.catalog.names]


def build(plan, adapter):
    """Full card context from pinned data. Raises on adapter/plan problems."""
    episodes = {}
    environment = adapter.suite.load_and_inject_default_environment({})
    mask = Mask()
    mask.learn(environment.model_dump(mode="json"))
    for task_id in sorted({meta["task_id"] for meta in CARD_CONTEXT.values()}):
        episodes[task_id] = adapter.episode(task_id, "card-context").public.prompt
    state = _masked_state(mask, environment)
    tools = _tools(adapter)
    attack = None
    fixtures = plan.get("fixtures") or {}
    if fixtures.get("injection_task_0"):
        # The released attack proposal replayed by the D02 scripted producer.
        attack = [dict(tool=call.get("tool_name"), arguments=public_view(mask(dict(call.get("arguments") or {}))))
                  for call in fixtures["injection_task_0"]]
    cards = []
    for card_id in CARDS:
        meta = CARD_CONTEXT[card_id]
        entry = dict(id=card_id, title=meta["title"], kind=meta["kind"], description=meta["description"],
            producer=meta["producer"], task_id=meta["task_id"], expected_decision=meta["expected"],
            expectation=meta["expectation"], invariants=list(meta["invariants"]), violation=meta["violation"],
            prompt=episodes[meta["task_id"]], documents=_documents(mask, environment, meta["documents"]),
            state_sections=list(meta["state_sections"]), state=state, tools=tools,
            source="live", schema_version="demo-card-context-v1")
        if card_id == "D02" and attack:
            entry["attack"] = attack
        if meta.get("fault"):
            entry["fault"] = dict(meta["fault"])
        cards.append(entry)
    return dict(cards=cards, source="live", context_sha256=digest(dict(cards=cards)))


def fallback(plan):
    """Curated card metadata only, used when pinned derivation is unavailable.

    The browser labels this fallback; no prompt, state, tools or attack
    proposal are invented here.
    """
    cards = []
    for card_id in CARDS:
        meta = CARD_CONTEXT[card_id]
        entry = dict(id=card_id, title=meta["title"], kind=meta["kind"], description=meta["description"],
            producer=meta["producer"], task_id=meta["task_id"], expected_decision=meta["expected"],
            expectation=meta["expectation"], invariants=list(meta["invariants"]), violation=meta["violation"],
            documents={}, state_sections=list(meta["state_sections"]), prompt=None, state=None, tools=None,
            source="fallback", schema_version="demo-card-context-v1")
        if meta.get("fault"):
            entry["fault"] = dict(meta["fault"])
        cards.append(entry)
    return dict(cards=cards, source="fallback", context_sha256=digest(dict(cards=cards)))


def bounded(value):
    """Reject context payloads that could not have come from the pinned slice."""
    text = json.dumps(value, allow_nan=False)
    if len(text) > 262144:
        raise ValueError("card_context_unexpectedly_large")
    return value
