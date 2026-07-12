"""In-memory session store: session_id -> {global_key, dataset, profile}.

Keeps the user's Inflectiv global key server-side after the Connect screen. The
browser only ever holds the opaque session_id.
"""
from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Optional

from schemas import DatasetProfile


@dataclass
class Session:
    session_id: str
    global_key: str = ""
    dataset_id: int = 0
    dataset_name: str = ""
    profile: Optional[DatasetProfile] = None
    knowledge_source_count: int = 0
    source_type: str = "inflectiv"
    conn_string: str = ""
    table_name: str = ""
    record_count: int = 0


_sessions: dict[str, Session] = {}


def create(global_key: str = "", dataset: Optional[dict] = None,
           source_type: str = "inflectiv", conn_string: str = "",
           table_name: str = "") -> Session:
    sid = "sess_" + secrets.token_urlsafe(16)
    ks_count = dataset.get("knowledge_source_count", 0) if dataset else 0
    s = Session(
        session_id=sid,
        global_key=global_key,
        dataset_id=dataset["id"] if dataset else 0,
        dataset_name=dataset.get("name", "") if dataset else table_name,
        knowledge_source_count=ks_count,
        source_type=source_type,
        conn_string=conn_string,
        table_name=table_name,
        record_count=ks_count,
    )
    _sessions[sid] = s
    return s


def get(session_id: str) -> Optional[Session]:
    return _sessions.get(session_id)
