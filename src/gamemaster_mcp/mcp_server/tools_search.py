"""MCP tools: list_games, list_sources, search_rules, get_chunks."""

from __future__ import annotations

from typing import Any, List, Union

from gamemaster_mcp.config import DB_PATH
from gamemaster_mcp.mcp_server.validation import (
    tool_error,
    validate_chunk_ids,
    validate_game_id,
    validate_search_args,
)
from gamemaster_mcp.storage import connect_db, list_games as store_list_games, list_sources as store_list_sources
from gamemaster_mcp.search import get_chunks_for_agent, search_rules as pipeline_search_rules


def list_games() -> list[dict] | dict[str, Any]:
    """List all games in the rules store. Returns [{game_id, game_name}]."""
    conn = connect_db(DB_PATH)
    try:
        return store_list_games(conn)
    finally:
        conn.close()


def list_sources(game_id: str) -> list[dict] | dict[str, Any]:
    """List sources for a game. Returns [{source_id, source_pdf_name, source_name, page_count, created_at}]."""
    err = validate_game_id(game_id)
    if err:
        return err
    conn = connect_db(DB_PATH)
    try:
        return store_list_sources(conn, game_id.strip())
    finally:
        conn.close()


def search_rules(
    game_id: str,
    query: str,
    source_pdf_names: Union[str, List[str]] = "all",
    k: int = 8,
    strategy: str = "hybrid",
) -> list[dict] | dict[str, Any]:
    """
    Search rule chunks for a game. Returns list of EvidenceSummary (citation + scores + snippet).
    source_pdf_names: "all", a single source_pdf_name, or a priority-ordered list (each result includes source_priority).
    strategy: "sparse" (FTS5 only), "hybrid" (sparse FTS5 + dense FAISS), "hybrid_rerank" (hybrid + cross-encoder rerank).
    """
    err = validate_search_args(game_id, query, k, strategy)
    if err:
        return err
    k_int = int(k) if k is not None else 8
    strat = str(strategy).strip().lower() if strategy is not None else "hybrid"
    return pipeline_search_rules(
        game_id.strip(), query.strip(), k=k_int, strategy=strat, source_pdf_names=source_pdf_names
    )


def get_chunks(chunk_ids: list[int]) -> list[dict] | dict[str, Any]:
    """Fetch full chunk text for the given chunk IDs (for answer grounding). Capped at 20 chunks, 4000 chars each."""
    err = validate_chunk_ids(chunk_ids)
    if err:
        return err
    return get_chunks_for_agent([int(x) for x in chunk_ids])
