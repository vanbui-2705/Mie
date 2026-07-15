import json

import pytest

from app.services import facebook_graph


class _FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code
        self.text = json.dumps(payload)

    def json(self) -> dict:
        return self._payload


class _FakeAsyncClient:
    calls: list[dict] = []
    photo_index = 0

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url: str, data=None, files=None):
        self.calls.append({"url": url, "data": dict(data or {}), "has_files": files is not None})
        if url.endswith("/photos"):
            self.__class__.photo_index += 1
            return _FakeResponse({"id": f"photo_{self.photo_index}"})
        if url.endswith("/feed"):
            return _FakeResponse({"id": "page_123_post_456"})
        return _FakeResponse({"error": {"message": "unexpected url"}}, status_code=500)


@pytest.mark.asyncio
async def test_post_page_media_groups_multiple_photos_into_one_feed_post(tmp_path, monkeypatch):
    first = tmp_path / "first.jpg"
    second = tmp_path / "second.png"
    first.write_bytes(b"fake-jpg")
    second.write_bytes(b"fake-png")
    _FakeAsyncClient.calls = []
    _FakeAsyncClient.photo_index = 0
    monkeypatch.setattr(facebook_graph.httpx, "AsyncClient", _FakeAsyncClient)

    result = await facebook_graph.post_page_media(
        "page_123",
        "page_token",
        "noi dung",
        [str(first), str(second)],
        link="https://example.test/post",
    )

    assert result["success"] is True
    assert result["post_id"] == "page_123_post_456"
    assert [call["url"].rsplit("/", 1)[-1] for call in _FakeAsyncClient.calls] == ["photos", "photos", "feed"]
    feed_call = _FakeAsyncClient.calls[-1]
    assert feed_call["data"]["message"] == "noi dung\n\nhttps://example.test/post"
    assert json.loads(feed_call["data"]["attached_media[0]"]) == {"media_fbid": "photo_1"}
    assert json.loads(feed_call["data"]["attached_media[1]"]) == {"media_fbid": "photo_2"}
