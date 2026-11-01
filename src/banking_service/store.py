"""Single-writer SQLite state, receipts and outbox on service-owned storage.

Tools run in an Actor on a private snapshot. Only this transaction boundary
publishes synthetic effects. It makes no exactly-once tool-invocation claim.
"""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
from pathlib import Path
import sqlite3
import time
from uuid import uuid4

from src.banking_contracts.codec import ContractError, canonical_bytes, public_view
from src.banking_contracts.models import ActionProposal, BindingCommitment, BoundAction, ExecutionReceipt, TrustedContext
from src.banking_contracts.tools import ToolCatalog

MAX_STATE_BYTES = 131072
MAX_RESULT_BYTES = 32768
MAX_EVENT_BYTES = 65536


def packed(value, limit=MAX_STATE_BYTES):
    return canonical_bytes(value, limit=limit).decode()


def fail(code):
    raise ContractError(code, "runtime")


class StateStore:
    def __init__(self, path, key, *, catalog=None, max_actions=1000, max_events=4000,ticket_lifetime=30):
        if not isinstance(key, bytes) or len(key) < 32: fail("invalid_runtime_key")
        if type(max_actions) is not int or type(max_events) is not int or min(max_actions, max_events) < 1:
            fail("invalid_store_capacity")
        self.path, self.key = Path(path), key
        self.catalog = catalog or ToolCatalog.from_pinned_agentdojo()
        self.max_actions, self.max_events = max_actions, max_events
        if type(ticket_lifetime) is not int or not 1<=ticket_lifetime<=90:fail("invalid_ticket_lifetime")
        self.ticket_lifetime=ticket_lifetime
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.transaction() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS metadata (name TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS trials (
                    id TEXT PRIMARY KEY, principal TEXT NOT NULL, generation INTEGER NOT NULL,
                    actor TEXT NOT NULL, uid TEXT NOT NULL UNIQUE, version INTEGER NOT NULL,
                    status TEXT NOT NULL, context TEXT NOT NULL, initial TEXT NOT NULL, state TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS actions (
                    ticket TEXT PRIMARY KEY, trial TEXT NOT NULL REFERENCES trials(id),
                    generation INTEGER NOT NULL, action TEXT NOT NULL, idem TEXT NOT NULL,
                    proposal TEXT NOT NULL, bound TEXT NOT NULL, status TEXT NOT NULL,
                    deadline REAL NOT NULL, result TEXT,
                    UNIQUE(trial, generation, action), UNIQUE(trial, generation, idem));
                CREATE TABLE IF NOT EXISTS outbox (
                    id TEXT PRIMARY KEY, kind TEXT NOT NULL, trial TEXT NOT NULL,
                    payload TEXT NOT NULL, exported INTEGER NOT NULL DEFAULT 0);
            """)
            db.execute("BEGIN IMMEDIATE")  # executescript ends the opening transaction
            existing = db.execute("SELECT value FROM metadata WHERE name='key_check'").fetchone()
            check = self.fingerprint({"domain": "store-key-check-v1"})
            if existing and not hmac.compare_digest(existing[0], check): fail("runtime_key_changed")
            db.execute("INSERT OR IGNORE INTO metadata VALUES ('key_check', ?)", (check,))
        self.path.chmod(0o600)

    @contextmanager
    def transaction(self):
        db = sqlite3.connect(self.path, isolation_level=None, timeout=3)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA synchronous=FULL")
            db.execute("PRAGMA max_page_count=65536")
            db.execute("BEGIN IMMEDIATE")
            yield db
            if db.in_transaction: db.commit()
        except sqlite3.Error:
            if db.in_transaction: db.rollback()
            fail("durable_store_unavailable")
        except BaseException:
            if db.in_transaction: db.rollback()
            raise
        finally:
            db.close()

    def fingerprint(self, value):
        return hmac.new(self.key, canonical_bytes(value, limit=MAX_STATE_BYTES), hashlib.sha256).hexdigest()

    def _event(self, db, kind, trial, payload):
        event_id = uuid4().hex
        db.execute("INSERT INTO outbox(id,kind,trial,payload) VALUES (?,?,?,?)",
            (event_id, kind, trial, packed(public_view(payload), MAX_EVENT_BYTES)))
        return event_id

    def _capacity(self, db, slots=1):
        count = db.execute("SELECT count(*) FROM outbox WHERE exported=0").fetchone()[0]
        reserved = db.execute("SELECT count(*) FROM actions WHERE status IN ('prepared','executing')").fetchone()[0] * 2
        if count + reserved + slots > self.max_events: fail("evidence_outbox_full")

    def _trial(self, db, trial_id, principal):
        trial = db.execute("SELECT * FROM trials WHERE id=?", (trial_id,)).fetchone()
        if trial is None or trial["principal"] != principal: fail("unknown_owned_trial")
        return trial

    def create(self, context, actor_uid, state):
        context = TrustedContext.model_validate(context)
        if context.authority_kind != "service-owned": fail("runtime_context_required")
        if not actor_uid or len(actor_uid) > 128: fail("invalid_actor_uid")
        state = packed(state)
        with self.transaction() as db:
            self._capacity(db)
            if db.execute("SELECT count(*) FROM trials").fetchone()[0] >= 100: fail("trial_capacity")
            if db.execute("SELECT 1 FROM trials WHERE id=?", (context.trial_id,)).fetchone(): fail("trial_exists")
            db.execute("INSERT INTO trials VALUES (?,?,?,?,?,?,?,?,?,?)", (context.trial_id, context.principal_id,
                context.actor_generation, context.actor_id, actor_uid, context.state_version, "active",
                packed(context), state, state))
            self._event(db, "trial_created", context.trial_id, dict(context=context, actor_uid=actor_uid,
                initial_fingerprint=self.fingerprint(json.loads(state))))
        return self.snapshot(context.trial_id, context.principal_id)

    def snapshot(self, trial_id, principal):
        with self.transaction() as db:
            t = self._trial(db, trial_id, principal)
            return dict(trial_id=trial_id, generation=t["generation"], actor_id=t["actor"], actor_uid=t["uid"],
                state_version=t["version"], status=t["status"], state=json.loads(t["state"]),
                fingerprint=self.fingerprint(json.loads(t["state"])), context=dict(json.loads(t["context"]),state_version=t["version"]))

    def prepare(self, trial_id, principal, proposal):
        proposal = ActionProposal.model_validate(proposal)
        proposal = proposal.model_copy(update={"arguments": self.catalog.validate_arguments(proposal.tool_name, proposal.arguments)})
        encoded = packed(proposal)
        with self.transaction() as db:
            t = self._trial(db, trial_id, principal)
            if t["status"] != "active": fail("trial_fenced")
            if proposal.expected_actor_generation != t["generation"]: fail("stale_actor_generation")
            old = db.execute("SELECT * FROM actions WHERE trial=? AND generation=? AND (action=? OR idem=?)",
                (trial_id, t["generation"], proposal.action_id, proposal.idempotency_key)).fetchall()
            if old:
                if len(old) != 1 or old[0]["proposal"] != encoded: fail("action_id_conflict")
                return self._status(old[0], replayed=True)
            if db.execute("SELECT count(*) FROM actions").fetchone()[0] >= self.max_actions: fail("action_capacity")
            if db.execute("SELECT 1 FROM actions WHERE trial=? AND generation=? AND status IN ('prepared','executing')", (trial_id,t["generation"])).fetchone():
                fail("trial_action_pending")
            self._capacity(db, slots=3)
            context = TrustedContext.model_validate(dict(json.loads(t["context"]), state_version=t["version"]))
            if context.expires_at <= datetime.now(timezone.utc): fail("context_expired")
            if proposal.expected_context_version != context.context_version: fail("stale_context")
            if proposal.expected_state_version != t["version"]: fail("stale_state")
            if proposal.tool_name not in context.policy.allowed_tools or context.policy.status != "active": fail("capability_denied")
            checked = self.catalog.validate_arguments(proposal.tool_name, proposal.arguments, context.policy)
            if checked != proposal.arguments: fail("noncanonical_arguments")
            self.catalog.to_upstream_arguments(proposal.tool_name, checked, context.policy)
            action_digest = self.fingerprint(dict(domain="runtime-action-v1", proposal=proposal.model_dump(mode="json")))
            context_digest = self.fingerprint(dict(domain="runtime-context-v1", context=context.model_dump(mode="json")))
            binding = BindingCommitment(key_ref="runtime-binding-key-v1", profile_id="runtime-structural-binding-v1",
                action_digest=action_digest, context_digest=context_digest,
                bound_digest=self.fingerprint(dict(domain="runtime-binding-v1", action=action_digest,
                    context=context_digest, catalog=self.catalog.schema_digest, actor_uid=t["uid"])))
            bound = BoundAction(proposal=proposal, context=context, binding=binding,
                tool_catalog_digest=self.catalog.schema_digest, fixture_only=False)
            ticket, deadline = uuid4().hex, min(time.time() + self.ticket_lifetime, context.expires_at.timestamp())
            db.execute("INSERT INTO actions VALUES (?,?,?,?,?,?,?,?,?,?)", (ticket, trial_id, t["generation"],
                proposal.action_id, proposal.idempotency_key, encoded, packed(bound), "prepared", deadline, None))
            self._event(db, "action_prepared", trial_id, dict(ticket=ticket, proposal=proposal, binding=bound.binding,
                state_version=t["version"], actor_id=t["actor"], actor_uid=t["uid"], generation=t["generation"]))
            return dict(ticket=ticket, status="prepared", replayed=False, result=None)

    def _status(self, row, replayed=False):
        return dict(ticket=row["ticket"], status=row["status"], replayed=replayed,
                    result=json.loads(row["result"]) if row["result"] else None)

    def status(self, trial_id, principal, ticket):
        with self.transaction() as db:
            self._trial(db, trial_id, principal)
            row = db.execute("SELECT * FROM actions WHERE trial=? AND ticket=?", (trial_id, ticket)).fetchone()
            if row is None: fail("unknown_action_ticket")
            return self._status(row)

    def reconcile(self, trial_id, principal, proposal):
        proposal=ActionProposal.model_validate(proposal)
        proposal=proposal.model_copy(update={"arguments":self.catalog.validate_arguments(proposal.tool_name,proposal.arguments)})
        with self.transaction() as db:
            self._trial(db,trial_id,principal)
            rows=db.execute("SELECT * FROM actions WHERE trial=? AND generation=? AND (action=? OR idem=?)",
                (trial_id,proposal.expected_actor_generation,proposal.action_id,proposal.idempotency_key)).fetchall()
            if not rows:return dict(status="unresolved",ticket=None,replayed=False,result=None)
            if len(rows)!=1 or rows[0]["proposal"]!=packed(proposal):fail("action_id_conflict")
            return self._status(rows[0],replayed=True)

    def _owned_action(self, db, ticket, actor_id, actor_uid):
        row = db.execute("SELECT * FROM actions WHERE ticket=?", (ticket,)).fetchone()
        if row is None: fail("unknown_action_ticket")
        t = db.execute("SELECT * FROM trials WHERE id=?", (row["trial"],)).fetchone()
        if (t["status"] != "active" or t["actor"] != actor_id or t["uid"] != actor_uid or
                t["generation"] != row["generation"]): fail("actor_identity_mismatch")
        return t, row

    def claim(self, ticket, actor_id, actor_uid):
        with self.transaction() as db:
            t, row = self._owned_action(db, ticket, actor_id, actor_uid)
            if row["status"] == "completed": return self._status(row, replayed=True)
            if row["status"] != "prepared": fail("execution_outcome_unknown")
            if time.time() >= row["deadline"]: fail("action_expired")
            db.execute("UPDATE actions SET status='executing' WHERE ticket=?", (ticket,))
            self._event(db, "tool_attempt", row["trial"], dict(ticket=ticket, proposal=json.loads(row["proposal"]),
                actor_id=actor_id, actor_uid=actor_uid, state_version=t["version"]))
            return dict(ticket=ticket, status="executing", proposal=json.loads(row["proposal"]),
                        state=json.loads(t["state"]), before_fingerprint=self.fingerprint(json.loads(t["state"])))

    def commit(self, ticket, actor_id, actor_uid, state, output, error=None):
        state_json, output_json = packed(state), packed(output, MAX_RESULT_BYTES)
        if error is not None and error != "upstream_tool_error": fail("invalid_tool_error")
        with self.transaction() as db:
            t, row = self._owned_action(db, ticket, actor_id, actor_uid)
            if row["status"] == "completed": return self._status(row, replayed=True)
            if row["status"] != "executing": fail("action_not_claimed")
            if time.time() >= row["deadline"]: fail("execution_outcome_unknown")
            proposal = json.loads(row["proposal"])
            if t["version"] != proposal["expected_state_version"]: fail("stale_state")
            if error and state_json != t["state"]: fail("error_cannot_commit_mutation")
            changed = state_json != t["state"]
            version = t["version"] + int(changed)
            bound = json.loads(row["bound"])
            receipt = ExecutionReceipt(receipt_id=uuid4().hex, action_id=row["action"], decision_id="controlled-driver-"+ticket,
                binding=bound["binding"], principal_id=t["principal"], trial_id=t["id"], actor_id=actor_id,
                actor_generation=t["generation"], state_version_before=t["version"], state_version_after=version,
                status="executed", executed=True, evidence_id="runtime-tool-"+ticket,
                recorded_at=datetime.now(timezone.utc), fixture_only=False)
            result = dict(output=json.loads(output_json), error=error, receipt=receipt.model_dump(mode="json"),
                state_changed=changed, before_fingerprint=self.fingerprint(json.loads(t["state"])),
                after_fingerprint=self.fingerprint(state), financial_authorization=False,
                admission_kind="controlled-validation-driver")
            db.execute("UPDATE trials SET state=?,version=? WHERE id=?", (state_json, version, t["id"]))
            db.execute("UPDATE actions SET status='completed', result=? WHERE ticket=?", (packed(result), ticket))
            self._event(db, "tool_result", t["id"], dict(ticket=ticket, proposal=proposal, result=result))
            return dict(ticket=ticket, status="completed", replayed=False, result=result)

    def fence(self, trial_id, principal):
        with self.transaction() as db:
            t = self._trial(db, trial_id, principal)
            self._capacity(db)
            db.execute("UPDATE trials SET status='fenced' WHERE id=?", (trial_id,))
            db.execute("UPDATE actions SET status=CASE status WHEN 'prepared' THEN 'fenced_not_dispatched' ELSE 'fenced_unknown' END "
                "WHERE trial=? AND status IN ('prepared','executing')",(trial_id,))
            self._event(db, "trial_fenced", trial_id, dict(generation=t["generation"], actor_id=t["actor"], actor_uid=t["uid"]))

    def replace(self, trial_id, principal, actor_id, actor_uid):
        with self.transaction() as db:
            t = self._trial(db, trial_id, principal)
            if t["status"] != "fenced": fail("reset_requires_fence")
            if actor_id == t["actor"] or actor_uid == t["uid"]: fail("reset_requires_fresh_actor")
            self._capacity(db)
            context = TrustedContext.model_validate(dict(json.loads(t["context"]), actor_id=actor_id,
                actor_generation=t["generation"]+1, context_version=json.loads(t["context"])["context_version"]+1,
                state_version=0, expires_at=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()))
            db.execute("UPDATE trials SET actor=?,uid=?,generation=?,version=0,status='active',state=initial,context=? WHERE id=?",
                (actor_id, actor_uid, context.actor_generation, packed(context), trial_id))
            self._event(db, "trial_reset", trial_id, dict(actor_id=actor_id, actor_uid=actor_uid,
                generation=context.actor_generation, initial_fingerprint=self.fingerprint(json.loads(t["initial"]))))
        return self.snapshot(trial_id, principal)

    def trial_events(self,trial_id,principal):
        with self.transaction() as db:
            self._trial(db,trial_id,principal)
            return [dict(event_id=row["id"],kind=row["kind"],trial_id=row["trial"],payload=json.loads(row["payload"]))
                for row in db.execute("SELECT * FROM outbox WHERE trial=? ORDER BY rowid",(trial_id,)).fetchall()]

    def events(self, limit=100):
        if type(limit) is not int or not 1 <= limit <= 100: fail("invalid_event_limit")
        with self.transaction() as db:
            return [dict(event_id=r["id"], kind=r["kind"], trial_id=r["trial"], payload=json.loads(r["payload"]))
                    for r in db.execute("SELECT * FROM outbox WHERE exported=0 ORDER BY rowid LIMIT ?", (limit,))]

    def acknowledge(self, event_id):
        with self.transaction() as db:
            db.execute("UPDATE outbox SET exported=1 WHERE id=?", (event_id,))

    def client_event(self, trial_id, principal, kind, payload):
        if kind not in {"model_attempt", "model_result", "model_error", "transport_unknown", "cleanup_result", "validation_result"}:
            fail("unsupported_client_event")
        with self.transaction() as db:
            self._trial(db, trial_id, principal)
            self._capacity(db)
            return dict(event_id=self._event(db, kind, trial_id, payload))
