"""Shared test setup: a throwaway database per test and a fixed set of extracted terms.

TERMS is what a correct LLM extraction of the data pack looks like. test_terms.py checks every quote
against the real PDFs with the same verifier the app uses, so these fixtures cannot drift from the documents.
"""
import re

import pytest

from app import classify, config, db, terms
from app.access import Principal


def _t(field, value, quote, severity=None, plan=None):
    return {"field": field, "value": value, "severity": severity, "plan": plan, "quote": quote}


_ENT = "Enterprise | 30 minutes, 24x7 | 2 hours | 1 business day"
_GRO = "Growth | 2 business hours | 4 business hours | 2 business days"
_STD = "Standard | 4 business hours | 1 business day | 2 business days"

TERMS = {
    "01_Support_Policy_v3_CURRENT": [
        _t("response_target", "30 minutes, 24x7", _ENT, "P1", "Enterprise"),
        _t("response_target", "2 hours", _ENT, "P2", "Enterprise"),
        _t("response_target", "1 business day", _ENT, "P3", "Enterprise"),
        _t("response_target", "2 business hours", _GRO, "P1", "Growth"),
        _t("response_target", "4 business hours", _GRO, "P2", "Growth"),
        _t("response_target", "2 business days", _GRO, "P3", "Growth"),
        _t("response_target", "4 business hours", _STD, "P1", "Standard"),
        _t("response_target", "1 business day", _STD, "P2", "Standard"),
        _t("response_target", "2 business days", _STD, "P3", "Standard"),
    ],
    "03_Cancellation_and_Service_Credit_SOP_v4": [
        _t("cancellation_free_window_minutes", 30, "No fee within 30 minutes of booking."),
        _t("cancellation_fee_inr", 250, "After 30 minutes, charge INR 250 unless a customer agreement explicitly waives the cancellation fee."),
        _t("credit_delay_threshold_hours", 2, "a customer is eligible for a service credit when the pickup is more than 2 hours past the end of the scheduled pickup window"),
        _t("credit_percent_of_fee", 10, "The default credit is the lower of INR 500 or 10% of the shipment fee."),
        _t("credit_max_inr", 500, "The default credit is the lower of INR 500 or 10% of the shipment fee."),
        _t("credit_approval_above_inr", 1000, "Any individual credit above INR 1,000 requires manager approval."),
    ],
    "05_Northstar_Logistics_Enterprise_Agreement": [
        _t("response_target", "15 minutes, 24x7", "P1: 15 minutes, 24x7", "P1"),
        _t("response_target", "1 hour", "P2: 1 hour", "P2"),
        _t("response_target", "8 business hours", "P3: 8 business hours", "P3"),
        _t("cancellation_fee_waived", True, "Northstar may cancel any BOOKED shipment before pickup with no cancellation fee, regardless of how long ago the shipment was booked."),
        _t("credit_monthly_cap_inr", 5000, "Monthly aggregate service credits are capped at INR 5,000."),
    ],
    "06_LumenWorks_Service_Agreement": [
        _t("response_target", "2 business hours", "P1: 2 business hours", "P1"),
        _t("response_target", "4 business hours", "P2: 4 business hours", "P2"),
        _t("response_target", "2 business days", "P3: 2 business days", "P3"),
        _t("cancellation_fee_waived", False, "No special cancellation-fee waiver applies."),
        _t("credit_delay_threshold_hours", 4, "If a pickup is more than 4 hours past the end of the scheduled pickup window"),
        _t("credit_fixed_inr", 300, "LumenWorks receives a fixed INR 300 service credit."),
    ],
}


# What a correct classifier run gives for the data pack (checked against the PDFs in test_classify.py).
# doc_id: (doc_type, doc_type_quote, in_force, in_force_quote, {commercial section heading: quote})
DOC_LABELS = {
    "01_Support_Policy_v3_CURRENT": ("policy", "ParcelPilot Support Policy v3", True, "Status: CURRENT", {}),
    "02_Support_Policy_v2_DEPRECATED": ("policy", "ParcelPilot Support Policy v2", False,
                                       "DEPRECATED - DO NOT USE FOR CURRENT REQUESTS", {}),
    "03_Cancellation_and_Service_Credit_SOP_v4": ("sop", "Cancellation & Service Credit SOP v4", True, "Status: CURRENT", {}),
    "04_Product_Operations_Guide_and_Known_Issues": ("product_guide", "ParcelPilot Product Operations Guide", True,
                                                     "Status: CURRENT", {}),
    "05_Northstar_Logistics_Enterprise_Agreement": ("contract", "Northstar Logistics Enterprise Agreement", True,
                                                    "Status: ACTIVE", {
        "2. Shipment cancellation": "with no cancellation fee",
        "3. Service credits": "Monthly aggregate service credits are capped at INR 5,000."}),
    "06_LumenWorks_Service_Agreement": ("contract", "LumenWorks Service Agreement", True, "Status: ACTIVE", {
        "2. Cancellation terms": "No special cancellation-fee waiver applies.",
        "3. Failed-pickup credits": "LumenWorks receives a fixed INR 300 service credit."}),
}
# ticket number (ids may be renamed by test_hidden_data) -> (severity, policy definition quote)
SEVERITY_LABELS = {
    "501": ("P1", "Complete production outage preventing all shipment creation for a customer"),
    "502": ("P2", "but core operations remain possible or a workaround exists"),
    "503": ("P3", "how-to question, configuration request"),
    "504": ("P3", "issue with limited operational impact"),
    "505": ("P1", "suspected credential exposure"),
    "450": ("P3", "how-to question, configuration request"),
    "451": ("P2", "Major feature unavailable or materially"),
}


# doc_id: metadata values exactly as the document writes them (None = not stated)
DOC_META = {
    "01_Support_Policy_v3_CURRENT": {"version": "v3", "effective": "1 May 2026"},
    "02_Support_Policy_v2_DEPRECATED": {"version": "v2", "effective": "1 January 2025"},
    "03_Cancellation_and_Service_Credit_SOP_v4": {"version": "v4", "effective": "15 June 2026"},
    "04_Product_Operations_Guide_and_Known_Issues": {"effective": "14 August 2026"},
    "05_Northstar_Logistics_Enterprise_Agreement": {"account_id": "ACCT-001", "term_start": "1 January 2026",
                                                    "term_end": "31 December 2026"},
    "06_LumenWorks_Service_Agreement": {"account_id": "ACCT-002", "term_start": "1 March 2026",
                                        "term_end": "28 February 2027"},
}


def undecided_labels(sections):
    """What a classifier whose runs agree on nothing returns."""
    return {"doc_type": None, "doc_type_quote": "", "in_force": None, "in_force_quote": "",
            "meta": dict.fromkeys(classify.META_FIELDS), "commercial": [True] * len(sections),
            "commercial_quotes": [""] * len(sections), "undecided": ["doc_type", "in_force", *classify.META_FIELDS]}


def fake_document_labels(doc_id, title, text, sections):
    if doc_id not in DOC_LABELS:
        return undecided_labels(sections)
    doc_type, type_quote, in_force, force_quote, commercial = DOC_LABELS[doc_id]
    return {"doc_type": doc_type, "doc_type_quote": type_quote, "in_force": in_force, "in_force_quote": force_quote,
            "meta": {name: DOC_META[doc_id].get(name) for name in classify.META_FIELDS},
            "commercial": [heading in commercial for heading, _ in sections],
            "commercial_quotes": [commercial.get(heading, "") for heading, _ in sections], "undecided": []}


def fake_ticket_severity(ticket, policy_text):
    number = re.sub(r"\D", "", str(ticket.get("ticket_id")))
    severity, quote = SEVERITY_LABELS.get(number, (None, ""))
    return {"severity": severity, "quote": quote, "reason": "", "tally": {severity: 5} if severity else {}}


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    """Throwaway database, fixed terms and labels, and no network: the per-turn checks default to 'the user
    asked for nothing', 'no injection' and 'every sentence is backed'. Tests that need other answers set them
    (intent, planted fixtures, or answer_support directly)."""
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    db.get_db.cache_clear()
    monkeypatch.setattr(terms, "get_terms", lambda: TERMS)
    monkeypatch.setattr(classify, "document_labels", fake_document_labels)
    monkeypatch.setattr(classify, "ticket_severity", fake_ticket_severity)
    monkeypatch.setattr(classify, "turn_intent", lambda *args: classify.Intent())
    monkeypatch.setattr(classify, "injection_score", lambda text: 0.0)
    monkeypatch.setattr(classify, "answer_support", lambda *args: classify.Support())
    yield
    db.get_db.cache_clear()


@pytest.fixture
def intent(monkeypatch):
    """Set what the request check finds the user asking for: intent(escalate="please escalate")."""
    def set_intent(outdated=None, **actions):
        monkeypatch.setattr(classify, "turn_intent", lambda *args: classify.Intent(actions, outdated or {}))
    return set_intent


@pytest.fixture
def planted(monkeypatch):
    """Texts the injection classifier should score as attacks: planted.append(text)."""
    texts: list[str] = []
    monkeypatch.setattr(classify, "injection_score", lambda text: 1.0 if any(p in text for p in texts) else 0.0)
    return texts


def principal(role: str, account_id: str | None = None, user_id: str | None = None) -> Principal:
    return Principal(user_id or f"{role}:{account_id}", role, role, account_id)


@pytest.fixture
def users():
    return {
        "northstar_user": principal("customer_user", "ACCT-001"),
        "northstar_admin": principal("customer_admin", "ACCT-001"),
        "lumen_user": principal("customer_user", "ACCT-002"),
        "l1": principal("support_l1"),
        "l2": principal("support_l2"),
        "l2_other": principal("support_l2", user_id="second-l2"),
        "ops": principal("ops_manager"),
    }
