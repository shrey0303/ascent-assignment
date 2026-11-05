"""Loads the structured workbook (accounts, orders, tickets, README).

Nothing here knows specific IDs: sheets and columns are read from header rows, so a swapped
workbook with new records or extra columns loads the same way.
"""
import re
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

from openpyxl import load_workbook

from . import config

_TIME_COLUMN = re.compile(r"(_at|_start|_end|_time)$")
_SNAPSHOT = re.compile(r"(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2})(?::\d{2})?\s*([A-Za-z_]+/[A-Za-z_]+)?")


@dataclass
class Dataset:
    snapshot: datetime          # "now" for every time-based answer (timezone-aware)
    tz: ZoneInfo
    currency: str
    tables: dict[str, list[dict]]
    source_file: str

    def rows(self, table: str) -> list[dict]:
        return self.tables.get(table, [])


def find_workbook(data_dir: Path | None = None) -> Path:
    data_dir = data_dir or config.DATA_DIR
    books = sorted(p for p in data_dir.glob("*.xlsx") if not p.name.startswith("~$"))
    if not books:
        raise FileNotFoundError(f"No .xlsx workbook found in {data_dir}")
    if len(books) > 1:  # picking one silently could answer from stale data (A-18)
        raise RuntimeError(f"Found {len(books)} workbooks in {data_dir} ({', '.join(p.name for p in books)}); keep only one.")
    return books[0]


def _parse_time(value, tz: ZoneInfo):
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=tz)
    if isinstance(value, str):
        match = _SNAPSHOT.match(value.strip())
        if match:
            return datetime.fromisoformat(match.group(1).replace(" ", "T")).replace(tzinfo=tz)
    return value


def _clean(column: str, value, tz: ZoneInfo):
    if isinstance(value, str):
        value = value.strip() or None
    if value is not None and _TIME_COLUMN.search(column):
        value = _parse_time(value, tz)
    return value


def _read_readme(rows: list[tuple]) -> dict[str, object]:
    return {str(r[0]).strip().lower(): r[1] for r in rows if r and r[0] is not None and len(r) > 1}


def load_dataset(path: Path | None = None) -> Dataset:
    path = path or find_workbook()
    book = load_workbook(path, read_only=True, data_only=True)
    sheets = {
        ws.title.strip().lower(): [r for r in ws.iter_rows(values_only=True) if any(c not in (None, "") for c in r)]
        for ws in book.worksheets
    }
    book.close()

    readme = _read_readme(sheets.pop("readme", []))
    snapshot_value = next((v for k, v in readme.items() if "snapshot" in k), None)
    if snapshot_value is None:
        raise ValueError("README sheet has no snapshot time; it defines 'now' for all calculations")
    if isinstance(snapshot_value, datetime):
        tz = ZoneInfo(config.FALLBACK_TIMEZONE)
        snapshot = _parse_time(snapshot_value, tz)
    else:
        match = _SNAPSHOT.search(str(snapshot_value))
        if not match:
            raise ValueError(f"Cannot parse snapshot time: {snapshot_value!r}")
        tz = ZoneInfo(match.group(2) or config.FALLBACK_TIMEZONE)
        snapshot = datetime.fromisoformat(match.group(1).replace(" ", "T")).replace(tzinfo=tz)

    tables = {}
    for name, rows in sheets.items():
        if not rows:
            continue
        header = [str(h).strip().lower() if h is not None else None for h in rows[0]]
        tables[name] = [
            {col: _clean(col, value, tz) for col, value in zip(header, row) if col}
            for row in rows[1:]
        ]

    currency = str(next((v for k, v in readme.items() if "currency" in k), "INR"))
    return Dataset(snapshot=snapshot, tz=tz, currency=currency, tables=tables, source_file=path.name)


@lru_cache(maxsize=1)
def get_dataset() -> Dataset:
    return load_dataset()
