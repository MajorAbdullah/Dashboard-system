"""Connect-time dataset profiling (one-time per dataset, cached).

Fires a fixed set of probe queries, feeds the sample + description to the LLM, and
produces a DatasetProfile that grounds later planning and powers "AI suggests
dashboards". size_estimate is derived from knowledge_source_count.
"""
from __future__ import annotations

import cache
import config
import prompts
from inflectiv import InflectivClient
from llm import chat_json
from schemas import DatasetProfile

PROBES = [
    "overview summary of this dataset",
    "key metrics and numbers",
    "categories segments or types",
    "dates time periods or trends",
    "records rows columns or fields",
]


async def profile_dataset(client: InflectivClient, dataset: dict, emit=None) -> DatasetProfile:
    dataset_id = dataset["id"]
    cached = cache.get_profile(dataset_id)
    if cached is not None:
        try:
            return cached if hasattr(cached, "size_estimate") else DatasetProfile(**cached)
        except Exception:
            pass

    async def _emit(t, s="run"):
        if emit:
            await emit(t, s)

    await _emit("Profiling the dataset")
    chunks: list[dict] = []
    try:
        batch = await client.query_batch(dataset_id, PROBES, top_k=12)
        for item in batch.get("results", []):
            chunks.extend(item.get("results", []))
    except Exception:
        for p in PROBES:
            try:
                r = await client.query(dataset_id, p, 12, config.DEFAULT_SCORE_THRESHOLD)
                chunks.extend(r.get("results", []))
            except Exception:
                pass

    sample = "\n\n".join(c.get("text", "").strip()[:500] for c in chunks[:20]) or "(no sample retrieved)"
    ks = dataset.get("knowledge_source_count", 0)
    user = (
        f"Dataset name: {dataset.get('name')!r}\n"
        f"Description: {dataset.get('description') or '(none)'}\n"
        f"Knowledge source count: {ks}\n\n"
        f"Sample passages:\n{sample}"
    )
    try:
        profile = await chat_json(prompts.PROFILER, user, DatasetProfile)
    except Exception:
        profile = DatasetProfile(summary=dataset.get("description") or "")

    profile.size_estimate = "small" if ks and ks <= 3 else "large"
    cache.set_profile(dataset_id, profile)
    await _emit("Profile ready", "done")
    return profile


async def profile_db_table(datasource, emit=None) -> DatasetProfile:
    """Profile a database table using the DatabaseDataSource directly."""
    return await datasource.get_profile(emit=emit)
