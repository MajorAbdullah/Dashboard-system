"""Core agent pipeline: plan -> retrieve -> structure -> drafts.

Numbers come from an LLM extracting over a non-exhaustive vector sample, so the
honesty layer (grounded flag, provenance sources, score-based confidence) is
load-bearing, not decorative.
"""
from __future__ import annotations

import asyncio

import cache
import prompts
from inflectiv import InflectivClient, InflectivError
from openrouter import chat_json, chat_text
from schemas import ChartSpec, DashboardPlan, DatasetProfile, SourceRef
import config


# ---------------- retrieval ----------------
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
            # batch may be gated to higher tiers — fall back to parallel single queries
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
    """Confidence from real retrieval: avg score scaled, nudged by chunk count + grounding."""
    if not chunks:
        return 35
    avg = sum(c.get("score", 0) for c in chunks) / len(chunks)
    base = max(0.0, min(1.0, avg)) * 100
    base = min(98, base + min(len(chunks), 8))  # more supporting chunks => a little more confident
    if not grounded:
        base *= 0.8
    return int(max(30, min(98, base)))


def _format_chunks(chunks: list[dict], limit: int = 12) -> str:
    lines = []
    for c in chunks[:limit]:
        lines.append(f"[score {c.get('score', 0):.2f}] {c.get('text', '').strip()[:600]}")
    return "\n\n".join(lines) if lines else "(no passages retrieved)"


async def _structure_one(chart, subqueries, retrieved, source_name: str, exact: bool, pool: list) -> ChartSpec | None:
    chunks = _chunks_for(chart.needs, subqueries, retrieved)
    if not chunks:
        chunks = pool[:14]  # fall back to the global pool so every chart gets context
    user = (
        f"Chart intent: type={chart.type}, title={chart.title!r}, data source={source_name!r}.\n\n"
        f"Retrieved passages:\n{_format_chunks(chunks)}"
    )
    try:
        spec = await chat_json(prompts.STRUCTURER, user, ChartSpec)
    except Exception:
        return None
    spec.type = chart.type
    spec.title = spec.title or chart.title
    spec.source = source_name
    spec.exact = exact and spec.grounded
    spec.sources = [
        SourceRef(text=c.get("text", "")[:400], score=c.get("score", 0.0),
                  knowledge_source_id=c.get("knowledge_source_id"))
        for c in chunks[:6]
    ]
    spec.confidence = _confidence(chunks, spec.grounded)
    return spec


# ---------------- top-level generate ----------------
async def generate(client: InflectivClient, dataset_id: int, dataset_name: str, goal: str,
                   profile: DatasetProfile | None, emit) -> dict:
    await emit("Understanding your goal")
    profile_hint = profile.model_dump_json() if profile else "{}"
    plan = await chat_json(
        prompts.PLANNER,
        f"Goal: {goal}\n\nDataset profile: {profile_hint}",
        DashboardPlan,
    )
    # dedupe subqueries while preserving order + index mapping
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

    # broad seed queries guarantee a retrieval pool even when the planner's specific
    # queries semantically miss (this dataset returns 0 for over-specified phrases)
    seeds = [" ".join(goal.split()[:4])]
    if profile:
        seeds += (profile.entities or [])[:3] + (profile.categorical_fields or [])[:2]
    for sd in seeds:
        n = cache.normalize(sd)
        if n and n not in seen:
            seen.add(n)
            subqueries.append(sd)

    await emit(f"Planned {len(plan.charts)} components from {len(subqueries)} analyses", "done")

    retrieved = await _retrieve(client, dataset_id, subqueries, config.DEFAULT_TOP_K, emit)

    # global pool: all retrieved chunks, deduped, best score first
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
    drafts: list[ChartSpec] = []
    for ch in plan.charts:
        await emit(f"Drafting: {ch.title}")
        spec = await _structure_one(ch, subqueries, retrieved, dataset_name, exact, pool)
        if spec:
            drafts.append(spec)
    await emit(f"Generated {len(drafts)} components", "done")
    return {"drafts": [d.model_dump(exclude_none=True) for d in drafts],
            "exactness": "exact" if exact else "illustrative"}


async def refine(client: InflectivClient, dataset_id: int, dataset_name: str, message: str, emit) -> dict:
    await emit("Investigating your question")
    queries = [message]
    # keyword form: drop stopwords so natural questions still retrieve
    stop = {"which", "what", "who", "where", "when", "why", "how", "do", "does", "did",
            "is", "are", "the", "a", "an", "of", "on", "in", "to", "for", "and", "or",
            "by", "with", "top", "focus", "show", "me", "our", "their", "this", "that"}
    kw = " ".join(w for w in message.lower().replace("?", "").split() if w not in stop)
    if kw and cache.normalize(kw) != cache.normalize(message):
        queries.append(kw)
    retrieved = await _retrieve(client, dataset_id, queries, config.DEFAULT_TOP_K, emit)
    chunks, seenc = [], set()
    for q in queries:
        for c in retrieved.get(q, []):
            k = (c.get("knowledge_source_id"), c.get("chunk_index"), c.get("text", "")[:50])
            if k not in seenc:
                seenc.add(k)
                chunks.append(c)
    chunks.sort(key=lambda c: c.get("score", 0), reverse=True)
    user = (
        f"Follow-up question: {message!r}. data source={dataset_name!r}.\n\n"
        f"Retrieved passages:\n{_format_chunks(chunks)}"
    )
    spec = await chat_json(prompts.REFINER, user, ChartSpec)
    spec.source = dataset_name
    spec.sources = [
        SourceRef(text=c.get("text", "")[:400], score=c.get("score", 0.0),
                  knowledge_source_id=c.get("knowledge_source_id"))
        for c in chunks[:6]
    ]
    spec.confidence = _confidence(chunks, spec.grounded)
    await emit("Done", "done")
    return {"draft": spec.model_dump(exclude_none=True)}
