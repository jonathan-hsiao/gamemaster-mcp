"""Middleware: log every MCP tool call (name, sanitized args, duration, success/error)."""

from __future__ import annotations

import logging
import time
from typing import Any

from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools.tool import ToolResult

log = logging.getLogger(__name__)

# Max chars to log per string arg (query, pdf_path, etc.)
_MAX_ARG_LOG_LEN = 80


def _sanitize_args(arguments: dict[str, Any] | None) -> dict[str, Any]:
    if not arguments:
        return {}
    out: dict[str, Any] = {}
    for k, v in arguments.items():
        if v is None:
            out[k] = None
        elif isinstance(v, str):
            s = v.strip()
            out[k] = (s[: _MAX_ARG_LOG_LEN] + "…") if len(s) > _MAX_ARG_LOG_LEN else s
        elif isinstance(v, list):
            out[k] = f"<list len={len(v)}>"
        else:
            out[k] = v
    return out


class ToolLoggingMiddleware(Middleware):
    """Log each tool invocation at INFO: name, sanitized args, duration, success/error code."""

    async def on_call_tool(
        self,
        context: MiddlewareContext[Any],
        call_next: CallNext[Any, Any],
    ) -> Any:
        name = getattr(context.message, "name", "unknown")
        arguments = getattr(context.message, "arguments", None) or {}
        args_sanitized = _sanitize_args(arguments)
        t0 = time.perf_counter()
        try:
            result = await call_next(context)
            dur = time.perf_counter() - t0
            success = True
            error_code = None
            if isinstance(result, ToolResult) and result.structured_content:
                sc = result.structured_content
                if isinstance(sc, dict) and sc.get("error") is True:
                    success = False
                    error_code = sc.get("code")
            log.info(
                "mcp_tool name=%s args=%s duration_sec=%.3f success=%s%s",
                name,
                args_sanitized,
                dur,
                success,
                f" error_code={error_code!r}" if error_code else "",
            )
            return result
        except Exception:
            dur = time.perf_counter() - t0
            log.exception(
                "mcp_tool name=%s args=%s duration_sec=%.3f success=False",
                name,
                args_sanitized,
                dur,
            )
            raise
