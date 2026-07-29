import pytest

from app.services import peer_client


class _FakeResp:
    def __init__(self, status_code: int, payload: dict | None = None) -> None:
        self.status_code = status_code
        self._payload = payload or {}

    def json(self) -> dict:
        return self._payload


class _FakeClient:
    def __init__(self, resp=None, boom=False) -> None:
        self._resp = resp
        self._boom = boom

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, **kw):
        if self._boom:
            raise RuntimeError("connection refused")
        return self._resp

    async def request(self, method, url, **kw):
        if self._boom:
            raise RuntimeError("connection refused")
        return self._resp


@pytest.mark.asyncio
async def test_peer_available_true_on_200(monkeypatch) -> None:
    monkeypatch.setattr(peer_client.httpx, "AsyncClient", lambda *a, **k: _FakeClient(_FakeResp(200)))
    assert await peer_client.peer_available("http://face") is True


@pytest.mark.asyncio
async def test_peer_available_false_when_down(monkeypatch) -> None:
    monkeypatch.setattr(peer_client.httpx, "AsyncClient", lambda *a, **k: _FakeClient(boom=True))
    assert await peer_client.peer_available("http://face") is False


@pytest.mark.asyncio
async def test_call_peer_returns_none_when_down(monkeypatch) -> None:
    monkeypatch.setattr(peer_client.httpx, "AsyncClient", lambda *a, **k: _FakeClient(boom=True))
    result = await peer_client.call_peer("http://face", "POST", "/api/x", json={"a": 1})
    assert result is None


@pytest.mark.asyncio
async def test_call_peer_returns_json_when_up(monkeypatch) -> None:
    monkeypatch.setattr(
        peer_client.httpx, "AsyncClient",
        lambda *a, **k: _FakeClient(_FakeResp(200, {"ok": True})),
    )
    result = await peer_client.call_peer("http://face", "GET", "/api/health")
    assert result == {"ok": True}
