"""Tamper-proof confirmation and idempotency."""
import json

import pytest

from app import actions, tools
from app.access import AccessDenied
from app.db import get_db


def _propose(principal, **args):
    out = tools.run(principal, "propose_escalation", {"reason": "P1 outage, SLA breached", **args})
    return out["_ui"]


def _confirm(principal, ui):
    return actions.confirm(principal, ui["preview_id"], ui["token"], tools.authorize_action)


def test_preview_does_not_execute(users):
    out = tools.run(users["l2"], "propose_escalation", {"reason": "x", "ticket_id": "TKT-501"})
    assert out["confirmation_required"] and actions.list_actions() == []
    assert "token" not in out["preview"]  # the model never sees the token


def test_confirm_executes_once_and_double_confirm_is_idempotent(users):
    ui = _propose(users["l2"], ticket_id="TKT-501")
    first, second = _confirm(users["l2"], ui), _confirm(users["l2"], ui)
    assert first["created"] and not second["created"]
    assert first["action"]["id"] == second["action"]["id"] and len(actions.list_actions()) == 1


def test_two_staff_confirming_same_escalation_creates_one(users):
    a = _confirm(users["l2"], _propose(users["l2"], ticket_id="TKT-501"))
    b = _confirm(users["l2_other"], _propose(users["l2_other"], ticket_id="TKT-501"))
    assert a["action"]["id"] == b["action"]["id"] and len(actions.list_actions()) == 1
    assert set(b["action"]["confirmed_by"]) == {users["l2"].user_id, users["l2_other"].user_id}


def test_forged_token_is_rejected(users):
    ui = _propose(users["l2"], ticket_id="TKT-501")
    with pytest.raises(actions.ConfirmationError):
        actions.confirm(users["l2"], ui["preview_id"], "0" * 64, tools.authorize_action)
    assert actions.list_actions() == []


def test_payload_changed_after_preview_is_rejected(users):
    ui = _propose(users["l2"], ticket_id="TKT-501")
    tampered = {**ui["payload"], "ticket_id": "TKT-502"}
    get_db().execute("UPDATE pending_actions SET payload = ? WHERE preview_id = ?",
                     (json.dumps(tampered, sort_keys=True, separators=(",", ":")), ui["preview_id"]))
    with pytest.raises(actions.ConfirmationError):
        _confirm(users["l2"], ui)
    assert actions.list_actions() == []


def test_only_the_previewing_user_can_confirm(users):
    ui = _propose(users["l2"], ticket_id="TKT-501")
    with pytest.raises(AccessDenied):
        _confirm(users["northstar_admin"], ui)


def test_expired_confirmation_is_rejected(users):
    ui = _propose(users["l2"], ticket_id="TKT-501")
    get_db().execute("UPDATE pending_actions SET expires_at = '2000-01-01T00:00:00+00:00' WHERE preview_id = ?",
                     (ui["preview_id"],))
    with pytest.raises(actions.ConfirmationError):
        _confirm(users["l2"], ui)


def test_customer_can_escalate_own_ticket_only(users):
    ui = _propose(users["northstar_user"], ticket_id="TKT-501")
    assert _confirm(users["northstar_user"], ui)["created"]
    assert tools.run(users["lumen_user"], "propose_escalation", {"reason": "x", "ticket_id": "TKT-501"})["error"] == "access_denied"


def test_customer_preview_of_existing_escalation_hides_staff(users):
    _confirm(users["l2"], _propose(users["l2"], ticket_id="TKT-501"))
    existing = _propose(users["northstar_user"], ticket_id="TKT-501")["already_exists"]
    assert existing["id"] and "confirmed_by" not in existing and "created_by" not in existing


def test_customer_confirm_of_existing_escalation_hides_staff(users):
    staff = _confirm(users["l2"], _propose(users["l2"], ticket_id="TKT-501"))
    seen = tools.confirmation_view(users["northstar_user"], _confirm(users["northstar_user"], _propose(users["northstar_user"], ticket_id="TKT-501")))
    assert seen == {"created": False, "action": {k: staff["action"][k] for k in ("id", "action", "created_at")}}
    assert "l2" not in json.dumps(seen)


def test_task_from_same_alert_is_not_duplicated(users):
    def task(p):
        return tools.run(p, "propose_task", {"title": "Follow up", "alert_id": "ALR-1"})["_ui"]
    a, b = _confirm(users["ops"], task(users["ops"])), _confirm(users["l2"], task(users["l2"]))
    assert a["action"]["id"] == b["action"]["id"]
