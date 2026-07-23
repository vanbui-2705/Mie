from __future__ import annotations

import json
import uuid

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import current_user
from app.db.postgres import get_session
from app.main import app
from app.models.sqlmodels import GoogleSheetConnection, User
from app.routers import google_sheets as router_module
from app.services.google_sheets import (
    GoogleSheetsClient,
    GoogleSheetsError,
    normalize_service_account_credentials,
    parse_spreadsheet_id,
)


SPREADSHEET_ID = "1AbCdEfGhIjKlMnOpQrStUvWxYz"


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


def test_parse_spreadsheet_id_from_url_and_raw_id() -> None:
    assert parse_spreadsheet_id(SPREADSHEET_ID) == SPREADSHEET_ID
    assert parse_spreadsheet_id(
        f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit#gid=0"
    ) == SPREADSHEET_ID


def test_rejects_non_google_token_endpoint() -> None:
    credentials = _credentials()
    credentials["token_uri"] = "https://example.test/token"
    with pytest.raises(GoogleSheetsError, match="Unsupported Google token endpoint"):
        normalize_service_account_credentials(credentials)


@pytest.mark.asyncio
async def test_google_client_returns_metadata_permissions_and_preview() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url == "https://oauth2.googleapis.com/token":
            assert b"assertion=" in request.content
            return httpx.Response(200, json={"access_token": "test-token", "expires_in": 3600})
        assert request.headers["authorization"] == "Bearer test-token"
        if request.url.host == "sheets.googleapis.com" and "/values/" not in request.url.path:
            return httpx.Response(200, json={
                "spreadsheetId": SPREADSHEET_ID,
                "properties": {"title": "FlowMeta Posts"},
                "sheets": [{"properties": {
                    "sheetId": 0, "title": "Posts", "rowCount": 100, "columnCount": 14,
                }}],
            })
        if request.url.host == "www.googleapis.com":
            return httpx.Response(200, json={
                "id": SPREADSHEET_ID,
                "name": "FlowMeta Posts",
                "capabilities": {"canEdit": True},
            })
        if request.url.host == "sheets.googleapis.com" and "/values/" in request.url.path:
            return httpx.Response(200, json={
                "range": "Posts!A1:N6",
                "values": [
                    ["external_id", "content", "status"],
                    ["PT-001", "Phòng trọ Quận 7", "READY"],
                ],
            })
        return httpx.Response(404, json={"error": {"message": "unexpected request"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        result = await GoogleSheetsClient(http_client).inspect_connection(
            credentials=_credentials(),
            spreadsheet_id=SPREADSHEET_ID,
            sheet_name="Posts",
        )

    assert result["connected"] is True
    assert result["can_edit"] is True
    assert result["spreadsheet_title"] == "FlowMeta Posts"
    assert result["headers"] == ["external_id", "content", "status"]
    assert result["preview_rows"][0][0] == "PT-001"


@pytest.mark.asyncio
async def test_connection_routes_never_return_credentials(
    session: AsyncSession, user_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = User(id=user_id, username=f"sheet-{user_id.hex[:8]}", password_hash=None)
    session.add(user)
    await session.commit()

    async def fake_inspect(credentials, spreadsheet_id, sheet_name):
        return {
            "connected": True,
            "spreadsheet_id": spreadsheet_id,
            "spreadsheet_title": "FlowMeta Posts",
            "sheet_name": sheet_name,
            "sheet_id": 0,
            "row_count": 100,
            "column_count": 14,
            "can_edit": True,
            "headers": ["external_id", "content", "status"],
            "preview_rows": [],
            "service_account_email": credentials["client_email"],
        }

    monkeypatch.setattr(router_module, "_inspect_or_400", fake_inspect)

    async def override_get_session():
        yield session

    app.dependency_overrides[current_user] = lambda: user
    app.dependency_overrides[get_session] = override_get_session
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            created = await client.post("/api/google-sheets/connections", json={
                "name": "Nguồn phòng trọ",
                "spreadsheet_url": f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit",
                "sheet_name": "Posts",
                "credentials": _credentials(),
            })
            assert created.status_code == 201, created.text
            payload = created.json()
            assert payload["name"] == "Nguồn phòng trọ"
            assert payload["service_account_email"].endswith(".gserviceaccount.com")
            assert "credentials" not in json.dumps(payload).lower()
            connection_id = payload["id"]

            listed = await client.get("/api/google-sheets/connections")
            assert listed.status_code == 200
            assert [row["id"] for row in listed.json()] == [connection_id]

            deleted = await client.delete(f"/api/google-sheets/connections/{connection_id}")
            assert deleted.status_code == 200
            assert deleted.json()["deleted"] is True
    finally:
        app.dependency_overrides.pop(current_user, None)
        app.dependency_overrides.pop(get_session, None)

    remaining = list((await session.execute(select(GoogleSheetConnection))).scalars())
    assert remaining == []
