"""Async client for the Inflectiv dataset / RAG API.

Key facts (verified live):
  - Base: https://app.inflectiv.ai/api/platform
  - Auth header: X-API-Key
  - GET  /ext/datasets                          -> list datasets (free)
  - POST /ext/datasets/query?dataset_id={id}    -> semantic search (1 credit)
        dataset_id MUST be a query-string param for a global key (body is ignored).
  - POST /ext/datasets/query/batch?dataset_id={id} -> batch queries (1 credit/query)
"""
from __future__ import annotations

from typing import Any

import httpx

from config import INFLECTIV_BASE


class InflectivError(RuntimeError):
    pass


class InflectivClient:
    def __init__(self, api_key: str, base: str = INFLECTIV_BASE, timeout: float = 40.0):
        if not api_key:
            raise InflectivError("Missing Inflectiv API key")
        self.api_key = api_key
        self.base = base.rstrip("/")
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {"X-API-Key": self.api_key, "Content-Type": "application/json"}

    async def _request(self, method: str, path: str, **kwargs) -> Any:
        url = f"{self.base}{path}"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.request(method, url, headers=self._headers(), **kwargs)
        # The platform returns its SPA HTML shell for unknown routes / bad auth.
        ct = resp.headers.get("content-type", "")
        if "application/json" not in ct:
            raise InflectivError(
                f"Non-JSON response from {path} (HTTP {resp.status_code}); "
                "check the API key and base URL."
            )
        data = resp.json()
        if resp.status_code >= 400 or (isinstance(data, dict) and data.get("error")):
            msg = data.get("message") if isinstance(data, dict) else str(data)
            raise InflectivError(f"Inflectiv {path} -> HTTP {resp.status_code}: {msg}")
        return data

    async def list_datasets(self) -> list[dict]:
        data = await self._request("GET", "/ext/datasets")
        return data.get("datasets", [])

    async def resolve_name_to_id(self, name: str) -> dict:
        """Match a dataset by name (case-insensitive exact, then substring). Returns the dataset dict."""
        datasets = await self.list_datasets()
        wanted = (name or "").strip().lower()
        exact = [d for d in datasets if (d.get("name") or "").strip().lower() == wanted]
        if exact:
            return exact[0]
        # also allow matching the api_name slug
        slug = [d for d in datasets if (d.get("api_name") or "").strip().lower() == wanted]
        if slug:
            return slug[0]
        partial = [d for d in datasets if wanted and wanted in (d.get("name") or "").lower()]
        if partial:
            return partial[0]
        raise InflectivError(
            f'Dataset "{name}" not found. Available: '
            + ", ".join(d.get("name", "?") for d in datasets[:10])
        )

    async def get_dataset_by_id(self, dataset_id: int) -> dict:
        for d in await self.list_datasets():
            if d.get("id") == dataset_id:
                return d
        raise InflectivError(f"Dataset id {dataset_id} not accessible with this key.")

    # The API rejects top_k > 20 with HTTP 422.
    MAX_TOP_K = 20

    async def query(self, dataset_id: int, query: str, top_k: int, score_threshold: float | None = None) -> dict:
        body: dict[str, Any] = {"query": query, "top_k": min(top_k, self.MAX_TOP_K)}
        if score_threshold is not None:
            body["score_threshold"] = score_threshold
        return await self._request(
            "POST", "/ext/datasets/query", params={"dataset_id": dataset_id}, json=body
        )

    async def query_batch(self, dataset_id: int, queries: list[str], top_k: int) -> dict:
        return await self._request(
            "POST",
            "/ext/datasets/query/batch",
            params={"dataset_id": dataset_id},
            json={"queries": queries, "top_k": min(top_k, self.MAX_TOP_K)},
        )
