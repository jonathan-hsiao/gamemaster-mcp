"""OpenAI LLM client implementation."""

from __future__ import annotations

from typing import Any, Dict, List

from openai import OpenAI

from gamemaster_mcp.agent.llm_base import LLMClient
from gamemaster_mcp.config import OPENAI_API_KEY, OPENAI_MODEL


class OpenAIClient(LLMClient):
    """OpenAI client with tool calling support."""

    def __init__(
        self,
        model: str = OPENAI_MODEL,
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> None:
        self.model = model
        self.client = OpenAI(api_key=api_key or OPENAI_API_KEY, base_url=base_url)

    def generate(
        self,
        messages: List[Dict[str, str]],
        tools: List[Dict[str, Any]] | None = None,
    ) -> Dict[str, Any]:
        """Send messages and tools; return response (may include tool_calls)."""
        kwargs: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        response = self.client.chat.completions.create(**kwargs)
        msg = response.choices[0].message

        out: Dict[str, Any] = {"content": msg.content or ""}
        if msg.tool_calls:
            out["tool_calls"] = [
                {
                    "id": tc.id,
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                }
                for tc in msg.tool_calls
            ]
        return out

    def parse_tool_calls(self, model_output: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Extract tool calls from OpenAI response."""
        calls = model_output.get("tool_calls", [])
        return [
            {
                "id": c.get("id"),
                "name": c.get("name"),
                "arguments": c.get("arguments"),
            }
            for c in calls
        ]

    def finalize(
        self,
        messages: List[Dict[str, str]],
        tool_outputs: List[Dict[str, Any]],
    ) -> str:
        """Send messages + tool outputs; return final answer."""
        full_messages = messages.copy()
        for tool_out in tool_outputs:
            full_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_out.get("id"),
                    "content": str(tool_out.get("result", "")),
                }
            )

        response = self.client.chat.completions.create(
            model=self.model,
            messages=full_messages,
        )
        return response.choices[0].message.content or ""
