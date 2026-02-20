"""Text cleanup: normalize whitespace, fix hyphenation."""

from __future__ import annotations

import re

_WS_RE = re.compile(r"[ \t]+")
_HYPHEN_WRAP_RE = re.compile(r"([A-Za-z])-\n([a-z])")


def normalize(s: str) -> str:
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = "\n".join(_WS_RE.sub(" ", ln).rstrip() for ln in s.split("\n"))
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def fix_hyphenation(s: str) -> str:
    return _HYPHEN_WRAP_RE.sub(r"\1\2", s)
