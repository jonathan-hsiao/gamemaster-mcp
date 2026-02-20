"""Sparse search via SQLite FTS5. Natural language query → FTS OR terms."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

from gamemaster_mcp.storage import connect_db


def nl_to_fts_or_query(q: str) -> str:
    tokens = re.findall(r"[A-Za-z0-9_]+", q.lower())
    tokens = [t for t in tokens if len(t) >= 2]
    terms = [(t + "*") if len(t) >= 4 else t for t in tokens]
    seen: set[str] = set()
    terms = [t for t in terms if t not in seen and not seen.add(t)]
    if not terms:
        return ""
    return " OR ".join(terms)


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


def sparse_search(
    conn: sqlite3.Connection,
    game_id: str,
    query: str,
    k: int = 50,
    raw_fts: bool = False,
    source_pdf_names: str | List[str] | None = None,
) -> List[Dict[str, Any]]:
    """Return top-k chunks for game_id matching query. Optionally restrict to given source_pdf_name(s)."""
    fts_q = query if raw_fts else nl_to_fts_or_query(query)
    if not fts_q:
        return []

    source_list = _normalize_source_pdf_names(source_pdf_names)
    sql = """
    SELECT
      c.chunk_id,
      g.game_id,
      g.game_name,
      s.source_id,
      s.source_pdf_name,
      s.source_name,
      c.page_start,
      c.page_end,
      c.section_title,
      snippet(chunks_fts, 0, '[', ']', '...', 18) AS snippet,
      bm25(chunks_fts) AS bm25_score
    FROM chunks_fts
    JOIN chunks  c ON c.chunk_id = chunks_fts.rowid
    JOIN sources s ON s.source_id = c.source_id
    JOIN games   g ON g.game_id = s.game_id
    WHERE g.game_id = ?
      AND chunks_fts MATCH ?
    """
    params: list = [game_id, fts_q]
    if source_list:
        placeholders = ",".join("?" for _ in source_list)
        sql += f" AND s.source_pdf_name IN ({placeholders})"
        params.extend(source_list)
    sql += " ORDER BY bm25_score LIMIT ?"
    params.append(k)

    rows = conn.execute(sql, tuple(params)).fetchall()
    return [dict(r) for r in rows]
