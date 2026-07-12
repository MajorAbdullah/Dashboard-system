"""Data-readiness guardrail: decides whether a session has real, queryable
data before chart/chat generation runs the (costly) retrieval + LLM pipeline.
"""
from __future__ import annotations

from typing import Literal, Optional

from sessions import Session

ReadinessState = Literal["not_connected", "no_source_data", "unreachable", "ready"]

READINESS_MESSAGES: dict[str, str] = {
    "not_connected": "Connect a data source to get started.",
    "no_source_data": "The connected source has no data yet — check your dataset or table.",
    "unreachable": "Could not reach the connected data source. Try again in a moment.",
}


def classify_readiness(session: Optional[Session]) -> ReadinessState:
    """Pure classification — no I/O. 'unreachable' is never returned here; the
    route handler reports it itself when a retrieval call raises (see main.py)."""
    if session is None:
        return "not_connected"
    if session.record_count <= 0:
        return "no_source_data"
    return "ready"
