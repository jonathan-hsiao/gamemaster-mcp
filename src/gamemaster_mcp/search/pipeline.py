"""Retrieval pipeline: sparse (and optional dense) → merge → optional rerank → evidence list."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from gamemaster_mcp.config import (
    DB_PATH,
    EMBED_MODEL_NAME,
    GET_CHUNKS_MAX_CHARS,
    GET_CHUNKS_MAX_CHUNKS,
    INDEX_PATH,
    RERANK_MODEL_NAME,
)
from gamemaster_mcp.storage import connect_db, get_chunks
from gamemaster_mcp.index import dense_search, rerank as index_rerank, sparse_search


def _normalize_source_pdf_names(
    source_pdf_names: str | List[str] | None,
) -> Optional[List[str]]:
    """Return list of source_pdf_name(s) or None for 'all'."""
    if source_pdf_names is None:
        return None
    if isinstance(source_pdf_names, str):
        if source_pdf_names.strip().lower() == "all":
            return None
        return [source_pdf_names.strip()]
    return [s.strip() for s in source_pdf_names if s and s.strip()]


def _row_to_evidence_summary(
    row: Dict[str, Any],
    question: str,
    *,
    sparse_score: Optional[float] = None,
    dense_score: Optional[float] = None,
    rerank_score: Optional[float] = None,
    source_priority: Optional[int] = None,
) -> Dict[str, Any]:
    """Build EvidenceSummary (citation + scores + snippet; optional source_priority)."""
    citation = {
        "source_id": row["source_id"],
        "source_name": row["source_name"],
        "source_pdf_name": row["source_pdf_name"],
        "page_start": row["page_start"],
        "page_end": row["page_end"],
    }
    if row.get("section_title"):
        citation["section_title"] = row["section_title"]
    score: Dict[str, Any] = {}
    if sparse_score is not None:
        score["sparse"] = sparse_score
    if dense_score is not None:
        score["dense"] = dense_score
    if rerank_score is not None:
        score["rerank"] = rerank_score

    out: Dict[str, Any] = {
        "chunk_id": row["chunk_id"],
        "game_id": row["game_id"],
        "game_name": row["game_name"],
        "citation": citation,
        "question": question,
        "score": score,
        "snippet": row.get("snippet") or (row.get("text_clean", "")[:220] + "…" if len(row.get("text_clean", "")) > 220 else row.get("text_clean", "")),
    }
    if source_priority is not None:
        out["source_priority"] = source_priority
    return out


def search_rules(
    game_id: str,
    query: str,
    k: int = 8,
    strategy: str = "hybrid",
    source_pdf_names: str | List[str] | None = "all",
    *,
    db_path: Optional[Path] = None,
    index_path: Optional[Path] = None,
    k_sparse: int = 50,
    k_dense: int = 50,
) -> List[Dict[str, Any]]:
    """
    Return list of EvidenceSummary (citation + scores + snippet).
    source_pdf_names: "all", a single source_pdf_name, or a priority-ordered list.
    When a list is given, each result includes source_priority (0-based index in that list).
    strategy: "sparse" (FTS only), "hybrid" (sparse + dense, then merge), "hybrid_rerank" (hybrid + rerank).
    """
    db_path = db_path or DB_PATH
    index_path = index_path or INDEX_PATH
    conn = connect_db(db_path)
    source_list = _normalize_source_pdf_names(source_pdf_names)
    priority_order = source_list if isinstance(source_pdf_names, list) else None

    try:
        sparse_hits = sparse_search(conn, game_id, query, k=k_sparse, source_pdf_names=source_pdf_names)
        sparse_by_id: Dict[int, Dict[str, Any]] = {int(h["chunk_id"]): h for h in sparse_hits}

        cand_ids: set[int] = set(sparse_by_id.keys())
        dense_score_by_id: Dict[int, float] = {}

        if strategy in ("hybrid", "hybrid_rerank") and index_path.exists():
            dense_hits = dense_search(conn, index_path, EMBED_MODEL_NAME, query, game_id, k=k_dense)
            for cid, sc in dense_hits:
                cand_ids.add(cid)
                dense_score_by_id[cid] = max(dense_score_by_id.get(cid, -1e9), sc)

        if not cand_ids:
            return []

        full_chunks = get_chunks(conn, list(cand_ids), max_chunks=500, max_chars_per_chunk=100_000)
        chunk_by_id = {c["chunk_id"]: c for c in full_chunks}
        candidates: List[Dict[str, Any]] = []
        for cid in cand_ids:
            ch = chunk_by_id.get(cid)
            if not ch or ch["game_id"] != game_id:
                continue
            if source_list and ch.get("source_pdf_name") not in source_list:
                continue
            ch["snippet"] = sparse_by_id[cid].get("snippet") if cid in sparse_by_id else (
                (ch["text_clean"][:220] + "…") if len(ch["text_clean"]) > 220 else ch["text_clean"]
            )
            ch["bm25_score"] = float(sparse_by_id[cid]["bm25_score"]) if cid in sparse_by_id else None
            ch["dense_score"] = dense_score_by_id.get(cid)
            candidates.append(ch)

        if strategy in ("hybrid", "hybrid_rerank") and (sparse_hits or dense_score_by_id):
            # RRF (reciprocal rank fusion), k=60
            rrf_k = 60
            rank_sparse: Dict[int, int] = {int(h["chunk_id"]): i + 1 for i, h in enumerate(sparse_hits)}
            dense_order = sorted(dense_score_by_id.items(), key=lambda x: -x[1])
            rank_dense: Dict[int, int] = {cid: i + 1 for i, (cid, _) in enumerate(dense_order)}
            for c in candidates:
                cid = c["chunk_id"]
                rs = rank_sparse.get(cid, rrf_k + 1000)
                rd = rank_dense.get(cid, rrf_k + 1000)
                c["rrf_score"] = 1.0 / (rrf_k + rs) + 1.0 / (rrf_k + rd)
            candidates = sorted(candidates, key=lambda c: -c.get("rrf_score", 0))
        else:
            candidates = sorted(candidates, key=lambda c: -(c.get("bm25_score") or 0))

        if strategy == "hybrid_rerank" and candidates:
            candidates = index_rerank(query, candidates[: max(k * 2, 50)], k=k, model_name=RERANK_MODEL_NAME)
        else:
            candidates = candidates[:k]

        result: List[Dict[str, Any]] = []
        for c in candidates:
            sp = None
            if priority_order and c.get("source_pdf_name") is not None:
                try:
                    sp = priority_order.index(c["source_pdf_name"])
                except ValueError:
                    pass
            result.append(
                _row_to_evidence_summary(
                    c,
                    query,
                    sparse_score=c.get("bm25_score"),
                    dense_score=c.get("dense_score"),
                    rerank_score=c.get("rerank_score"),
                    source_priority=sp,
                )
            )
        return result
    finally:
        conn.close()


def get_chunks_for_agent(chunk_ids: List[int]) -> List[Dict[str, Any]]:
    """Return EvidenceFull (with text) for chunk_ids, capped per brief."""
    conn = connect_db(DB_PATH)
    try:
        return get_chunks(
            conn,
            chunk_ids,
            max_chunks=GET_CHUNKS_MAX_CHUNKS,
            max_chars_per_chunk=GET_CHUNKS_MAX_CHARS,
        )
    finally:
        conn.close()
