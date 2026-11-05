"""HTTP-level isolation tests: what a malicious client can try against the API."""
import json

import pytest
from fastapi.testclient import TestClient

from app import config, llm
from app.main import app


@pytest.fixture
def client(monkeypatch):
    # Scripted model: always answers without tools, echoing nothing from other users.
    monkeypatch.setattr(llm, "chat", lambda messages, tools=None, json_mode=False: llm.LLMResult(
        {"content": f"I saw {sum(m['role'] == 'user' for m in messages)} user message(s).\nConfidence: low"},
        "fake", 1, 1, 0.0, 1))
    with TestClient(app) as test_client:
        yield test_client


def _login(client, username):
    response = client.post("/api/login", json={"username": username, "password": config.DEMO_PASSWORD})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['token']}"}


def _chat(client, headers, message, conversation_id=None):
    response = client.post("/api/chat", json={"message": message, "conversation_id": conversation_id}, headers=headers)
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
    return events[-1]


def test_client_cannot_read_or_join_another_clients_chat(client):
    northstar, lumen = _login(client, "northstar.user"), _login(client, "lumenworks.user")
    first = _chat(client, northstar, "Secret question about ORD-1001")
    _chat(client, northstar, "Follow-up", first["conversation_id"])

    hijack = _chat(client, lumen, "What did we discuss?", first["conversation_id"])
    assert hijack["conversation_id"] != first["conversation_id"]
    assert hijack["text"] == "I saw 1 user message(s)."  # none of Northstar's history reached the model

    own = _chat(client, northstar, "Again", first["conversation_id"])
    assert own["conversation_id"] == first["conversation_id"] and own["text"] == "I saw 3 user message(s)."


def test_bad_or_tampered_tokens_are_rejected(client):
    assert client.post("/api/login", json={"username": "ops.manager", "password": "wrong"}).status_code == 401
    token = _login(client, "lumenworks.user")["Authorization"].split()[1]
    body, signature = token.split(".")
    forged = body[:-2] + ("AA" if body[-2:] != "AA" else "BB")
    assert client.get("/api/me", headers={"Authorization": f"Bearer {forged}.{signature}"}).status_code == 401
    assert client.get("/api/me").status_code == 401


def test_customers_cannot_reach_internal_endpoints(client):
    headers = _login(client, "northstar.admin")
    for path in ("/api/audit", "/api/actions", "/api/usage", "/api/dashboard/alerts"):
        assert client.get(path, headers=headers).status_code == 403, path
    assert client.post("/api/dashboard/alerts/ALR-x/task", headers=headers).status_code == 403


def test_dashboard_is_ops_manager_only(client):
    assert client.get("/api/dashboard/alerts", headers=_login(client, "l2.agent")).status_code == 403
    assert client.get("/api/dashboard/alerts", headers=_login(client, "ops.manager")).status_code == 200


def test_logins_are_audited(client):
    client.post("/api/login", json={"username": "ops.manager", "password": "wrong"})
    entries = client.get("/api/audit?decision=denied", headers=_login(client, "ops.manager")).json()["entries"]
    assert any(e["event"] == "login" and e["name"] == "ops.manager" for e in entries)


def test_action_free_text_is_hidden_from_l1(client):
    from app import actions, tools
    from app.access import Principal
    from app.data import get_dataset
    l2 = Principal(user_id="l2.agent", name="L2", role="support_l2", account_id=None)
    order_id = get_dataset().rows("orders")[0]["order_id"]
    preview = tools.run(l2, "propose_escalation", {"reason": "Customer phone +91 98765 43210", "order_id": order_id})["_ui"]
    actions.confirm(l2, preview["preview_id"], preview["token"], tools.authorize_action)

    l1_rows = client.get("/api/actions", headers=_login(client, "l1.agent")).json()
    l2_rows = client.get("/api/actions", headers=_login(client, "l2.agent")).json()
    assert l1_rows[0]["payload"]["reason"] == "[hidden for your role]"
    assert l1_rows[0]["payload"]["order_id"] == order_id  # ids stay visible for triage
    assert "98765" in l2_rows[0]["payload"]["reason"]
    assert client.get("/api/actions", headers=_login(client, "northstar.admin")).status_code == 403
