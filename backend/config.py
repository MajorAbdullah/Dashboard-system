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

# --- LLM providers (OpenAI-compatible) ---
# Priority provider: "fireworks" (AMD-hardware-hosted, e.g. Gemma) or "openrouter".
# The other is used as an automatic fallback. See backend/llm.py for routing.
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "fireworks").strip().lower()

# Fireworks AI (primary) — models served on AMD hardware. Model IDs are
# account-scoped: "accounts/fireworks/models/<slug>". Override the two model
# vars to match whatever Gemma model the hackathon officially announces; the
# serverless catalog rotates, so a retired slug will 404 (and we fall back).
FIREWORKS_BASE = os.getenv("FIREWORKS_BASE", "https://api.fireworks.ai/inference/v1")
FIREWORKS_API_KEY = os.getenv("FIREWORKS_API_KEY", "")
FIREWORKS_MODEL_FAST = os.getenv(
    "FIREWORKS_MODEL_FAST", "accounts/fireworks/models/gemma-3-12b-it")
FIREWORKS_MODEL_STRONG = os.getenv(
    "FIREWORKS_MODEL_STRONG", "accounts/fireworks/models/gemma-3-12b-it")

# OpenRouter (fallback) — kept so the app still works without Fireworks credits.
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

# --- User-supplied DB connections (SSRF guard) ---
# Blocks connections to private/loopback/link-local hosts by default, since
# /api/db/test and /api/db/tables accept an arbitrary connection string from
# an unauthenticated onboarding flow. Flip to "true" only for local dev where
# the target Postgres genuinely lives on localhost/a private network.
ALLOW_PRIVATE_DB_HOSTS = os.getenv("ALLOW_PRIVATE_DB_HOSTS", "false").strip().lower() == "true"

# --- Redis cache ---
REDIS_URL = os.getenv("REDIS_URL", "")


def have_llm() -> bool:
    """True if any LLM provider (Fireworks or OpenRouter) is configured."""
    return bool(FIREWORKS_API_KEY or OPENROUTER_API_KEY)


def active_provider() -> str | None:
    """Name of the highest-priority provider that has a key, or None."""
    order = [("fireworks", FIREWORKS_API_KEY), ("openrouter", OPENROUTER_API_KEY)]
    if LLM_PROVIDER == "openrouter":
        order.reverse()
    for name, key in order:
        if key:
            return name
    return None


def have_openrouter() -> bool:  # kept for backward compatibility
    return bool(OPENROUTER_API_KEY)
