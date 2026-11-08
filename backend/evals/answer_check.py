"""Score the answer check (classify.answer_support) against hand labels: python -m evals.answer_check

Every case is made up (evals/answer_check_gold.json). Two numbers matter:
- caught: unsupported sentences that were removed (missing one lets a wrong answer through),
- kept: supported sentences that were kept (losing one hides a right answer).
Writes a report to evals/results/.
"""
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from app import classify, config

HERE = Path(__file__).parent


def main() -> int:
    cases = json.loads((HERE / "answer_check_gold.json").read_text(encoding="utf-8"))["cases"]
    lines, caught, bad_total, kept, good_total = [], 0, 0, 0, 0
    started = time.perf_counter()
    for case in cases:
        pieces = classify.answer_pieces(case["answer"])
        checked = [i for i, p in enumerate(pieces) if classify.is_sentence(p)]
        evidence = case["evidence"] if isinstance(case["evidence"], list) else [case["evidence"]] * bool(case["evidence"])
        support = classify.answer_support(case["question"], evidence, case["previous"], case["answer"])
        flagged = {n for n, i in enumerate(checked, 1) if i in support.unsupported}
        expected = set(case["bad"])
        caught += len(flagged & expected)
        bad_total += len(expected)
        kept += len(set(range(1, len(checked) + 1)) - expected - flagged)
        good_total += len(checked) - len(expected)
        ok = support.checked and flagged == expected
        lines.append(f"| {case['id']} | {case['about']} | {sorted(expected)} | "
                     f"{sorted(flagged) if support.checked else 'unchecked'} | {'pass' if ok else 'FAIL'} |")
    seconds = time.perf_counter() - started
    passed = sum(line.endswith("pass |") for line in lines)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    report = [f"# Answer check: {passed}/{len(cases)} cases exactly right",
              "", f"Model `{config.ANSWER_CHECK_MODEL}`, {config.ANSWER_CHECK_VOTES} runs, reasoning "
              f"`{config.ANSWER_CHECK_REASONING_EFFORT}`. Unsupported sentences caught: **{caught}/{bad_total}**. "
              f"Supported sentences kept: **{kept}/{good_total}**. {seconds / len(cases):.1f} s per case.",
              "", "| Case | About | Must remove | Removed | Result |", "|---|---|---|---|---|", *lines]
    out = HERE / "results" / f"answer_check_{stamp}_{config.ANSWER_CHECK_MODEL.split('/')[-1]}_{config.ANSWER_CHECK_REASONING_EFFORT}.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text("\n".join(report) + "\n", encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    print("\n".join(report))
    print(f"\nReport: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
