"""SQLite store: connect, list_games, list_sources, get_chunks (capped), and ingest helpers."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from gamemaster_mcp.config import GET_CHUNKS_MAX_CHARS, GET_CHUNKS_MAX_CHUNKS
from gamemaster_mcp.storage.schema import SCHEMA_SQL
from gamemaster_mcp.storage.source_id import source_id_from_path


def connect_db(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_SQL)
    return conn


def list_games(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    rows = conn.execute("SELECT game_id, game_name FROM games ORDER BY game_name").fetchall()
    return [{"game_id": r["game_id"], "game_name": r["game_name"]} for r in rows]


def list_sources(conn: sqlite3.Connection, game_id: str) -> List[Dict[str, Any]]:
    sql = """
    SELECT s.source_id, s.source_pdf_name, s.source_name, s.created_at,
           COALESCE(MAX(c.page_end), 0) AS page_count
    FROM sources s
    LEFT JOIN chunks c ON c.source_id = s.source_id
    WHERE s.game_id = ?
    GROUP BY s.source_id, s.source_pdf_name, s.source_name, s.created_at
    ORDER BY s.source_name, s.source_pdf_name
    """
    rows = conn.execute(sql, (game_id,)).fetchall()
    return [
        {
            "source_id": r["source_id"],
            "source_pdf_name": r["source_pdf_name"],
            "source_name": r["source_name"],
            "page_count": int(r["page_count"]),
            "created_at": r["created_at"],
        }
        for r in rows
    ]


def get_chunks(
    conn: sqlite3.Connection,
    chunk_ids: List[int],
    *,
    max_chunks: int = GET_CHUNKS_MAX_CHUNKS,
    max_chars_per_chunk: int = GET_CHUNKS_MAX_CHARS,
) -> List[Dict[str, Any]]:
    """Return chunks by id. Caps count and text length per brief."""
    if not chunk_ids:
        return []
    ids = chunk_ids[:max_chunks]
    placeholders = ",".join("?" for _ in ids)
    sql = f"""
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
      c.text_clean
    FROM chunks c
    JOIN sources s ON s.source_id = c.source_id
    JOIN games   g ON g.game_id = s.game_id
    WHERE c.chunk_id IN ({placeholders})
    ORDER BY c.chunk_id
    """
    rows = conn.execute(sql, tuple(ids)).fetchall()
    out: List[Dict[str, Any]] = []
    for r in rows:
        row_dict = dict(r)
        text = row_dict.get("text_clean") or ""
        if len(text) > max_chars_per_chunk:
            row_dict["text_clean"] = text[:max_chars_per_chunk] + "…"
        row_dict["text"] = row_dict["text_clean"]
        out.append(row_dict)
    return out


def get_meta(conn: sqlite3.Connection, key: str) -> Optional[str]:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


# --- Ingest helpers ---

def upsert_game(conn: sqlite3.Connection, game_id: str, game_name: str, created_at: str) -> None:
    conn.execute(
        "INSERT INTO games(game_id, game_name, created_at) VALUES (?, ?, ?) "
        "ON CONFLICT(game_id) DO UPDATE SET game_name = excluded.game_name",
        (game_id, game_name, created_at),
    )


def upsert_source(
    conn: sqlite3.Connection,
    game_id: str,
    source_pdf_name: str,
    source_name: str,
    pdf_path: str,
    created_at: str,
) -> int:
    """Insert or replace source by deterministic source_id from pdf_path. Returns source_id."""
    sid = source_id_from_path(pdf_path)
    conn.execute(
        """
        INSERT INTO sources(source_id, game_id, source_pdf_name, source_name, pdf_path, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(source_id) DO UPDATE SET
          source_name = excluded.source_name,
          pdf_path = excluded.pdf_path,
          created_at = excluded.created_at
        """,
        (sid, game_id, source_pdf_name, source_name, pdf_path, created_at),
    )
    return sid


def delete_chunks_by_source(conn: sqlite3.Connection, source_id: int) -> List[int]:
    rows = conn.execute("SELECT chunk_id FROM chunks WHERE source_id = ?", (source_id,)).fetchall()
    old_ids = [r["chunk_id"] for r in rows]
    conn.execute("DELETE FROM chunks WHERE source_id = ?", (source_id,))
    return old_ids


def insert_chunks(
    conn: sqlite3.Connection,
    source_id: int,
    chunk_rows: List[Tuple[int, int, Optional[str], str]],
) -> List[Tuple[int, str]]:
    """Insert chunks; return (chunk_id, text_clean) for each for embedding."""
    conn.executemany(
        "INSERT INTO chunks(source_id, page_start, page_end, section_title, text_clean) VALUES (?, ?, ?, ?, ?)",
        [(source_id, ps, pe, st, txt) for (ps, pe, st, txt) in chunk_rows],
    )
    rows = conn.execute(
        "SELECT chunk_id, text_clean FROM chunks WHERE source_id = ? ORDER BY chunk_id",
        (source_id,),
    ).fetchall()
    return [(r["chunk_id"], r["text_clean"]) for r in rows]
