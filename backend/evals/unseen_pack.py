"""Builds an unseen data pack for evals/unseen_cases.json: the same six PDFs with a rewritten workbook.

Every order and ticket id gets a new prefix (ORD- -> SHP-, TKT- -> CASE-), support staff are renamed, all times
move three days (Sunday 16 Aug -> Wednesday 19 Aug, so business hours apply), and a new customer account plus new
orders and tickets are added. Company names stay as in the PDFs, as they would in an updated workbook.

    python -m evals.unseen_pack <out_dir>
then run the eval with DATA_DIR=<out_dir>.
"""
import json
import re
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.cell.cell import MergedCell

SOURCE = Path(__file__).resolve().parents[2] / "data"
SHIFT = timedelta(days=3)
STAFF = {"Rohit": "Ines Duarte", "Maya": "Tomas Berg"}

NEW_ACCOUNTS = [
    dict(account_id="ACCT-005", account_name="Nimbus Traders", plan="Growth", status="active", csm="Lena Ortiz",
         contract_file=None, premium_support=False, notes="Growth customer; no custom agreement."),
]
NEW_ORDERS = [
    # 50 minutes after booking, no agreement: the SOP fee applies
    dict(order_id="SHP-5001", account_id="ACCT-005", carrier="AeroPost", status="BOOKED",
         booked_at="2026-08-19 10:00", pickup_window_start="2026-08-19 13:00", pickup_window_end="2026-08-19 14:00",
         shipment_fee_inr=2600, carrier_fault=False, customer_fault=False,
         cancellation_requested_at="2026-08-19 10:50", notes="Customer asks to cancel."),
    dict(order_id="SHP-5002", account_id="ACCT-005", carrier="TrailCo", status="PICKED_UP",
         booked_at="2026-08-19 07:00", pickup_window_start="2026-08-19 08:00", pickup_window_end="2026-08-19 09:00",
         pickup_actual_at="2026-08-19 08:40", shipment_fee_inr=1500, carrier_fault=False, customer_fault=False,
         notes="Collected on time."),
    # pickup window ended 07:00, still not collected at 11:00, carrier at fault: 4 h late, 10% of 4,000 = 400
    dict(order_id="SHP-5003", account_id="ACCT-005", carrier="TrailCo", status="BOOKED",
         booked_at="2026-08-19 04:00", pickup_window_start="2026-08-19 06:00", pickup_window_end="2026-08-19 07:00",
         shipment_fee_inr=4000, carrier_fault=True, customer_fault=False,
         notes="Pickup missed; carrier confirmed its driver did not arrive."),
    # Beacon Retail (Standard, no agreement): 2.5 h late, carrier at fault, 10% of 9,000 = 900, capped at 500
    dict(order_id="SHP-5004", account_id="ACCT-003", carrier="RoadRunner", status="PICKED_UP",
         booked_at="2026-08-19 05:00", pickup_window_start="2026-08-19 07:00", pickup_window_end="2026-08-19 08:00",
         pickup_actual_at="2026-08-19 10:30", shipment_fee_inr=9000, carrier_fault=True, customer_fault=False,
         notes="Pickup 2.5 hours late; carrier accepted fault."),
    # Northstar: 3.5 h late but the customer caused it
    dict(order_id="SHP-1003", account_id="ACCT-001", carrier="SwiftShip", status="PICKED_UP",
         booked_at="2026-08-19 03:00", pickup_window_start="2026-08-19 05:00", pickup_window_end="2026-08-19 06:00",
         pickup_actual_at="2026-08-19 09:30", shipment_fee_inr=3800, carrier_fault=False, customer_fault=True,
         notes="Customer's loading bay was closed when the driver arrived."),
    # Northstar: cancel requested 2 h 45 min after booking, before pickup (agreement waives the fee)
    dict(order_id="SHP-1004", account_id="ACCT-001", carrier="BlueDart Pro", status="BOOKED",
         booked_at="2026-08-19 08:00", pickup_window_start="2026-08-19 12:00", pickup_window_end="2026-08-19 13:00",
         shipment_fee_inr=2900, carrier_fault=False, customer_fault=False,
         cancellation_requested_at="2026-08-19 10:45", notes="Customer asks to cancel before pickup."),
]

NEW_TICKETS = [
    dict(ticket_id="CASE-601", account_id="ACCT-005", created_at="2026-08-19 09:20", status="open",
         subject="Tracking page error for one end customer",
         description="One of our end customers sees an error on the tracking page for a single shipment. Tracking "
                     "works for all other shipments.", channel="email", assigned_to="Tomas Berg",
         last_customer_message_at="2026-08-19 09:20"),
    dict(ticket_id="CASE-602", account_id="ACCT-002", created_at="2026-08-19 09:30", status="open",
         subject="Cannot create any shipment: label printing fails",
         description="Since this morning every shipment we try to create fails at label generation, for all users. "
                     "We cannot ship anything and have no workaround.", channel="chat", assigned_to="Ines Duarte",
         last_customer_message_at="2026-08-19 09:35"),
    dict(ticket_id="CASE-603", account_id="ACCT-004", created_at="2026-08-19 10:00", status="open",
         subject="Webhook notifications delayed",
         description="Status webhooks are arriving 30-60 minutes late for all shipments. We can still see the "
                     "correct status in the dashboard, so operations continue.", channel="email",
         assigned_to="Tomas Berg", last_customer_message_at="2026-08-19 10:00"),
    dict(ticket_id="CASE-604", account_id="ACCT-003", created_at="2026-08-18 15:00", status="open",
         subject="API returns 503 for every request",
         description="All our API calls return HTTP 503 and we cannot create any shipments, in the app or by API.",
         channel="email", assigned_to="Tomas Berg", last_customer_message_at="2026-08-18 15:00"),
    dict(ticket_id="CASE-605", account_id="ACCT-001", created_at="2026-08-19 10:20", status="open",
         subject="Change delivery contact",
         description="Please update our delivery contact to Anita Desai, anita.desai@example.com, +91 98200 12345.",
         channel="email", assigned_to="Ines Duarte", last_customer_message_at="2026-08-19 10:20"),
    dict(ticket_id="CASE-452", account_id="ACCT-005", created_at="2026-08-12 12:00", status="closed",
         subject="Can we use Bulk Upload?", description="Nimbus Traders asked whether Bulk Upload is available.",
         channel="chat", assigned_to="Tomas Berg", last_customer_message_at="2026-08-12 12:30",
         historical_resolution="Agent told the customer that Growth plans cannot use Bulk Upload."),
]
NEW_USERS = [{"username": "nimbus.user", "name": "Nimbus Traders Shipping Desk", "role": "customer_user",
              "account_id": "ACCT-005"}]


def _rewrite(value):
    if not isinstance(value, str):
        return value
    stamp = re.fullmatch(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2})(.*)", value)
    if stamp:
        value = (datetime.fromisoformat(stamp.group(1)) + SHIFT).strftime("%Y-%m-%d %H:%M") + stamp.group(2)
    for old, new in STAFF.items():
        value = re.sub(rf"\b{old}\b", new, value)
    return value.replace("ORD-", "SHP-").replace("TKT-", "CASE-")


def _append(sheet, row: dict) -> None:
    header = [c.value for c in sheet[1]]
    sheet.append([row.get(h) for h in header])


def build(out: Path) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    for pdf in SOURCE.glob("*.pdf"):
        shutil.copy(pdf, out)
    users = json.loads((SOURCE / "users.json").read_text(encoding="utf-8")) + NEW_USERS
    (out / "users.json").write_text(json.dumps(users, indent=2), encoding="utf-8")
    book = load_workbook(next(SOURCE.glob("*.xlsx")))
    for sheet in book.worksheets:
        for row in sheet.iter_rows():
            for cell in row:
                if not isinstance(cell, MergedCell):
                    cell.value = _rewrite(cell.value)
    for sheet, rows in (("accounts", NEW_ACCOUNTS), ("orders", NEW_ORDERS), ("tickets", NEW_TICKETS)):
        for row in rows:
            _append(book[sheet], row)
    book.save(out / "Updated_Workbook.xlsx")
    return out


if __name__ == "__main__":
    print(build(Path(sys.argv[1])))
