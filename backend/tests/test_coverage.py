"""Search coverage: which searched words no readable document contains (calibrated abstention, B8).
Words are taken from the loaded documents at test time, so nothing here depends on the data pack's wording."""
import re

import pytest

from app import agent, tools
from app.docs import _singular, get_library, words


def _doc_words(include) -> set[str]:
    found = set()
    for doc in get_library().documents.values():
        for section in doc.sections:
            if include(doc, section):
                found |= words(f"{doc.title} {section.heading} {section.text}")
    return found


def _missing(out: dict) -> list[str]:
    return (out.get("not_in_any_document") or {}).get("words", [])


def test_word_in_no_document_is_reported(users):
    out = tools.run(users["l2"], "search_documents", {"query": "zorbulated parcel handling"})
    assert "zorbulated" in _missing(out)
    assert "parcel" not in _missing(out)  # in the documents, so not reported
    assert "not cover" in out["not_in_any_document"]["note"]


def test_plural_and_singular_count_as_the_same_word(users):
    policy_words = _doc_words(lambda d, s: d.usable and d.doc_type == "policy")
    word = next(w for w in sorted(policy_words) if len(w) >= 6 and w.isalpha() and not w.endswith(("s", "y")))
    assert _singular(word + "s") == word
    out = tools.run(users["l2"], "search_documents", {"query": f"{word}s"})
    assert _missing(out) == []


def test_no_report_when_every_word_is_found(users):
    out = tools.run(users["l2"], "search_documents", {"query": "support policy"})
    assert "not_in_any_document" not in out


def test_another_customers_contract_never_counts(users):
    """A word only another customer's agreement contains is reported as missing, exactly as if no document had it,
    so the report never hints at another customer's terms."""
    library = get_library()
    other = {d.doc_id for d in library.documents.values() if d.doc_type == "contract" and d.account_id == "ACCT-002"}
    rest = _doc_words(lambda d, s: d.usable and d.doc_id not in other)
    only_other = sorted(w for w in _doc_words(lambda d, s: d.doc_id in other) - rest if len(w) >= 5 and w.isalpha())
    if not only_other:
        pytest.skip("no word unique to the other customer's agreement")
    word = only_other[0]
    assert word in _missing(tools.run(users["northstar_user"], "search_documents", {"query": word}))
    assert word not in _missing(tools.run(users["lumen_user"], "search_documents", {"query": word}))


def test_commercial_sections_hidden_from_l1_never_count(users):
    library = get_library()
    commercial = _doc_words(lambda d, s: d.usable and s.commercial)
    readable = _doc_words(lambda d, s: d.usable and not s.commercial)
    only_commercial = sorted(w for w in commercial - readable if len(w) >= 5 and w.isalpha())
    if not only_commercial:
        pytest.skip("no word unique to commercial sections")
    word = only_commercial[0]
    account = next(d.account_id for d in library.documents.values()
                   for s in d.sections if s.commercial and word in words(s.text))
    args = {"query": word, "account": account}
    assert word in _missing(tools.run(users["l1"], "search_documents", args))
    assert word not in _missing(tools.run(users["l2"], "search_documents", args))


def test_company_names_are_not_reported(users):
    out = tools.run(users["l2"], "search_documents", {"query": "Beacon Retail zorbulated"})
    assert _missing(out) == ["zorbulated"]


def test_confidence_capped_when_searched_words_are_missing(users):
    evidence = agent.Evidence()
    evidence.add("search_documents", tools.run(users["l2"], "search_documents", {"query": "zorbulated limit"}))
    answer = agent.finalize("The limit is 12.\nConfidence: high", evidence)
    assert answer["confidence"] == "medium"
    assert any(re.search("zorbulated", r) for r in answer["confidence_basis"])


def test_unknown_customer_fault_states_the_credit_rule(users):
    out = tools.run(users["l2"], "calc_pickup_credit",
                    {"account": "ACCT-002", "delay_hours": 9, "carrier_fault": True})
    assert out["outcome"] == "cannot_determine"
    assert "NOT at fault" in out["rule"]
    stated = tools.run(users["l2"], "calc_pickup_credit",
                       {"account": "ACCT-002", "delay_hours": 9, "carrier_fault": True, "customer_fault": True})
    assert stated["outcome"] == "not_eligible"
