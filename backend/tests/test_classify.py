"""The classifier's checks with scripted model answers: evidence must be real, agreement decides, undecided
labels fail closed, and only complete runs are stored. Also: the conftest labels are backed by the PDFs."""
import pytest

from app import classify, config, llm
from app.docs import get_library
from tests.conftest import DOC_LABELS, DOC_META, SEVERITY_LABELS

REAL_DOCUMENT_LABELS = classify.document_labels  # captured before conftest swaps in the fixture labels
REAL_TICKET_SEVERITY = classify.ticket_severity
REAL_TURN_INTENT = classify.turn_intent
REAL_INJECTION_SCORE = classify.injection_score

SECTIONS = [("Header", "Acme Service Agreement\nStatus: ACTIVE"),
            ("1. Support terms", "P1: 1 hour"),
            ("2. Fees", "Acme pays no cancellation fee.")]
TEXT = "\n".join(f"{h}\n{b}" for h, b in SECTIONS)


@pytest.fixture
def runs(monkeypatch, tmp_path):
    """Script the answers of the parallel runs: runs(answer1, answer2, ...)."""
    monkeypatch.setattr(config, "LABELS_CACHE", tmp_path / "labels.json")
    monkeypatch.setattr(config, "LLM_API_KEY", "test")
    classify._cache.cache_clear()
    calls = []

    def install(*answers):
        calls.clear()
        monkeypatch.setattr(config, "LABEL_VOTES", len(answers))
        monkeypatch.setattr(config, "INTENT_VOTES", len(answers))
        monkeypatch.setattr(classify, "_runs", lambda *args: calls.append(args) or list(answers))
        return calls
    yield install
    classify._cache.cache_clear()


def _doc(commercial_quote="Acme pays no cancellation fee.", doc_type="contract"):
    return {"doc_type": doc_type, "doc_type_quote": "Acme Service Agreement", "in_force": True,
            "sections": [{"s": "S0", "commercial": False}, {"s": "S1", "commercial": False},
                         {"s": "[S2]", "commercial": True, "quote": commercial_quote}]}


def test_labels_need_agreement_of_quote_backed_runs(runs):
    misquoted = _doc(commercial_quote="Acme pays INR 0")  # not in the text: that claim is discarded
    runs(_doc(), misquoted, misquoted, _doc(), _doc(doc_type="policy"))
    out = REAL_DOCUMENT_LABELS("acme", "Acme Service Agreement", TEXT, SECTIONS)
    assert out["doc_type"] == "contract" and out["in_force"] is True  # 4 of 5 said contract: agreed
    assert out["tallies"]["doc_type"] == {"contract": 4, "policy": 1}
    assert out["tallies"]["commercial: 2. Fees"] == {"True": 3}  # the two misquoted runs are not counted
    # S2: three runs back "commercial" with a real quote; 3 of 5 is below the 4 needed, so it stays hidden
    assert out["commercial"] == [False, False, True] and out["undecided"] == ["commercial: 2. Fees"]
    assert out["meta"] == dict.fromkeys(classify.META_FIELDS)  # every run said "not stated": agreed null


def test_metadata_values_must_be_in_the_document(runs):
    stated = {**_doc(), "account_id": "ACME-7", "effective": "1 July 2026"}
    invented = {**stated, "account_id": "ACME-9"}  # not in the text: discarded
    text = TEXT + "\nAccount: ACME-7\nEffective: 1 July 2026"
    runs(stated, stated, stated, stated, invented)
    out = REAL_DOCUMENT_LABELS("acme", "Acme Service Agreement", text, SECTIONS)
    assert out["meta"]["account_id"] == "ACME-7" and out["meta"]["effective"] == "1 July 2026"
    runs(stated, stated, stated, invented, invented)  # 3 of 5: not enough agreement
    out = REAL_DOCUMENT_LABELS("acme", "Acme Service Agreement (copy)", text, SECTIONS)
    assert out["meta"]["account_id"] is None and "account_id" in out["undecided"]


def test_no_majority_fails_closed_and_is_not_frozen(runs, monkeypatch):
    calls = runs(None, None, _doc())
    out = REAL_DOCUMENT_LABELS("acme", "Acme Service Agreement", TEXT, SECTIONS)
    assert out["doc_type"] is None and out["commercial"] == [True, True, True]  # everything hidden
    assert not config.LABELS_CACHE.exists()  # failed runs are retried next start, never stored
    runs(_doc(), _doc(), _doc())
    REAL_DOCUMENT_LABELS("acme", "Acme Service Agreement", TEXT, SECTIONS)
    stored = config.LABELS_CACHE.read_text(encoding="utf-8")
    assert '"doc_type": "contract"' in stored
    calls = runs(None, None, None)  # same text again: answered from the file, the model is not asked
    assert REAL_DOCUMENT_LABELS("acme", "Acme Service Agreement", TEXT, SECTIONS)["doc_type"] == "contract"
    assert calls == []


def test_no_api_key_means_undecided(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "LABELS_CACHE", tmp_path / "labels.json")
    monkeypatch.setattr(config, "LLM_API_KEY", "")
    classify._cache.cache_clear()
    out = REAL_DOCUMENT_LABELS("acme", "Acme Service Agreement", TEXT, SECTIONS)
    assert out["doc_type"] is None and all(out["commercial"])
    classify._cache.cache_clear()


def test_unclassified_document_is_never_used(monkeypatch):
    from app import docs
    from tests.conftest import undecided_labels
    monkeypatch.setattr(classify, "document_labels", lambda *a: undecided_labels(a[3]))
    library = docs.load_library()
    assert library.documents and all(not d.usable and d.status == "unclassified" for d in library.documents.values())


POLICY = ("Severity definitions\n- P1 - Critical: Complete outage of shipment creation.\n"
          "- P2 - High: Major feature degraded but a workaround exists.\n- P3 - Normal: How-to question.")


def test_severity_quote_must_come_from_that_severitys_definition(runs):
    ticket = {"ticket_id": "T-1", "subject": "Bulk upload fails", "description": "Single shipments work."}
    p2 = {"severity": "P2", "definition_quote": "Major feature degraded but a workaround exists", "reason": "r"}
    p3 = {"severity": "P3", "definition_quote": "How-to question", "reason": "r"}
    wrong_owner = {"severity": "P1", "definition_quote": "Major feature degraded"}  # P2's words used for P1
    invented = {"severity": "P1", "definition_quote": "Any failure is critical"}
    runs(p2, p2, wrong_owner, p2, p2)
    out = REAL_TICKET_SEVERITY(ticket, POLICY)
    assert out["severity"] == "P2" and out["quote"] == p2["definition_quote"] and out["tally"] == {"P2": 4}
    runs(p2, wrong_owner, invented)
    assert REAL_TICKET_SEVERITY({**ticket, "description": "changed"}, POLICY)["severity"] is None
    runs(p2, p2, p2, p3, p3)  # a close call is not decided by a 3-2 vote
    split = REAL_TICKET_SEVERITY({**ticket, "description": "close call"}, POLICY)
    assert split["severity"] is None and split["tally"] == {"P2": 3, "P3": 2}
    assert classify.severity_codes(POLICY) == ["P1", "P2", "P3"]  # codes come from the policy text


def test_split_severity_vote_is_handled_as_the_stricter_reading(monkeypatch):
    from app.calculator import severity_of
    monkeypatch.setattr(classify, "ticket_severity",
                        lambda *a: {"severity": None, "quote": "", "reason": "", "tally": {"P3": 3, "P2": 2}})
    severity, basis = severity_of({"ticket_id": "X-2", "subject": "Status shows late"})
    assert severity == "P2" and basis.startswith("NEEDS REVIEW") and "P2 x2" in basis and "P3 x3" in basis


def test_message_is_split_into_numbered_parts():
    assert classify.message_parts("Hi there. Is it late?\nPlease escalate it!") == [
        "Hi there.", "Is it late?", "Please escalate it!"]
    assert classify.message_parts("v2.1 costs 1.5 INR") == ["v2.1 costs 1.5 INR"]  # no split inside numbers
    assert classify.message_parts("   ") == [""]


def test_request_check_needs_a_part_of_the_users_message_and_a_majority(runs):
    message = "Hi there. Please escalate TKT-9."
    asked = {"actions": [{"action": "escalate", "part": 2}], "outdated_documents": []}
    no_such_part = {"actions": [{"action": "escalate", "part": 7}]}  # e.g. words from the previous reply: discarded
    task = {"actions": [{"action": "task", "part": 2}]}
    calls = runs(asked, asked, no_such_part)
    assert REAL_TURN_INTENT(message, "Shall I escalate this ticket as P1?", {}).actions == {
        "escalate": "Please escalate TKT-9."}  # the user's exact words, taken from the message by the code
    assert "[U1] Hi there.\n[U2] Please escalate TKT-9." in calls[0][1]  # the model sees the numbered parts
    runs(asked, no_such_part, task)  # one backed vote of three for each action: no majority
    assert REAL_TURN_INTENT(message, "", {}).actions == {}
    old = {"actions": [], "outdated_documents": [{"doc_id": "policy-v2", "part": "U2"},
                                                 {"doc_id": "not-listed", "part": 2}]}  # unknown id: discarded
    runs(old, old, None)
    found = REAL_TURN_INTENT("Thanks. Does the 2025 policy still apply?", "", {"policy-v2": "Support Policy v2 (deprecated)"})
    assert found.outdated == {"policy-v2": "Does the 2025 policy still apply?"} and found.actions == {}
    runs(None, None, None)
    assert REAL_TURN_INTENT("escalate", "", {}).checked is False



def test_injection_scan_reads_every_chunk_and_retries_failures(monkeypatch):
    scores, caps = iter(["0.01", "0.97"]), []
    monkeypatch.setattr(llm, "chat", lambda *a, **k: caps.append(k.get("max_tokens")) or
                        llm.LLMResult({"content": next(scores)}, "guard", 1, 0, 0.0, 1))
    text = "a " * 1000  # 2,000 characters: two overlapping chunks; the attack is in the second
    assert REAL_INJECTION_SCORE(text) == 0.97
    assert caps and all(c and c <= 512 for c in caps)  # Prompt Guard refuses the agent's larger output cap
    monkeypatch.setattr(llm, "chat", lambda *a, **k: (_ for _ in ()).throw(llm.LLMError("down")))
    assert REAL_INJECTION_SCORE("another text that is long enough") is None
    assert "another text that is long enough" not in classify._scores


def test_unit_test_labels_match_the_hand_labels_the_model_is_scored_on():
    import json
    from pathlib import Path
    gold = json.loads((Path(__file__).resolve().parents[1] / "evals" / "labels_gold.json").read_text(encoding="utf-8"))
    for doc_id, (doc_type, _, in_force, _, commercial) in DOC_LABELS.items():
        assert gold["documents"][doc_id] == {"doc_type": doc_type, "in_force": in_force,
                                             "commercial": list(commercial), "meta": DOC_META[doc_id]}, doc_id
    assert {k.split("-")[1]: v for k, v in gold["tickets"].items()} == {k: v[0] for k, v in SEVERITY_LABELS.items()}


def test_fixture_labels_are_backed_by_the_documents():
    docs = get_library().documents
    for doc_id, (doc_type, type_quote, in_force, force_quote, commercial) in DOC_LABELS.items():
        text = docs[doc_id].text
        assert classify.quote_in(type_quote, text) and classify.quote_in(force_quote, text), doc_id
        assert all(classify.quote_in(v, text) for v in DOC_META[doc_id].values()), doc_id
        sections = {s.heading: s.text for s in docs[doc_id].sections}
        for heading, quote in commercial.items():
            assert classify.quote_in(quote, f"{heading}\n{sections[heading]}"), (doc_id, heading)
    policy = docs["01_Support_Policy_v3_CURRENT"].text
    for number, (severity, quote) in SEVERITY_LABELS.items():
        assert classify._definition_owner(quote, policy) == severity, number
