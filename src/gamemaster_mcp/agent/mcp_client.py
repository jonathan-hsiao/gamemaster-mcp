"""MCP client: connect to gamemaster server via stdio, list tools, call tools."""

from __future__ import annotations

import json
import sys
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Dict, List

import mcp.types as types
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


def _default_server_params() -> StdioServerParameters:
    """Spawn the gamemaster MCP server as subprocess (same Python as current process)."""
    # Same Python/venv: python -m gamemaster_mcp.mcp_server.server
    exe = sys.executable
    # Run the server module so it uses the same venv
    args = ["-m", "gamemaster_mcp.mcp_server.server"]
    return StdioServerParameters(command=exe, args=args)


def mcp_tools_to_openai(mcp_tools: List[types.Tool]) -> List[Dict[str, Any]]:
    """Convert MCP tools/list result to OpenAI tools format for chat completions."""
    out: List[Dict[str, Any]] = []
    for t in mcp_tools:
        out.append({
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description or "",
                "parameters": t.inputSchema,
            },
        })
    return out


def call_tool_result_to_content(result: types.CallToolResult) -> str:
    """Turn MCP CallToolResult into a string for the LLM (JSON if structured, else text)."""
    if result.structuredContent is not None:
        return json.dumps(result.structuredContent, indent=2, default=str)
    parts: List[str] = []
    for block in result.content:
        if getattr(block, "type", None) == "text" and hasattr(block, "text"):
            parts.append(block.text)
        else:
            parts.append(str(block))
    return "\n".join(parts) if parts else ""


@asynccontextmanager
async def with_mcp_session(
    server_params: StdioServerParameters | None = None,
) -> AsyncIterator[tuple[ClientSession, List[Dict[str, Any]], str]]:
    """
    Async context manager: spawn MCP server, create session, yield (session, openai_tools, server_instructions).
    On exit, closes session and terminates server.
    """
    params = server_params or _default_server_params()
    async with stdio_client(params, errlog=sys.stderr) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            init_result = await session.initialize()
            server_instructions = getattr(init_result, "instructions", None) or ""
            list_result = await session.list_tools()
            openai_tools = mcp_tools_to_openai(list_result.tools)
            yield session, openai_tools, server_instructions
