"""Core agent pipeline: plan -> retrieve -> structure -> drafts.

Numbers come from an LLM extracting over a non-exhaustive vector sample, so the
honesty layer (grounded flag, provenance sources, score-based confidence) is
load-bearing, not decorative. Supports both Inflectiv and direct database modes.
"""
from __future__ import annotations

import asyncio
from typing import Optional

import cache
import prompts
from datasource import BaseDataSource
from inflectiv import InflectivClient, InflectivError
from llm import chat_json, chat_text
from schemas import ChartSpec, ChatAnswer, DashboardPlan, DatasetProfile, SourceRef
import config


# ---------------- retrieval (Inflectiv-only) ----------------
async def _retrieve(client: InflectivClient, dataset_id: int, queries: list[str],
                    top_k: int, emit) -> dict[str, list[dict]]:
    """Return {query: [chunk,...]} using cache + dedupe + batch (with sequential fallback)."""
    out: dict[str, list[dict]] = {}
    misses: list[str] = []
    for q in queries:
        cached = cache.get_query(dataset_id, q, top_k)
        if cached is not None:
            out[q] = cached
        elif q not in misses:
            misses.append(q)

    if misses:
        await emit(f"Retrieving {len(misses)} semantic " + ("query" if len(misses) == 1 else "queries"))
        results_by_query: dict[str, list[dict]] = {}
        try:
            batch = await client.query_batch(dataset_id, misses, top_k)
            for item in batch.get("results", []):
                q = item.get("query", "")
                results_by_query[q] = item.get("results", [])
        except InflectivError:
            async def one(q: str):
                try:
                    r = await client.query(dataset_id, q, top_k, None)
                    return q, r.get("results", [])
                except InflectivError:
                    return q, []
            for q, chunks in await asyncio.gather(*[one(q) for q in misses]):
                results_by_query[q] = chunks

        for q in misses:
            chunks = results_by_query.get(q, [])
            cache.set_query(dataset_id, q, top_k, chunks)
            out[q] = chunks
            avg = (sum(c.get("score", 0) for c in chunks) / len(chunks)) if chunks else 0.0
            await emit(f"  ↳ {q} — {len(chunks)} chunks, avg relevance {avg:.2f}")
    return out


def _chunks_for(plan_needs: list[int], subqueries: list[str], retrieved: dict[str, list[dict]]) -> list[dict]:
    seen, chunks = set(), []
    for i in plan_needs or range(len(subqueries)):
        if 0 <= i < len(subqueries):
            for c in retrieved.get(subqueries[i], []):
                key = (c.get("knowledge_source_id"), c.get("chunk_index"), c.get("text", "")[:60])
                if key not in seen:
                    seen.add(key)
                    chunks.append(c)
    return chunks


def _confidence(chunks: list[dict], grounded: bool) -> int:
    if not chunks:
        return 35
    avg = sum(c.get("score", 0) for c in chunks) / len(chunks)
    base = max(0.0, min(1.0, avg)) * 100
    base = min(98, base + min(len(chunks), 8))
    if not grounded:
        base *= 0.8
    return int(max(30, min(98, base)))


def _format_chunks(chunks: list[dict], limit: int = 12) -> str:
    lines = []
    for c in chunks[:limit]:
        lines.append(f"[score {c.get('score', 0):.2f}] {c.get('text', '').strip()[:600]}")
    return "\n\n".join(lines) if lines else "(no passages retrieved)"


async def _structure_one(chart, subqueries, retrieved, source_name: str, exact: bool, pool: list,
                         source_type: str = "inflectiv") -> ChartSpec | None:
    chunks = _chunks_for(chart.needs, subqueries, retrieved)
    if not chunks:
        chunks = pool[:14]
    if source_type == "database":
        prompt = prompts.DB_STRUCTURER
        results_text = "\n".join(c.get("text", "") for c in chunks[:20]) or "(no results)"
        user = (
            f"Chart intent: type={chart.type}, title={chart.title!r}, data source={source_name!r}.\n\n"
            f"Query results:\n{results_text}"
        )
    else:
        prompt = prompts.STRUCTURER
        user = (
            f"Chart intent: type={chart.type}, title={chart.title!r}, data source={source_name!r}.\n\n"
            f"Retrieved passages:\n{_format_chunks(chunks)}"
        )
    try:
        spec = await chat_json(prompt, user, ChartSpec)
    except Exception:
        return None
    spec.type = chart.type
    spec.title = spec.title or chart.title
    spec.source = source_name
    spec.exact = exact and spec.grounded if source_type != "database" else True
    spec.sources = [
        SourceRef(text=c.get("text", "")[:400], score=c.get("score", 0.0),
                  knowledge_source_id=c.get("knowledge_source_id"))
        for c in chunks[:6]
    ]
    spec.confidence = 95 if source_type == "database" else _confidence(chunks, spec.grounded)
    return spec


def _plan_for_source(datasource: BaseDataSource, goal: str, profile: DatasetProfile | None) -> str:
    """Choose the right planner prompt based on datasource type."""
    if hasattr(datasource, '_conn_string'):
        schema = getattr(datasource, '_schema', None) or {}
        cols = "\n".join(f"  - {c['column_name']} ({c['data_type']})"
                         for c in schema.get("columns", []))
        fks = schema.get("foreign_keys", [])
        if fks:
            cols += "\nForeign keys:\n" + "\n".join(
                f"  {fk['column_name']} -> {fk['ref_table']}({fk['ref_column']})" for fk in fks)
        if not cols:
            cols = "(schema not yet loaded)"
        return prompts.DB_PLANNER.replace("{columns}", cols)
    return prompts.PLANNER


# ---------------- top-level generate ----------------
async def generate(datasource: BaseDataSource, goal: str,
                   profile: DatasetProfile | None, emit) -> dict:
    await emit("Understanding your goal")
    source_type = getattr(datasource, '_conn_string', None) and "database" or "inflectiv"

    plan_prompt = _plan_for_source(datasource, goal, profile)
    profile_hint = profile.model_dump_json() if profile else "{}"
    plan = await chat_json(
        plan_prompt,
        f"Goal: {goal}\n\nDataset profile: {profile_hint}",
        DashboardPlan,
    )

    seen, subqueries, remap = set(), [], {}
    for i, q in enumerate(plan.subqueries):
        n = cache.normalize(q)
        if n and n not in seen:
            seen.add(n)
            remap[i] = len(subqueries)
            subqueries.append(q)
        elif n:
            remap[i] = next(j for j, qq in enumerate(subqueries) if cache.normalize(qq) == n)
    for ch in plan.charts:
        ch.needs = sorted({remap.get(i, 0) for i in ch.needs}) if ch.needs else []

    seeds = [" ".join(goal.split()[:4])]
    if profile:
        seeds += (profile.entities or [])[:3] + (profile.categorical_fields or [])[:2]
    for sd in seeds:
        n = cache.normalize(sd)
        if n and n not in seen:
            seen.add(n)
            subqueries.append(sd)

    await emit(f"Planned {len(plan.charts)} components from {len(subqueries)} analyses", "done")

    retrieved = await datasource.query("", subqueries, config.DEFAULT_TOP_K, emit)

    pool, seenc = [], set()
    for q in subqueries:
        for c in retrieved.get(q, []):
            k = (c.get("knowledge_source_id"), c.get("chunk_index"), c.get("text", "")[:50])
            if k not in seenc:
                seenc.add(k)
                pool.append(c)
    pool.sort(key=lambda c: c.get("score", 0), reverse=True)
    await emit(f"Retrieved {len(pool)} relevant passages", "done")

    exact = (profile.size_estimate == "small") if profile else False
    if source_type == "database":
        exact = True

    source_name = datasource.source_name
    drafts: list[ChartSpec] = []
    for ch in plan.charts:
        await emit(f"Drafting: {ch.title}")
        spec = await _structure_one(ch, subqueries, retrieved, source_name, exact, pool, source_type)
        if spec:
            drafts.append(spec)
    await emit(f"Generated {len(drafts)} components", "done")
    return {"drafts": [d.model_dump(exclude_none=True) for d in drafts],
            "exactness": "exact" if exact else "illustrative"}


async def _retrieve_for_message(datasource: BaseDataSource, message: str, emit) -> tuple[list[dict], str, str]:
    """Shared by refine() and chat(): keyword-augmented retrieval for a free-form
    message. Returns (pooled chunks sorted by score desc, source_type, source_name)."""
    stop = {"which", "what", "who", "where", "when", "why", "how", "do", "does", "did",
            "is", "are", "the", "a", "an", "of", "on", "in", "to", "for", "and", "or",
            "by", "with", "top", "focus", "show", "me", "our", "their", "this", "that"}
    kw = " ".join(w for w in message.lower().replace("?", "").split() if w not in stop)
    queries = [message]
    if kw and cache.normalize(kw) != cache.normalize(message):
        queries.append(kw)

    retrieved = await datasource.query("", queries, config.DEFAULT_TOP_K, emit)
    chunks, seenc = [], set()
    for q in queries:
        for c in retrieved.get(q, []):
            k = (c.get("knowledge_source_id"), c.get("chunk_index"), c.get("text", "")[:50])
            if k not in seenc:
                seenc.add(k)
                chunks.append(c)
    chunks.sort(key=lambda c: c.get("score", 0), reverse=True)
    source_type = getattr(datasource, '_conn_string', None) and "database" or "inflectiv"
    return chunks, source_type, datasource.source_name


async def refine(datasource: BaseDataSource, message: str, emit) -> dict:
    await emit("Investigating your question")
    chunks, source_type, source_name = await _retrieve_for_message(datasource, message, emit)

    if source_type == "database":
        results_text = "\n".join(c.get("text", "") for c in chunks[:20]) or "(no results)"
        user = (
            f"Follow-up question: {message!r}. data source={source_name!r}.\n\n"
            f"Query results:\n{results_text}"
        )
    else:
        user = (
            f"Follow-up question: {message!r}. data source={source_name!r}.\n\n"
            f"Retrieved passages:\n{_format_chunks(chunks)}"
        )
    spec = await chat_json(prompts.REFINER, user, ChartSpec)
    spec.source = source_name
    spec.sources = [
        SourceRef(text=c.get("text", "")[:400], score=c.get("score", 0.0),
                  knowledge_source_id=c.get("knowledge_source_id"))
        for c in chunks[:6]
    ]
    spec.confidence = 95 if source_type == "database" else _confidence(chunks, spec.grounded)
    await emit("Done", "done")
    return {"draft": spec.model_dump(exclude_none=True)}


async def chat(datasource: BaseDataSource, message: str, emit) -> dict:
    """Direct Q&A over the connected source: reuses the same retrieval refine()
    uses, but asks for a written answer (with an optional attached chart) instead
    of forcing everything into a ChartSpec."""
    await emit("Answering your question")
    chunks, source_type, source_name = await _retrieve_for_message(datasource, message, emit)

    if source_type == "database":
        prompt = prompts.CHAT_DB_ANSWERER
        results_text = "\n".join(c.get("text", "") for c in chunks[:20]) or "(no results)"
        user = f"Question: {message!r}. data source={source_name!r}.\n\nQuery results:\n{results_text}"
    else:
        prompt = prompts.CHAT_INFLECTIV_ANSWERER
        user = f"Question: {message!r}. data source={source_name!r}.\n\nRetrieved passages:\n{_format_chunks(chunks)}"

    result = await chat_json(prompt, user, ChatAnswer)
    result.confidence = 95 if source_type == "database" else _confidence(chunks, result.grounded)
    sources = [
        SourceRef(text=c.get("text", "")[:400], score=c.get("score", 0.0),
                  knowledge_source_id=c.get("knowledge_source_id"))
        for c in chunks[:6]
    ]
    if result.chart:
        result.chart.source = source_name
        result.chart.sources = sources
        result.chart.confidence = result.confidence
    await emit("Done", "done")
    return {
        "answer": result.answer,
        "chart": result.chart.model_dump(exclude_none=True) if result.chart else None,
        "confidence": result.confidence,
        "sources": [s.model_dump() for s in sources] if source_type != "database" else None,
    }
