"""Shared test setup: a throwaway database per test and a fixed set of extracted terms.

TERMS is what a correct LLM extraction of the data pack looks like. test_terms.py checks every quote
against the real PDFs with the same verifier the app uses, so these fixtures cannot drift from the documents.
"""
import pytest

from app import config, db, terms
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


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    db.get_db.cache_clear()
    monkeypatch.setattr(terms, "get_terms", lambda: TERMS)
    yield
    db.get_db.cache_clear()


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
