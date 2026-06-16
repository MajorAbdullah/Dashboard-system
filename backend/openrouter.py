"""Minimal async OpenRouter client (OpenAI-compatible chat completions).

chat_json() forces a JSON object response, validates it against a Pydantic model,
and does one repair retry on validation failure — robust across OpenRouter models
without relying on per-model strict json_schema support.
"""
from __future__ import annotations

import json
from typing import Type, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

import config

T = TypeVar("T", bound=BaseModel)


class OpenRouterError(RuntimeError):
    pass


def _headers() -> dict[str, str]:
    if not config.OPENROUTER_API_KEY:
        raise OpenRouterError("OPENROUTER_API_KEY is not set in backend/.env")
    return {
        "Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        # Optional attribution headers OpenRouter recommends:
        "HTTP-Referer": "http://localhost",
        "X-Title": "Agentic Dashboard AI",
    }


async def _chat(messages: list[dict], model: str, json_mode: bool, temperature: float) -> str:
    payload: dict = {"model": model, "messages": messages, "temperature": temperature}
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    async with httpx.AsyncClient(timeout=90.0) as client:
        resp = await client.post(
            f"{config.OPENROUTER_BASE}/chat/completions", headers=_headers(), json=payload
        )
    if resp.status_code >= 400:
        raise OpenRouterError(f"OpenRouter HTTP {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError):
        raise OpenRouterError(f"Unexpected OpenRouter response: {json.dumps(data)[:300]}")


async def chat_text(system: str, user: str, model: str | None = None, temperature: float = 0.4) -> str:
    model = model or config.OPENROUTER_MODEL_STRONG
    return await _chat(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        model, json_mode=False, temperature=temperature,
    )


def _extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.lstrip().startswith("json"):
            text = text.lstrip()[4:]
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise OpenRouterError(f"No JSON object in model output: {text[:200]}")
    return json.loads(text[start : end + 1])


async def chat_json(
    system: str,
    user: str,
    model_cls: Type[T],
    model: str | None = None,
    temperature: float = 0.2,
) -> T:
    """Get a validated instance of model_cls from the LLM. Embeds the JSON schema in
    the prompt, requests json_object mode, validates, and retries once on failure."""
    model = model or config.OPENROUTER_MODEL_FAST
    schema = json.dumps(model_cls.model_json_schema())
    sys_full = (
        f"{system}\n\nReturn ONLY a JSON object matching this JSON Schema "
        f"(no prose, no markdown):\n{schema}"
    )
    messages = [
        {"role": "system", "content": sys_full},
        {"role": "user", "content": user},
    ]
    last_err = ""
    for attempt in range(2):
        raw = await _chat(messages, model, json_mode=True, temperature=temperature)
        try:
            return model_cls.model_validate(_extract_json(raw))
        except (ValidationError, json.JSONDecodeError, OpenRouterError) as e:
            last_err = str(e)
            messages.append({"role": "assistant", "content": raw})
            messages.append(
                {"role": "user", "content": f"That failed validation: {last_err}. "
                 "Return corrected JSON only."}
            )
    raise OpenRouterError(f"chat_json failed after retry: {last_err}")
