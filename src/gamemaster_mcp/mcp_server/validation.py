"""Structured errors and input validation for MCP tools. Return error dicts instead of raising for bad input."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from gamemaster_mcp.config import GET_CHUNKS_MAX_CHUNKS

# Allow game_id: alphanumeric, hyphen, underscore; 1–200 chars
GAME_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,200}$")
VALID_STRATEGIES = ("sparse", "hybrid", "hybrid_rerank")


def tool_error(code: str, message: str) -> Dict[str, Any]:
    """Return a structured error dict for tool responses. Agent can pass through to the model."""
    return {"error": True, "code": code, "message": message}


def validate_game_id(game_id: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(game_id, str) or not (s := game_id.strip()):
        return tool_error("invalid_game_id", "game_id must be a non-empty string.")
    if not GAME_ID_RE.match(s):
        return tool_error("invalid_game_id", "game_id must be 1–200 chars, alphanumeric, hyphen, or underscore.")
    return None


def validate_search_args(
    game_id: Any,
    query: Any,
    k: Any,
    strategy: Any,
) -> Optional[Dict[str, Any]]:
    err = validate_game_id(game_id)
    if err:
        return err
    if not isinstance(query, str) or not query.strip():
        return tool_error("invalid_query", "query must be a non-empty string.")
    try:
        k_int = int(k) if k is not None else 8
    except (TypeError, ValueError):
        return tool_error("invalid_k", "k must be an integer.")
    if not (1 <= k_int <= 100):
        return tool_error("invalid_k", "k must be between 1 and 100.")
    if strategy is not None and str(strategy).strip().lower() not in VALID_STRATEGIES:
        return tool_error("invalid_strategy", f"strategy must be one of: {', '.join(VALID_STRATEGIES)}.")
    return None


def validate_chunk_ids(chunk_ids: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(chunk_ids, list):
        return tool_error("invalid_chunk_ids", "chunk_ids must be a list of integers.")
    if len(chunk_ids) > GET_CHUNKS_MAX_CHUNKS:
        return tool_error("invalid_chunk_ids", f"At most {GET_CHUNKS_MAX_CHUNKS} chunk IDs allowed.")
    for i, x in enumerate(chunk_ids):
        try:
            int(x)
        except (TypeError, ValueError):
            return tool_error("invalid_chunk_ids", f"chunk_ids[{i}] must be an integer.")
    return None


def validate_ingest_args(
    rulebooks_dir: Any,
    game_id: Any,
    pdf_name: Any,
) -> Optional[Dict[str, Any]]:
    """Validate ingest parameters. Full path is rulebooks_dir/game_id/pdf_name."""
    if rulebooks_dir is None or (isinstance(rulebooks_dir, str) and not str(rulebooks_dir).strip()):
        return tool_error("invalid_rulebooks_dir", "rulebooks_dir must be a non-empty path (relative or absolute).")
    root = Path(rulebooks_dir).resolve()
    if not root.exists():
        return tool_error("rulebooks_dir_not_found", f"RULEBOOKS_DIR does not exist: {root}")
    if not root.is_dir():
        return tool_error("rulebooks_dir_not_dir", f"RULEBOOKS_DIR is not a directory: {root}")
    err = validate_game_id(game_id)
    if err:
        return err
    if not isinstance(pdf_name, str) or not (name := pdf_name.strip()):
        return tool_error("invalid_pdf_name", "pdf_name must be a non-empty string (filename only).")
    if "/" in name or "\\" in name:
        return tool_error("invalid_pdf_name", "pdf_name must be a filename only (no path separators).")
    if not name.lower().endswith(".pdf"):
        return tool_error("invalid_pdf_name", "pdf_name must end with .pdf.")
    return None
