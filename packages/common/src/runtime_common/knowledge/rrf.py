"""Reciprocal Rank Fusion for multi-project retrieval."""

from __future__ import annotations

from typing import Any


def reciprocal_rank_fusion(
    ranked_lists: list[list[dict[str, Any]]],
    *,
    k: int = 60,
    top_n: int = 10,
    id_key: str = "id",
) -> list[dict[str, Any]]:
    """Merge ranked result lists with RRF. Each item must have ``id_key``."""
    scores: dict[str, float] = {}
    items: dict[str, dict[str, Any]] = {}

    for results in ranked_lists:
        for rank, item in enumerate(results, start=1):
            item_id = str(item.get(id_key) or item.get("chunk_id") or rank)
            scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (k + rank)
            if item_id not in items:
                items[item_id] = dict(item)

    ordered = sorted(scores.items(), key=lambda pair: pair[1], reverse=True)
    merged: list[dict[str, Any]] = []
    for item_id, score in ordered[:top_n]:
        row = dict(items[item_id])
        row["rrf_score"] = score
        merged.append(row)
    return merged
