"""CLI entry points: ingest-rulebook, ask-agent."""

from gamemaster_mcp.cli.agent import main as ask_agent_main
from gamemaster_mcp.cli.ingest import main as ingest_main

__all__ = ["ask_agent_main", "ingest_main"]
