"""CLI for ingesting rulebook PDF(s). Path is RULEBOOKS_DIR/<game_id>/<pdf_name> from env/config.

Entries use key=value format: game_id=wingspan,pdf_name=rulebook.pdf
Single ingest = one entry; batch = multiple entries.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from gamemaster_mcp.config import DB_PATH, INDEX_PATH, RULEBOOKS_DIR
from gamemaster_mcp.ingest import run_ingest
from gamemaster_mcp.ingest.path_validate import PathRejectedError

ALLOWED_ENTRY_KEYS = frozenset({"game_id", "pdf_name"})


def _parse_entry(s: str) -> dict[str, str] | None:
    """Parse 'key=value,key=value' into a dict. Returns None on parse error. Only game_id and pdf_name allowed."""
    out: dict[str, str] = {}
    for part in s.split(","):
        part = part.strip()
        if "=" not in part:
            return None
        key, _, value = part.partition("=")
        key, value = key.strip(), value.strip()
        if key not in ALLOWED_ENTRY_KEYS:
            return None
        out[key] = value
    return out if out else None


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Ingest rulebook PDF(s). Path is RULEBOOKS_DIR/<game_id>/<pdf_name> (from env/config). "
        "Pass one or more entries as key=value,key=value (e.g. game_id=wingspan,pdf_name=rulebook.pdf)."
    )
    ap.add_argument(
        "entries",
        nargs="+",
        help="One or more entries: key=value,key=value (keys: game_id, pdf_name). Example: game_id=wingspan,pdf_name=rulebook.pdf",
    )
    ap.add_argument("--db", default=None, help=f"SQLite path (default: {DB_PATH})")
    ap.add_argument("--index", default=None, help=f"FAISS index path (default: {INDEX_PATH})")
    ap.add_argument("--no-faiss", action="store_true", help="Skip dense index (FTS only)")
    args = ap.parse_args()

    root = RULEBOOKS_DIR.resolve()
    db_path = Path(args.db) if args.db else None
    index_path = Path(args.index) if args.index else None

    parsed: list[dict[str, str]] = []
    for i, raw in enumerate(args.entries):
        entry = _parse_entry(raw)
        if not entry or "game_id" not in entry or "pdf_name" not in entry:
            print(
                f"Error: Entry {i + 1} must be key=value,key=value with game_id and pdf_name. Got: {raw!r}",
                file=sys.stderr,
            )
            sys.exit(1)
        parsed.append(entry)

    batch = len(parsed) > 1
    n = len(parsed)
    print("Starting ingest…", file=sys.stderr, flush=True)
    if batch:
        print(f"Ingesting {n} file(s).", file=sys.stderr, flush=True)
    ok = 0
    last_report = None
    for i, entry in enumerate(parsed):
        game_id = entry["game_id"]
        pdf_name = entry["pdf_name"]
        if batch:
            print(f"  [{i + 1}/{n}] {game_id}/{pdf_name}…", file=sys.stderr, flush=True)
        else:
            print(f"  {game_id}/{pdf_name}…", file=sys.stderr, flush=True)
        try:
            report = run_ingest(
                root,
                game_id,
                pdf_name,
                source_name=None,
                skip_faiss=args.no_faiss,
                db_path=db_path,
                index_path=index_path,
                meta_path=None,
            )
            ok += 1
            last_report = report
            print(f"  {game_id}/{pdf_name}: {report['page_count']} pages, {report['chunk_count']} chunks")
        except (PathRejectedError, ValueError) as e:
            print(f"  {game_id}/{pdf_name}: failed — {e}", file=sys.stderr)

    if batch:
        print("=== Batch ingest complete ===")
        print(f"DB: {DB_PATH if not db_path else db_path}")
        print(f"OK: {ok}/{len(parsed)}")
        if ok < len(parsed):
            sys.exit(1)
    else:
        print("=== Ingest complete ===")
        print(f"DB:    {DB_PATH if not db_path else db_path}")
        if last_report is not None:
            print(f"Pages: {last_report['page_count']}, Chunks: {last_report['chunk_count']}")
            print(f"FAISS: {'built' if last_report['index_built'] else 'skipped (--no-faiss)'}")
            for w in last_report.get("warnings", []):
                print(f"Warning: {w}")
        else:
            sys.exit(1)
