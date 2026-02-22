# Tool call execution pipeline

Tool call flow for the CLI chat client

| Step | Where | What happens |
|------|--------|----------------|
| 1 | `mcp_client.with_mcp_session` | Spawn server, stdio, `list_tools()` |
| 2 | `runner` + `llm.generate()` | Send messages + tools to LLM; get back `tool_calls` (name + arguments) |
| 3 | `runner` | For each call: `session.call_tool(name, arguments)` over MCP (JSON-RPC over stdio) |
| 4 | MCP server (FastMCP) | Receives `tools/call`, middleware runs, registered Python function (e.g. `search_rules`) is called with those args |
| 5 | Server → client | Return value is sent back as MCP `CallToolResult`. |
| 6 | `runner` | `call_tool_result_to_content(mcp_result)` → string; append as `role="tool"` message. |
| 7 | Loop | Go to step 2 with updated messages; stop when the model doesn’t return any tool calls. |
