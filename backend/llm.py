"""Provider-agnostic LLM layer (OpenAI-compatible chat completions).

The app can talk to more than one inference provider. By default the PRIMARY
provider is Fireworks AI (AMD-hardware-hosted models, e.g. Gemma) and the
FALLBACK is OpenRouter. Both speak the same OpenAI-compatible
/chat/completions API, so a single request+parse path serves both — only the
base URL, API key and model IDs differ. Priority is set by config.LLM_PROVIDER.

Routing: each call tries providers in priority order, skipping any whose API
key is unset, and falls back to the next provider on error. chat_json()
additionally forces a JSON-object response, validates it against a Pydantic
model, and does one in-provider repair retry before falling back.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Type, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

import config

T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    pass


@dataclass(frozen=True)
class Provider:
    name: str
    base: str
    api_key: str
    model_fast: str
    model_strong: str

    @property
    def ready(self) -> bool:
        return bool(self.api_key)

    def headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            # Optional attribution headers (harmless on providers that ignore them):
            "HTTP-Referer": "http://localhost",
            "X-Title": "Cogni Board",
        }


def _providers() -> list[Provider]:
    """All known providers in priority order (per config.LLM_PROVIDER)."""
    fireworks = Provider(
        "fireworks", config.FIREWORKS_BASE, config.FIREWORKS_API_KEY,
        config.FIREWORKS_MODEL_FAST, config.FIREWORKS_MODEL_STRONG,
    )
    openrouter = Provider(
        "openrouter", config.OPENROUTER_BASE, config.OPENROUTER_API_KEY,
        config.OPENROUTER_MODEL_FAST, config.OPENROUTER_MODEL_STRONG,
    )
    return [openrouter, fireworks] if config.LLM_PROVIDER == "openrouter" else [fireworks, openrouter]


def _ready_providers() -> list[Provider]:
    ready = [p for p in _providers() if p.ready]
    if not ready:
        raise LLMError(
            "No LLM provider configured. Set FIREWORKS_API_KEY (preferred) "
            "or OPENROUTER_API_KEY in backend/.env."
        )
    return ready


async def _post(provider: Provider, messages: list[dict], model: str,
                json_mode: bool, temperature: float) -> str:
    payload: dict = {"model": model, "messages": messages, "temperature": temperature}
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    async with httpx.AsyncClient(timeout=90.0) as client:
        resp = await client.post(
            f"{provider.base}/chat/completions", headers=provider.headers(), json=payload
        )
    if resp.status_code >= 400:
        raise LLMError(f"{provider.name} HTTP {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError):
        raise LLMError(f"Unexpected {provider.name} response: {json.dumps(data)[:300]}")
    if content is None:
        raise LLMError(
            f"{provider.name} returned null content (reasoning overflow?): {json.dumps(data)[:300]}"
        )
    return content


def _extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.lstrip().startswith("json"):
            text = text.lstrip()[4:]
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise LLMError(f"No JSON object in model output: {text[:200]}")
    return json.loads(text[start : end + 1])


async def chat_text(system: str, user: str, model: str | None = None,
                    temperature: float = 0.4) -> str:
    """Free-text completion. Uses each provider's 'strong' model unless overridden."""
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    last = ""
    for p in _ready_providers():
        try:
            return await _post(p, messages, model or p.model_strong, False, temperature)
        except LLMError as e:
            last = f"{p.name}: {e}"
    raise LLMError(f"chat_text failed across providers. Last error: {last}")


async def chat_json(
    system: str,
    user: str,
    model_cls: Type[T],
    model: str | None = None,
    temperature: float = 0.2,
) -> T:
    """Validated JSON completion. Embeds the JSON schema in the prompt, requests
    json_object mode, validates against model_cls, and retries once per provider
    on validation failure before falling back to the next provider."""
    schema = json.dumps(model_cls.model_json_schema())
    sys_full = (
        f"{system}\n\nReturn ONLY a JSON object matching this JSON Schema "
        f"(no prose, no markdown):\n{schema}"
    )
    last = ""
    for p in _ready_providers():
        m = model or p.model_fast
        messages = [
            {"role": "system", "content": sys_full},
            {"role": "user", "content": user},
        ]
        for _ in range(2):
            try:
                raw = await _post(p, messages, m, True, temperature)
            except LLMError as e:
                last = f"{p.name}: {e}"
                break  # transport/HTTP error — no point repairing; try next provider
            try:
                return model_cls.model_validate(_extract_json(raw))
            except (ValidationError, json.JSONDecodeError, LLMError) as e:
                last = f"{p.name}: {e}"
                messages.append({"role": "assistant", "content": raw})
                messages.append(
                    {"role": "user", "content": f"That failed validation: {last}. "
                     "Return corrected JSON only."}
                )
    raise LLMError(f"chat_json failed across providers. Last error: {last}")
