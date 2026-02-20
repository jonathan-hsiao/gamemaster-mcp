"""CLI for the agent: start a session, ask questions via MCP server, get cited answers. Exit with empty line."""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from datetime import datetime

import anyio

from gamemaster_mcp.agent.llm_openai import OpenAIClient
from gamemaster_mcp.agent.mcp_client import with_mcp_session
from gamemaster_mcp.agent.prompts import build_system_prompt
from gamemaster_mcp.agent.runner import answer_with_session
from gamemaster_mcp.config import AGENT_DEBUG_LOG_DIR, OPENAI_API_KEY

# Visual constants (work in any terminal)
RULER = "────────────────────────────────────────"
PROGRESS_PREFIX = "  › "
CHAT_PROMPT = "  Chat: "

# Label colors for "Gamemaster" and "You" on stdout (only applied when stdout is a TTY; NO_COLOR disables).
# ANSI SGR: 34=blue, 33=yellow, 94=bright blue, 93=bright yellow.
GAMEMASTER_LABEL_COLOR = "\033[34m"
YOU_LABEL_COLOR = "\033[33m"
LABEL_RESET = "\033[0m"
BANNER = r"""
  ╔════════════════════════════════════════════════════════╗
  ║   ___   _   __  __ ___ __  __   _   ___ _____ ___ ___  ║
  ║  / __| /_\ |  \/  | __|  \/  | /_\ / __|_   _| __| _ \ ║
  ║ | (_ |/ _ \| |\/| | _|| |\/| |/ _ \__  \ | | | _||   / ║
  ║  \___/_/ \_\_|  |_|___|_|  |_/_/ \_\___/ |_| |___|_|_\ ║
  ║                                                        ║
  ║     MCP + Agent · Rulebook Q&A with page citations     ║
  ╚════════════════════════════════════════════════════════╝
"""                                                          
                                                    
# Typing effect: delay in seconds per word when stdout is a TTY
TYPING_DELAY_PER_WORD = 0.05

# Optional ANSI: only if TTY and NO_COLOR not set
def _use_color(stream: object) -> bool:
    return getattr(stream, "isatty", lambda: False)() and not os.environ.get("NO_COLOR")


def _style(stream: object) -> tuple[str, str, str]:
    """Return (dim, emphasis, reset) ANSI codes or empty strings."""
    if not _use_color(stream):
        return "", "", ""
    return "\033[2m", "\033[1m", "\033[0m"


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Start the rules referee. Ask questions in the session; press Enter with no text to quit.",
    )
    ap.add_argument("--game-id", help="Default game (optional; agent will ask if missing or ambiguous)")
    ap.add_argument(
        "--source-pdf-names",
        help="Default source(s): 'all', a single filename, or comma-separated priority list.",
    )
    ap.add_argument("--model", default="gpt-5-mini", help="LLM model (default: gpt-5-mini)")
    ap.add_argument("--api-key", help="OpenAI API key (overrides OPENAI_API_KEY env)")
    ap.add_argument(
        "--debug",
        action="store_true",
        help="Write debug log (prompts, tool calls, responses) to logs/agent_debug_<timestamp>.log",
    )
    args = ap.parse_args()

    if not args.api_key and not OPENAI_API_KEY:
        print("Error: OPENAI_API_KEY not set. Set it in .env or pass --api-key", file=sys.stderr)
        sys.exit(1)

    client = OpenAIClient(model=args.model, api_key=args.api_key)
    dim_s, emph_s, reset_s = _style(sys.stderr)
    if _use_color(sys.stdout):
        gamemaster_label = f"{GAMEMASTER_LABEL_COLOR}Gamemaster{LABEL_RESET}"
        you_label = f"{YOU_LABEL_COLOR}You{LABEL_RESET}"
    else:
        gamemaster_label = "Gamemaster"
        you_label = "You"
    debug_path: str | None = None
    if args.debug:
        AGENT_DEBUG_LOG_DIR.mkdir(parents=True, exist_ok=True)
        debug_path = str(
            AGENT_DEBUG_LOG_DIR / f"agent_debug_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        )
        print(f"{dim_s}Debug log: {debug_path}{reset_s}", file=sys.stderr)
    # Stdout: never use ANSI so redirecting (e.g. ask-agent > out.txt) stays plain text.

    # Print a separator on stderr before progress whenever we just had user output (new question or clarification reply)
    _need_separator_before_next_progress: list[bool] = [False]

    def on_progress(msg: str) -> None:
        if _need_separator_before_next_progress[0]:
            _need_separator_before_next_progress[0] = False
            print(file=sys.stderr)
            sep = f"{dim_s}{RULER}{reset_s}" if dim_s else RULER
            print(sep, file=sys.stderr, flush=True)
        line = f"{PROGRESS_PREFIX}{msg}"
        if dim_s:
            line = f"{dim_s}{line}{reset_s}"
        print(line, file=sys.stderr, flush=True)

    async def _print_typing(text: str) -> None:
        """Print text word-by-word with a typing effect when stdout is a TTY; preserve newlines."""
        if not getattr(sys.stdout, "isatty", lambda: False)():
            print(text, file=sys.stdout)
            return
        # Split into tokens: each token is either a run of whitespace (e.g. newline) or a word.
        tokens = re.split(r"(\s+)", text)
        for i, tok in enumerate(tokens):
            if not tok:
                continue
            sys.stdout.write(tok)
            sys.stdout.flush()
            # Delay after words (non-whitespace), not after every space/newline
            if tok.strip():
                await asyncio.sleep(TYPING_DELAY_PER_WORD)
        print(file=sys.stdout)

    async def get_user_input(agent_message: str) -> str:
        print(RULER, file=sys.stdout)
        print(gamemaster_label, file=sys.stdout)
        print(file=sys.stdout)
        await _print_typing(agent_message)
        print(file=sys.stdout)
        print(RULER, file=sys.stdout)
        print(you_label, file=sys.stdout)
        print(file=sys.stdout)
        loop = asyncio.get_event_loop()
        reply = await loop.run_in_executor(None, lambda: input(CHAT_PROMPT).strip())
        _need_separator_before_next_progress[0] = True
        return reply

    async def run() -> None:
        print(BANNER, file=sys.stderr)
        print(f"{dim_s}Starting Gamemaster (loading models)…{reset_s}", file=sys.stderr, flush=True)
        async with with_mcp_session() as (session, openai_tools, server_instructions):
            system_prompt = build_system_prompt(server_instructions=server_instructions)
            if debug_path:
                with open(debug_path, "w", encoding="utf-8") as f:
                    f.write("Gamemaster agent debug log (MCP session)\n")
            print(file=sys.stderr)
            print(f"{emph_s}{GAMEMASTER_LABEL_COLOR if dim_s else ''}Gamemaster{reset_s}{emph_s} ready.{reset_s} Chat below; press Enter with no text to quit.", file=sys.stderr)
            if args.game_id:
                print(f"{dim_s}  Game: {args.game_id}{reset_s}", file=sys.stderr)
            if args.source_pdf_names:
                print(f"{dim_s}  Sources: {args.source_pdf_names}{reset_s}", file=sys.stderr)
            print(file=sys.stderr)
            while True:
                print(RULER, file=sys.stdout)
                print(you_label, file=sys.stdout)
                print(file=sys.stdout)
                try:
                    q = input(CHAT_PROMPT).strip()
                except (EOFError, KeyboardInterrupt):
                    print(file=sys.stderr)
                    print(RULER, file=sys.stdout)
                    print(file=sys.stderr)
                    print(f"{dim_s}So long, and thanks for all the fish.{reset_s}", file=sys.stderr)
                    print(file=sys.stderr)
                    break
                if not q:
                    print(file=sys.stderr)
                    print(RULER, file=sys.stdout)
                    print(f"{dim_s}So long, and thanks for all the fish.{reset_s}", file=sys.stderr)
                    print(file=sys.stderr)
                    break
                _need_separator_before_next_progress[0] = True
                answer = await answer_with_session(
                    session,
                    openai_tools,
                    client,
                    q,
                    game_id=args.game_id,
                    source_pdf_names=args.source_pdf_names,
                    debug_path=debug_path,
                    get_user_input=get_user_input,
                    on_progress=on_progress,
                    system_prompt=system_prompt,
                )
                print(RULER, file=sys.stdout)
                print(gamemaster_label, file=sys.stdout)
                print(file=sys.stdout)
                await _print_typing(answer)
                print(file=sys.stdout)

    try:
        anyio.run(run, backend="asyncio")
    except Exception as e:
        if "Connection closed" in str(e) or "McpError" in type(e).__name__:
            print(
                "\nTip: If the MCP server exited or failed to start, check stderr above for server errors.",
                file=sys.stderr,
            )
        raise


if __name__ == "__main__":
    main()
