"""Deterministic calculations, business hours and severity, run through the tools as an L2 agent."""
from datetime import datetime
from zoneinfo import ZoneInfo

from app import tools
from app.business_hours import add_business_minutes, business_minutes_between, parse_target

IST = ZoneInfo("Asia/Kolkata")


def test_business_hours_skip_weekend_and_nights():
    friday_5pm = datetime(2026, 8, 14, 17, 0, tzinfo=IST)
    assert add_business_minutes(friday_5pm, 120) == datetime(2026, 8, 17, 10, 0, tzinfo=IST)
    sunday = datetime(2026, 8, 16, 11, 0, tzinfo=IST)
    assert add_business_minutes(sunday, 240) == datetime(2026, 8, 17, 13, 0, tzinfo=IST)
    assert business_minutes_between(friday_5pm, datetime(2026, 8, 17, 10, 0, tzinfo=IST)) == 120


def test_target_parsing():
    assert parse_target("30 minutes, 24x7").business is False
    assert parse_target("4 business hours").minutes == 240 and parse_target("4 business hours").business
    assert parse_target("2 business days").minutes == 2 * 540
    assert parse_target("2 hours").business is False  # A-03: no 'business' means wall clock


def test_contract_waiver_beats_sop_fee_and_reports_conflict(users):
    out = tools.run(users["l2"], "calc_cancellation", {"order_id": "ORD-1001"})
    assert out["can_cancel"] is True and out["fee_inr"] == 0
    assert out["minutes_since_booking"] == 120
    conflict = next(c for c in out["conflicts"] if c["term"] == "cancellation fee")
    assert conflict["winner"]["source"]["doc_type"] == "contract"
    assert conflict["overridden"][0]["source"]["doc_type"] == "sop"
    assert out["warnings"], "pickup window had started, so BOOKED may be stale"


def test_sop_fee_applies_after_free_window_without_waiver(users):
    out = tools.run(users["l2"], "calc_cancellation", {"order_id": "ORD-2001"})
    assert out["fee_inr"] == 250 and out["minutes_since_booking"] == 75


def test_free_window_and_terminal_states(users):
    assert tools.run(users["l2"], "calc_cancellation", {"order_id": "ORD-3001"})["fee_inr"] == 0
    picked = tools.run(users["l2"], "calc_cancellation", {"order_id": "ORD-1002"})
    assert picked["can_cancel"] is False and "return-to-origin" in picked["rule"]
    assert tools.run(users["l2"], "calc_cancellation", {"order_id": "ORD-4001"})["can_cancel"] is False


def test_contract_credit_rule_replaces_default(users):
    out = tools.run(users["l2"], "calc_pickup_credit", {"order_id": "ORD-2002"})
    assert out["outcome"] == "eligible" and out["amount_inr"] == 300 and out["delay_minutes"] == 270
    assert any(c["term"] == "credit_delay_threshold_hours" for c in out["conflicts"])


def test_hypothetical_credit_uses_contract_threshold(users):
    lumen = tools.run(users["lumen_user"], "calc_pickup_credit", {"delay_hours": 3, "carrier_fault": True, "customer_fault": False})
    assert lumen["outcome"] == "not_eligible"
    north = tools.run(users["northstar_user"], "calc_pickup_credit", {"delay_hours": 3, "carrier_fault": True})
    assert north["outcome"] == "cannot_determine"  # customer fault unknown: SOP says do not promise
    north = tools.run(users["northstar_user"], "calc_pickup_credit",
                      {"delay_hours": 3, "carrier_fault": True, "customer_fault": False, "shipment_fee_inr": 4200})
    assert north["outcome"] == "eligible_if_verified" and north["amount_inr"] == 420


def test_default_credit_cap_and_approval(users):
    out = tools.run(users["l2"], "calc_pickup_credit",
                    {"account": "Beacon", "delay_hours": 5, "carrier_fault": True, "customer_fault": False, "shipment_fee_inr": 9000})
    assert out["amount_inr"] == 500 and out["manager_approval_required"] is False


def test_contract_sla_clock_24x7(users):
    out = tools.run(users["l2"], "calc_ticket_sla", {"ticket_id": "TKT-501"})
    assert out["severity"] == "P1" and out["target"] == "15 minutes, 24x7"
    assert out["sla_state"] == "breached" and out["minutes_until_due"] == -15


def test_business_hours_sla_on_weekend(users):
    out = tools.run(users["l2"], "calc_ticket_sla", {"ticket_id": "TKT-502"})
    assert out["severity"] == "P2" and out["target"] == "4 business hours"
    assert out["due_at"].startswith("2026-08-17T13:00") and out["sla_state"] == "open"


def test_sla_watchlist_lists_breaches_with_owner(users):
    out = tools.run(users["ops"], "sla_watchlist", {"within_hours": 4})
    assert [t["ticket_id"] for t in out["tickets"]] == ["TKT-505", "TKT-501"]
    assert all(t["assigned_to"] for t in out["tickets"])


def test_severity_comes_from_policy_definitions_and_fails_closed(monkeypatch):
    from app import classify
    from app.calculator import severity_of
    severity, basis = severity_of({"ticket_id": "TKT-505", "subject": "Possible API key exposure"})
    assert severity == "P1" and "suspected credential exposure" in basis  # the definition used is quoted
    assert severity_of({"ticket_id": "X", "severity": "p2"}) == ("P2", "from the ticket's severity field")
    monkeypatch.setattr(classify, "ticket_severity", lambda *a: {"severity": None, "quote": "", "reason": ""})
    severity, basis = severity_of({"ticket_id": "X-1", "subject": "Something odd"})
    assert severity == "P1" and basis.startswith("NEEDS REVIEW")  # undecided: strictest until a person looks


def test_two_workbooks_refuse_to_load(tmp_path):
    import pytest
    from app.data import find_workbook
    for name in ("Assessment_Data.xlsx", "ParcelPilot_Assessment_Data.xlsx"):
        (tmp_path / name).write_bytes(b"")
    with pytest.raises(RuntimeError, match="keep only one"):
        find_workbook(tmp_path)


def test_missed_pickups_at_two_accounts_raise_multi_customer_alert(monkeypatch):
    import copy
    from datetime import timedelta
    from app import detect
    from app.data import get_dataset
    dataset = copy.deepcopy(get_dataset())
    booked = {o["account_id"]: o for o in dataset.rows("orders") if o["status"] == "BOOKED"}
    for order in list(booked.values())[:2]:  # two accounts, same carrier, both missed
        order.update(carrier="TestCarrier", pickup_actual_at=None, pickup_window_end=dataset.snapshot - timedelta(hours=2))
    monkeypatch.setattr(detect, "get_dataset", lambda: dataset)
    alerts = [a for a in detect.order_alerts() if a["kind"] == "multi_customer"]
    assert len(alerts) == 1 and len(alerts[0]["accounts"]) == 2
