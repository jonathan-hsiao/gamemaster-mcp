"""Agent runner: connects to MCP server via stdio, uses LLM + tools/list and tools/call."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

from gamemaster_mcp.agent.llm_base import LLMClient
from gamemaster_mcp.agent.mcp_client import call_tool_result_to_content
from gamemaster_mcp.agent.prompts import build_system_prompt
from gamemaster_mcp.config import CONTEXT_MAX_TURNS, INNER_MAX_TURNS, QUIT_TRIGGER

if TYPE_CHECKING:
    from mcp import ClientSession

log = logging.getLogger(__name__)

# Tool name the model uses to signal final answer for the turn
SUBMIT_ANSWER_TOOL = "submit_answer"

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


def _trim_messages(
    messages: List[Dict[str, Any]],
    max_turns: int = CONTEXT_MAX_TURNS,
) -> None:
    """
    Trim messages in place: keep system and last max_turns full turns.
    A turn = one user message + all following assistant/tool messages until the next user message.
    """
    if len(messages) <= 1:
        return
    system = messages[0]
    rest = messages[1:]
    user_indices = [i for i, m in enumerate(rest) if m.get("role") == "user"]
    if not user_indices:
        return
    turns = []
    for k, start in enumerate(user_indices):
        end = user_indices[k + 1] if k + 1 < len(user_indices) else len(rest)
        turns.append(rest[start:end])
    kept_turns = turns[-max_turns:] if len(turns) > max_turns else turns
    new_rest = []
    for t in kept_turns:
        new_rest.extend(t)
    messages.clear()
    messages.append(system)
    messages.extend(new_rest)


async def _invoke_on_reply(
    on_reply: Callable[[str], None],
    text: str,
) -> None:
    """Call on_reply(text), awaiting if it's a coroutine."""
    if asyncio.iscoroutinefunction(on_reply):
        await on_reply(text)
    else:
        on_reply(text)


async def _invoke_get_user_input(
    get_user_input: Callable[[Optional[str]], str],
    prompt: Optional[str],
) -> str:
    """Call get_user_input(prompt), awaiting if it's a coroutine."""
    if asyncio.iscoroutinefunction(get_user_input):
        return await get_user_input(prompt)
    return get_user_input(prompt)


async def run_session(
    session: ClientSession,
    openai_tools: List[Dict[str, Any]],
    llm: LLMClient,
    get_user_input: Callable[[Optional[str]], str],
    on_reply: Callable[[str], None],
    game_id: Optional[str] = None,
    source_pdf_names: Optional[str] = None,
    max_turns: int = INNER_MAX_TURNS,
    debug_path: Optional[str] = None,
    on_progress: Optional[Callable[[str], None]] = None,
    system_prompt: Optional[str] = None,
) -> None:
    """
    Run one session: get user messages via get_user_input(None), run LLM+tools until the turn
    ends (submit_answer or no tool_calls + content), call on_reply(text), repeat. Exit only when
    get_user_input returns the configured quit trigger (/quit). game_id/source_pdf_names are
    injected only into the first user message.
    """
    tools_for_run = list(openai_tools)
    prompt = system_prompt or build_system_prompt()
    messages: List[Dict[str, Any]] = [{"role": "system", "content": prompt}]
    first_user = True

    if debug_path:
        with open(debug_path, "w", encoding="utf-8") as f:
            f.write("Gamemaster agent debug log (long-lived session)\n")
        _write_debug(debug_path, "System prompt", prompt)
        _write_debug(debug_path, "Tools", [t.get("function", {}).get("name") for t in tools_for_run])

    while True:
        # Get next user message; re-prompt on empty, quit on trigger
        raw = await _invoke_get_user_input(get_user_input, None)
        if raw.strip() == QUIT_TRIGGER:
            log.info("long_lived_session quit trigger received")
            return
        if not raw.strip():
            continue
        # First user message: inject game_id/source_pdf_names if provided
        if first_user and (game_id or source_pdf_names):
            parts = []
            if game_id:
                parts.append(f"Game: {game_id}")
            if source_pdf_names:
                parts.append(
                    f"Sources to search (use for search_rules source_pdf_names): {source_pdf_names.strip()}"
                )
            user_content = "\n".join(parts) + "\n\n" + raw
            first_user = False
        else:
            user_content = raw
            if first_user:
                first_user = False
        messages.append({"role": "user", "content": user_content})

        if debug_path:
            _write_debug(debug_path, "User message", user_content[:500])

        turn_ended = False
        for turn in range(max_turns):
            _trim_messages(messages)
            if debug_path:
                _write_debug(
                    debug_path,
                    f"Inner turn {turn + 1} — messages",
                    [{"role": m.get("role"), "content_length": len(str(m.get("content", "")))} for m in messages],
                )
            if on_progress:
                on_progress("Thinking…")
            response = llm.generate(messages, tools=tools_for_run)
            tool_calls = llm.parse_tool_calls(response)

            if debug_path:
                _write_debug(
                    debug_path,
                    f"Inner turn {turn + 1} — response",
                    {"content": response.get("content", ""), "tool_calls": [c.get("name") for c in tool_calls]},
                )

            # Check for submit_answer in tool_calls (extract content for on_reply)
            submit_content: Optional[str] = None
            for c in tool_calls:
                if c.get("name") == SUBMIT_ANSWER_TOOL:
                    args_str = c.get("arguments", "{}")
                    try:
                        args = json.loads(args_str) if isinstance(args_str, str) else args_str
                        submit_content = args.get("content", "") or ""
                    except json.JSONDecodeError:
                        submit_content = ""
                    break

            if not tool_calls:
                final = response.get("content", "") or ""
                if response.get("content"):
                    messages.append({"role": "assistant", "content": response["content"]})
                if final.strip():
                    await _invoke_on_reply(on_reply, final)
                else:
                    out = llm.finalize(messages, [])
                    await _invoke_on_reply(on_reply, out or "")
                turn_ended = True
                break

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
                    log.warning("mcp_tool_timeout name=%s", name)
                    result_for_llm = (
                        f"Error: tool {name!r} did not respond within {MCP_TOOL_CALL_TIMEOUT_SEC}s."
                    )
                else:
                    sc = getattr(mcp_result, "structuredContent", None)
                    if (
                        name == "ask_user_clarification"
                        and get_user_input
                        and isinstance(sc, dict)
                        and sc.get("client_action") == _CLARIFICATION_SENTINEL_ACTION
                    ):
                        result_for_llm = await _invoke_get_user_input(get_user_input, sc.get("message", ""))
                    else:
                        result_for_llm = call_tool_result_to_content(mcp_result)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.get("id"),
                        "name": name,
                        "content": result_for_llm,
                    }
                )
                if debug_path:
                    _write_debug(debug_path, f"Tool: {name}", _truncate(str(args), 500))

            if submit_content is not None:
                await _invoke_on_reply(on_reply, submit_content)
                turn_ended = True
                break

        if not turn_ended:
            await _invoke_on_reply(
                on_reply,
                "I couldn't finish this; try rephrasing or asking something else.",
            )
