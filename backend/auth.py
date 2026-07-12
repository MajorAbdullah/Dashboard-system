"""Demo-grade auth: sha256(salt+password) + opaque bearer token stored on the user row."""
from __future__ import annotations

import hashlib
import re
import secrets
from typing import Optional

from fastapi import Header, HTTPException

import db


def make_salt() -> str:
    return secrets.token_hex(8)


def hash_pw(password: str, salt: str) -> str:
    return hashlib.sha256((salt + (password or "")).encode()).hexdigest()


def make_token() -> str:
    return secrets.token_urlsafe(24)


def verify_pw(user: dict, password: str) -> bool:
    return hash_pw(password, user.get("pw_salt", "")) == user.get("pw_hash")


def _token_from_header(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    return authorization[7:].strip() if authorization.lower().startswith("bearer ") else authorization.strip()


def current_user(authorization: Optional[str] = Header(None)) -> dict:
    """FastAPI dependency — raises 401 if no valid token."""
    token = _token_from_header(authorization)
    if not token:
        raise HTTPException(401, "Not authenticated")
    user = db.one("SELECT * FROM users WHERE api_token=%s", (token,))
    if not user:
        raise HTTPException(401, "Invalid or expired session")
    return user


def optional_user(authorization: Optional[str] = Header(None)) -> Optional[dict]:
    """Soft variant — returns the user if a valid token is present, else None (no error)."""
    token = _token_from_header(authorization)
    if not token:
        return None
    return db.one("SELECT * FROM users WHERE api_token=%s", (token,))


def _mask_conn_string(cs: Optional[str]) -> Optional[str]:
    """host/db only, credentials and full path stripped — safe to send to the browser."""
    if not cs:
        return None
    masked = re.sub(r"//.*?@", "//***:***@", cs)
    masked = re.sub(r"/[^/]+$", "/***", masked)
    return masked


def public_user(user: dict) -> dict:
    """Strip secrets for client responses."""
    if not user:
        return {}
    return {
        "id": user["id"], "email": user["email"], "name": user.get("name"),
        "company": user.get("company"), "role": user.get("role"),
        "inflectiv_dataset_id": user.get("inflectiv_dataset_id"),
        "inflectiv_dataset_name": user.get("inflectiv_dataset_name"),
        "has_key": bool(user.get("inflectiv_key")),
        "db_type": user.get("db_type"),
        "db_host_masked": _mask_conn_string(user.get("db_connection_string")),
        "db_table_name": user.get("db_table_name"),
        "has_db": bool(user.get("db_connection_string")),
        "ai_prefs": user.get("ai_prefs"), "onboarding": user.get("onboarding"),
        "created_at": str(user.get("created_at") or ""),
    }
