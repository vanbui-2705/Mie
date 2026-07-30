from __future__ import annotations

import json

import httpx
import pytest

from app.config import settings
from app.services.ai_pipeline import llm_clients
from app.services.ai_pipeline.llm_clients import LLMUnavailable, extract_json, query_llm


def test_extract_json_plain_array():
    assert extract_json('[{"a": 1}]') == [{"a": 1}]


def test_extract_json_strips_markdown_fence():
    raw = 'Sure, here you go:\n```json\n[{"rank": 1, "score": 90}]\n```\nHope that helps!'
    assert extract_json(raw) == [{"rank": 1, "score": 90}]


def test_extract_json_finds_embedded_object():
    assert extract_json('noise {"ok": true} trailing') == {"ok": True}


def test_extract_json_raises_on_garbage():
    with pytest.raises(LLMUnavailable):
        extract_json("no json at all")


async def test_query_llm_rejects_unknown_backend():
    with pytest.raises(LLMUnavailable) as exc:
        await query_llm("prompt", backend="nope")
    assert "nope" in str(exc.value)


async def test_query_llm_gemini_parses_response(monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-key")
    payload = {
        "candidates": [
            {"content": {"parts": [{"text": json.dumps([{"region_index": 0, "score": 88}])}]}}
        ]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert "generativelanguage.googleapis.com" in str(request.url)
        # The key must ride in the header, never the query string, so it cannot
        # leak through httpx's INFO request log or an HTTPError message.
        assert request.headers["x-goog-api-key"] == "test-key"
        assert "test-key" not in str(request.url)
        body = json.loads(request.content)
        assert body["generationConfig"]["maxOutputTokens"] == settings.GEMINI_MAX_OUTPUT_TOKENS
        assert body["generationConfig"]["thinkingConfig"]["thinkingLevel"] == "minimal"
        return httpx.Response(200, json=payload)

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(llm_clients, "_build_client", lambda: httpx.AsyncClient(transport=transport))

    assert await query_llm("prompt", backend="gemini") == [{"region_index": 0, "score": 88}]


async def test_query_llm_gemini_without_key_raises(monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "")
    with pytest.raises(LLMUnavailable):
        await query_llm("prompt", backend="gemini")


async def test_query_llm_wraps_transport_errors(monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(settings, "LLM_MAX_RETRIES", 0)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(llm_clients, "_build_client", lambda: httpx.AsyncClient(transport=transport))

    with pytest.raises(LLMUnavailable):
        await query_llm("prompt", backend="gemini")


async def test_gemini_retries_a_transient_503(monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(settings, "LLM_MAX_RETRIES", 2)
    monkeypatch.setattr(settings, "LLM_RETRY_BASE_SECONDS", 0)
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            return httpx.Response(503, request=request)
        return httpx.Response(
            200,
            request=request,
            json={"candidates": [{"content": {"parts": [{"text": '{"ok": true}'}]}}]},
        )

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(llm_clients, "_build_client", lambda: httpx.AsyncClient(transport=transport))

    assert await query_llm("prompt", backend="gemini") == {"ok": True}
    assert attempts == 3


async def test_gemini_does_not_retry_a_missing_model(monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(settings, "GEMINI_MODEL", "retired-model")
    monkeypatch.setattr(settings, "LLM_MAX_RETRIES", 2)
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(404, request=request)

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(llm_clients, "_build_client", lambda: httpx.AsyncClient(transport=transport))

    with pytest.raises(LLMUnavailable, match="retired-model"):
        await query_llm("prompt", backend="gemini")
    assert attempts == 1


async def test_gemini_retries_a_truncated_json_response(monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(settings, "LLM_MAX_RETRIES", 1)
    monkeypatch.setattr(settings, "LLM_RETRY_BASE_SECONDS", 0)
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        text = '{"ok":' if attempts == 1 else '{"ok": true}'
        finish = "MAX_TOKENS" if attempts == 1 else "STOP"
        return httpx.Response(
            200,
            request=request,
            json={
                "candidates": [
                    {
                        "finishReason": finish,
                        "content": {"parts": [{"text": text}]},
                    }
                ]
            },
        )

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(llm_clients, "_build_client", lambda: httpx.AsyncClient(transport=transport))

    assert await query_llm("prompt", backend="gemini") == {"ok": True}
    assert attempts == 2


async def test_query_llm_ollama_parses_response(monkeypatch):
    monkeypatch.setattr(settings, "OLLAMA_BASE_URL", "http://ollama.test")

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "http://ollama.test/api/generate"
        return httpx.Response(200, json={"response": '{"ok": 1}'})

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(llm_clients, "_build_client", lambda: httpx.AsyncClient(transport=transport))

    assert await query_llm("prompt", backend="ollama") == {"ok": 1}


async def test_query_llm_claude_without_key_raises(monkeypatch):
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "")
    with pytest.raises(LLMUnavailable):
        await query_llm("prompt", backend="claude")
