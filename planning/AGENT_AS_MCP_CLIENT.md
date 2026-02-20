# Agent as MCP Client (proper agent + MCP)

**Status: Implemented.** The agent is MCP-only: it connects to the MCP server over stdio, discovers tools via `tools/list`, and executes via `tools/call`. There is no in-process agent path.

This doc describes the architecture and how it was built.

## Current vs original (in-process)

| | Before (in-process) | Now (agent + MCP) |
|---|----------------------|----------------------|
| **Agent** | Same process as CLI; imported tool implementations | Spawns MCP server subprocess; no tool imports |
| **Tool discovery** | Derived from Python functions (`tool_schemas.py`) | MCP `tools/list` at runtime |
| **Tool execution** | Direct Python call | MCP `tools/call` over stdio |
| **Single source of truth** | Python functions + shared schema module | MCP server (agent gets everything from it) |

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  ask-agent (CLI)                                                 │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │  MCP-backed agent                                            │ │
│  │  • Spawns MCP server subprocess (stdio)                      │ │
│  │  • ClientSession: initialize → list_tools → (loop) call_tool │ │
│  │  • Converts MCP tools → OpenAI tools format                  │ │
│  │  • LLM loop: user msg → model → tool_calls → MCP tools/call   │ │
│  │  • ask_user_clarification: local only (prompt user, no MCP)   │ │
│  └─────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
        │ stdio (JSON-RPC)
        ▼
┌─────────────────────────────────────────────────────────────────┐
│  MCP server (run-mcp or spawned subprocess)                      │
│  • list_games, list_sources, search_rules, get_chunks, ingest_pdf│
│  • Same code as today; no change to server or tool implementations│
└─────────────────────────────────────────────────────────────────┘
```

## Implementation steps

### 1. Add MCP client dependency

- Add the official SDK: `mcp` (PyPI). FastMCP is server-only; for a client you use the `mcp` package.
- In `pyproject.toml`: `mcp = "^1.0.0"` (or current stable).

### 2. MCP client helper (new module)

- **Location:** e.g. `src/gamemaster_mcp/agent/mcp_client.py`.
- **Responsibilities:**
  - **Spawn server:** `StdioServerParameters(command="poetry", args=["run", "run-mcp"], env=...)` (or resolve to the same Python that runs the agent and invoke `run-mcp`).
  - **Connect:** `async with stdio_client(server_params) as (read, write):` then `ClientSession(read, write)`, `session.initialize()`.
  - **List tools:** `session.list_tools()` → returns MCP tool list (name, description, inputSchema).
  - **Convert to OpenAI format:** Map each MCP tool to `{ "type": "function", "function": { "name", "description", "parameters": inputSchema } }`. This is the only place that needs to know OpenAI’s shape.
  - **Call tool:** `session.call_tool(name, arguments)` → return content (and isError if present) for the LLM.
- Expose: `async def get_mcp_tools_openai_format(session) -> list[dict]`, and `async def call_mcp_tool(session, name, arguments) -> dict/str`.

### 3. Agent runner that uses MCP (new or refactor)

- **Option A – New class:** `MCPAgentRunner` in e.g. `agent/runner_mcp.py`.
  - Constructor: takes LLM client + (optionally) server command/args or an already-running transport.
  - `answer(question, game_id, source_pdf_names, get_user_input, ...)`:
    1. Spawn MCP server and create session (or reuse existing).
    2. `tools_from_mcp = await get_mcp_tools_openai_format(session)`.
    3. Append `ask_user_clarification` schema (not from MCP; same as today).
    4. Run the same high-level loop as today: messages → LLM with tools → if tool_calls, for each: if `ask_user_clarification` then `get_user_input(...)`, else `await call_mcp_tool(session, name, arguments)` → append results to messages; repeat until no tool calls and return final content.
  - Same observability (logging) and debug_path behavior as current runner.
- **Option B – Refactor existing:** Replace `_execute_tool_call` with a “tool executor” abstraction: in-process executor (current) vs MCP executor (calls session.call_tool). Then one runner, two backends. Slightly more refactor, single code path.

### 4. CLI entrypoint

- **New script:** e.g. `ask-agent-mcp` (or `ask-agent` with `--use-mcp`).
  - Same args as current `ask-agent` (--question, --game-id, --source-pdf-names, --interactive, --debug).
  - Uses `MCPAgentRunner` (or runner with MCP executor) instead of `AgentRunner`.
  - Runs the async loop (e.g. `asyncio.run(runner.answer_async(...))` if you make the runner async, or the runner spawns the MCP process and uses a sync wrapper around the async MCP client if you prefer to keep the CLI sync).

### 5. Lifecycle and cleanup

- Server process: start before first tool use, keep alive for the duration of one “ask” (or optionally for the lifetime of the CLI for multiple questions). On exit, close session and terminate the server subprocess so you don’t leave run-mcp orphans.

### 6. What stays the same

- **MCP server:** No change. Same FastMCP app, same tools, same validation and logging.
- **Tool implementations:** `tools_search.py`, `tools_ingest.py`, validation, ingest pipeline unchanged.
- **Prompts:** Same system prompt and evidence-first rules; only the source of “which tools exist” and “run this tool” changes from in-process to MCP.
- **ask_user_clarification:** Still agent-only; not an MCP tool. The agent adds it to the tool list for the LLM and handles it locally (prompt user, no MCP call).

## Tool schema source

- **Today (in-process):** Schemas derived from Python functions in `tool_schemas.py`; server uses same functions and descriptions from that module.
- **With agent-as-MCP-client:** Schemas come from MCP `tools/list` only for the agent. The server remains the single source of truth; no need for the agent to import or derive from Python tool code. `tool_schemas.py` is still used by the server if you keep passing descriptions from it when registering tools, or you rely entirely on FastMCP’s inferred schema for the server; the agent just uses whatever `list_tools()` returns.

## Testing

- Run `ask-agent-mcp --question "..." --game-id wingspan --interactive` and confirm it spawns the server, gets tools, and returns a cited answer.
- Optional: integration test that starts the MCP server subprocess, connects with the MCP client, calls `list_tools` and one `call_tool`, asserts on shape and content.

## Optional later

- **SSE/HTTP:** If you run the MCP server as an HTTP/SSE service, the agent can connect with `mcp.client.sse` (or equivalent) instead of stdio; same `ClientSession` and list_tools/call_tool usage.
- **Reuse server:** For a long-running “agent service,” one MCP server process could serve many agent sessions (if the server supports concurrent sessions on that transport).
