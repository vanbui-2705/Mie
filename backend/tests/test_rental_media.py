import socket
import uuid

import httpx
import pytest

from app.services.rental_media import RentalMediaError, RentalMediaStore


@pytest.mark.asyncio
async def test_downloads_image_to_user_scoped_path(tmp_path, monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
        ],
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"\x89PNG\r\n\x1a\nimage",
            headers={"content-type": "image/png"},
        )

    user_id = uuid.uuid4()
    config_id = uuid.uuid4()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        paths = await RentalMediaStore(
            root=tmp_path, http_client=client,
        ).download(
            user_id=user_id,
            config_id=config_id,
            external_room_id="R1",
            urls=["https://images.example.com/r1.png"],
        )

    assert len(paths) == 1
    assert str(user_id) in paths[0]
    assert str(config_id) in paths[0]
    assert open(paths[0], "rb").read().startswith(b"\x89PNG")


@pytest.mark.asyncio
async def test_rejects_private_image_address(tmp_path, monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80))
        ],
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200))) as client:
        with pytest.raises(RentalMediaError, match="Private"):
            await RentalMediaStore(root=tmp_path, http_client=client).download(
                user_id=uuid.uuid4(),
                config_id=uuid.uuid4(),
                external_room_id="R1",
                urls=["http://example.com/r1.png"],
            )
