from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests

from app.config import get_settings


@dataclass
class LLMResult:
    content: str
    provider: str
    model: str
    used_fallback: bool = False
    error: str | None = None


class LLMClient:
    def __init__(self):
        self.settings = get_settings()

    @property
    def available(self) -> bool:
        provider = self.settings.llm_provider.lower()
        if provider == "anthropic":
            return bool(self.settings.anthropic_api_key and self.settings.llm_model)
        if provider in {"openai", "openai-compatible"}:
            return bool(self.settings.openai_api_key and self.settings.llm_model)
        return False

    def complete(self, system: str, user: str, temperature: float = 0.2, max_tokens: int = 1200) -> LLMResult:
        provider = self.settings.llm_provider.lower()
        if not self.available:
            return LLMResult(content="", provider=provider or "none", model=self.settings.llm_model, used_fallback=True, error="LLM is not configured")
        try:
            if provider == "anthropic":
                return self._complete_anthropic(system, user, temperature, max_tokens)
            if provider in {"openai", "openai-compatible"}:
                return self._complete_openai(system, user, temperature, max_tokens)
            return LLMResult(content="", provider=provider, model=self.settings.llm_model, used_fallback=True, error=f"Unsupported provider: {provider}")
        except requests.RequestException as exc:
            return LLMResult(content="", provider=provider, model=self.settings.llm_model, used_fallback=True, error=str(exc))

    def _complete_anthropic(self, system: str, user: str, temperature: float, max_tokens: int) -> LLMResult:
        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": self.settings.anthropic_api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": self.settings.llm_model,
                "system": system,
                "messages": [{"role": "user", "content": user}],
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
            timeout=self.settings.llm_timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        content = "".join(block.get("text", "") for block in payload.get("content", []) if block.get("type") == "text")
        return LLMResult(content=content.strip(), provider="anthropic", model=self.settings.llm_model)

    def _complete_openai(self, system: str, user: str, temperature: float, max_tokens: int) -> LLMResult:
        base_url = self.settings.openai_base_url.rstrip("/")
        response = requests.post(
            f"{base_url}/chat/completions",
            headers={"authorization": f"Bearer {self.settings.openai_api_key}", "content-type": "application/json"},
            json={
                "model": self.settings.llm_model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
            timeout=self.settings.llm_timeout_seconds,
        )
        response.raise_for_status()
        payload: dict[str, Any] = response.json()
        content = payload.get("choices", [{}])[0].get("message", {}).get("content", "")
        return LLMResult(content=content.strip(), provider="openai-compatible", model=self.settings.llm_model)


_llm_client: LLMClient | None = None


def get_llm_client() -> LLMClient:
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient()
    return _llm_client
