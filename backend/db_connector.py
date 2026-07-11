"""PostgreSQL connector for direct database mode.
Handles connection, schema introspection, and read-only SQL execution.
"""
from __future__ import annotations

import re
from typing import Any

import psycopg2
import psycopg2.extras


class DbConnectorError(RuntimeError):
    pass


def _connect(conn_string: str):
    try:
        dsn = conn_string.replace("postgres://", "postgresql://", 1)
        conn = psycopg2.connect(dsn)
        conn.autocommit = True
        return conn
    except Exception as e:
        raise DbConnectorError(f"Connection failed: {e}")


def test_connection(conn_string: str) -> dict:
    try:
        conn = _connect(conn_string)
        with conn.cursor() as c:
            c.execute("SELECT 1 AS ok")
            r = c.fetchone()
        conn.close()
        return {"ok": True, "server": conn.server_version if hasattr(conn, 'server_version') else "unknown"}
    except DbConnectorError as e:
        return {"ok": False, "error": str(e)}


def list_tables(conn_string: str) -> list[dict]:
    conn = _connect(conn_string)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as c:
            c.execute(
                """SELECT table_name,
                          (SELECT reltuples::bigint FROM pg_class WHERE oid::regclass::text = t.table_name) AS row_estimate
                   FROM information_schema.tables t
                   WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
                   ORDER BY table_name"""
            )
            return [dict(r) for r in c.fetchall()]
    finally:
        conn.close()


def get_table_schema(conn_string: str, table_name: str) -> dict:
    conn = _connect(conn_string)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as c:
            c.execute(
                """SELECT column_name, data_type, is_nullable,
                          COALESCE(character_maximum_length::text, '') AS max_length
                   FROM information_schema.columns
                   WHERE table_schema = 'public' AND table_name = %s
                   ORDER BY ordinal_position""",
                (table_name,),
            )
            columns = [dict(r) for r in c.fetchall()]

            c.execute("SELECT COUNT(*) AS n FROM " + _quote(table_name))
            row_count = c.fetchone()["n"]

            # Foreign keys
            c.execute(
                """SELECT kcu.column_name,
                          ccu.table_name AS ref_table,
                          ccu.column_name AS ref_column
                   FROM information_schema.table_constraints tc
                   JOIN information_schema.key_column_usage kcu
                     ON tc.constraint_name = kcu.constraint_name
                    AND tc.table_schema = kcu.table_schema
                   JOIN information_schema.constraint_column_usage ccu
                     ON ccu.constraint_name = tc.constraint_name
                    AND ccu.table_schema = tc.table_schema
                   WHERE tc.table_schema = 'public'
                     AND tc.table_name = %s
                     AND tc.constraint_type = 'FOREIGN KEY'""",
                (table_name,),
            )
            foreign_keys = [dict(r) for r in c.fetchall()]

            sample_rows = []
            try:
                c.execute("SELECT * FROM " + _quote(table_name) + " LIMIT 20")
                sample_rows = [dict(r) for r in c.fetchall()]
            except Exception:
                pass

            stats = {}
            for col in columns:
                col_name = col["column_name"]
                qt = _quote(col_name)
                if col["data_type"] in ("integer", "bigint", "numeric", "real", "double precision", "smallint"):
                    try:
                        c.execute(
                            f"SELECT COUNT(DISTINCT {qt}) AS distinct_count, "
                            f"MIN({qt}) AS min_val, MAX({qt}) AS max_val, "
                            f"AVG({qt}) AS avg_val FROM " + _quote(table_name)
                        )
                        stats[col_name] = dict(c.fetchone())
                    except Exception:
                        pass
                elif col["data_type"] in ("text", "character varying", "varchar", "char", "name"):
                    try:
                        c.execute(
                            f"SELECT COUNT(DISTINCT {qt}) AS distinct_count FROM " + _quote(table_name)
                        )
                        stats[col_name] = dict(c.fetchone())
                    except Exception:
                        pass

            return {
                "table_name": table_name,
                "row_count": row_count,
                "columns": columns,
                "sample_rows": sample_rows,
                "stats": stats,
                "foreign_keys": foreign_keys,
            }
    finally:
        conn.close()


def execute_readonly(conn_string: str, sql: str) -> list[dict]:
    safe = sql.strip()
    if not safe.upper().startswith("SELECT"):
        raise DbConnectorError("Only SELECT queries are allowed")
    conn = _connect(conn_string)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as c:
            c.execute("SET statement_timeout = '15s'")
            c.execute(safe)
            return [dict(r) for r in c.fetchall()]
    finally:
        conn.close()


def _quote(name: str) -> str:
    return f'"{name}"'
