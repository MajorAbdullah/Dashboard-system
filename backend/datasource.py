"""Data source abstraction: InflectivClient and PostgreSQL share the same interface
so the pipeline never needs to know which backend is serving the data.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable, Optional

import json

import db_connector
import prompts
import config
from inflectiv import InflectivClient
from llm import chat_json, chat_text
from schemas import DatasetProfile


class BaseDataSource(ABC):
    @abstractmethod
    async def list_collections(self) -> list[dict]:
        """Return available datasets/tables: [{id, name, ...}]."""
        ...

    @abstractmethod
    async def get_profile(self, collection_id: str, emit: Optional[Callable] = None) -> DatasetProfile:
        """Profile the dataset/table, returning a DatasetProfile."""
        ...

    @abstractmethod
    async def query(self, collection_id: str, queries: list[str], top_k: int,
                    emit: Optional[Callable] = None) -> dict[str, list[dict]]:
        """Run queries against the data source, return {query: [chunk_or_row, ...]}."""
        ...

    @property
    @abstractmethod
    def source_name(self) -> str:
        ...

    @property
    @abstractmethod
    def size_estimate(self) -> str:
        ...


class InflectivDataSource(BaseDataSource):
    def __init__(self, client: InflectivClient, dataset_id: int, dataset_name: str,
                 knowledge_source_count: int = 0):
        self._client = client
        self._dataset_id = dataset_id
        self._dataset_name = dataset_name
        self._ks_count = knowledge_source_count

    async def list_collections(self) -> list[dict]:
        return await self._client.list_datasets()

    async def get_profile(self, _collection_id: str = "", emit: Optional[Callable] = None) -> DatasetProfile:
        from profiler import profile_dataset
        dataset = {"id": self._dataset_id, "name": self._dataset_name,
                   "knowledge_source_count": self._ks_count}
        return await profile_dataset(self._client, dataset, emit=emit)

    async def query(self, _collection_id: str, queries: list[str], top_k: int,
                    emit: Optional[Callable] = None) -> dict[str, list[dict]]:
        import pipeline as pipeline_mod
        return await pipeline_mod._retrieve(self._client, self._dataset_id, queries, top_k, emit or (lambda *a: None))

    @property
    def source_name(self) -> str:
        return self._dataset_name

    @property
    def size_estimate(self) -> str:
        return "small" if self._ks_count and self._ks_count <= 3 else "large"


class DatabaseDataSource(BaseDataSource):
    def __init__(self, conn_string: str, table_name: str):
        self._conn_string = conn_string
        self._table_name = table_name
        self._schema: Optional[dict] = None
        self._profile: Optional[DatasetProfile] = None

    async def list_collections(self) -> list[dict]:
        tables = db_connector.list_tables(self._conn_string)
        return [{"id": t["table_name"], "name": t["table_name"],
                 "row_estimate": t.get("row_estimate", 0)} for t in tables]

    async def get_profile(self, _collection_id: str = "", emit: Optional[Callable] = None) -> DatasetProfile:
        if self._profile:
            return self._profile

        async def _emit(t, s="run"):
            if emit:
                await emit(t, s)

        await _emit("Profiling database table")
        schema = db_connector.get_table_schema(self._conn_string, self._table_name)
        self._schema = schema

        col_lines = []
        for col in schema.get("columns", []):
            col_lines.append(f"  - {col['column_name']} ({col['data_type']}) nullable={col['is_nullable']}")
        sample_lines = []
        for row in schema.get("sample_rows", [])[:5]:
            sample_lines.append(f"  {row}")
        stats_lines = []
        for col_name, st in schema.get("stats", {}).items():
            stats_lines.append(f"  {col_name}: {st}")

        user = (
            f"Table: {self._table_name}\n"
            f"Row count: {schema['row_count']}\n\n"
            f"Columns:\n" + "\n".join(col_lines) + "\n\n"
            f"Sample rows:\n" + "\n".join(sample_lines) + "\n\n"
            f"Basic stats:\n" + "\n".join(stats_lines) + "\n"
        )
        try:
            profile = await chat_json(prompts.DB_PROFILER, user, DatasetProfile)
        except Exception:
            profile = DatasetProfile(summary=f"PostgreSQL table: {self._table_name}")

        profile.size_estimate = "small" if schema.get("row_count", 0) <= 10000 else "large"
        self._profile = profile
        await _emit("Profile ready", "done")
        return profile

    async def query(self, _collection_id: str, queries: list[str], top_k: int,
                    emit: Optional[Callable] = None) -> dict[str, list[dict]]:
        async def _emit(t, s="run"):
            if emit:
                await emit(t, s)

        if not self._schema:
            self._schema = db_connector.get_table_schema(self._conn_string, self._table_name)

        schema_text = f"Table: {self._table_name}\nColumns:\n"
        for col in self._schema.get("columns", []):
            schema_text += f"  - {col['column_name']} ({col['data_type']})\n"
        # Include foreign key info so the LLM can write JOIN queries
        fks = self._schema.get("foreign_keys", [])
        if fks:
            schema_text += "\nForeign keys:\n"
            for fk in fks:
                schema_text += f"  {fk['column_name']} -> {fk['ref_table']}({fk['ref_column']})\n"
        schema_text += f"\nRow count: {self._schema.get('row_count', 0)}"

        out: dict[str, list[dict]] = {}
        for q in queries:
            await _emit(f"Querying database: {q}")
            user = (
                f"Schema:\n{schema_text}\n\n"
                f"Query intent: {q}\n\n"
                f"Write a single PostgreSQL SELECT statement to answer this query. "
                f"Use column names from the schema. "
                f"JOIN with related tables (via foreign keys) to get human-readable labels "
                f"instead of raw IDs wherever possible. "
                f"Include a LIMIT {top_k}. "
                f"Return ONLY the SQL, no explanation."
            )
            try:
                sql = await chat_text(prompts.SQL_WRITER, user, temperature=0.1)
                sql = sql.strip()
                if sql.startswith("```"):
                    sql = sql.split("```", 2)[1]
                    if sql.lstrip().startswith("sql"):
                        sql = sql.lstrip()[3:]
                    sql = sql.strip()
                rows = db_connector.execute_readonly(self._conn_string, sql)
                out[q] = [{"text": json.dumps(r, default=str), "score": 1.0, "knowledge_source_id": 0, "chunk_index": i}
                          for i, r in enumerate(rows)]
                await _emit(f"  ↳ {q} — {len(rows)} rows returned")
            except Exception as e:
                out[q] = []
                await _emit(f"  ↳ {q} — error: {e}")
        return out

    @property
    def source_name(self) -> str:
        return self._table_name

    @property
    def size_estimate(self) -> str:
        return "small"

    @property
    def row_count(self) -> int:
        return (self._schema or {}).get("row_count", 0)


def make_datasource(session) -> BaseDataSource:
    if session.source_type == "database" and session.conn_string:
        return DatabaseDataSource(session.conn_string, session.table_name)
    client = InflectivClient(session.global_key)
    return InflectivDataSource(client, session.dataset_id, session.dataset_name,
                               session.knowledge_source_count)
