"""
Thin LangChain wrapper around the LLM call.

Kept provider-agnostic: swap ANTHROPIC <-> OPENAI via config/env without
touching any other layer of the pipeline. The rest of the system only
depends on `LLMClient.generate(system_prompt, user_prompt) -> str`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from langchain_core.messages import HumanMessage, SystemMessage


@dataclass
class LLMConfig:
    provider: str = "anthropic"  # "anthropic" | "openai"
    model: str = "claude-sonnet-4-6"
    temperature: float = 0.0  # deterministic SQL generation
    max_tokens: int = 1024
    api_key: Optional[str] = None  # falls back to provider's env var


class LLMClient:
    def __init__(self, config: Optional[LLMConfig] = None):
        self.config = config or LLMConfig()
        self._chat_model = self._build_chat_model()

    def _build_chat_model(self):
        provider = self.config.provider.lower()

        if provider == "anthropic":
            from langchain_anthropic import ChatAnthropic

            return ChatAnthropic(
                model=self.config.model,
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
                api_key=self.config.api_key or os.getenv("ANTHROPIC_API_KEY"),
            )

        if provider == "openai":
            from langchain_openai import ChatOpenAI

            return ChatOpenAI(
                model=self.config.model,
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
                api_key=self.config.api_key or os.getenv("OPENAI_API_KEY"),
            )

        raise ValueError(f"Unsupported LLM provider: {self.config.provider!r}")

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]
        response = self._chat_model.invoke(messages)
        return response.content
