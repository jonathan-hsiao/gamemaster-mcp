"""Deterministic source_id from full PDF path. Same path -> same id; re-ingest overwrites."""

from __future__ import annotations

from pathlib import Path
import hashlib


def source_id_from_path(pdf_path: str | Path) -> int:
    """
    Return a deterministic 63-bit positive integer from the full PDF path.
    Same path always yields the same id. Used for source identity and re-ingest overwrite.
    """
    path_str = str(Path(pdf_path).resolve())
    h = hashlib.sha256(path_str.encode("utf-8")).digest()[:8]
    return int.from_bytes(h, "big") % (2**63)
