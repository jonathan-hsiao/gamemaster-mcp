"""PyMuPDF extraction: blocks per page, ordering (including 2-column)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List

import numpy as np
import fitz  # PyMuPDF

from gamemaster_mcp.ingest.normalize import normalize


@dataclass
class Block:
    x0: float
    y0: float
    text: str


def extract_blocks_page(page: fitz.Page) -> List[Block]:
    d = page.get_text("dict")
    blocks: List[Block] = []
    for b in d.get("blocks", []):
        if b.get("type") != 0:
            continue
        lines = b.get("lines", [])
        parts = []
        for ln in lines:
            spans = ln.get("spans", [])
            line_text = "".join(sp.get("text", "") for sp in spans)
            line_text = line_text.strip()
            if line_text:
                parts.append(line_text)
        txt = "\n".join(parts).strip()
        if not txt:
            continue
        x0, y0, x1, y1 = b.get("bbox", [0, 0, 0, 0])
        blocks.append(Block(float(x0), float(y0), txt))
    return blocks


def order_blocks(blocks: List[Block]) -> List[Block]:
    if not blocks:
        return blocks
    xs = np.array([b.x0 for b in blocks], dtype=np.float32)
    if xs.max() - xs.min() > 200:
        med = float(np.median(xs))
        left = [b for b in blocks if b.x0 <= med]
        right = [b for b in blocks if b.x0 > med]
        left_sorted = sorted(left, key=lambda b: (b.y0, b.x0))
        right_sorted = sorted(right, key=lambda b: (b.y0, b.x0))
        return left_sorted + right_sorted
    return sorted(blocks, key=lambda b: (b.y0, b.x0))


def is_heading(text: str) -> bool:
    t = text.strip()
    if not t:
        return False
    words = t.split()
    if len(words) > 10:
        return False
    if t.isupper():
        return True
    if sum(1 for w in words if w[:1].isupper()) >= max(2, len(words) // 2):
        return True
    return False


def extract_text_stats(pdf_path: Path) -> tuple[int, int]:
    """Return (total_chars, page_count) for text-density check."""
    doc = fitz.open(str(pdf_path))
    n_pages = doc.page_count
    total = 0
    for i in range(n_pages):
        total += len(doc.load_page(i).get_text())
    doc.close()
    return total, n_pages
