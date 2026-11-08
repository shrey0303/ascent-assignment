"""Security tests that call the tools directly with forged arguments, as a jailbroken model would."""
import json

from app import tools
from app.access import Principal, scrub_text


def test_customer_cannot_read_other_account_by_name(users):
    out = tools.run(users["lumen_user"], "query_records", {"entity": "orders", "account": "Northstar", "latest": True})
    assert out["error"] == "access_denied"


def test_customer_cannot_read_other_account_by_record_id(users):
    for tool, args in [("query_records", {"entity": "orders", "record_id": "ORD-1001"}),
                       ("calc_cancellation", {"order_id": "ORD-1001"}),
                       ("calc_pickup_credit", {"order_id": "ORD-1001"}),
                       ("calc_ticket_sla", {"ticket_id": "TKT-501"}),
                       ("get_account_terms", {"account": "ACCT-001"}),
                       ("propose_escalation", {"reason": "x", "ticket_id": "TKT-501"})]:
        assert tools.run(users["lumen_user"], tool, args)["error"] == "access_denied", tool


def test_customer_listing_only_returns_own_rows(users):
    for entity in ("orders", "tickets", "accounts"):
        rows = tools.run(users["lumen_user"], "query_records", {"entity": entity, "limit": 25})["rows"]
        assert rows and {r["account_id"] for r in rows} == {"ACCT-002"}


def test_customer_search_never_returns_other_contracts(users):
    out = tools.run(users["lumen_user"], "search_documents", {"query": "Northstar cancellation fee contract", "top_k": 8})
    assert all(r["account_id"] in (None, "ACCT-002") for r in out["results"])


def test_customer_cannot_use_internal_tools(users):
    for tool in ("sla_watchlist", "audit_lookup", "propose_task"):
        assert tools.run(users["northstar_admin"], tool, {"title": "x"} if tool == "propose_task" else {})["error"] == "access_denied"


def test_forged_role_in_arguments_is_ignored(users):
    out = tools.run(users["lumen_user"], "query_records", {"entity": "orders", "account": "ACCT-001", "role": "ops_manager"})
    assert out["error"] in ("access_denied", "invalid_request")


def test_l1_cannot_see_contract_commercial_terms(users):
    terms = tools.run(users["l1"], "get_account_terms", {"account": "Northstar"})
    # removed by name too: a term name such as "cancellation_fee_waived" would itself reveal the term
    assert "cancellation_fee_waived" not in terms["terms"] and "credit_monthly_cap_inr" not in terms["terms"]
    assert terms["restricted"] is True and '"commercial": true' not in json.dumps(terms, default=str)
    assert terms["terms"]["response_target.P1"]["value"] == "15 minutes, 24x7"  # support terms stay visible
    search = tools.run(users["l1"], "search_documents", {"query": "Northstar shipment cancellation fee", "top_k": 8})
    contract = [r for r in search["results"] if r["doc_type"] == "contract" and "cancellation" in r["source_id"].lower()]
    assert contract and all(r["text"].startswith("[restricted") for r in contract)


def test_l1_calculation_that_needs_commercial_terms_is_restricted(users):
    out = tools.run(users["l1"], "calc_cancellation", {"order_id": "ORD-1001"})
    assert out["restricted"] is True and "fee_inr" not in out


def test_l2_sees_commercial_terms(users):
    terms = tools.run(users["l2"], "get_account_terms", {"account": "Northstar"})
    assert terms["terms"]["cancellation_fee_waived"]["value"] is True


def test_pii_masking_by_role(users):
    masked = tools.run(users["northstar_user"], "query_records", {"entity": "accounts"})["rows"][0]
    visible = tools.run(users["northstar_admin"], "query_records", {"entity": "accounts"})["rows"][0]
    assert masked["csm"] == "[masked]" and visible["csm"] != "[masked]"
    assert "notes" not in masked  # internal account notes never go to customers
    staff = tools.run(users["l2"], "query_records", {"entity": "tickets", "record_id": "TKT-501"})["rows"][0]
    assert staff["assigned_to"] != "[masked]"


def test_free_text_scrubbing():
    p = Principal("u", "u", "support_l1", None)
    text = "Call +91 98765 43210 or mail ravi.k@example.com"
    assert "98765" not in scrub_text(p, text, set()) and "example.com" not in scrub_text(p, text, set())


def test_audit_payloads_hidden_from_l1(users):
    tools.run(users["l2"], "get_account_terms", {"account": "Northstar"})
    entries = tools.run(users["l1"], "audit_lookup", {})["entries"]
    assert entries and all(e["output"] == "[hidden for your role]" for e in entries)


def test_every_tool_call_is_audited(users):
    tools.run(users["lumen_user"], "query_records", {"entity": "orders", "account": "Northstar"})
    entry = tools.run(users["ops"], "audit_lookup", {"decision": "denied"})["entries"][0]
    assert entry["user_id"] == users["lumen_user"].user_id and entry["name"] == "query_records"


def test_ids_with_unicode_hyphens_are_found(users):
    """Models often write ids with a non-breaking hyphen (U+2011); the lookup must still find the record, and
    access checks still apply to it."""
    from app.data import get_dataset
    ticket = get_dataset().rows("tickets")[0]["ticket_id"]
    odd = ticket.replace("-", "\u2011")
    assert odd != ticket
    out = tools.run(users["l2"], "calc_ticket_sla", {"ticket_id": odd})
    assert out.get("ticket_id") == ticket
    rows = tools.run(users["l2"], "query_records", {"entity": "tickets", "record_id": odd})["rows"]
    assert [r["ticket_id"] for r in rows] == [ticket]
