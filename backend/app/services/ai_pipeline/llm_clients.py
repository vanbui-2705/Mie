"""LLM backends for clip scoring.

Every backend returns raw text; `query_llm` is the only public entry point and
always returns parsed JSON or raises `LLMUnavailable`. Callers (the scorer)
catch that one exception and fall back to the heuristic tier.

Gemini and Ollama are plain HTTP services (httpx). Claude goes through the
official `anthropic` SDK — never raw HTTP.
"""
from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger("flowmeta.ai_pipeline.llm")

SUPPORTED_BACKENDS = frozenset({"gemini", "ollama", "claude"})

_GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class LLMUnavailable(RuntimeError):
    """The chosen backend could not produce usable JSON."""


def _build_client() -> httpx.AsyncClient:
    """Seam so tests can inject an httpx.MockTransport."""
    return httpx.AsyncClient(timeout=settings.LLM_TIMEOUT_SECONDS)


def extract_json(text: str) -> Any:
    """Pull the first complete JSON value out of an LLM response.

    Handles bare JSON, ```json fences, and JSON surrounded by prose.
    """
    if not text or not text.strip():
        raise LLMUnavailable("empty LLM response")

    candidate = text.strip()
    if "```" in candidate:
        chunks = candidate.split("```")
        for chunk in chunks[1:]:
            body = chunk
            if body.lower().startswith("json"):
                body = body[4:]
            body = body.strip()
            if body.startswith("[") or body.startswith("{"):
                candidate = body
                break

    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass

    open_idx = min(
        (i for i in (candidate.find("["), candidate.find("{")) if i != -1),
        default=-1,
    )
    if open_idx == -1:
        raise LLMUnavailable(f"no JSON found in LLM response: {text[:200]!r}")

    opener = candidate[open_idx]
    closer = "]" if opener == "[" else "}"
    depth = 0
    in_string = False
    escaped = False
    for i in range(open_idx, len(candidate)):
        ch = candidate[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(candidate[open_idx : i + 1])
                except json.JSONDecodeError as exc:
                    raise LLMUnavailable(f"malformed JSON in LLM response: {exc}") from exc
    raise LLMUnavailable(f"unterminated JSON in LLM response: {text[:200]!r}")


async def call_gemini(prompt: str) -> str:
    if not settings.GEMINI_API_KEY:
        raise LLMUnavailable("GEMINI_API_KEY is not set")
    url = _GEMINI_URL.format(model=settings.GEMINI_MODEL)
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json"},
    }
    async with _build_client() as client:
        try:
            response = await client.post(
                url, params={"key": settings.GEMINI_API_KEY}, json=payload
            )
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPError as exc:
            raise LLMUnavailable(f"gemini request failed: {exc}") from exc
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMUnavailable(f"unexpected gemini payload: {str(data)[:200]}") from exc


async def call_ollama(prompt: str) -> str:
    url = f"{settings.OLLAMA_BASE_URL.rstrip('/')}/api/generate"
    payload = {
        "model": settings.OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "format": "json",
    }
    async with _build_client() as client:
        try:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPError as exc:
            raise LLMUnavailable(f"ollama request failed: {exc}") from exc
    text = data.get("response")
    if not text:
        raise LLMUnavailable(f"unexpected ollama payload: {str(data)[:200]}")
    return text


async def call_claude(prompt: str) -> str:
    if not settings.ANTHROPIC_API_KEY:
        raise LLMUnavailable("ANTHROPIC_API_KEY is not set")
    try:
        from anthropic import AsyncAnthropic
    except ImportError as exc:  # pragma: no cover - dependency is in requirements
        raise LLMUnavailable("anthropic SDK is not installed") from exc

    client = AsyncAnthropic(
        api_key=settings.ANTHROPIC_API_KEY, timeout=settings.LLM_TIMEOUT_SECONDS
    )
    try:
        message = await client.messages.create(
            model=settings.ANTHROPIC_MODEL,
            max_tokens=8000,
            system="You return only JSON. No prose, no markdown fences.",
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as exc:
        raise LLMUnavailable(f"claude request failed: {exc}") from exc

    if getattr(message, "stop_reason", None) == "refusal":
        raise LLMUnavailable("claude declined the request")
    parts = [block.text for block in message.content if getattr(block, "type", None) == "text"]
    if not parts:
        raise LLMUnavailable("claude returned no text content")
    return "".join(parts)


async def query_llm(prompt: str, *, backend: str) -> Any:
    """Call `backend` and return parsed JSON. Raises `LLMUnavailable` on any failure."""
    normalised = (backend or "").strip().lower()
    if normalised not in SUPPORTED_BACKENDS:
        raise LLMUnavailable(f"unsupported scoring backend: {backend!r}")

    caller = {"gemini": call_gemini, "ollama": call_ollama, "claude": call_claude}[normalised]
    logger.info("querying LLM backend=%s prompt_chars=%d", normalised, len(prompt))
    text = await caller(prompt)
    return extract_json(text)
