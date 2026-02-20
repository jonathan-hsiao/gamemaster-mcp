"""System prompt builder: app prompt (here) + MCP server instructions."""

from __future__ import annotations

# Single place for app-level system prompt. Prepended to server instructions when present.
APP_PROMPT = """You are a board game rules referee."""


def build_system_prompt(server_instructions: str | None = None) -> str:
    """Build system prompt from APP_PROMPT plus MCP server instructions."""
    app = (APP_PROMPT or "").strip()
    server = (server_instructions or "").strip()
    if not app:
        return server
    if not server:
        return app
    return app + "\n\n" + server
