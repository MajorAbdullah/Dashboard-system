"""Central configuration. Secrets come from backend/.env (never committed)."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

# --- Inflectiv (data source) ---
INFLECTIV_BASE = os.getenv("INFLECTIV_BASE", "https://app.inflectiv.ai/api/platform")
# Optional fallback key for quick local testing; the real flow passes the key per-session
# via the Connect screen, so this is only a convenience default.
INFLECTIV_FALLBACK_KEY = os.getenv("INFLECTIV_API_KEY", "")

# --- OpenRouter (LLM) ---
OPENROUTER_BASE = os.getenv("OPENROUTER_BASE", "https://openrouter.ai/api/v1")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
# Fast model for planning/structuring (many small calls); strong model for summaries.
OPENROUTER_MODEL_FAST = os.getenv("OPENROUTER_MODEL_FAST", "anthropic/claude-3.5-haiku")
OPENROUTER_MODEL_STRONG = os.getenv("OPENROUTER_MODEL_STRONG", "anthropic/claude-3.5-sonnet")

# --- Retrieval tuning ---
DEFAULT_TOP_K = int(os.getenv("DEFAULT_TOP_K", "30"))
DEFAULT_SCORE_THRESHOLD = float(os.getenv("DEFAULT_SCORE_THRESHOLD", "0.2"))

# --- CORS: the dc-runtime page origin(s). "*" is fine for the local hackathon demo. ---
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*").split(",")

# --- Database (Postgres) ---
DATABASE_URL = os.getenv("DATABASE_URL", "")

# --- Redis cache ---
REDIS_URL = os.getenv("REDIS_URL", "")


def have_openrouter() -> bool:
    return bool(OPENROUTER_API_KEY)
