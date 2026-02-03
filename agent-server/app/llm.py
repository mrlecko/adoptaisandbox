"""
LLM factory — consolidates provider selection into one place.

Resolution order:
  1. provider in ("auto","openai") AND openai_api_key set  → ChatOpenAI
  2. provider in ("auto","anthropic") AND anthropic_api_key set → ChatAnthropic
  3. Else → ValueError
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .main import Settings

from langchain_core.language_models import BaseChatModel


def create_llm(settings: "Settings") -> BaseChatModel:
    provider = (settings.llm_provider or "auto").strip().lower()

    if provider in ("auto", "openai") and settings.openai_api_key:
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=settings.openai_model,
            temperature=0,
            api_key=settings.openai_api_key,
        )

    if provider in ("auto", "anthropic") and settings.anthropic_api_key:
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            model=settings.anthropic_model,
            temperature=0,
            api_key=settings.anthropic_api_key,
        )

    raise ValueError(
        "No LLM key configured. Set ANTHROPIC_API_KEY or OPENAI_API_KEY, "
        "or pass llm= to create_app() for testing."
    )
