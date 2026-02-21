# Long-lived session in client chat (current limitation and shape of solution)

## The issue

The CLI keeps **one MCP session** for the whole run (`with_mcp_session` around the loop), but each user message is handled by a **new** call to `answer_with_session` with **only** that message (system + current question). So:

- **No cross-run history** - When the user sends a second message (e.g. a follow-up or “Poker” after “Which game?”), the runner builds a fresh `messages` list. The model never sees the previous Q/A or clarification from the prior run.
- **Brittle “done”** - The runner treats “no tool_calls + non-empty content” as the final answer and returns. If the model replies with plain text that isn’t the final answer (e.g. “Let me look that up.” or “Which game?”) and doesn’t call a tool, the session ends prematurely and the next user message starts a new run with no context.
- **Clarification depends on tool use** - Context is preserved only when the model uses **ask_user_clarification**; the client then prompts the user and injects the reply in the same run. If the model asks in plain text instead, we return that text, the user replies, and the next run sees only the reply with no prior question.

So we rely on prompt compliance for clarification and have no persistent conversation across user messages.

## Shape of solution: one long-lived runner + sliding context

**Goal:** A single runner invocation that never returns until an explicit quit trigger. One growing `messages` list for the whole chat; many questions, many clarifications, history preserved. When the buffer gets too large, trim using a simple sliding window so we stay within context limits.

**High-level implementation:**

1. **Runner owns the loop** - Replace “answer one question and return” with an outer loop: get next user message (callback) → if quit trigger (e.g. user types `quit` or empty), break and return; else append to `messages`. Then run the existing inner loop (LLM + tools until we have “this turn’s reply”). When we have the reply, call `on_reply(text)` so the CLI can show it, then go back to get next user message. No return except on quit. Same MCP session and tool list for the whole run.

2. **Callbacks** - The runner needs: (a) a way to get the next user message (and to get clarification when **ask_user_clarification** is called). One callback `get_user_input(prompt: str | None)` works: `None` = “prompt for next turn,” string = “show this clarification and return user’s reply.” (b) `on_reply(text)` to deliver each turn’s reply (final answer or e.g. **miscellaneous_chat** content) to the CLI for display.

3. **CLI** - Replace the current “while True: input → answer_with_session → print” with a single call to the long-lived runner, passing `get_user_input` and `on_reply`. Quit is whatever the user types that matches the configured trigger when the runner asks for the next message.

4. **Sliding context window** - Before each LLM call (or once per user turn), if `messages` exceeds a size limit, trim: keep the **system** message and drop **oldest full turns** until under the limit. A “turn” = one user message plus all following assistant/tool messages until the next user message. Limit can be by approximate token count (e.g. `len(json.dumps(messages)) // 4` or tiktoken) or by turn count (e.g. keep system + last N turns). No summarization in the minimal version.

5. **Optional: explicit text tools** - To remove reliance on “no tool_calls + content” as “done,” introduce **submit_answer(content=...)** (final answer) and **miscellaneous_chat(message=...)** (other text). Instruct the model to use these (plus **ask_user_clarification**) for all text replies. The runner then treats “done for this turn” only when **submit_answer** is called (or falls back to finalize when no tool_calls). This avoids premature session end when the model would have sent non-final text; it is independent of but compatible with the long-lived loop.

No change to MCP server tools beyond the optional submit_answer / miscellaneous_chat; the main change is runner control flow and one persistent `messages` list with trimming.
