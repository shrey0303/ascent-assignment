"""PDF ingestion, document metadata (type, status, version) and keyword retrieval (BM25).

Layout is parsed in code: title, sections (numbered headings, or short capitalised lines when a document has
none) and table rows. What the text means and states is read by the classifier (classify.document_labels):
type, whether it is in force, commercial contract sections, and the customer account, version, effective date
and contract term, each checked against the document. Dates are then parsed in code in several formats. Nothing
is taken from file names or keyword lists, so new document versions and layouts are handled the same way.
"""
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path

from pypdf import PdfReader

from . import classify, config
from .data import get_dataset

_HEADING = re.compile(r"^\d+(?:\.\d+)*\.?\s+[A-Z]")
_META = re.compile(r"^([A-Z][A-Za-z ]{1,30}):\s*(.+)$")
_TABLE_GAP = re.compile(r"\s{8,}")
_STOP = set(
    "a an and are as at be by can do does for from has have how i if in is it its may me my of on or our "
    "that the their then this to was we what when which who will with you your".split()
)


def tokens(text: str) -> list[str]:
    """Lowercase words, stop words removed, cut to 5 chars as a cheap stemmer (cancel/cancellation)."""
    return [w[:5] for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in _STOP]


def _singular(word: str) -> str:
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 4 and word.endswith(("ses", "xes", "zes", "ches", "shes")):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def words(text: str) -> set[str]:
    """Whole words in singular form, for checking whether a term appears at all. The 5-letter stems used for
    ranking are too loose for that ("tablet" would match "tables", "interval" "intervention")."""
    return {_singular(w) for w in re.findall(r"[a-z]+", text.lower()) if w not in _STOP}


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
    status: str = "current"  # current | deprecated | superseded | expired | not_yet_effective | unclassified
    status_reason: str = ""
    labels: dict = field(default_factory=dict)  # classifier output with quotes (classify.document_labels)

    @property
    def tier(self) -> int:
        order = config.SOURCE_PRECEDENCE
        return order.index(self.doc_type) if self.doc_type in order else len(order)

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


# Date formats documents use; numeric dates are read day first (A-02: an India-based operation).
_DATE_FORMATS = [
    (re.compile(r"\d{1,2}\s+[A-Za-z]+,?\s+\d{4}"), ("%d %B %Y", "%d %b %Y")),
    (re.compile(r"[A-Za-z]+\s+\d{1,2},?\s+\d{4}"), ("%B %d %Y", "%b %d %Y")),
    (re.compile(r"\d{4}-\d{2}-\d{2}"), ("%Y-%m-%d",)),
    (re.compile(r"\d{1,2}[/.-]\d{1,2}[/.-]\d{4}"), ("%d/%m/%Y",)),
]


def parse_date(text: str | None) -> date | None:
    """The first date in the text, in any of the formats above; None if there is none."""
    text = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", text or "")
    for pattern, formats in _DATE_FORMATS:
        for match in pattern.finditer(text):
            value = re.sub(r"[.-]", "/", match.group(0)) if "%d/%m/%Y" in formats else match.group(0).replace(",", "")
            for fmt in formats:
                try:
                    return datetime.strptime(value, fmt).date()
                except ValueError:
                    continue
    return None


def _version_number(value: str | None) -> int | None:
    digits = re.search(r"\d+", value or "")
    return int(digits.group(0)) if digits else None


def _looks_like_heading(line: str) -> bool:
    """For documents without numbered headings: a short, capitalised line that is not a sentence or field."""
    words = line.split()
    return (0 < len(words) <= 8 and line[0].isupper() and not line.endswith((".", ":", ";", ","))
            and ":" not in line and "|" not in line)


def _parse_lines(stem: str, lines: list[tuple[int, str]]) -> tuple[str, dict, list[Section]]:
    """Title (lines before the first 'Field: value'), header fields, and sections. Headings are numbered lines
    ("4. Refund rules"); a document with fewer than two of them uses short capitalised lines instead."""
    numbered = sum(bool(_HEADING.match(line)) for _, line in lines) >= 2
    title_lines, meta, sections = [], {}, []
    heading, page_of_heading, body = "Header", 1, []
    for page_no, line in lines:
        header_done = bool(meta) or len(body) >= 3
        if _HEADING.match(line) if numbered else (header_done and _looks_like_heading(line)):
            sections.append(Section(stem, heading, page_of_heading, "\n".join(body)))
            heading, page_of_heading, body = line, page_no, []
            continue
        meta_match = _META.match(line) if heading == "Header" else None
        if meta_match:
            meta[meta_match.group(1).strip().lower()] = meta_match.group(2).strip()
        elif heading == "Header" and not meta:
            title_lines.append(line)  # titles can wrap over several lines
        body.append(line)
    sections.append(Section(stem, heading, page_of_heading, "\n".join(body)))
    return " ".join(title_lines), meta, [s for s in sections if s.text or s.heading != "Header"]


def _parse_pdf(path: Path) -> tuple[str, dict, list[Section]]:
    lines = [(page_no, line) for page_no, page in enumerate(PdfReader(path).pages, 1)
             for line in map(_clean_line, page.extract_text(extraction_mode="layout").splitlines()) if line]
    return _parse_lines(path.stem, lines)


def load_document(path: Path, today: date) -> Document:
    title, meta, sections = _parse_pdf(path)
    return document_from_parts(path.stem, title, meta, sections, today)


def document_from_parts(doc_id: str, title: str, meta: dict, sections: list[Section], today: date) -> Document:
    """Labels and status for a parsed document. Type, in force, commercial sections and the metadata values
    (account, version, dates, term) all come from classify.document_labels: each value is checked against the
    document text and agreed by the runs; dates are then parsed in code. Anything undecided fails closed."""
    doc = Document(doc_id=doc_id, title=title, doc_type="unclassified", version=None, effective=None,
                   account_id=None, meta=meta, sections=sections)
    labels = classify.document_labels(doc.doc_id, title, doc.text, [(s.heading, s.text) for s in sections])
    found = labels.get("meta") or {}
    doc.doc_type = labels["doc_type"] or "unclassified"
    doc.labels = labels
    doc.account_id = found.get("account_id")
    doc.version = _version_number(found.get("version"))
    term = [parse_date(found.get("term_start")), parse_date(found.get("term_end"))]
    doc.effective = parse_date(found.get("effective")) or term[0]
    if doc.doc_type == "contract":
        for s, commercial in zip(sections, labels["commercial"]):
            s.commercial = commercial

    needed = ["doc_type", "in_force", "version", "effective"]
    if doc.doc_type == "contract":
        # A contract's dates are its term; an undecided separate effective date falls back to the term start.
        needed = ["doc_type", "in_force", "version", "account_id", "term_start", "term_end"]
    unparsed = [name for name in ("effective", "term_start", "term_end")
                if found.get(name) and parse_date(found[name]) is None]
    problems = [n for n in needed if n in labels.get("undecided", [])] + unparsed
    if doc.doc_type == "contract" and not doc.account_id and "account_id" not in problems:
        problems.append("account_id (no customer stated)")
    if problems:
        doc.status = "unclassified"
        doc.status_reason = ("Not used until a person reviews it: could not decide " + ", ".join(problems))
    elif labels["in_force"] is False:
        doc.status, doc.status_reason = "deprecated", f"The document says: \"{labels['in_force_quote']}\""
    elif doc.effective and doc.effective > today and doc.doc_type != "contract":
        doc.status, doc.status_reason = "not_yet_effective", f"Effective {doc.effective}, after the snapshot date"
    elif (term[0] and today < term[0]) or (term[1] and today > term[1]):
        doc.status, doc.status_reason = "expired", f"Contract term {term[0]} to {term[1]} does not cover {today}"
    return doc


def _family(doc: Document) -> str:
    """The title without its version, so 'Policy v3' and 'Policy Version 4' are the same document family."""
    title = doc.title
    if doc.version is not None:
        title = re.sub(rf"(?i)\b(?:v|ver\.?|version|rev\.?|revision)?\s*{doc.version}\b", " ", title, count=1)
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def _mark_superseded(documents: list[Document]) -> None:
    """Of several current versions of the same document, only the newest stays current."""
    families: dict[tuple, list[Document]] = {}
    for doc in documents:
        if doc.usable:
            families.setdefault((doc.doc_type, doc.account_id, _family(doc)), []).append(doc)
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

    def missing_words(self, query: str, include) -> list[str]:
        """Words of the query (4+ letters) that appear in no section `include(doc, section)` accepts. Ranking
        always returns something; this says when the documents do not mention the topic at all."""
        found = set()
        for section, _ in self._index:
            doc = self.documents[section.doc_id]
            if include(doc, section):
                found |= words(f"{doc.title} {section.heading} {section.text}")
        asked = dict.fromkeys(_singular(w) for w in re.findall(r"[a-z]+", query.lower()) if w not in _STOP)
        return [w for w in asked if len(w) >= 4 and w not in found]


def load_library(data_dir: Path | None = None, today: date | None = None) -> Library:
    data_dir = data_dir or config.DATA_DIR
    today = today or get_dataset().snapshot.date()
    documents = [load_document(p, today) for p in sorted(data_dir.glob("*.pdf"))]
    _mark_superseded(documents)
    return Library(documents)


@lru_cache(maxsize=1)
def get_library() -> Library:
    return load_library()
