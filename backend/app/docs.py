"""PDF ingestion, document metadata (type, status, version) and keyword retrieval (BM25).

Document type and status are read from each PDF's own title and header ("Status:", "Effective:",
"Account:", "Term:"), never from file names in code, so new document versions are handled the same way.
"""
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path

from pypdf import PdfReader

from . import config
from .data import get_dataset

_HEADING = re.compile(r"^\d+(?:\.\d+)*\.?\s+[A-Z]")
_META = re.compile(r"^([A-Z][A-Za-z ]{1,30}):\s*(.+)$")
_TABLE_GAP = re.compile(r"\s{8,}")
_VERSION = re.compile(r"\bv(\d+)\b", re.I)
_DATE = re.compile(r"\d{1,2}\s+[A-Za-z]+\s+\d{4}")
_COMMERCIAL = re.compile(r"\b(inr|usd|discount\w*|pric\w*|rates?|fees?|credits?|cap|capped|rebates?|invoic\w*)\b", re.I)
_STOP = set(
    "a an and are as at be by can do does for from has have how i if in is it its may me my of on or our "
    "that the their then this to was we what when which who will with you your".split()
)


def tokens(text: str) -> list[str]:
    """Lowercase words, stop words removed, cut to 5 chars as a cheap stemmer (cancel/cancellation)."""
    return [w[:5] for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in _STOP]


@dataclass
class Section:
    doc_id: str
    heading: str
    page: int
    text: str
    commercial: bool = False  # contract section with money terms; hidden from roles without commercial access

    @property
    def cite(self) -> str:
        return f"{self.doc_id} § {self.heading}"


@dataclass
class Document:
    doc_id: str
    title: str
    doc_type: str
    version: int | None
    effective: date | None
    account_id: str | None
    meta: dict
    sections: list[Section] = field(default_factory=list)
    status: str = "current"  # current | deprecated | superseded | expired | not_yet_effective
    status_reason: str = ""

    @property
    def tier(self) -> int:
        return config.SOURCE_PRECEDENCE.index(self.doc_type)

    @property
    def usable(self) -> bool:
        return self.status == "current"

    @property
    def text(self) -> str:
        return "\n".join(f"{s.heading}\n{s.text}" for s in self.sections)


def _clean_line(raw: str) -> str:
    line = raw.replace("●", "-").replace("•", "-").strip()
    if len(_TABLE_GAP.findall(line)) >= 2:  # layout-mode table row: keep the columns apart
        return " | ".join(re.sub(r"\s+", " ", cell) for cell in _TABLE_GAP.split(line))
    return re.sub(r"\s+", " ", line)


def _parse_date(text: str | None) -> date | None:
    match = _DATE.search(text or "")
    if not match:
        return None
    try:
        return datetime.strptime(match.group(0), "%d %B %Y").date()
    except ValueError:
        return None


def _term_range(text: str | None) -> tuple[date, date] | None:
    found = _DATE.findall(text or "")
    if len(found) < 2:
        return None
    start, end = _parse_date(found[0]), _parse_date(found[1])
    return (start, end) if start and end else None


def _parse_pdf(path: Path) -> tuple[str, dict, list[Section]]:
    title_lines, meta, sections = [], {}, []
    heading, page_of_heading, body = "Header", 1, []
    for page_no, page in enumerate(PdfReader(path).pages, 1):
        for raw in page.extract_text(extraction_mode="layout").splitlines():
            line = _clean_line(raw)
            if not line:
                continue
            if _HEADING.match(line):
                sections.append(Section(path.stem, heading, page_of_heading, "\n".join(body)))
                heading, page_of_heading, body = line, page_no, []
                continue
            meta_match = _META.match(line) if heading == "Header" else None
            if meta_match:
                meta[meta_match.group(1).strip().lower()] = meta_match.group(2).strip()
            elif heading == "Header" and not meta:
                title_lines.append(line)  # titles can wrap over several lines
            body.append(line)
    sections.append(Section(path.stem, heading, page_of_heading, "\n".join(body)))
    return " ".join(title_lines), meta, [s for s in sections if s.text or s.heading != "Header"]


def load_document(path: Path, today: date) -> Document:
    title, meta, sections = _parse_pdf(path)
    lower = title.lower()
    doc_type = next((t for t, words in config.DOC_TYPE_KEYWORDS if any(w in lower for w in words)), "product_guide")
    version = _VERSION.search(title)
    doc = Document(
        doc_id=path.stem,
        title=title,
        doc_type=doc_type,
        version=int(version.group(1)) if version else None,
        effective=_parse_date(meta.get("effective") or meta.get("updated") or meta.get("term")),
        account_id=meta.get("account"),
        meta=meta,
        sections=sections,
    )
    if doc_type == "contract":
        for s in sections:
            s.commercial = bool(_COMMERCIAL.search(f"{s.heading} {s.text}"))

    status = meta.get("status", "").upper()
    term = _term_range(meta.get("term"))
    if "DEPRECATED" in status or "SUPERSEDED" in status or "superseded by" in meta:
        doc.status, doc.status_reason = "deprecated", f"Header says: Status {meta.get('status')}"
    elif doc.effective and doc.effective > today and doc_type != "contract":
        doc.status, doc.status_reason = "not_yet_effective", f"Effective {doc.effective}, after the snapshot date"
    elif term and not term[0] <= today <= term[1]:
        doc.status, doc.status_reason = "expired", f"Contract term {term[0]} to {term[1]} does not cover {today}"
    return doc


def _mark_superseded(documents: list[Document]) -> None:
    """Of several current versions of the same document, only the newest stays current."""
    families: dict[tuple, list[Document]] = {}
    for doc in documents:
        if doc.usable:
            family = re.sub(r"\s+", " ", _VERSION.sub("", doc.title)).strip().lower()
            families.setdefault((doc.doc_type, doc.account_id, family), []).append(doc)
    for group in families.values():
        group.sort(key=lambda d: (d.effective or date.min, d.version or 0), reverse=True)
        for older in group[1:]:
            older.status, older.status_reason = "superseded", f"Newer version {group[0].doc_id} is current"


class Library:
    """All documents plus a BM25 index over their sections."""

    def __init__(self, documents: list[Document]):
        self.documents = {d.doc_id: d for d in documents}
        self._index = [
            (s, Counter(tokens(f"{d.title} {s.heading} {s.text}"))) for d in documents for s in d.sections
        ]
        doc_freq = Counter(t for _, tf in self._index for t in tf)
        n = len(self._index)
        self._idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in doc_freq.items()}
        self._avg_len = sum(sum(tf.values()) for _, tf in self._index) / max(n, 1)

    def search(self, query: str, k: int, include) -> list[tuple[float, Section]]:
        """Top-k sections whose document passes `include(doc)`."""
        terms = set(tokens(query))
        scored = []
        for section, tf in self._index:
            if not include(self.documents[section.doc_id]):
                continue
            norm = 1.2 * (0.25 + 0.75 * sum(tf.values()) / self._avg_len)
            score = sum(self._idf[t] * tf[t] * 2.2 / (tf[t] + norm) for t in terms if t in tf)
            if score > 0:
                scored.append((score, section))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return scored[:k]


def load_library(data_dir: Path | None = None, today: date | None = None) -> Library:
    data_dir = data_dir or config.DATA_DIR
    today = today or get_dataset().snapshot.date()
    documents = [load_document(p, today) for p in sorted(data_dir.glob("*.pdf"))]
    _mark_superseded(documents)
    return Library(documents)


@lru_cache(maxsize=1)
def get_library() -> Library:
    return load_library()
