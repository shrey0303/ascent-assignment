"""State-changing actions: preview -> explicit confirmation -> idempotent execution.

- `propose` stores the exact payload server-side and returns a preview plus an HMAC token computed
  over (preview id, user, payload hash, expiry). The token goes to the UI only, never to the model.
- `confirm` is called by the UI button, not by the model (there is no confirm tool). It recomputes
  the hash from the stored payload and checks the token, the user and the expiry, so the action that
  runs is byte-for-byte the one the user saw.
- Every action has an idempotency key derived from its target (same ticket, same alert ...). A UNIQUE
  constraint makes a second confirmation, or a second staff member confirming the same escalation,
  return the existing action instead of creating a duplicate.
"""
import hashlib
import hmac
import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone

from . import config
from .access import AccessDenied, Principal
from .db import get_db

ACTION_LABELS = {"escalate_ticket": "Escalate", "create_task": "Create follow-up task"}


class ConfirmationError(Exception):
    pass


def _canonical(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _payload_hash(action: str, payload: dict) -> str:
    return hashlib.sha256(f"{action}|{_canonical(payload)}".encode()).hexdigest()


def _sign(preview_id: str, user_id: str, payload_hash: str, expires_at: str) -> str:
    message = f"{preview_id}|{user_id}|{payload_hash}|{expires_at}".encode()
    return hmac.new(config.SECRET_KEY.encode(), message, hashlib.sha256).hexdigest()


def idempotency_key(action: str, payload: dict) -> str:
    """One escalation per ticket (or order); one task per alert (or identical task)."""
    if action == "escalate_ticket":
        target = payload.get("ticket_id") or payload.get("order_id") or f"{payload['account_id']}:{payload['reason'].lower()}"
    else:
        target = payload.get("alert_id") or _canonical({k: payload.get(k) for k in ("title", "related_id", "assignee")})
    return hashlib.sha256(f"{action}|{target}".encode()).hexdigest()


def existing_action(action: str, payload: dict) -> dict | None:
    rows = get_db().query("SELECT * FROM actions WHERE idempotency_key = ?", (idempotency_key(action, payload),))
    return _public(rows[0]) if rows else None


def _public(row: dict) -> dict:
    return {**row, "payload": json.loads(row["payload"]), "confirmed_by": json.loads(row["confirmed_by"])}


def propose(principal: Principal, action: str, payload: dict) -> dict:
    preview_id = f"PRV-{uuid.uuid4().hex[:10]}"
    expires_at = (datetime.now(timezone.utc) + timedelta(minutes=config.CONFIRMATION_TTL_MINUTES)).isoformat()
    payload_hash = _payload_hash(action, payload)
    get_db().execute(
        "INSERT INTO pending_actions (preview_id, user_id, action, payload, payload_hash, expires_at) VALUES (?, ?, ?, ?, ?, ?)",
        (preview_id, principal.user_id, action, _canonical(payload), payload_hash, expires_at),
    )
    return {
        "preview_id": preview_id, "action": action, "label": ACTION_LABELS[action], "payload": payload,
        "expires_at": expires_at, "already_exists": existing_action(action, payload),
        "token": _sign(preview_id, principal.user_id, payload_hash, expires_at),
    }


def confirm(principal: Principal, preview_id: str, token: str, authorize) -> dict:
    """Execute a previewed action. `authorize(principal, action, payload)` re-checks permissions now."""
    rows = get_db().query("SELECT * FROM pending_actions WHERE preview_id = ?", (preview_id,))
    if not rows:
        raise ConfirmationError("Unknown preview.")
    pending = rows[0]
    if pending["user_id"] != principal.user_id:
        raise AccessDenied("Only the user who saw this preview can confirm it.")
    if datetime.fromisoformat(pending["expires_at"]) < datetime.now(timezone.utc):
        raise ConfirmationError("This confirmation has expired. Ask again to get a fresh preview.")
    payload = json.loads(pending["payload"])
    payload_hash = _payload_hash(pending["action"], payload)
    expected = _sign(preview_id, principal.user_id, payload_hash, pending["expires_at"])
    if payload_hash != pending["payload_hash"] or not hmac.compare_digest(expected, token or ""):
        raise ConfirmationError("Confirmation token does not match this action. Nothing was executed.")
    authorize(principal, pending["action"], payload)

    key = idempotency_key(pending["action"], payload)
    action_id = f"ACT-{uuid.uuid4().hex[:8].upper()}"
    try:
        get_db().execute(
            "INSERT INTO actions (id, idempotency_key, action, payload, created_by, confirmed_by, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (action_id, key, pending["action"], _canonical(payload), principal.user_id,
             json.dumps([principal.user_id]), datetime.now(timezone.utc).isoformat(timespec="seconds")),
        )
        created = True
    except sqlite3.IntegrityError:
        created = False
        row = get_db().query("SELECT * FROM actions WHERE idempotency_key = ?", (key,))[0]
        confirmers = json.loads(row["confirmed_by"])
        if principal.user_id not in confirmers:
            get_db().execute("UPDATE actions SET confirmed_by = ? WHERE id = ?",
                             (json.dumps(confirmers + [principal.user_id]), row["id"]))
    row = get_db().query("SELECT * FROM actions WHERE idempotency_key = ?", (key,))[0]
    return {"created": created, "action": _public(row)}


def list_actions(action: str | None = None) -> list[dict]:
    sql, params = "SELECT * FROM actions", ()
    if action:
        sql, params = sql + " WHERE action = ?", (action,)
    return [_public(r) for r in get_db().query(sql + " ORDER BY created_at DESC", params)]
