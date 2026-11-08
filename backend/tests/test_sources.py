"""Document metadata, deprecated exclusion, term verification and the precedence engine."""
from datetime import date

from app import tools
from app.docs import Document, _mark_superseded, get_library
from app.terms import check_terms, resolve, verify
from tests.conftest import TERMS


def test_document_type_and_status_come_from_labels_and_header_fields():
    docs = get_library().documents
    assert docs["02_Support_Policy_v2_DEPRECATED"].status == "deprecated"
    assert docs["01_Support_Policy_v3_CURRENT"].usable
    assert docs["05_Northstar_Logistics_Enterprise_Agreement"].account_id == "ACCT-001"
    assert docs["05_Northstar_Logistics_Enterprise_Agreement"].doc_type == "contract"


def test_newer_version_supersedes_older():
    old = Document("p_v3", "Support Policy v3", "policy", 3, date(2026, 5, 1), None, {})
    new = Document("p_v4", "Support Policy v4", "policy", 4, date(2026, 9, 1), None, {})
    _mark_superseded([old, new])
    assert new.usable and old.status == "superseded"


def test_deprecated_policy_never_returned(users):
    out = tools.run(users["l2"], "search_documents", {"query": "Enterprise P1 response target 1 hour", "top_k": 8})
    assert all("DEPRECATED" not in r["source_id"] for r in out["results"])
    assert any(e["status"] == "deprecated" for e in out["excluded_sources"])


def test_fixture_terms_are_backed_by_documents():
    docs = get_library().documents
    for doc_id, items in TERMS.items():
        for term in items:
            assert verify(term, docs[doc_id].text) is None, (doc_id, term)


def test_invented_terms_are_rejected():
    text = get_library().documents["05_Northstar_Logistics_Enterprise_Agreement"].text
    assert verify({"field": "credit_fixed_inr", "value": 1000, "quote": "Northstar gets INR 1000 per failure."}, text)
    assert verify({"field": "credit_monthly_cap_inr", "value": 9000,
                   "quote": "Monthly aggregate service credits are capped at INR 5,000."}, text) == "number not in quote"


def test_table_cell_quote_must_come_from_one_row():
    text = get_library().documents["01_Support_Policy_v3_CURRENT"].text
    cell = {"field": "response_target", "value": "2 hours", "severity": "P2", "plan": "Enterprise"}
    assert verify({**cell, "quote": "Enterprise | 2 hours"}, text) is None
    assert verify({**cell, "quote": "Standard | 2 hours"}, text) == "quote not found in document"


def test_flat_amount_misread_from_percent_formula_is_dropped():
    text = get_library().documents["03_Cancellation_and_Service_Credit_SOP_v4"].text
    quote = "The default credit is the lower of INR 500 or 10% of the shipment fee."
    kept, rejected = check_terms([
        {"field": "credit_fixed_inr", "value": "INR 500", "quote": quote},
        {"field": "credit_percent_of_fee", "value": "10%", "quote": quote},
        {"field": "credit_max_inr", "value": 500, "quote": quote},
    ], text)
    assert {t["field"] for t in kept} == {"credit_percent_of_fee", "credit_max_inr"}
    assert rejected[0]["field"] == "credit_fixed_inr"


def test_string_null_plan_is_treated_as_empty():
    text = get_library().documents["06_LumenWorks_Service_Agreement"].text
    kept, _ = check_terms([{"field": "response_target", "value": "2 business days", "severity": "P3",
                            "plan": "null", "quote": "P3: 2 business days"}], text)
    assert kept[0]["plan"] is None


def _account(account_id):
    from app.data import get_dataset
    return next(a for a in get_dataset().rows("accounts") if a["account_id"] == account_id)


def test_contract_overrides_policy_with_named_conflict():
    out = resolve(_account("ACCT-001"))
    assert out["terms"]["response_target.P1"]["value"] == "15 minutes, 24x7"
    conflict = next(c for c in out["conflicts"] if c["term"] == "response_target.P1")
    assert conflict["winner"]["source"]["doc_type"] == "contract"
    assert conflict["overridden"][0]["value"] == "30 minutes, 24x7"
    assert any(e["doc_id"] == "02_Support_Policy_v2_DEPRECATED" for e in out["excluded_sources"])


def test_credit_amount_group_comes_from_one_source():
    out = resolve(_account("ACCT-002"))
    assert out["terms"]["credit_fixed_inr"]["value"] == 300
    assert "credit_percent_of_fee" not in out["terms"] and "credit_max_inr" not in out["terms"]


def test_account_without_contract_uses_plan_policy():
    out = resolve(_account("ACCT-003"))
    assert out["terms"]["response_target.P1"]["value"] == "4 business hours"
    assert out["terms"]["response_target.P1"]["source"]["doc_type"] == "policy"
