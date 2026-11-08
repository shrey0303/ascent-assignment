"""Hidden data may be formatted differently from the data pack. The unchanged code must still read it:
other date formats, unnumbered headings, 'Version 4' instead of 'v4', a renamed customer field, a policy
with four severity levels. Labels are scripted here as a correct classifier would return them."""
from datetime import date

import pytest

from app import calculator, classify, docs, terms, tools
from tests.conftest import principal

TODAY = date(2026, 8, 16)


@pytest.mark.parametrize("text, expected", [
    ("1 May 2026", date(2026, 5, 1)), ("1st May, 2026", date(2026, 5, 1)), ("May 1, 2026", date(2026, 5, 1)),
    ("Sep 30 2026", date(2026, 9, 30)), ("2026-09-30", date(2026, 9, 30)), ("30/09/2026", date(2026, 9, 30)),
    ("30.09.2026", date(2026, 9, 30)), ("05-01-2026", date(2026, 1, 5)),  # numeric dates are day first (A-02)
    ("no date here", None), ("31 February 2026", None),
])
def test_dates_in_common_formats(text, expected):
    assert docs.parse_date(text) == expected


def test_unnumbered_headings_still_split_sections():
    lines = [(1, "Acme Support Handbook"), (1, "Status: CURRENT"), (1, "Updated: 2026-08-01"),
             (1, "Severity levels"), (1, "P1 means a full outage."), (2, "Response targets"),
             (2, "Enterprise | 1 hour | 4 hours"), (2, "Dedicated CSM: Jane Roe.")]
    title, _, sections = docs._parse_lines("handbook", lines)
    assert title == "Acme Support Handbook"
    assert [s.heading for s in sections] == ["Header", "Severity levels", "Response targets"]
    assert sections[2].page == 2 and "Dedicated CSM: Jane Roe." in sections[2].text  # a field line is not a heading
    numbered = docs._parse_lines("p", [(1, "Policy"), (1, "1. Scope"), (1, "Short Line"), (1, "2. Targets")])[2]
    assert [s.heading for s in numbered] == ["Header", "1. Scope", "2. Targets"]  # numbered docs keep numbered rule


def _labels(doc_type, in_force=True, **meta):
    def fake(doc_id, title, text, sections):
        return {"doc_type": doc_type, "doc_type_quote": "", "in_force": in_force, "in_force_quote": "",
                "meta": {name: meta.get(name) for name in classify.META_FIELDS},
                "commercial": [False] * len(sections), "commercial_quotes": [""] * len(sections), "undecided": []}
    return fake


def _doc(monkeypatch, title, doc_type, **meta):
    monkeypatch.setattr(classify, "document_labels", _labels(doc_type, **meta))
    sections = [docs.Section("x", "Header", 1, title), docs.Section("x", "Terms", 1, "Some terms.")]
    return docs.document_from_parts(title.replace(" ", "_"), title, {}, sections, TODAY)


def test_version_written_out_still_supersedes(monkeypatch):
    old = _doc(monkeypatch, "Acme Support Policy Version 3", "policy", version="Version 3", effective="2026-05-01")
    new = _doc(monkeypatch, "Acme Support Policy Version 4", "policy", version="Version 4", effective="01/08/2026")
    future = _doc(monkeypatch, "Acme Support Policy Rev. 5", "policy", version="Rev. 5", effective="September 1, 2026")
    docs._mark_superseded([old, new, future])
    assert (old.status, new.status, future.status) == ("superseded", "current", "not_yet_effective")
    assert new.effective == date(2026, 8, 1) and new.version == 4


def test_contract_fields_come_from_labels_not_field_names(monkeypatch):
    linked = _doc(monkeypatch, "Acme Master Services Agreement", "contract", account_id="ACCT-9",
                  term_start="2026-01-01", term_end="2026-12-31")
    assert linked.usable and linked.account_id == "ACCT-9" and linked.effective == date(2026, 1, 1)
    ended = _doc(monkeypatch, "Acme Old Agreement", "contract", account_id="ACCT-9",
                 term_start="01/01/2025", term_end="31/12/2025")
    assert ended.status == "expired"
    nobody = _doc(monkeypatch, "Unsigned Agreement", "contract")
    assert nobody.status == "unclassified" and "account_id" in nobody.status_reason  # cannot apply to anyone
    unreadable = _doc(monkeypatch, "Odd Policy", "policy", effective="sometime next spring")
    assert unreadable.status == "unclassified" and "effective" in unreadable.status_reason


def test_undecided_metadata_fails_closed(monkeypatch):
    def fake(doc_id, title, text, sections):
        out = _labels("policy", effective="2026-05-01")(doc_id, title, text, sections)
        return {**out, "undecided": ["version"]}
    monkeypatch.setattr(classify, "document_labels", fake)
    doc = docs.document_from_parts("p", "Some Policy", {}, [docs.Section("p", "Header", 1, "x")], TODAY)
    assert doc.status == "unclassified" and "version" in doc.status_reason


FOUR_LEVELS = ("Severity definitions\n- P1 - Critical: outage.\n- P2 - High: major feature down.\n"
               "- P3 - Normal: minor issue.\n- P4 - Low: cosmetic or feedback.\n"
               "Plan | P1 | P2 | P3 | P4\nGrowth | 1 hour | 4 hours | 1 business day | 5 business days")


def test_a_fourth_severity_level_is_read_from_the_policy(monkeypatch):
    assert classify.severity_codes(FOUR_LEVELS) == ["P1", "P2", "P3", "P4"]
    p4 = {"field": "response_target", "value": "5 business days", "severity": "P4", "plan": "Growth",
          "quote": "Growth | 1 hour | 4 hours | 1 business day | 5 business days"}
    assert terms.verify(p4, FOUR_LEVELS) is None  # no longer rejected as an unknown severity
    assert terms.verify({**p4, "severity": "P5"}, FOUR_LEVELS) == "missing severity"  # not in the document
    monkeypatch.setattr(calculator, "severity_scale", lambda: classify.severity_codes(FOUR_LEVELS))
    assert calculator.high_severities() == ["P1", "P2"]
    out = tools.run(principal("ops_manager"), "sla_watchlist", {"within_hours": 4, "severities": ["P9"]})
    assert out["error"] == "invalid_request" and "P4" in out["message"]
