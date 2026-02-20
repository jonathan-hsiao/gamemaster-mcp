"""Agent runner: connects to MCP server via stdio, uses LLM + tools/list and tools/call."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

from gamemaster_mcp.agent.llm_base import LLMClient
from gamemaster_mcp.agent.mcp_client import (
    call_tool_result_to_content,
    with_mcp_session,
)
from gamemaster_mcp.agent.prompts import build_system_prompt

if TYPE_CHECKING:
    from mcp import ClientSession

log = logging.getLogger(__name__)

_DEBUG_TRUNCATE_CHARS = 8000
# Max time to wait for an MCP tool call (e.g. search_rules). Model load should be ~1–2 min; longer suggests stderr blocking or network issue.
MCP_TOOL_CALL_TIMEOUT_SEC = 180

# MCP server returns this so the client prompts the user and uses their reply as the tool result
_CLARIFICATION_SENTINEL_ACTION = "prompt_user"


def _truncate(s: str, max_chars: int = _DEBUG_TRUNCATE_CHARS) -> str:
    if len(s) <= max_chars:
        return s
    return s[:max_chars] + f"\n... [truncated, total {len(s)} chars]"


def _write_debug(
    debug_path: Optional[str],
    section: str,
    content: str | Dict[str, Any] | List[Any],
) -> None:
    if not debug_path:
        return
    try:
        with open(debug_path, "a", encoding="utf-8") as f:
            f.write(f"\n{'='*60}\n{section}\n{'='*60}\n")
            if isinstance(content, (dict, list)):
                f.write(json.dumps(content, indent=2, default=str))
            else:
                f.write(_truncate(str(content)))
            f.write("\n")
    except OSError:
        pass


async def answer_with_session(
    session: ClientSession,
    openai_tools: List[Dict[str, Any]],
    llm: LLMClient,
    question: str,
    game_id: Optional[str] = None,
    source_pdf_names: Optional[str] = None,
    max_turns: int = 10,
    debug_path: Optional[str] = None,
    get_user_input: Optional[Callable[[str], str]] = None,
    on_progress: Optional[Callable[[str], None]] = None,
    system_prompt: Optional[str] = None,
) -> str:
    """
    Answer one question using an existing MCP session and tool list. Caller owns session lifecycle.
    system_prompt: built from APP_PROMPT + server instructions; optional (defaults to build_system_prompt()).
    """
    tools_for_run = list(openai_tools)
    prompt = system_prompt or build_system_prompt()

    if debug_path:
        _write_debug(
            debug_path,
            "Input",
            {"question": question, "game_id": game_id, "source_pdf_names": source_pdf_names},
        )
        _write_debug(debug_path, "System prompt", prompt)
        _write_debug(debug_path, "Tools (from MCP)", [t.get("function", {}).get("name") for t in tools_for_run])

    parts: List[str] = []
    if game_id:
        parts.append(f"Game: {game_id}")
    if source_pdf_names:
        parts.append(
            f"Sources to search (use for search_rules source_pdf_names): {source_pdf_names.strip()}"
        )
    user_content = "\n".join(parts) + "\n\n" + question if parts else question

    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": user_content},
    ]

    for turn in range(max_turns):
        if debug_path:
            _write_debug(
                debug_path,
                f"Turn {turn + 1} — messages sent to LLM",
                [
                    {
                        "role": m.get("role"),
                        "content_length": len(m.get("content", "") or ""),
                        "tool_calls": m.get("tool_calls"),
                    }
                    for m in messages
                ],
            )
        if on_progress:
            on_progress("Thinking…")
        response = llm.generate(messages, tools=tools_for_run)
        tool_calls = llm.parse_tool_calls(response)

        if debug_path:
            _write_debug(
                debug_path,
                f"Turn {turn + 1} — LLM response",
                {"content": response.get("content", ""), "tool_calls": tool_calls},
            )

        if not tool_calls:
            final_answer = response.get("content", "")
            if response.get("content"):
                messages.append({"role": "assistant", "content": response["content"]})
            if final_answer and not any(
                kw in final_answer.lower()
                for kw in ["let me", "i'll", "i will", "calling", "searching", "fetching"]
            ):
                log.info("agent_run_done turn_count=%s answer_len=%s", turn + 1, len(final_answer))
                return final_answer
            out = llm.finalize(messages, [])
            log.info("agent_run_done turn_count=%s answer_len=%s", turn + 1, len(out))
            return out

        assistant_msg: Dict[str, Any] = {
            "role": "assistant",
            "content": response.get("content") or None,
            "tool_calls": [
                {
                    "id": c.get("id"),
                    "type": "function",
                    "function": {"name": c.get("name"), "arguments": c.get("arguments", "{}")},
                }
                for c in tool_calls
            ],
        }
        messages.append(assistant_msg)

        tool_names_this_turn: List[str] = []
        result_sizes_this_turn: List[int] = []
        for call in tool_calls:
            name = call.get("name", "")
            args_str = call.get("arguments", "{}")
            try:
                args = json.loads(args_str) if isinstance(args_str, str) else args_str
            except json.JSONDecodeError:
                args = {}

            if on_progress:
                on_progress(f"Calling {name}…")
            try:
                mcp_result = await asyncio.wait_for(
                    session.call_tool(name, arguments=args or None),
                    timeout=MCP_TOOL_CALL_TIMEOUT_SEC,
                )
            except asyncio.TimeoutError:
                log.warning(
                    "mcp_tool_timeout name=%s timeout_sec=%s (server did not respond)",
                    name,
                    MCP_TOOL_CALL_TIMEOUT_SEC,
                )
                result_for_llm = (
                    f"Error: tool {name!r} did not respond within {MCP_TOOL_CALL_TIMEOUT_SEC}s. "
                    "If this is search_rules, the server may be loading models (first run) or blocked on output."
                )
                mcp_result = None
            else:
                # MCP ask_user_clarification returns a sentinel; client must prompt user and use reply
                sc = getattr(mcp_result, "structuredContent", None)
                if (
                    name == "ask_user_clarification"
                    and get_user_input
                    and isinstance(sc, dict)
                    and sc.get("client_action") == _CLARIFICATION_SENTINEL_ACTION
                ):
                    msg = sc.get("message", "")
                    if asyncio.iscoroutinefunction(get_user_input):
                        result_for_llm = await get_user_input(msg)
                    else:
                        result_for_llm = get_user_input(msg)
                else:
                    result_for_llm = call_tool_result_to_content(mcp_result)
            result = result_for_llm

            tool_names_this_turn.append(name)
            result_sizes_this_turn.append(len(result_for_llm))
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.get("id"),
                    "name": name,
                    "content": result_for_llm,
                }
            )
            if debug_path:
                _write_debug(
                    debug_path,
                    f"Turn {turn + 1} — tool: {name}",
                    {"arguments": args, "result_preview": _truncate(result_for_llm, 2000)},
                )

        log.info(
            "agent_turn turn=%s tool_names=%s result_sizes=%s",
            turn + 1,
            tool_names_this_turn,
            result_sizes_this_turn,
        )

    out = llm.finalize(messages, [])
    log.info("agent_run_done turn_count=%s answer_len=%s", max_turns, len(out or ""))
    return out or ""


async def answer_async(
    llm: LLMClient,
    question: str,
    game_id: Optional[str] = None,
    source_pdf_names: Optional[str] = None,
    max_turns: int = 10,
    debug_path: Optional[str] = None,
    get_user_input: Optional[Callable[[str], str]] = None,
    on_progress: Optional[Callable[[str], None]] = None,
) -> str:
    """
    Answer a question by connecting to the MCP server, discovering tools, and running the LLM loop.
    Returns final answer with citations. Spawns the MCP server for this run and tears it down after.
    """
    interactive = get_user_input is not None
    log.info(
        "agent_run_start question_len=%s game_id=%s source_pdf_names=%s interactive=%s",
        len(question),
        game_id or "",
        (source_pdf_names or "").strip() or "",
        interactive,
    )
    try:
        async with with_mcp_session() as (session, mcp_openai_tools, server_instructions):
            system_prompt = build_system_prompt(server_instructions=server_instructions)
            if debug_path:
                with open(debug_path, "w", encoding="utf-8") as f:
                    f.write("Gamemaster agent debug log (MCP)\n")
            return await answer_with_session(
                session,
                mcp_openai_tools,
                llm,
                question,
                game_id=game_id,
                source_pdf_names=source_pdf_names,
                max_turns=max_turns,
                debug_path=debug_path,
                get_user_input=get_user_input,
                on_progress=on_progress,
                system_prompt=system_prompt,
            )
    except Exception:
        log.exception("agent_run failed")
        raise
