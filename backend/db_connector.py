"""PostgreSQL connector for direct database mode.
Handles connection, schema introspection, and read-only SQL execution.
"""
from __future__ import annotations

import ipaddress
import socket

import psycopg2
import psycopg2.extras
import psycopg2.extensions
import sqlparse
from psycopg2 import sql as psql

import config


class DbConnectorError(RuntimeError):
    pass


class DbConnectionFailed(DbConnectorError):
    """Raised specifically when the underlying psycopg2.connect() call fails.
    str() is a generic, safe-for-unauthenticated-callers message — the raw
    driver exception text (which can leak infra details: open vs filtered
    ports, auth-failure vs host-unreachable, database existence) is kept on
    .detail for server-side logging only, never returned to a client."""

    def __init__(self, detail: str):
        self.detail = detail
        super().__init__("Could not connect to the database. Check your connection string and try again.")


def _resolve_safe_ip(host: str) -> str:
    """Resolve host once and return a single validated non-private IP — used to
    block SSRF via the (unauthenticated, pre-signup) db/test and db/tables
    endpoints. The caller connects directly to this IP (via hostaddr=) rather
    than letting psycopg2 re-resolve the hostname at connect time, which would
    reopen a DNS-rebinding TOCTOU gap (attacker's DNS answers public here,
    private by the time libpq connects). Fails closed: unresolvable hosts are
    rejected rather than allowed through."""
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as e:
        raise DbConnectorError(f"Could not resolve host: {host}") from e
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
        if not (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast):
            return str(ip)
    raise DbConnectorError("Connections to private/internal network addresses are not allowed.")


def _connect(conn_string: str):
    dsn = conn_string.replace("postgres://", "postgresql://", 1)
    try:
        host = psycopg2.extensions.parse_dsn(dsn).get("host")
    except Exception as e:
        raise DbConnectorError(f"Invalid connection string: {e}")
    if not config.ALLOW_PRIVATE_DB_HOSTS and host:
        safe_ip = _resolve_safe_ip(host)
        # host= stays for TLS SNI/cert verification; hostaddr= pins the actual
        # socket connection to the address we just validated, closing the gap.
        dsn = psycopg2.extensions.make_dsn(dsn, hostaddr=safe_ip)
    try:
        conn = psycopg2.connect(dsn)
        conn.autocommit = True
        return conn
    except DbConnectorError:
        raise
    except Exception as e:
        print(f"[db_connector] connect failed for host={host}: {e}")
        raise DbConnectionFailed(str(e)) from e


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

            c.execute(psql.SQL("SELECT COUNT(*) AS n FROM {}").format(psql.Identifier(table_name)))
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
                c.execute(psql.SQL("SELECT * FROM {} LIMIT 20").format(psql.Identifier(table_name)))
                sample_rows = [dict(r) for r in c.fetchall()]
            except Exception:
                pass

            stats = {}
            for col in columns:
                col_name = col["column_name"]
                col_id = psql.Identifier(col_name)
                tbl_id = psql.Identifier(table_name)
                if col["data_type"] in ("integer", "bigint", "numeric", "real", "double precision", "smallint"):
                    try:
                        c.execute(
                            psql.SQL(
                                "SELECT COUNT(DISTINCT {col}) AS distinct_count, "
                                "MIN({col}) AS min_val, MAX({col}) AS max_val, "
                                "AVG({col}) AS avg_val FROM {tbl}"
                            ).format(col=col_id, tbl=tbl_id)
                        )
                        stats[col_name] = dict(c.fetchone())
                    except Exception:
                        pass
                elif col["data_type"] in ("text", "character varying", "varchar", "char", "name"):
                    try:
                        c.execute(
                            psql.SQL("SELECT COUNT(DISTINCT {col}) AS distinct_count FROM {tbl}")
                            .format(col=col_id, tbl=tbl_id)
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
    """Run exactly one SELECT and nothing else. Defense in depth: sqlparse
    rejects multi-statement payloads and non-SELECT statements up front, and
    the query additionally runs inside an explicit read-only transaction so
    Postgres itself refuses any write even if a parsing edge case slips by."""
    statements = [s for s in sqlparse.split(sql) if s.strip().rstrip(";").strip()]
    if len(statements) != 1:
        raise DbConnectorError("Only a single SELECT statement is allowed.")
    safe = statements[0].strip()
    parsed = sqlparse.parse(safe)
    if not parsed or parsed[0].get_type() != "SELECT":
        raise DbConnectorError("Only SELECT queries are allowed.")

    conn = _connect(conn_string)
    try:
        conn.autocommit = False
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as c:
            c.execute("SET statement_timeout = '15s'")
            c.execute("SET TRANSACTION READ ONLY")
            c.execute(safe)
            rows = [dict(r) for r in c.fetchall()]
        conn.rollback()
        return rows
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
