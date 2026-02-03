"""Unit tests for app.llm.create_llm factory."""

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "agent-server"))

from app.llm import create_llm  # noqa: E402
from app.main import Settings  # noqa: E402


def _settings(**overrides):
    defaults = dict(
        datasets_dir="datasets",
        capsule_db_path="/tmp/test_llm_capsules.db",
        anthropic_api_key=None,
        openai_api_key=None,
    )
    defaults.update(overrides)
    return Settings(**defaults)


def test_create_llm_raises_when_no_keys():
    with pytest.raises(ValueError, match="No LLM key configured"):
        create_llm(_settings())


def test_create_llm_raises_explicit_provider_no_key():
    with pytest.raises(ValueError, match="No LLM key configured"):
        create_llm(_settings(llm_provider="anthropic"))


class _FakeChatOpenAI:
    """Stand-in for ChatOpenAI — avoids importing the real provider package."""
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class _FakeChatAnthropic:
    """Stand-in for ChatAnthropic."""
    def __init__(self, **kwargs):
        self.kwargs = kwargs


def test_create_llm_anthropic_selected_when_key_present(monkeypatch):
    import types
    fake_mod = types.ModuleType("langchain_anthropic")
    fake_mod.ChatAnthropic = _FakeChatAnthropic
    monkeypatch.setitem(__import__("sys").modules, "langchain_anthropic", fake_mod)

    s = _settings(anthropic_api_key="sk-test-fake", llm_provider="anthropic")
    llm = create_llm(s)
    assert isinstance(llm, _FakeChatAnthropic)
    assert llm.kwargs["api_key"] == "sk-test-fake"


def test_create_llm_openai_selected_when_key_present(monkeypatch):
    import types
    fake_mod = types.ModuleType("langchain_openai")
    fake_mod.ChatOpenAI = _FakeChatOpenAI
    monkeypatch.setitem(__import__("sys").modules, "langchain_openai", fake_mod)

    s = _settings(openai_api_key="sk-test-fake", llm_provider="openai")
    llm = create_llm(s)
    assert isinstance(llm, _FakeChatOpenAI)
    assert llm.kwargs["api_key"] == "sk-test-fake"


def test_create_llm_auto_prefers_openai_when_both_keys(monkeypatch):
    import types
    fake_openai_mod = types.ModuleType("langchain_openai")
    fake_openai_mod.ChatOpenAI = _FakeChatOpenAI
    fake_anthropic_mod = types.ModuleType("langchain_anthropic")
    fake_anthropic_mod.ChatAnthropic = _FakeChatAnthropic
    monkeypatch.setitem(__import__("sys").modules, "langchain_openai", fake_openai_mod)
    monkeypatch.setitem(__import__("sys").modules, "langchain_anthropic", fake_anthropic_mod)

    s = _settings(
        openai_api_key="sk-test-fake",
        anthropic_api_key="sk-test-fake",
        llm_provider="auto",
    )
    llm = create_llm(s)
    # auto prefers openai when both keys are set
    assert isinstance(llm, _FakeChatOpenAI)
