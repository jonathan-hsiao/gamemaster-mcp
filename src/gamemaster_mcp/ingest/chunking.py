"""Section-aware chunking with size/overlap fallback. Build chunks from PDF."""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Tuple

import fitz

from gamemaster_mcp.ingest.normalize import fix_hyphenation, normalize
from gamemaster_mcp.ingest.pdf_extract import (
    extract_blocks_page,
    is_heading,
    order_blocks,
)

# Brief: ~1200 chars, ~180 overlap
MAX_CHARS = 1200
OVERLAP_CHARS = 180


def build_chunks_from_pdf(pdf_path: Path) -> List[Tuple[int, int, Optional[str], str]]:
    """
    Returns list of (page_start, page_end, section_title, text_clean).
    Section-aware when headings detectable; otherwise size + overlap.
    """
    doc = fitz.open(str(pdf_path))
    chunks: List[Tuple[int, int, Optional[str], str]] = []
    cur_section: Optional[str] = None
    cur_text = ""
    cur_start_page = 1
    cur_end_page = 1

    def flush() -> None:
        nonlocal cur_text, cur_start_page, cur_end_page
        t = normalize(fix_hyphenation(cur_text))
        if t:
            chunks.append((cur_start_page, cur_end_page, cur_section, t))
        cur_text = ""

    for i in range(doc.page_count):
        page_no = i + 1
        blocks = order_blocks(extract_blocks_page(doc.load_page(i)))

        for b in blocks:
            bt = normalize(b.text)
            if not bt:
                continue

            if is_heading(bt):
                flush()
                cur_section = bt
                cur_start_page = page_no
                cur_end_page = page_no
                continue

            if not cur_text:
                cur_start_page = page_no
            cur_end_page = page_no
            cur_text = (cur_text + "\n\n" + bt) if cur_text else bt

            if len(cur_text) >= MAX_CHARS:
                flush()
                if OVERLAP_CHARS > 0 and bt:
                    cur_text = bt[-OVERLAP_CHARS:]
                    cur_start_page = page_no
                    cur_end_page = page_no

    flush()
    doc.close()
    return chunks
