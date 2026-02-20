"""Base LLM client abstraction."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List


class LLMClient(ABC):
    """Abstract base for LLM providers (OpenAI now; others can be added later)."""

    @abstractmethod
    def generate(
        self,
        messages: List[Dict[str, str]],
        tools: List[Dict[str, Any]] | None = None,
    ) -> Dict[str, Any]:
        """
        Send messages and optional tools; return model output (may include tool calls).
        Returns dict with 'content' and optionally 'tool_calls'.
        """

    @abstractmethod
    def parse_tool_calls(self, model_output: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Extract tool calls from model output.
        Returns list of {name, arguments} dicts.
        """

    @abstractmethod
    def finalize(
        self,
        messages: List[Dict[str, str]],
        tool_outputs: List[Dict[str, Any]],
    ) -> str:
        """
        Send messages + tool outputs; return final answer text.
        """
