"""Single place for runtime settings and for business assumptions the data pack does not state.

Every value here can be overridden by an environment variable (or a `.env` file at the repo root).
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
# OpenRouter only: serve every call from this one upstream provider (e.g. "groq"), no fallback, so quality,
# latency and price do not change from call to call. Empty = the endpoint's own routing.
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "")
# Output cap per call (reasoning included). Bounds the cost of one call; OpenRouter also reserves this many
# tokens against the key's spend limit before answering, so leaving it unset there can refuse small budgets.
LLM_MAX_OUTPUT_TOKENS = int(os.getenv("LLM_MAX_OUTPUT_TOKENS", "8192"))
LLM_TIMEOUT_SECONDS = 30
LLM_MAX_RETRY_WAIT_SECONDS = 60  # per-minute limits clear within this; a longer wait (daily cap) fails fast
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

# --- Classifier (classify.py): meaning-level labels (document type, in force, commercial sections, ticket
# severity, what the user asks for) come from a model applying the documents' own rules, never keyword lists.
# Same OpenAI-compatible endpoint and key as the agent; the model is a setting (A/B: evals/labels_check.py).
# gpt-oss-safeguard-20b: OpenAI's open-weight model trained to classify text against a written policy.
CLASSIFIER_MODEL = os.getenv("CLASSIFIER_MODEL", "openai/gpt-oss-safeguard-20b")  # document and ticket labels (made once)
INTENT_MODEL = os.getenv("INTENT_MODEL", "openai/gpt-oss-20b")          # per-turn request check (latency, rate)
CLASSIFIER_PRICE_IN_PER_M = float(os.getenv("CLASSIFIER_PRICE_IN_PER_M", "0.075"))
CLASSIFIER_PRICE_OUT_PER_M = float(os.getenv("CLASSIFIER_PRICE_OUT_PER_M", "0.30"))
CLASSIFIER_REASONING_EFFORT = os.getenv("CLASSIFIER_REASONING_EFFORT", "medium")
CLASSIFIER_TEMPERATURE = float(os.getenv("CLASSIFIER_TEMPERATURE", "1.0"))  # sampled runs, so the vote means something
LABEL_VOTES = int(os.getenv("LABEL_VOTES", "5"))     # document and ticket labels (decided once per text version)
# Share of runs that must agree on a label made once (> 0.75 of 5 = 4 runs); a closer vote is undecided and the
# caller fails closed (for severity: the strictest code the runs chose, marked NEEDS REVIEW).
LABEL_AGREEMENT = float(os.getenv("LABEL_AGREEMENT", "0.75"))
INTENT_VOTES = int(os.getenv("INTENT_VOTES", "3"))   # the per-turn request check
# Answer check (classify.answer_support): before an answer is shown, every sentence must be backed by this turn's
# tool results or the earlier reply; runs vote, disagreement = unsupported. Its own setting, not LLM_MODEL, so a
# chat-model comparison keeps the same check. 120b: 16/16 on evals/answer_check_gold.json; the 20b models 14/16,
# both missing a value moved onto a different thing (the case the check exists for).
# Off by default: in the 8 Nov eval it still removed correct facts and made single-tool answers take 12-27 s (target
# under 6 s), so it was rejected for the submission (see EVALUATION.md). The code stays for the roadmap.
ANSWER_CHECK_ENABLED = os.getenv("ANSWER_CHECK_ENABLED", "false").lower() == "true"
ANSWER_CHECK_MODEL = os.getenv("ANSWER_CHECK_MODEL", "openai/gpt-oss-120b")
ANSWER_CHECK_VOTES = int(os.getenv("ANSWER_CHECK_VOTES", "3"))
ANSWER_CHECK_REASONING_EFFORT = os.getenv("ANSWER_CHECK_REASONING_EFFORT", "low")  # low scored the same as medium
ANSWER_CHECK_PRICE_IN_PER_M = float(os.getenv("ANSWER_CHECK_PRICE_IN_PER_M", "0.15"))   # gpt-oss-120b on Groq
ANSWER_CHECK_PRICE_OUT_PER_M = float(os.getenv("ANSWER_CHECK_PRICE_OUT_PER_M", "0.60"))
LABELS_CACHE = Path(os.getenv("LABELS_CACHE", ROOT / "cache" / "labels.json"))
# Prompt-injection scan of retrieved text (a warning signal; the request check is what blocks actions).
INJECTION_MODEL = os.getenv("INJECTION_MODEL", "meta-llama/llama-prompt-guard-2-86m")
# Prompt Guard is not on every endpoint (OpenRouter has none), so it may use its own endpoint and key.
INJECTION_BASE_URL = os.getenv("INJECTION_BASE_URL", "") or LLM_BASE_URL
INJECTION_API_KEY = os.getenv("INJECTION_API_KEY", "") or LLM_API_KEY
INJECTION_PRICE_PER_M = float(os.getenv("INJECTION_PRICE_PER_M", "0.04"))
INJECTION_THRESHOLD = float(os.getenv("INJECTION_THRESHOLD", "0.5"))
INJECTION_CHUNK_CHARS = 1500  # the model reads at most 512 tokens
