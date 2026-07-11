"""Postgres layer (demo-grade). One module-level connection, autocommit, dict rows.

Local dev points DATABASE_URL at a docker Postgres; on Railway it's auto-injected.
Flexible objects are stored as JSONB.
"""
from __future__ import annotations

from typing import Any, Optional

import psycopg2
import psycopg2.extras

import config

_conn = None


def _connect():
    global _conn
    if _conn is not None and _conn.closed == 0:
        return _conn
    if not config.DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not set")
    # Railway sometimes provides postgres:// — psycopg2 wants postgresql://
    dsn = config.DATABASE_URL.replace("postgres://", "postgresql://", 1)
    _conn = psycopg2.connect(dsn)
    _conn.autocommit = True
    return _conn


def _cur():
    return _connect().cursor(cursor_factory=psycopg2.extras.RealDictCursor)


def query(sql: str, params: tuple = ()) -> list[dict]:
    with _cur() as c:
        c.execute(sql, params)
        return [dict(r) for r in c.fetchall()]


def one(sql: str, params: tuple = ()) -> Optional[dict]:
    with _cur() as c:
        c.execute(sql, params)
        r = c.fetchone()
        return dict(r) if r else None


def execute(sql: str, params: tuple = ()) -> Optional[dict]:
    """Run a write. If the SQL has RETURNING, return that row."""
    with _cur() as c:
        c.execute(sql, params)
        if c.description:
            r = c.fetchone()
            return dict(r) if r else None
        return None


def Json(obj: Any):
    return psycopg2.extras.Json(obj)


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id SERIAL PRIMARY KEY,
  email TEXT UNIQUE NOT NULL,
  name TEXT,
  company TEXT,
  pw_hash TEXT NOT NULL,
  pw_salt TEXT NOT NULL,
  api_token TEXT UNIQUE NOT NULL,
  inflectiv_key TEXT,
  inflectiv_dataset_id INTEGER,
  inflectiv_dataset_name TEXT,
  onboarding JSONB,
  ai_prefs JSONB,
  settings JSONB,
  role TEXT DEFAULT 'owner',
  created_at TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE IF NOT EXISTS dashboards (
  id SERIAL PRIMARY KEY,
  user_id INTEGER NOT NULL,
  name TEXT NOT NULL,
  widgets JSONB NOT NULL,
  dataset_id INTEGER,
  dataset_name TEXT,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE IF NOT EXISTS saved_components (
  id SERIAL PRIMARY KEY,
  user_id INTEGER NOT NULL,
  spec JSONB NOT NULL,
  goal TEXT,
  type TEXT,
  fav BOOLEAN DEFAULT false,
  dataset_name TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE IF NOT EXISTS saved_insights (
  id SERIAL PRIMARY KEY,
  user_id INTEGER NOT NULL,
  spec JSONB NOT NULL,
  headline TEXT,
  tone TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE IF NOT EXISTS activity_log (
  id SERIAL PRIMARY KEY,
  user_id INTEGER NOT NULL,
  kind TEXT NOT NULL,
  detail TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE IF NOT EXISTS team_members (
  id SERIAL PRIMARY KEY,
  owner_id INTEGER NOT NULL,
  email TEXT NOT NULL,
  name TEXT,
  role TEXT DEFAULT 'member',
  status TEXT DEFAULT 'active',
  created_at TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE IF NOT EXISTS api_keys (
  id SERIAL PRIMARY KEY,
  user_id INTEGER NOT NULL,
  label TEXT,
  token TEXT NOT NULL,
  created_at TIMESTAMPTZ DEFAULT now(),
  last_used TIMESTAMPTZ
);
"""


def init_db() -> None:
    with _cur() as c:
        c.execute(SCHEMA)
        # additive columns for existing DBs
        c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS workspace JSONB;")
        c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS db_type TEXT;")
        c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS db_connection_string TEXT;")
        c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS db_table_name TEXT;")


def reset_db() -> None:
    """Dev only — drops all app tables."""
    with _cur() as c:
        c.execute(
            "DROP TABLE IF EXISTS users, dashboards, saved_components, saved_insights, "
            "activity_log, team_members, api_keys CASCADE;"
        )
    init_db()


def log_activity(user_id: int, kind: str, detail: str = "") -> None:
    try:
        execute("INSERT INTO activity_log (user_id, kind, detail) VALUES (%s,%s,%s)",
                (user_id, kind, detail))
    except Exception:
        pass
