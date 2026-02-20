"""MCP tools: ingest_pdf, ingest_pdfs."""

from __future__ import annotations

from typing import Any, Optional

from gamemaster_mcp.config import RULEBOOKS_DIR
from gamemaster_mcp.ingest import run_ingest
from gamemaster_mcp.ingest.path_validate import PathRejectedError
from gamemaster_mcp.mcp_server.validation import tool_error, validate_ingest_args


def _ingest_one(
    game_id: str,
    pdf_name: str,
    options: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Run single-file ingest; returns same shape as ingest_pdf (report or error dict). Uses server RULEBOOKS_DIR."""
    root = RULEBOOKS_DIR.resolve()
    err = validate_ingest_args(str(root), game_id, pdf_name)
    if err:
        return {
            **err,
            "page_count": 0,
            "chunk_count": 0,
            "index_built": False,
            "warnings": [],
        }
    options = options or {}
    try:
        return run_ingest(
            root,
            game_id.strip(),
            pdf_name.strip(),
            source_name=None,
            skip_faiss=options.get("skip_faiss", False),
            options=options,
        )
    except PathRejectedError as e:
        return {
            **tool_error("path_rejected", e.message),
            "page_count": 0,
            "chunk_count": 0,
            "index_built": False,
            "warnings": [],
        }
    except ValueError as e:
        return {
            **tool_error("ingest_failed", str(e)),
            "page_count": 0,
            "chunk_count": 0,
            "index_built": False,
            "warnings": [],
        }


def ingest_pdf(
    game_id: str,
    pdf_name: str,
    options: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """
    Ingest a text-based PDF into the rules store. Path is server RULEBOOKS_DIR/<game_id>/<pdf_name>.
    Required: game_id, pdf_name. source_name is set to pdf_name. Rejects scanned/low-text-density PDFs.
    Returns IngestReport (page_count, chunk_count, index_built, warnings).
    """
    return _ingest_one(game_id, pdf_name, options=options)


def ingest_pdfs(
    entries: list[dict[str, Any]],
    options: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """
    Ingest multiple PDFs in one call. Each element of entries must have: game_id, pdf_name. Uses server RULEBOOKS_DIR.
    Best-effort: failures do not stop the batch. Returns: results (list of per-file reports), summary (total, ok, failed).
    """
    if not isinstance(entries, list):
        return {
            "results": [],
            "summary": {"total": 0, "ok": 0, "failed": 0},
            **tool_error("invalid_entries", "entries must be a list of objects with game_id, pdf_name."),
        }
    results: list[dict[str, Any]] = []
    opts = options or {}
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            results.append({
                **tool_error("invalid_entry", f"entries[{i}] must be an object with game_id, pdf_name."),
                "page_count": 0,
                "chunk_count": 0,
                "index_built": False,
                "warnings": [],
            })
            continue
        gid = entry.get("game_id")
        pdf_name = entry.get("pdf_name")
        one_opts = entry.get("options")
        if one_opts is not None and isinstance(one_opts, dict):
            one_opts = {**opts, **one_opts}
        else:
            one_opts = opts
        if not gid or not pdf_name:
            results.append({
                **tool_error("invalid_entry", "Each entry must have game_id and pdf_name."),
                "page_count": 0,
                "chunk_count": 0,
                "index_built": False,
                "warnings": [],
            })
            continue
        results.append(_ingest_one(str(gid), str(pdf_name), options=one_opts))
    ok = sum(1 for r in results if not r.get("error"))
    return {
        "results": results,
        "summary": {"total": len(results), "ok": ok, "failed": len(results) - ok},
    }
