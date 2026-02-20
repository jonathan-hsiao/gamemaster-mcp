"""MCP tool: ask_user_clarification — core referee capability to resolve ambiguity."""

from __future__ import annotations

# Sentinel key so MCP clients know to prompt the user and substitute the reply as the tool result.
CLIENT_ACTION_PROMPT_USER = "prompt_user"


def ask_user_clarification(message: str) -> dict:
    """
    Ask the user to choose or clarify something (e.g. which game, which sources).

    The server cannot read user input. It returns a **sentinel** (not the user's reply).
    The MCP **client** is responsible for:

    1. Recognizing this tool's result as the sentinel (see response shape below).
    2. Showing the user `message` and collecting their reply.
    3. **Replacing** the sentinel with the user's reply when passing the tool result
       back to the model—so the model sees the user's reply as the return value of
       this tool call and can use it (e.g. as source_pdf_names or game_id).

    **Response shape (sentinel):** ``{"client_action": "prompt_user", "message": "<message>"}``
    Clients must intercept this and substitute the actual user reply as the tool result.
    """
    return {"client_action": CLIENT_ACTION_PROMPT_USER, "message": message}
