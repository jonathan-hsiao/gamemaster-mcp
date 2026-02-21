"""FAISS dense index: load/save, add/remove ids, search. Uses E5 prefix convention."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

_embedder_cache: Dict[str, Any] = {}


def _get_embedder(embed_model_name: str):
    """Process-wide lazy singleton for SentenceTransformer."""
    from sentence_transformers import SentenceTransformer

    if embed_model_name not in _embedder_cache:
        _embedder_cache[embed_model_name] = SentenceTransformer(embed_model_name)
    return _embedder_cache[embed_model_name]


def _load_faiss():
    import faiss  # type: ignore
    return faiss


def load_or_create_index(index_path: Path, dim: int):
    faiss = _load_faiss()
    if index_path.exists():
        return faiss.read_index(str(index_path))
    base = faiss.IndexFlatIP(dim)
    return faiss.IndexIDMap2(base)


def save_index(index_path: Path, idx) -> None:
    _load_faiss().write_index(idx, str(index_path))


def remove_ids(idx, ids: np.ndarray) -> None:
    if ids.size == 0:
        return
    faiss = _load_faiss()
    # SWIG expects pointer via swig_ptr; array must be contiguous int64
    id_arr = np.ascontiguousarray(np.asarray(ids, dtype=np.int64).ravel())
    selector = faiss.IDSelectorBatch(id_arr.size, faiss.swig_ptr(id_arr))
    try:
        idx.remove_ids(selector)
    except Exception:
        pass


def dense_search(
    conn,
    index_path: Path,
    embed_model_name: str,
    query: str,
    game_id: str,
    k: int = 50,
    *,
    allowed_chunk_ids: Optional[Sequence[int]] = None,
) -> List[Tuple[int, float]]:
    """Search FAISS; returns (chunk_id, score).
    If allowed_chunk_ids is provided and non-empty, search is restricted to those ids (IDSelector).
    Otherwise searches the full index (caller may post-filter by game_id)."""
    embedder = _get_embedder(embed_model_name)
    q_emb = embedder.encode(
        [f"query: {query}"],
        normalize_embeddings=True,
        show_progress_bar=False,
    ).astype(np.float32)

    idx = _load_faiss().read_index(str(index_path))
    faiss = _load_faiss()

    if allowed_chunk_ids is not None and len(allowed_chunk_ids) == 0:
        return []

    if allowed_chunk_ids is not None and len(allowed_chunk_ids) > 0:
        id_arr = np.ascontiguousarray(
            np.array(allowed_chunk_ids, dtype=np.int64).ravel()
        )
        selector = faiss.IDSelectorBatch(id_arr.size, faiss.swig_ptr(id_arr))
        params = faiss.SearchParameters(sel=selector)
        scores, ids = idx.search(q_emb, k, params=params)
    else:
        scores, ids = idx.search(q_emb, k)

    out: List[Tuple[int, float]] = []
    for cid, sc in zip(ids[0].tolist(), scores[0].tolist()):
        if cid == -1:
            continue
        out.append((int(cid), float(sc)))
    return out


def build_embeddings(
    texts: List[str],
    embed_model_name: str,
    *,
    batch_size: int = 32,
    show_progress: bool = True,
) -> np.ndarray:
    """Encode passage texts (with 'passage: ' prefix for E5). Returns (n, dim) float32."""
    embedder = _get_embedder(embed_model_name)
    prefixed = [f"passage: {t}" for t in texts]
    emb = embedder.encode(
        prefixed,
        batch_size=batch_size,
        show_progress_bar=show_progress,
        normalize_embeddings=True,
    ).astype(np.float32)
    return emb
