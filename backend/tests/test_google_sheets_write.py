from __future__ import annotations

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization

from app.services.google_sheets import GoogleSheetsClient


def _credentials() -> dict:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_key = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    return {
        "type": "service_account",
        "project_id": "flowmeta-test",
        "private_key_id": "key-id",
        "private_key": private_key,
        "client_email": "flowmeta@flowmeta-test.iam.gserviceaccount.com",
        "client_id": "123456",
        "token_uri": "https://oauth2.googleapis.com/token",
    }


@pytest.mark.asyncio
async def test_append_rows_posts_values() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "tok"})
        seen["url"] = str(request.url)
        seen["body"] = request.content.decode()
        seen["method"] = request.method
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json={"updates": {"updatedRows": 1}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        gs = GoogleSheetsClient(http_client=http_client)
        await gs.append_rows(
            credentials=_credentials(),
            spreadsheet_id="1AbCdEfGhIjKlMnOpQrStUvWxYz",
            sheet_name="Posts",
            rows=[["P1", "3tr"]],
        )

    assert "/values/" in seen["url"]
    assert ":append" in seen["url"]
    assert seen["method"] == "POST"
    assert "P1" in seen["body"]
    assert seen["params"]["valueInputOption"] == "USER_ENTERED"
    assert seen["params"]["insertDataOption"] == "INSERT_ROWS"


@pytest.mark.asyncio
async def test_update_cells_puts_values() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "tok"})
        seen["url"] = str(request.url)
        seen["body"] = request.content.decode()
        seen["method"] = request.method
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json={"updatedRows": 1})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        gs = GoogleSheetsClient(http_client=http_client)
        await gs.update_cells(
            credentials=_credentials(),
            spreadsheet_id="1AbCdEfGhIjKlMnOpQrStUvWxYz",
            sheet_name="Posts",
            a1_range="A2:B2",
            values=[["P1", "5tr"]],
        )

    assert "values/" in seen["url"]
    assert "A2%3AB2" in seen["url"] or "A2:B2" in seen["url"]
    assert seen["method"] == "PUT"
    assert "P1" in seen["body"]
    assert seen["params"]["valueInputOption"] == "USER_ENTERED"
