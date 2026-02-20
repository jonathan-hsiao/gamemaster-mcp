"""Full ingest: validate path, check text density, chunk, write to DB, optional FAISS."""

from __future__ import annotations

import datetime as dt
import json
import logging
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

from gamemaster_mcp.config import (
    DB_PATH,
    EMBED_MODEL_NAME,
    INDEX_PATH,
    META_PATH,
    RULES_STORE_DIR,
    RULEBOOKS_DIR,
    TEXT_DENSITY_MIN_CHARS_PER_PAGE,
)
from gamemaster_mcp.ingest.chunking import build_chunks_from_pdf
from gamemaster_mcp.ingest.path_validate import PathRejectedError, validate_pdf_path
from gamemaster_mcp.ingest.pdf_extract import extract_text_stats
from gamemaster_mcp.storage import (
    connect_db,
    delete_chunks_by_source,
    insert_chunks,
    set_meta,
    upsert_game,
    upsert_source,
)
from gamemaster_mcp.index import build_embeddings, load_or_create_index, remove_ids, save_index

SCANNED_PDF_MESSAGE = (
    "This PDF appears to be scanned or image-based; extraction yielded very little text. "
    "Use an OCR tool and try again, or provide a text-based PDF."
)

log = logging.getLogger(__name__)


@contextmanager
def _ingest_lock(store_dir: Path):
    """Single-writer lock for ingest: only one run_ingest at a time."""
    lock_path = store_dir / "ingest.lock"
    store_dir.mkdir(parents=True, exist_ok=True)
    f = open(lock_path, "a+b")
    f.write(b"x")
    f.seek(0)
    try:
        try:
            import fcntl
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        except ModuleNotFoundError:
            import msvcrt
            msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)
        yield
    finally:
        try:
            import fcntl
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        except ModuleNotFoundError:
            import msvcrt
            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
        f.close()


def run_ingest(
    rulebooks_dir: str | Path,
    game_id: str,
    pdf_name: str,
    source_name: str | None = None,
    *,
    skip_faiss: bool = False,
    db_path: Optional[Path] = None,
    index_path: Optional[Path] = None,
    meta_path: Optional[Path] = None,
    min_chars_per_page: int = TEXT_DENSITY_MIN_CHARS_PER_PAGE,
    options: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Ingest a PDF into the rules store. Path is rulebooks_dir/<game_id>/<pdf_name>.
    Validates path and text density. Returns IngestReport: page_count, chunk_count, index_built, warnings.
    """
    options = options or {}
    root = Path(rulebooks_dir).resolve()
    if not root.exists():
        raise ValueError(f"RULEBOOKS_DIR does not exist: {root}")
    if not root.is_dir():
        raise ValueError(f"RULEBOOKS_DIR is not a directory: {root}")
    path = validate_pdf_path(root / game_id.strip() / pdf_name.strip(), root, game_id=game_id.strip())
    store_dir = (db_path or DB_PATH).parent if (db_path or DB_PATH) else RULES_STORE_DIR
    t0 = time.perf_counter()
    log.info("ingest start path=%s game_id=%s", path, game_id)
    try:
        source_pdf_name = path.name
        display_name = source_name if source_name is not None else source_pdf_name

        total_chars, page_count = extract_text_stats(path)
        if page_count == 0:
            raise ValueError("PDF has no pages.")
        chars_per_page = total_chars / page_count
        if chars_per_page < min_chars_per_page:
            raise ValueError(
                f"Low text density ({chars_per_page:.0f} chars/page < {min_chars_per_page}). "
                + SCANNED_PDF_MESSAGE
            )

        chunk_rows = build_chunks_from_pdf(path)
        if not chunk_rows:
            raise ValueError("No text chunks extracted. " + SCANNED_PDF_MESSAGE)

        db_path = db_path or DB_PATH
        index_path = index_path or INDEX_PATH
        meta_path = meta_path or META_PATH

        with _ingest_lock(store_dir):
            conn = connect_db(db_path)
            now = dt.datetime.now(dt.timezone.utc).isoformat()
            warnings: List[str] = []

            try:
                upsert_game(conn, game_id, game_id, now)
                source_id = upsert_source(
                    conn, game_id, source_pdf_name, display_name, str(path), now
                )
                old_ids = delete_chunks_by_source(conn, source_id)
                conn.commit()

                id_texts = insert_chunks(conn, source_id, chunk_rows)
                conn.commit()

                set_meta(conn, "embed_model", EMBED_MODEL_NAME)
                set_meta(conn, "faiss_index_path", str(index_path.resolve()))
                conn.commit()
            finally:
                conn.close()

            chunk_ids = np.array([x[0] for x in id_texts], dtype=np.int64)
            texts = [x[1] for x in id_texts]
            index_built = False

            if not skip_faiss and texts:
                emb = build_embeddings(texts, EMBED_MODEL_NAME, show_progress=False)
                dim = emb.shape[1]
                idx = load_or_create_index(index_path, dim)
                if len(old_ids) > 0:
                    remove_ids(idx, np.array(old_ids, dtype=np.int64))
                idx.add_with_ids(emb, chunk_ids)
                tmp_path = index_path.parent / (index_path.name + ".tmp")
                save_index(tmp_path, idx)
                tmp_path.replace(index_path)
                index_built = True

                meta_path.parent.mkdir(parents=True, exist_ok=True)
                meta_path.write_text(
                    json.dumps(
                        {
                            "embed_model": EMBED_MODEL_NAME,
                            "faiss_index_path": str(index_path.resolve()),
                            "dim": int(dim),
                        },
                        indent=2,
                    ),
                    encoding="utf-8",
                )

            report = {
                "page_count": page_count,
                "chunk_count": len(chunk_rows),
                "index_built": index_built,
                "warnings": warnings,
            }
        dur = time.perf_counter() - t0
        log.info(
            "ingest done path=%s game_id=%s page_count=%s chunk_count=%s index_built=%s duration_sec=%.2f",
            path, game_id, page_count, len(chunk_rows), index_built, dur,
        )
        return report
    except Exception:
        log.exception("ingest failed path=%s game_id=%s", path, game_id)
        raise
