"""Audit trail: every tool call, its input, output and access decision, plus agent decisions."""
import json
from datetime import datetime, timezone

from .access import Principal
from .db import get_db

MAX_STORED_CHARS = 8000


def _dump(value) -> str:
    text = json.dumps(value, default=str, ensure_ascii=False)
    return text if len(text) <= MAX_STORED_CHARS else text[:MAX_STORED_CHARS] + "...[truncated]"


def log(principal: Principal | None, event: str, name: str, input=None, output=None,
        decision: str = "", conversation_id: str | None = None) -> None:
    get_db().execute(
        "INSERT INTO audit (ts, user_id, role, conversation_id, event, name, input, output, decision)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
            principal.user_id if principal else None,
            principal.role if principal else None,
            conversation_id, event, name, _dump(input), _dump(output), decision,
        ),
    )


def lookup(conversation_id: str | None = None, user_id: str | None = None, name: str | None = None,
           decision: str | None = None, limit: int = 20) -> list[dict]:
    clauses, params = [], []
    for column, value in (("conversation_id", conversation_id), ("user_id", user_id),
                          ("name", name), ("decision", decision)):
        if value:
            clauses.append(f"{column} = ?")
            params.append(value)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return get_db().query(
        f"SELECT * FROM audit {where} ORDER BY id DESC LIMIT ?", (*params, max(1, min(limit, 200)))
    )
