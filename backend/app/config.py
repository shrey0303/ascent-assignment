"""Single place for runtime settings and for business assumptions the data pack does not state.

Every value here can be overridden by an environment variable (or a `.env` file at the repo root).
Assumptions are numbered (A-xx) and explained in docs/ASSUMPTIONS.md.
"""
import os
from datetime import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load_dotenv(path: Path) -> None:
    """Minimal .env reader so local runs need no extra dependency. Real env vars win."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


_load_dotenv(ROOT / ".env")

# --- Paths ---
DATA_DIR = Path(os.getenv("DATA_DIR", ROOT / "data"))
DB_PATH = Path(os.getenv("DB_PATH", ROOT / "var" / "app.db"))
TERMS_CACHE = Path(os.getenv("TERMS_CACHE", ROOT / "cache" / "terms.json"))

# --- Security ---
APP_ENV = os.getenv("APP_ENV", "development")
DEFAULT_SECRET_KEY = "dev-only-secret-change-me"
SECRET_KEY = os.getenv("SECRET_KEY", DEFAULT_SECRET_KEY)
DEMO_PASSWORD = os.getenv("DEMO_PASSWORD", "demo123")
SESSION_TTL_MINUTES = 12 * 60
CONFIRMATION_TTL_MINUTES = 15


def check_production_secrets() -> None:
    """The repo is public, so the default key is public: a deployment using it would accept forged tokens."""
    if APP_ENV == "production" and (SECRET_KEY == DEFAULT_SECRET_KEY or len(SECRET_KEY) < 32):
        raise RuntimeError("Set SECRET_KEY to a random value of at least 32 characters before running in production.")

# --- LLM (any OpenAI-compatible endpoint: Groq, OpenRouter, local vLLM/Ollama...) ---
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.groq.com/openai/v1")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "openai/gpt-oss-120b")
LLM_PRICE_IN_PER_M = float(os.getenv("LLM_PRICE_IN_PER_M", "0.15"))   # USD per 1M input tokens
LLM_PRICE_OUT_PER_M = float(os.getenv("LLM_PRICE_OUT_PER_M", "0.60"))  # USD per 1M output tokens
LLM_REASONING_EFFORT = os.getenv("LLM_REASONING_EFFORT", "")          # only sent if set (reasoning models)
LLM_TIMEOUT_SECONDS = 30
AGENT_MAX_STEPS = 6            # max LLM round-trips per user message
TOOL_OUTPUT_MAX_CHARS = 6000   # tool results are truncated before going back to the model
HISTORY_MAX_MESSAGES = 16      # earlier turns kept for follow-up questions

# --- Business calendar (A-01, A-02): no document defines business hours ---
FALLBACK_TIMEZONE = "Asia/Kolkata"   # used only if the workbook README has no timezone
BUSINESS_DAYS = {0, 1, 2, 3, 4}      # Monday-Friday
BUSINESS_START = time(9, 0)
BUSINESS_END = time(18, 0)

# --- Source precedence (from the brief and the support policy's precedence rule). Lower index wins. ---
SOURCE_PRECEDENCE = ["contract", "policy", "sop", "product_guide", "historical_ticket"]

# Document type is inferred from the document title, first match wins (A-05).
DOC_TYPE_KEYWORDS = [
    ("contract", ("agreement", "contract")),
    ("sop", ("sop", "procedure")),
    ("policy", ("policy",)),
    ("product_guide", ("guide", "known issues", "documentation")),
]

# --- Severity (A-06): tickets carry no severity column, so it is derived from the
# Support Policy definitions with generic keyword rules (vocabulary of the definitions plus common
# synonyms, never ticket wording). A `severity`/`priority` column wins if present.
SEVERITY_RULES = [
    ("P1", "security incident or credential exposure",
     ("security incident", "exposure", "exposed", "data breach", "leaked", "compromised")),
    ("P1", "complete outage of shipment creation",
     ("all shipment creation", "outage", "completely down")),
    ("P2", "major feature failing or degraded",
     ("fails", "failing", "failure", "error", "degraded", "unavailable", "not working")),
]
DEFAULT_SEVERITY = ("P3", "minor issue, how-to or configuration request")
