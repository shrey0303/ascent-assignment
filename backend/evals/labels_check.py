"""Scores the classifier against hand labels (evals/labels_gold.json). One command, from backend/:

    python -m evals.labels_check                       # the configured CLASSIFIER_MODEL and INTENT_MODEL
    python -m evals.labels_check --model openai/gpt-oss-safeguard-20b     # A/B: one model for every task
    python -m evals.labels_check --votes 1             # one run per item: per-run accuracy, cheapest A/B

Labels are made fresh into a temporary file (cache/labels.json is not read or changed), so the score is the
model's, not the cache's. An undecided label counts as wrong here, even though the app handles it safely.
Results go to evals/results/labels_<time>_<model>.md.
"""
import argparse
import json
import os
import re
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="ascent-labels-"))
os.environ["LABELS_CACHE"] = str(TMP / "labels.json")  # set before app.config is imported
os.environ["DB_PATH"] = str(TMP / "usage.db")

from app import agent, calculator, classify, config, db, docs  # noqa: E402
from app.access import Principal  # noqa: E402
from app.data import get_dataset  # noqa: E402
from app.docs import get_library  # noqa: E402

HERE = Path(__file__).resolve().parent
STAFF = Principal("labels-check", "labels-check", "support_l2", None)


def _meaning(field: str, value: str | None):
    """What the app uses from a metadata value: the version number, the parsed date, or the id as written."""
    if not value:
        return "not stated"
    if field == "version":
        return docs._version_number(value)
    if field == "account_id":
        return value
    return str(docs.parse_date(value) or f"unreadable: {value}")


def _severity(ticket: dict) -> tuple[str | None, str]:
    severity, basis = calculator.severity_of(ticket)
    return (None if basis.startswith("NEEDS REVIEW") else severity), basis


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Score the classifier against hand labels.")
    parser.add_argument("--model", help="use this model for labels and the request check")
    parser.add_argument("--votes", type=int, help="runs per label and per request check")
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    if not config.LLM_API_KEY:
        print("LLM_API_KEY is not set (see .env.example).")
        return 2
    if args.model:
        config.CLASSIFIER_MODEL = config.INTENT_MODEL = args.model
    if args.votes:
        config.LABEL_VOTES = config.INTENT_VOTES = args.votes
    gold = json.loads((HERE / "labels_gold.json").read_text(encoding="utf-8"))
    started, rows = time.time(), []  # (task, item, expected, got, detail)

    library = get_library()
    for doc_id, want in gold["documents"].items():
        doc = library.documents[doc_id]
        labels = doc.labels
        rows.append(("document type", doc_id, want["doc_type"], labels.get("doc_type"), ""))
        rows.append(("in force", doc_id, want["in_force"], labels.get("in_force"), ""))
        for name in classify.META_FIELDS:  # undecided -> None (wrong); compared by meaning (v3 == 3, date == date)
            got = None if name in labels.get("undecided", []) else _meaning(name, (labels.get("meta") or {}).get(name))
            rows.append(("metadata", f"{doc_id} / {name}", _meaning(name, want["meta"].get(name)), got, ""))
        if want["doc_type"] == "contract":
            undecided = {u.removeprefix("commercial: ") for u in labels.get("undecided", [])}
            for section in doc.sections:
                got = None if section.heading in undecided else section.commercial
                rows.append(("commercial section", f"{doc_id} / {section.heading}",
                             section.heading in want["commercial"], got, ""))

    tickets = {t["ticket_id"]: t for t in get_dataset().rows("tickets")}
    for ticket_id, want in gold["tickets"].items():
        got, basis = _severity(tickets[ticket_id])
        rows.append(("ticket severity", ticket_id, want, got, basis[:160]))
    for i, case in enumerate(gold["reworded_tickets"]):
        got, basis = _severity({"ticket_id": f"REWORDED-{i}", **case})
        rows.append(("reworded ticket severity", case["subject"], case["severity"], got, basis[:160]))

    outdated = agent.outdated_documents(STAFF)
    for case in gold["intents"]:
        found = classify.turn_intent(case["message"], case.get("previous", ""), outdated)
        rows.append(("request check: actions", case["message"], sorted(case["actions"]),
                     sorted(found.actions) if found.checked else None, ""))
        rows.append(("request check: outdated document", case["message"], sorted(case["outdated"]),
                     sorted(found.outdated) if found.checked else None, ""))

    usage = db.get_db().query("SELECT COUNT(*) AS calls, SUM(cost_usd) AS cost FROM llm_usage")[0]
    report = _markdown(rows, usage, time.time() - started)
    stem = re.sub(r"[^A-Za-z0-9]+", "-", config.CLASSIFIER_MODEL)
    out = HERE / "results" / f"labels_{datetime.now(timezone.utc):%Y%m%d-%H%M%S}_{stem}_v{config.LABEL_VOTES}.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print(report + f"\nSaved: {out}")
    return 0 if all(want == got for _, _, want, got, _ in rows) else 1


def _markdown(rows: list[tuple], usage: dict, seconds: float) -> str:
    tasks = list(dict.fromkeys(task for task, *_ in rows))
    correct = sum(w == g for _, _, w, g, _ in rows)
    lines = [f"# Classifier check: labels `{config.CLASSIFIER_MODEL}`, request check `{config.INTENT_MODEL}`", "",
             f"{config.LABEL_VOTES} runs per document/ticket label (agreement needed: more than "
             f"{config.LABEL_AGREEMENT:.0%}), {config.INTENT_VOTES} per request check, temperature "
             f"{config.CLASSIFIER_TEMPERATURE}, reasoning effort {config.CLASSIFIER_REASONING_EFFORT}. "
             f"{usage['calls']} calls, USD {usage['cost'] or 0:.4f}, {seconds:.0f} s.", "",
             f"**{correct}/{len(rows)} correct ({correct / len(rows):.0%}).**", "",
             "| Task | Items | Correct | Undecided (handled fail-closed) |", "|---|---|---|---|"]
    for task in tasks:
        items = [r for r in rows if r[0] == task]
        lines.append(f"| {task} | {len(items)} | {sum(w == g for _, _, w, g, _ in items)} | "
                     f"{sum(g is None for _, _, _, g, _ in items)} |")
    wrong = [r for r in rows if r[2] != r[3]]
    lines += ["", "## Not correct", ""]
    lines += [f"- {t}: `{i}` expected {w!r}, got {g!r}" + (f" ({d})" if d else "") for t, i, w, g, d in wrong] or ["None."]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    sys.exit(main())
