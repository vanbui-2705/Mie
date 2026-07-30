"""LLM backends for clip scoring.

Every backend returns raw text; `query_llm` is the only public entry point and
always returns parsed JSON or raises `LLMUnavailable`. Callers (the scorer)
catch that one exception and fall back to the heuristic tier.

Gemini and Ollama are plain HTTP services (httpx). Claude goes through the
official `anthropic` SDK — never raw HTTP.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger("flowmeta.ai_pipeline.llm")

SUPPORTED_BACKENDS = frozenset({"gemini", "ollama", "claude"})

_GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


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
        "generationConfig": {
            "responseMimeType": "application/json",
            "maxOutputTokens": settings.GEMINI_MAX_OUTPUT_TOKENS,
            # Gemini 3.5 defaults to medium thinking. These calls only need to
            # score clips/write a short JSON script, so minimal leaves the
            # output budget for the JSON instead of spending it on reasoning.
            "thinkingConfig": {"thinkingLevel": settings.GEMINI_THINKING_LEVEL},
        },
    }
    max_retries = max(0, settings.LLM_MAX_RETRIES)
    async with _build_client() as client:
        for attempt in range(max_retries + 1):
            try:
                # The key goes in a header, never the query string: httpx logs
                # the full URL and HTTPError embeds it in str(exc).
                response = await client.post(
                    url, headers={"x-goog-api-key": settings.GEMINI_API_KEY}, json=payload
                )
                response.raise_for_status()
                data = response.json()
                try:
                    candidate = data["candidates"][0]
                    text = candidate["content"]["parts"][0]["text"]
                    finish_reason = str(candidate.get("finishReason") or "").upper()
                except (KeyError, IndexError, TypeError) as exc:
                    raise LLMUnavailable(
                        f"unexpected Gemini payload: {str(data)[:200]}"
                    ) from exc
                if finish_reason == "MAX_TOKENS":
                    if attempt >= max_retries:
                        raise LLMUnavailable(
                            "Gemini truncated the JSON response after all retry attempts"
                        )
                    delay = settings.LLM_RETRY_BASE_SECONDS * (2 ** attempt)
                    logger.warning(
                        "Gemini truncated output; retrying in %.2fs (%d/%d)",
                        delay, attempt + 1, max_retries,
                    )
                    await asyncio.sleep(max(0.0, delay))
                    continue
                if not text:
                    raise LLMUnavailable("Gemini returned an empty response")
                return text
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                if status not in _RETRYABLE_STATUS or attempt >= max_retries:
                    if status == 404:
                        message = (
                            f"Gemini model {settings.GEMINI_MODEL!r} is unavailable; "
                            "check GEMINI_MODEL"
                        )
                    elif status in {401, 403}:
                        message = "Gemini rejected the API key"
                    elif status == 429:
                        message = "Gemini quota or rate limit was exceeded"
                    else:
                        message = f"Gemini request failed with HTTP {status}"
                    raise LLMUnavailable(message) from exc
                delay = settings.LLM_RETRY_BASE_SECONDS * (2 ** attempt)
                logger.warning(
                    "Gemini HTTP %d; retrying in %.2fs (%d/%d)",
                    status, delay, attempt + 1, max_retries,
                )
                await asyncio.sleep(max(0.0, delay))
            except httpx.RequestError as exc:
                if attempt >= max_retries:
                    raise LLMUnavailable(
                        f"Gemini network request failed after {attempt + 1} attempt(s)"
                    ) from exc
                delay = settings.LLM_RETRY_BASE_SECONDS * (2 ** attempt)
                logger.warning(
                    "Gemini network error; retrying in %.2fs (%d/%d)",
                    delay, attempt + 1, max_retries,
                )
                await asyncio.sleep(max(0.0, delay))
            except (ValueError, TypeError) as exc:
                raise LLMUnavailable("Gemini returned an invalid JSON response") from exc
    raise LLMUnavailable("Gemini did not return a usable response")


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
