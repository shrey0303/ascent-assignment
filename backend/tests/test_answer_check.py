"""Answer check (A12): every sentence of an answer must be backed by this turn's evidence before it is shown.

The model's labels are scripted here, so these tests check the code around it: cited items and values are
verified, runs vote, failed runs don't vote, a rewrite is asked for once, then sentences are removed.
All texts are made up; none come from the data pack or the eval cases.
"""
import json
import threading

import pytest

from app import agent, classify, config, llm

REAL_ANSWER_SUPPORT = classify.answer_support  # the autouse fixture replaces it with "all supported"


@pytest.fixture(autouse=True)
def check_on(monkeypatch):
    """The check is off by default (rejected for the submission); these tests switch it on."""
    monkeypatch.setattr(config, "ANSWER_CHECK_ENABLED", True)


def test_check_is_off_by_default_and_never_runs(monkeypatch, users):
    monkeypatch.setattr(config, "ANSWER_CHECK_ENABLED", False)
    calls = []
    monkeypatch.setattr(classify, "answer_support", lambda *args: calls.append(args) or classify.Support())
    monkeypatch.setattr(llm, "chat", lambda messages, tools=None, json_mode=False: llm.LLMResult(
        {"content": "Hello.\nConfidence: low"}, "fake", 1, 1, 0.0, 1))
    answer = list(agent.run_turn(users["lumen_user"], None, "hi"))[-1]
    assert calls == [] and answer["removed_statements"] == []

EVIDENCE = ['lookup result: {"plan":"Silver","monthly_refund_cap":"EUR 900","region":"North"}']


def _run(*labels, answers="yes"):
    """One scripted run: labels[i] is (label, items, values) for sentence i+1."""
    return {"answers_question": answers, "sentences": [
        {"n": n, "label": label, "items": items, "values": values} for n, (label, items, values) in enumerate(labels, 1)]}


def _scripted(monkeypatch, runs):
    """The model runs return these answers (in parallel threads, so in any order)."""
    queue, lock = list(runs), threading.Lock()

    def fake(*args, **kwargs):
        with lock:
            return queue.pop(0)
    monkeypatch.setattr(classify, "_run", fake)


def test_pieces_join_back_and_keep_citations_and_list_numbers_whole():
    text = "Your plan is Silver [doc-9 § 4. Refunds]. The cap is EUR 900.\n\n1. First step. Then more!\nConfidence: high"
    pieces = classify.answer_pieces(text)
    assert "".join(pieces) == text
    assert "Your plan is Silver [doc-9 § 4. Refunds]. " in pieces
    assert any(p.startswith("1. First step.") for p in pieces)
    assert not classify.is_sentence("Confidence: high") and not classify.is_sentence("\n")
    table = "| Rule | Result |\n|---|---|\n| Override | The deal wins. Fee is zero. |\nDone."
    rows = classify.answer_pieces(table)
    assert "| Override | The deal wins. Fee is zero. |\n" in rows and "".join(rows) == table
    assert not classify.is_sentence("|---|---|\n")


def test_values_must_be_in_the_cited_items_and_a_majority_decides(monkeypatch):
    text = "Your plan is Silver. Your refund cap is EUR 900. Happy to help."
    good = _run(("supported", [1], ["Silver"]), ("supported", ["E1"], ["EUR 900"]), ("no_claim", [], []))
    invented = _run(("supported", [1], ["Silver"]), ("supported", [1], ["EUR 950"]), ("no_claim", [], []))
    _scripted(monkeypatch, [good, good, invented])
    assert REAL_ANSWER_SUPPORT("refund cap?", EVIDENCE, "", text).unsupported == []
    _scripted(monkeypatch, [good, invented, invented])  # two runs list a value that isn't in the evidence
    pieces = classify.answer_pieces(text)
    support = REAL_ANSWER_SUPPORT("refund cap?", EVIDENCE, "", text)
    assert [pieces[i].strip() for i in support.unsupported] == ["Your refund cap is EUR 900."]


def test_iso_times_in_the_evidence_match_their_written_forms():
    searched = classify._with_written_dates('{"due_at":"2031-05-13T09:12:00+02:00"}')
    for written in ("13 May 2031", "13 May 2031, 09:12", "13 May 2031 at 09:12", "May 13, 2031", "09:12",
                    "2031-05-13 09:12", "2031-05-13T09:12:00+02:00"):
        assert classify.quote_in(written, searched), written
    for wrong in ("14 May 2031", "13 May 2031 at 10:12", "13 June 2031"):
        assert not classify.quote_in(wrong, searched), wrong


def test_supported_needs_a_real_item_and_at_least_one_value(monkeypatch):
    text = "Your plan is Silver."
    for bad in (_run(("supported", [7], ["Silver"])), _run(("supported", [1], [])), _run(("supported", [], ["Silver"]))):
        _scripted(monkeypatch, [bad] * 3)
        assert REAL_ANSWER_SUPPORT("plan?", EVIDENCE, "", text).unsupported == [0]


def test_a_value_moved_to_another_thing_is_removed_when_the_runs_say_so(monkeypatch):
    # The number is in the evidence, but for a different thing: only the model's label can catch that.
    text = "Your monthly order limit is EUR 900."
    unsupported, supported = _run(("unsupported", [], [])), _run(("supported", [1], ["EUR 900"]))
    _scripted(monkeypatch, [unsupported, unsupported, supported])
    assert REAL_ANSWER_SUPPORT("order limit?", EVIDENCE, "", text).unsupported == [0]


def test_failed_runs_do_not_vote(monkeypatch):
    text = "Your plan is Silver."
    good = _run(("supported", [1], ["Silver"]))
    _scripted(monkeypatch, [None, good, good])  # a provider error is no vote, not a vote against
    assert REAL_ANSWER_SUPPORT("plan?", EVIDENCE, "", text).unsupported == []
    _scripted(monkeypatch, [good, None, None])  # one successful run is not enough to decide
    assert REAL_ANSWER_SUPPORT("plan?", EVIDENCE, "", text).checked is False
    _scripted(monkeypatch, [None, None, None])
    assert REAL_ANSWER_SUPPORT("plan?", EVIDENCE, "", text).checked is False
    _scripted(monkeypatch, [None, good, _run(("unsupported", [], []))])  # two runs disagree: not backed
    assert REAL_ANSWER_SUPPORT("plan?", EVIDENCE, "", text).unsupported == [0]


def test_absence_needs_no_value_and_earlier_reply_counts_as_evidence(monkeypatch):
    text = "The sources don't state an order limit. Your region is East."
    run = _run(("absence", [], []), ("supported", [2], ["East"]))  # item 2 is the earlier reply when there is one
    _scripted(monkeypatch, [run] * 3)
    support = REAL_ANSWER_SUPPORT("limits?", EVIDENCE, "Your region is East.", text)
    assert support.unsupported == []
    _scripted(monkeypatch, [run] * 3)
    support = REAL_ANSWER_SUPPORT("limits?", EVIDENCE, "", text)
    assert support.unsupported == [1]  # without the earlier reply there is no item 2: "East" is backed by nothing


def _turn(monkeypatch, users, drafts, supports):
    """Run one chat turn with scripted model replies and scripted answer checks."""
    replies, checks, seen = iter(drafts), iter(supports), []
    monkeypatch.setattr(llm, "chat", lambda messages, tools=None, json_mode=False: seen.append(messages) or
                        llm.LLMResult(next(replies), "fake", 1, 1, 0.0, 1))
    monkeypatch.setattr(classify, "answer_support", lambda *args: next(checks))
    return list(agent.run_turn(users["lumen_user"], None, "What is my order limit?"))[-1], seen


def test_unsupported_sentence_gets_one_rewrite(monkeypatch, users):
    draft = {"content": "Hello. Your order limit is 900.\nConfidence: high"}
    rewrite = {"content": "The sources don't state an order limit.\nConfidence: low"}
    answer, seen = _turn(monkeypatch, users, [draft, rewrite],
                         [classify.Support(unsupported=[1]), classify.Support(answers_question="no")])
    assert answer["text"].startswith("The sources don't state an order limit.")
    assert answer["removed_statements"] == [] and answer["confidence"] == "low"
    assert "Your order limit is 900." in seen[-1][-1]["content"]  # the model was told which sentence failed


def test_still_unsupported_after_the_rewrite_is_removed_with_a_note(monkeypatch, users):
    draft = {"content": "Hello. Your order limit is 900.\nConfidence: high"}
    answer, _ = _turn(monkeypatch, users, [draft, draft],
                      [classify.Support(unsupported=[1]), classify.Support(unsupported=[1])])
    assert "900" not in answer["text"] and "Not stated in the sources" in answer["text"]
    assert answer["removed_statements"] == ["Your order limit is 900."] and answer["confidence"] == "low"


def test_nothing_backed_leaves_a_plain_statement(monkeypatch, users):
    draft = {"content": "Your order limit is 900.\nConfidence: high"}
    answer, _ = _turn(monkeypatch, users, [draft, draft],
                      [classify.Support(unsupported=[0]), classify.Support(unsupported=[0])])
    assert answer["text"].startswith(agent.NOTHING_LEFT)


def test_check_unavailable_caps_confidence(monkeypatch, users):
    draft = {"content": "Hello there.\nConfidence: high"}
    answer, _ = _turn(monkeypatch, users, [draft], [classify.Support(checked=False)])
    assert answer["text"].startswith("Hello there.") and answer["confidence"] != "high"
    assert "answer check unavailable" in answer["confidence_basis"]


def test_rewrite_may_look_things_up_and_steps_keep_their_own_numbers(monkeypatch, users):
    lookup = {"content": "", "tool_calls": [{"id": "c9", "type": "function", "function": {
        "name": "query_records", "arguments": json.dumps({"entity": "orders"})}}]}
    replies = iter([{"content": "Your order limit is 900.\nConfidence: high"}, lookup,
                    {"content": "Here are your orders.\nConfidence: medium"}])
    checks = iter([classify.Support(unsupported=[0]), classify.Support()])
    monkeypatch.setattr(llm, "chat", lambda messages, tools=None, json_mode=False: llm.LLMResult(next(replies), "fake", 1, 1, 0.0, 1))
    monkeypatch.setattr(classify, "answer_support", lambda *args: next(checks))
    events = list(agent.run_turn(users["lumen_user"], None, "What is my order limit?"))
    assert any(e["type"] == "tool_call" and e["name"] == "query_records" for e in events)
    assert events[-1]["text"].startswith("Here are your orders.") and events[-1]["removed_statements"] == []
    steps = [e["step"] for e in events if e["type"] == "plan"]
    assert len(steps) == len(set(steps))  # the web app groups the trace by step number


def test_check_sees_tool_results_exactly_as_the_model_did(monkeypatch, users):
    calls = []
    replies = iter([
        {"content": "", "tool_calls": [{"id": "c1", "type": "function",
                                        "function": {"name": "query_records", "arguments": json.dumps({"entity": "orders"})}}]},
        {"content": "Here are your orders.\nConfidence: medium"},
    ])
    monkeypatch.setattr(llm, "chat", lambda messages, tools=None, json_mode=False: llm.LLMResult(next(replies), "fake", 1, 1, 0.0, 1))
    monkeypatch.setattr(classify, "answer_support", lambda *args: calls.append(args) or classify.Support())
    list(agent.run_turn(users["lumen_user"], None, "my orders"))
    question, evidence, _previous, draft = calls[0]
    assert question == "my orders" and draft.startswith("Here are your orders.")
    assert evidence[0].startswith("Session: ")  # who the user is counts as evidence
    assert evidence[1].startswith("query_records result:") and len(evidence) == 2  # one item per tool result
