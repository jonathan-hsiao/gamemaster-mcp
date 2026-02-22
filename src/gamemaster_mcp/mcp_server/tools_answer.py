"""MCP tool: submit_answer — signals the final answer for the current turn (client ends turn on this)."""

from __future__ import annotations


def submit_answer(content: str) -> str:
    """
    Submit your final answer to the user for this turn.

    Call this when you have the complete, cited answer to the user's question.
    The client will show this content and then wait for the next user message.
    Do not rely on returning plain text as the final response; always use
    submit_answer for the final answer so the conversation can continue correctly.
    """
    return "OK"
