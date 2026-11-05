"""Static guard: no data-pack identifier, name, document name or heading appears anywhere in the app code
(backend and frontend)."""
import re
from pathlib import Path

from app import config
from app.data import get_dataset
from app.docs import get_library

APP = Path(__file__).resolve().parents[1] / "app"
UI = Path(__file__).resolve().parents[2] / "frontend" / "src"
NAME_COLUMNS = {"account_name", "csm", "assigned_to", "carrier", "contract_file"}


def _data_pack_values() -> set[str]:
    values = set()
    for rows in get_dataset().tables.values():
        for row in rows:
            for column, value in row.items():
                if value and (column.endswith("_id") or column in NAME_COLUMNS):
                    values.add(str(value))
    for doc in get_library().documents.values():
        values.add(doc.doc_id)
        values.update(re.findall(r"\b[A-Z]{2,}-\d+\b", doc.text))  # known-issue ids, account ids in headers
        values.update(s.heading for s in doc.sections if s.heading != "Header")  # numbered: "2. Shipment ..."
    return {v for v in values if len(v) >= 3}


def test_app_code_contains_no_data_pack_values():
    values = _data_pack_values()
    assert len(values) > 40  # ids, names, document ids, headings were actually collected
    found = []
    for path in sorted([*APP.glob("*.py"), *UI.rglob("*.js"), *UI.rglob("*.jsx")]):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for value in values:
                if re.search(rf"(?<![A-Za-z0-9]){re.escape(value)}(?![A-Za-z0-9])", line, re.I):
                    found.append(f"{path.name}:{number}: {value!r}")
            if re.search(r"(section|clause|§)\s*\d", line, re.I):  # clause numbers, even in comments
                found.append(f"{path.name}:{number}: clause reference")
    assert found == []


def test_no_data_pack_amounts_or_targets_in_prompts():
    """Contract/SOP amounts and targets reach the model only through tool results, never through prompts."""
    from app import agent, terms
    from tests.conftest import TERMS
    prompts = agent.BASE_RULES + agent.CUSTOMER_PROMPT + agent.STAFF_PROMPT + terms.EXTRACTION_PROMPT
    values = {t["value"] for items in TERMS.values() for t in items if not isinstance(t["value"], bool)}
    checked = [v for v in values if isinstance(v, str) or v >= 10]  # 2, 4 ... are too common to be evidence
    assert checked
    for value in checked:
        # (?!\.\s) skips numbered-rule markers such as "10. When you need tools"
        assert not re.search(rf"(?<![\w.]){re.escape(str(value))}(?!\w|\.\s)", prompts), value
    assert config.DATA_DIR
