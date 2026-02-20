"""System prompt builder: APP_PROMPT + SERVER_INSTRUCTIONS + RESOURCES."""

from __future__ import annotations

from typing import List, Tuple
from urllib.parse import urlparse

# Single place for app-level system prompt.
APP_PROMPT = """You are a board game rules referee."""


def _format_resources(resources: List[Tuple[str, str]]) -> str:
    """Format (uri, content) pairs as a single RESOURCES section."""
    parts: List[str] = []
    for uri, text in resources:
        if not text.strip():
            continue
        # Use path as label so clarification/game and clarification/source keep the prefix
        try:
            label = urlparse(uri).path.lstrip("/") or uri
        except Exception:
            label = uri
        parts.append(f"## {label}\n\n{text.strip()}")
    if not parts:
        return ""
    return "---\n\n**RESOURCES**\n\n" + "\n\n".join(parts)


def build_system_prompt(
    server_instructions: str | None = None,
    resources: List[Tuple[str, str]] | None = None,
) -> str:
    """Build system prompt: APP_PROMPT, then SERVER_INSTRUCTIONS, then RESOURCES."""
    app = (APP_PROMPT or "").strip()
    server = (server_instructions or "").strip()
    res_section = _format_resources(resources or [])

    out: List[str] = []
    if app:
        out.append(app)
    if server:
        out.append(server)
    if res_section:
        out.append(res_section)
    return "\n\n".join(out) if out else ""
