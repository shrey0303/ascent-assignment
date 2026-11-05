"""SQLite store for everything the app writes: audit trail, actions, pending confirmations,
conversations and LLM usage. The workbook itself is read-only input."""
import sqlite3
import threading
from functools import lru_cache
from pathlib import Path

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL, user_id TEXT, role TEXT, conversation_id TEXT,
    event TEXT NOT NULL, name TEXT, input TEXT, output TEXT, decision TEXT
);
CREATE TABLE IF NOT EXISTS pending_actions (
    preview_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, action TEXT NOT NULL,
    payload TEXT NOT NULL, payload_hash TEXT NOT NULL, expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS actions (
    id TEXT PRIMARY KEY, idempotency_key TEXT NOT NULL UNIQUE, action TEXT NOT NULL,
    payload TEXT NOT NULL, created_by TEXT NOT NULL, confirmed_by TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY, user_id TEXT NOT NULL, messages TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS llm_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, conversation_id TEXT, model TEXT,
    input_tokens INTEGER, output_tokens INTEGER, cost_usd REAL, latency_ms INTEGER
);
"""


class Database:
    def __init__(self, path: Path | str):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._conn.executescript(SCHEMA)

    def execute(self, sql: str, params: tuple = ()) -> int:
        """Run one write in its own transaction. Raises sqlite3.IntegrityError on UNIQUE clashes."""
        with self._lock, self._conn:
            return self._conn.execute(sql, params).rowcount

    def query(self, sql: str, params: tuple = ()) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, params).fetchall()]


@lru_cache(maxsize=1)
def get_db() -> Database:
    return Database(config.DB_PATH)
