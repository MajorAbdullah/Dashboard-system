"""Cache layer — Redis-backed (JSON + TTL), with an in-memory fallback if Redis is
unavailable so the app always boots. Keys: per-subquery retrieval results, dataset profiles."""
from __future__ import annotations

import json
import re

from cachetools import TTLCache

import config

_QUERY_TTL = 3600      # 1h
_PROFILE_TTL = 86400   # 24h

# in-memory fallback
_mem_query: TTLCache = TTLCache(maxsize=2000, ttl=_QUERY_TTL)
_mem_profile: TTLCache = TTLCache(maxsize=200, ttl=_PROFILE_TTL)

_redis = None
_redis_ok = False
try:
    if config.REDIS_URL:
        import redis as _redislib
        _redis = _redislib.from_url(config.REDIS_URL, decode_responses=True, socket_connect_timeout=2)
        _redis.ping()
        _redis_ok = True
except Exception as e:  # pragma: no cover
    print(f"[cache] Redis unavailable ({e}); using in-memory fallback.")
    _redis_ok = False


def backend() -> str:
    return "redis" if _redis_ok else "memory"


def normalize(q: str) -> str:
    return re.sub(r"\s+", " ", (q or "").strip().lower())


def query_key(dataset_id: int, query: str, top_k: int) -> str:
    return f"q:{dataset_id}:{normalize(query)}:{top_k}"


def _get(key: str, mem: TTLCache):
    if _redis_ok:
        try:
            v = _redis.get(key)
            return json.loads(v) if v is not None else None
        except Exception:
            pass
    return mem.get(key)


def _set(key: str, value, ttl: int, mem: TTLCache):
    if _redis_ok:
        try:
            _redis.setex(key, ttl, json.dumps(value))
            return
        except Exception:
            pass
    mem[key] = value


# ---- query results ----
def get_query(dataset_id: int, query: str, top_k: int):
    return _get(query_key(dataset_id, query, top_k), _mem_query)


def set_query(dataset_id: int, query: str, top_k: int, chunks: list) -> None:
    _set(query_key(dataset_id, query, top_k), chunks, _QUERY_TTL, _mem_query)


# ---- dataset profiles (stored as dict; profiler re-validates) ----
def get_profile(dataset_id: int):
    return _get(f"profile:{dataset_id}", _mem_profile)


def set_profile(dataset_id: int, profile) -> None:
    data = profile.model_dump() if hasattr(profile, "model_dump") else profile
    _set(f"profile:{dataset_id}", data, _PROFILE_TTL, _mem_profile)
