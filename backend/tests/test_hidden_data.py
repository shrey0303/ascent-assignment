"""No hard-coding: the unchanged code runs on a rewritten workbook.

Every record id gets a new prefix, every company / carrier / staff name changes, all times move from a
Sunday to a Wednesday, and a brand-new account with a new order is added. The answers must follow the data.
"""
import re
import shutil
from datetime import datetime, timedelta

import pytest
from openpyxl import load_workbook
from openpyxl.cell.cell import MergedCell

from app import auth, config, detect, tools
from app.data import get_dataset
from app.docs import get_library
from tests.conftest import principal

ORIGINAL = config.DATA_DIR
SHIFT = timedelta(days=3)  # Sunday 16 Aug -> Wednesday 19 Aug: business-hours results must change
NEW_NAMES = {
    "Northstar Logistics": "Orion Freight", "LumenWorks": "Kestrel Labs", "Beacon Retail": "Harbor Goods",
    "Axis Labs": "Vega Systems", "SwiftShip": "AeroPost", "RoadRunner": "TrailCo", "BlueDart Pro": "MetroX",
    "Rohit": "Ines Duarte", "Maya": "Tomas Berg", "Priya Mehta": "Lena Ortiz", "Arjun Rao": "Omar Haddad",
    "Neha Kapoor": "Sara Lind",
}


def _rewrite(value):
    if not isinstance(value, str):
        return value
    stamp = re.fullmatch(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2})(.*)", value)
    if stamp:
        value = (datetime.fromisoformat(stamp.group(1)) + SHIFT).strftime("%Y-%m-%d %H:%M") + stamp.group(2)
    for old, new in NEW_NAMES.items():
        value = value.replace(old, new)
    return value.replace("ORD-", "SHP-").replace("TKT-", "CASE-")


def _append(sheet, **values):
    header = [c.value for c in sheet[1]]
    sheet.append([values.get(h) for h in header])


@pytest.fixture
def hidden_pack(tmp_path, monkeypatch):
    for pdf in ORIGINAL.glob("*.pdf"):
        shutil.copy(pdf, tmp_path)
    shutil.copy(ORIGINAL / "users.json", tmp_path)
    book = load_workbook(next(ORIGINAL.glob("*.xlsx")))
    for sheet in book.worksheets:
        for row in sheet.iter_rows():
            for cell in row:
                if not isinstance(cell, MergedCell):
                    cell.value = _rewrite(cell.value)
    _append(book["accounts"], account_id="ACCT-777", account_name="Nimbus Traders", plan="Growth",
            status="active", csm="Lena Ortiz", premium_support=0)
    _append(book["orders"], order_id="SHP-9001", account_id="ACCT-777", carrier="AeroPost", status="BOOKED",
            booked_at="2026-08-19 10:10", pickup_window_start="2026-08-19 12:00", pickup_window_end="2026-08-19 13:00",
            shipment_fee_inr=3000, carrier_fault=0, customer_fault=0, cancellation_requested_at="2026-08-19 10:55")
    book.save(tmp_path / "Renamed_Workbook.xlsx")

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    for cached in (get_dataset, get_library, auth.users):
        cached.cache_clear()
    yield
    for cached in (get_dataset, get_library, auth.users):
        cached.cache_clear()


L2 = principal("support_l2")


def test_snapshot_comes_from_the_new_readme(hidden_pack):
    now = get_dataset().snapshot
    assert (now.strftime("%A %Y-%m-%d %H:%M")) == "Wednesday 2026-08-19 11:00"


def test_old_ids_no_longer_exist(hidden_pack):
    assert tools.run(L2, "calc_cancellation", {"order_id": "ORD-1001"})["error"] == "invalid_request"
    assert tools.run(L2, "query_records", {"entity": "orders", "record_id": "ORD-1001"})["rows"] == []


def test_renamed_order_still_gets_contract_waiver(hidden_pack):
    out = tools.run(L2, "calc_cancellation", {"order_id": "SHP-1001"})
    assert out["fee_inr"] == 0 and out["minutes_since_booking"] == 120
    assert any(c["term"] == "cancellation fee" for c in out["conflicts"])


def test_brand_new_account_uses_sop_and_plan_policy(hidden_pack):
    fee = tools.run(L2, "calc_cancellation", {"order_id": "SHP-9001"})
    assert fee["fee_inr"] == 250 and fee["minutes_since_booking"] == 45
    terms = tools.run(L2, "get_account_terms", {"account": "Nimbus"})
    assert terms["account_id"] == "ACCT-777" and terms["plan"] == "Growth"
    assert terms["terms"]["response_target.P1"]["value"] == "2 business hours"
    assert terms["terms"]["response_target.P1"]["source"]["doc_type"] == "policy"


def test_weekday_snapshot_changes_business_hours_sla(hidden_pack):
    out = tools.run(L2, "calc_ticket_sla", {"ticket_id": "CASE-502"})
    assert out["due_at"].startswith("2026-08-19T13:45") and out["minutes_until_due"] == 165
    watch = tools.run(principal("ops_manager"), "sla_watchlist", {"within_hours": 4})
    assert [t["ticket_id"] for t in watch["tickets"]] == ["CASE-505", "CASE-501", "CASE-502"]


def test_new_names_are_masked_and_isolated(hidden_pack):
    customer = principal("customer_user", "ACCT-001")
    row = tools.run(customer, "query_records", {"entity": "accounts"})["rows"][0]
    assert row["account_name"] == "Orion Freight" and row["csm"] == "[masked]"
    assert tools.run(L2, "query_records", {"entity": "accounts", "record_id": "ACCT-001"})["rows"][0]["csm"] == "Lena Ortiz"
    other = principal("customer_user", "ACCT-002")
    assert tools.run(other, "query_records", {"entity": "orders", "account": "Orion"})["error"] == "access_denied"


def test_dashboard_alerts_follow_new_data(hidden_pack):
    alerts = detect.all_alerts(principal("ops_manager"))
    evidence = {e for a in alerts for e in a["evidence"]}
    assert {"SHP-2002", "CASE-502", "CASE-451"} <= evidence
    leftovers = [m.group(0) + " in: " + str(a)[max(0, m.start() - 120): m.end() + 40] for a in alerts
                 for m in re.finditer(r"\b(ORD-|TKT-|Northstar|LumenWorks|SwiftShip|RoadRunner)", str(a))]
    assert leftovers == []  # \b skips the unchanged PDF file names such as 05_Northstar_..., which are real citations
