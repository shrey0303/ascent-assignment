"""Deterministic calculations: cancellation fee, failed-pickup credit, ticket SLA, severity.

The model never does arithmetic; it calls these through tools. Numbers come from resolved terms
(terms.resolve: contract > policy > SOP), facts from the workbook, and "now" from the README snapshot.
The order-state rules (DRAFT / BOOKED / PICKED_UP / DELIVERED) follow the SOP's cancellation rules (A-08).
"""
from datetime import datetime

from . import classify, config
from .business_hours import CALENDAR_TEXT, business_minutes_between, due_at, parse_target
from .docs import get_library

CLOSED_STATUSES = {"closed", "resolved", "solved"}
CANCEL_KEYS = ("cancellation_free_window_minutes", "cancellation_fee_inr", "cancellation_fee_waived")
CREDIT_KEYS = ("credit_delay_threshold_hours", "credit_fixed_inr", "credit_percent_of_fee", "credit_max_inr",
               "credit_approval_above_inr", "credit_monthly_cap_inr")
SOP_NO_PROMISE = "SOP: do not promise a credit when carrier fault, pickup timing or customer fault is unknown."
CREDIT_RULE = ("A credit is due only when the delay is over the threshold, the carrier is at fault and the customer is "
               "NOT at fault. If the customer caused the delay, no credit is due.")


def _value(terms: dict, key: str):
    return terms["terms"].get(key, {}).get("value")


def _sources(terms: dict, keys) -> list[dict]:
    return [terms["terms"][k]["source"] for k in keys if k in terms["terms"]]


def _conflicts(terms: dict, keys) -> list[dict]:
    return [c for c in terms["conflicts"] if c["term"] in keys]


def _iso(value):
    return value.isoformat(timespec="minutes") if isinstance(value, datetime) else value


def _minutes(a: datetime, b: datetime) -> int:
    return int((b - a).total_seconds() // 60)


def _flag(value) -> bool | None:
    return None if value is None else bool(value)


def _policies() -> list:
    return [d for d in get_library().documents.values() if d.usable and d.doc_type == "policy"]


def severity_scale() -> list[str]:
    """Severity codes defined by the current support policy, strictest first (read from the PDF, not fixed)."""
    return classify.severity_codes("\n".join(d.text for d in _policies()))


def high_severities() -> list[str]:
    """'High severity' = the two strictest levels of the current policy (A-06; P1 and P2 in the data pack)."""
    return severity_scale()[:2]


def severity_of(ticket: dict) -> tuple[str | None, str]:
    """Ticket severity and how it was decided (A-06). An explicit severity/priority column wins. Otherwise the
    classifier applies the current support policy's severity definitions, quoting the one it used. If its runs
    do not agree, the ticket is handled as the strictest code they chose (or the strictest code of all) and
    marked NEEDS REVIEW, so a person decides the close calls."""
    policies = _policies()
    policy_text = "\n\n".join(f"{d.title}\n{d.text}" for d in policies)
    codes = classify.severity_codes(policy_text)
    if not codes:
        return None, "NEEDS REVIEW: no current support policy defines severity levels"
    for column in ("severity", "priority"):
        value = str(ticket.get(column) or "").strip().upper()
        if value in codes:
            return value, f"from the ticket's {column} field"
    text = f"{ticket.get('subject') or ''}\n{ticket.get('description') or ''}"
    score = classify.injection_score(text)
    if score is not None and score >= config.INJECTION_THRESHOLD:  # text that gives orders could steer the label
        return codes[0], (f"NEEDS REVIEW: the ticket text contains instructions, so its severity is not decided "
                          f"automatically; handled as {codes[0]} (the strictest) until a person reviews it")
    label = classify.ticket_severity(ticket, policy_text)
    if label["severity"]:
        source = " / ".join(d.title for d in policies)
        return label["severity"], f"{source} definition: \"{label['quote']}\". {label['reason']}".strip()
    voted = [c for c in codes if c in (label.get("tally") or {})]
    if voted:
        split = ", ".join(f"{c} x{label['tally'][c]}" for c in voted)
        return voted[0], (f"NEEDS REVIEW: the classifier runs did not agree ({split}), so it is handled as "
                          f"{voted[0]}, the stricter reading, until a person reviews it")
    return codes[0], (f"NEEDS REVIEW: the severity could not be decided from the support policy definitions, "
                      f"so it is handled as {codes[0]} (the strictest) until a person reviews it")


def cancellation(order: dict, terms: dict, now: datetime) -> dict:
    status = str(order.get("status") or "").upper()
    at = order.get("cancellation_requested_at") or now
    out = {
        "order_id": order.get("order_id"), "status": status, "evaluated_at": _iso(at),
        "evaluated_at_basis": "cancellation_requested_at" if order.get("cancellation_requested_at")
        else "snapshot time (no cancellation request recorded)",
        "warnings": [],
    }
    if status == "DRAFT":
        return {**out, "can_cancel": True, "fee_inr": 0, "rule": "DRAFT orders can be cancelled with no fee."}
    if status == "PICKED_UP":
        return {**out, "can_cancel": False, "fee_inr": None,
                "rule": "Picked-up shipments cannot be cancelled. Use the return-to-origin workflow instead."}
    if status == "DELIVERED":
        return {**out, "can_cancel": False, "fee_inr": None, "rule": "Delivered shipments cannot be cancelled."}
    if status != "BOOKED":
        return {**out, "can_cancel": None, "fee_inr": None, "rule": f"Unknown order status {status!r}; verify first."}

    minutes = _minutes(order["booked_at"], at) if order.get("booked_at") else None
    window, fee, waived = (_value(terms, k) for k in CANCEL_KEYS)
    out.update(minutes_since_booking=minutes, sources=_sources(terms, CANCEL_KEYS),
               conflicts=_conflicts(terms, CANCEL_KEYS))
    start = order.get("pickup_window_start")
    if start and at >= start and not order.get("pickup_actual_at"):
        out["warnings"].append(
            "The pickup window had started. BOOKED only means no pickup confirmation was received; the parcel "
            "may already be collected. Verify the carrier status before cancelling.")

    if waived is True:
        out.update(can_cancel=True, fee_inr=0,
                   rule="The customer agreement waives the cancellation fee for BOOKED shipments before pickup, "
                        "regardless of time since booking.")
        if fee is not None and window is not None and minutes is not None and minutes > window:
            out["conflicts"] = out["conflicts"] + [{
                "term": "cancellation fee",
                "winner": terms["terms"]["cancellation_fee_waived"],
                "overridden": [terms["terms"]["cancellation_fee_inr"]],
                "reason": f"The default rule would charge INR {fee:g} ({minutes} min after booking > {window:g} min "
                          f"free window), but the customer contract outranks the SOP. "
                          f"Precedence: {' > '.join(config.SOURCE_PRECEDENCE)}.",
            }]
        return out
    if window is None or fee is None or minutes is None:
        return {**out, "can_cancel": True, "fee_inr": None,
                "rule": "The cancellation fee terms could not be determined from the sources. Do not quote a fee."}
    if minutes <= window:
        return {**out, "can_cancel": True, "fee_inr": 0,
                "rule": f"Requested {minutes} min after booking, within the {window:g}-minute free window."}
    return {**out, "can_cancel": True, "fee_inr": fee,
            "rule": f"Requested {minutes} min after booking, after the {window:g}-minute free window, "
                    f"so the INR {fee:g} fee applies (no waiver in the customer agreement)."}


def pickup_credit(terms: dict, now: datetime, order: dict | None = None, delay_minutes: int | None = None,
                  carrier_fault: bool | None = None, customer_fault: bool | None = None,
                  shipment_fee_inr: float | None = None) -> dict:
    """Failed-pickup credit. Facts from an order win; stated facts fill only what the data lacks."""
    verified = True
    basis = "stated in the question (not verified against order data)"
    if order:
        end, actual = order.get("pickup_window_end"), order.get("pickup_actual_at")
        if end:
            delay_minutes = _minutes(end, actual or now)
            basis = "pickup_actual_at" if actual else "not picked up yet; delay counted up to the snapshot time"
        data_carrier, data_customer = _flag(order.get("carrier_fault")), _flag(order.get("customer_fault"))
        verified = data_carrier is not None and data_customer is not None
        carrier_fault = data_carrier if data_carrier is not None else carrier_fault
        customer_fault = data_customer if data_customer is not None else customer_fault
        shipment_fee_inr = order.get("shipment_fee_inr") or shipment_fee_inr
    else:
        verified = False

    threshold = _value(terms, "credit_delay_threshold_hours")
    out = {
        "order_id": (order or {}).get("order_id"), "delay_minutes": delay_minutes, "delay_basis": basis,
        "carrier_fault": carrier_fault, "customer_fault": customer_fault, "facts_verified": verified,
        "threshold_hours": threshold, "sources": _sources(terms, CREDIT_KEYS), "conflicts": _conflicts(terms, CREDIT_KEYS),
        "notes": [],
    }
    missing = [name for name, v in (("pickup delay", delay_minutes), ("carrier fault", carrier_fault),
                                    ("customer fault", customer_fault), ("delay threshold term", threshold)) if v is None]
    if threshold is not None and delay_minutes is not None and delay_minutes <= threshold * 60:
        return {**out, "outcome": "not_eligible", "amount_inr": 0,
                "reason": f"Pickup delay of {delay_minutes} min is not more than the {threshold:g}-hour threshold."}
    if carrier_fault is False:
        return {**out, "outcome": "not_eligible", "amount_inr": 0, "reason": "The carrier is not at fault."}
    if customer_fault is True:
        return {**out, "outcome": "not_eligible", "amount_inr": 0, "reason": "There is a customer-caused issue."}

    fixed, percent, cap = (_value(terms, k) for k in ("credit_fixed_inr", "credit_percent_of_fee", "credit_max_inr"))
    if fixed is not None:
        amount, formula = fixed, f"fixed INR {fixed:g}"
    elif percent is not None and shipment_fee_inr is not None:
        raw = shipment_fee_inr * percent / 100
        amount = min(raw, cap) if cap is not None else raw
        formula = f"{percent:g}% of INR {shipment_fee_inr:g} = INR {raw:g}" + (f", capped at INR {cap:g}" if cap is not None else "")
    elif percent is not None and cap is not None:
        amount, formula = None, f"lower of INR {cap:g} or {percent:g}% of the shipment fee (fee unknown), so at most INR {cap:g}"
    else:
        amount, formula = None, "credit amount terms not found"
    approval_above = _value(terms, "credit_approval_above_inr")
    out.update(amount_inr=amount, formula=formula,
               manager_approval_required=bool(amount is not None and approval_above is not None and amount > approval_above))
    monthly_cap = _value(terms, "credit_monthly_cap_inr")
    if monthly_cap is not None:
        out["notes"].append(f"Monthly aggregate credit cap of INR {monthly_cap:g} applies. Credits already issued this "
                            "month are not in the data; check the credit ledger before issuing (A-09).")

    if missing:
        return {**out, "outcome": "cannot_determine", "reason": f"Unknown: {', '.join(missing)}. {SOP_NO_PROMISE}",
                "verdict": f"NOT CONFIRMED. Do not tell the user they are eligible. First confirm: {', '.join(missing)}.",
                "rule": CREDIT_RULE}
    if not verified:
        return {**out, "outcome": "eligible_if_verified",
                "reason": f"Eligible only if the stated facts are confirmed. {SOP_NO_PROMISE}",
                "verdict": "POSSIBLY ELIGIBLE, only once the order data confirms the facts. Do not promise a credit."}
    return {**out, "outcome": "eligible",
            "reason": f"Delay of {delay_minutes} min exceeds the {threshold:g}-hour threshold, carrier at fault, "
                      "no customer-caused issue."}


def ticket_sla(ticket: dict, terms: dict, now: datetime) -> dict:
    severity, severity_basis = severity_of(ticket)
    key = f"response_target.{severity}"
    target_text = _value(terms, key)
    target = parse_target(target_text)
    out = {
        "ticket_id": ticket.get("ticket_id"), "account_id": ticket.get("account_id"), "status": ticket.get("status"),
        "subject": ticket.get("subject"), "assigned_to": ticket.get("assigned_to"),
        "severity": severity, "severity_basis": severity_basis, "created_at": _iso(ticket.get("created_at")),
        "sources": _sources(terms, [key]), "conflicts": _conflicts(terms, [key]),
    }
    if target is None or not ticket.get("created_at"):
        return {**out, "sla_state": "unknown", "note": "No first-response target found for this account and severity."}
    due = due_at(ticket["created_at"], target)
    out.update(target=target_text, clock=CALENDAR_TEXT if target.business else "wall clock (24x7)", due_at=_iso(due))
    responded = ticket.get("first_response_at")
    if str(ticket.get("status") or "").lower() in CLOSED_STATUSES:
        return {**out, "sla_state": "closed"}
    if responded:
        return {**out, "sla_state": "responded_on_time" if responded <= due else "responded_late"}
    remaining = _minutes(now, due)
    out.update(sla_state="breached" if remaining < 0 else "open", minutes_until_due=remaining,
               note="No first-response time in the data, so the ticket is treated as not yet answered (A-07).")
    if target.business:
        out["business_minutes_until_due"] = business_minutes_between(now, due)
    return out
