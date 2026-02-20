"""Cross-encoder rerank: (query, candidates) → top-k by relevance score."""

from __future__ import annotations

from typing import Any, Dict, List

_reranker_cache: Dict[str, Any] = {}


def _get_reranker(model_name: str):
    """Process-wide lazy singleton for CrossEncoder."""
    from sentence_transformers import CrossEncoder

    if model_name not in _reranker_cache:
        _reranker_cache[model_name] = CrossEncoder(model_name)
    return _reranker_cache[model_name]


def rerank(
    query: str,
    candidates: List[Dict[str, Any]],
    k: int = 8,
    model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2",
) -> List[Dict[str, Any]]:
    if not candidates:
        return []

    model = _get_reranker(model_name)
    pairs = [(query, c["text_clean"]) for c in candidates]
    scores = model.predict(pairs)

    for c, sc in zip(candidates, scores):
        c["rerank_score"] = float(sc)

    candidates.sort(key=lambda x: x["rerank_score"], reverse=True)
    return candidates[:k]
