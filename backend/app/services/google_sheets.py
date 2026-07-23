"""Google Sheets service-account authentication and connection inspection."""
from __future__ import annotations

import base64
import json
import re
import time
from typing import Any
from urllib.parse import quote, urlparse

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding


GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"
GOOGLE_SCOPES = " ".join((
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
))
SPREADSHEET_ID_RE = re.compile(r"^[A-Za-z0-9_-]{10,255}$")


class GoogleSheetsError(Exception):
    """Safe, user-facing Google Sheets integration error."""


def parse_spreadsheet_id(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        raise GoogleSheetsError("Spreadsheet URL or ID is required")
    if "/spreadsheets/d/" in raw:
        parsed = urlparse(raw)
        if parsed.scheme not in {"http", "https"} or parsed.hostname not in {
            "docs.google.com", "drive.google.com",
        }:
            raise GoogleSheetsError("Invalid Google Sheets URL")
        raw = raw.split("/spreadsheets/d/", 1)[1].split("/", 1)[0]
    if not SPREADSHEET_ID_RE.fullmatch(raw):
        raise GoogleSheetsError("Invalid spreadsheet ID")
    return raw


def normalize_service_account_credentials(value: Any) -> dict[str, str]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise GoogleSheetsError("Credentials file is not valid JSON") from exc
    if not isinstance(value, dict):
        raise GoogleSheetsError("Service-account credentials are required")

    required = ("type", "client_email", "private_key")
    missing = [field for field in required if not str(value.get(field) or "").strip()]
    if missing:
        raise GoogleSheetsError(f"Credentials are missing: {', '.join(missing)}")
    if value.get("type") != "service_account":
        raise GoogleSheetsError("Credentials must belong to a Google service account")

    email = str(value["client_email"]).strip()
    if not email.endswith(".gserviceaccount.com") or "@" not in email:
        raise GoogleSheetsError("Invalid Google service-account email")

    token_uri = str(value.get("token_uri") or GOOGLE_TOKEN_URI).strip()
    if token_uri != GOOGLE_TOKEN_URI:
        raise GoogleSheetsError("Unsupported Google token endpoint")

    private_key = str(value["private_key"])
    try:
        serialization.load_pem_private_key(private_key.encode(), password=None)
    except (TypeError, ValueError) as exc:
        raise GoogleSheetsError("Invalid service-account private key") from exc

    return {
        "type": "service_account",
        "project_id": str(value.get("project_id") or ""),
        "private_key_id": str(value.get("private_key_id") or ""),
        "private_key": private_key,
        "client_email": email,
        "client_id": str(value.get("client_id") or ""),
        "token_uri": GOOGLE_TOKEN_URI,
    }


def serialize_service_account_credentials(credentials: dict[str, str]) -> str:
    return json.dumps(credentials, ensure_ascii=False, separators=(",", ":"))


class GoogleSheetsClient:
    def __init__(self, http_client: httpx.AsyncClient | None = None) -> None:
        self._http_client = http_client

    async def inspect_connection(
        self,
        *,
        credentials: dict[str, str],
        spreadsheet_id: str,
        sheet_name: str,
        preview_rows: int = 5,
    ) -> dict:
        normalized = normalize_service_account_credentials(credentials)
        spreadsheet_id = parse_spreadsheet_id(spreadsheet_id)
        sheet_name = str(sheet_name or "Posts").strip() or "Posts"
        if len(sheet_name) > 255:
            raise GoogleSheetsError("Sheet name is too long")

        if self._http_client is not None:
            return await self._inspect(
                self._http_client, normalized, spreadsheet_id, sheet_name, preview_rows,
            )
        async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
            return await self._inspect(
                client, normalized, spreadsheet_id, sheet_name, preview_rows,
            )

    async def _inspect(
        self,
        client: httpx.AsyncClient,
        credentials: dict[str, str],
        spreadsheet_id: str,
        sheet_name: str,
        preview_rows: int,
    ) -> dict:
        access_token = await self._access_token(client, credentials)
        headers = {"Authorization": f"Bearer {access_token}"}
        encoded_id = quote(spreadsheet_id, safe="")

        metadata = await _get_json(
            client,
            f"https://sheets.googleapis.com/v4/spreadsheets/{encoded_id}",
            headers=headers,
            params={"fields": "spreadsheetId,properties(title),sheets(properties(sheetId,title,rowCount,columnCount))"},
        )
        sheets = [
            row.get("properties", {})
            for row in metadata.get("sheets", [])
            if isinstance(row, dict)
        ]
        selected = next((row for row in sheets if row.get("title") == sheet_name), None)
        if selected is None:
            available = ", ".join(str(row.get("title")) for row in sheets[:10] if row.get("title"))
            suffix = f" Available sheets: {available}" if available else ""
            raise GoogleSheetsError(f"Sheet '{sheet_name}' was not found.{suffix}")

        drive = await _get_json(
            client,
            f"https://www.googleapis.com/drive/v3/files/{encoded_id}",
            headers=headers,
            params={"fields": "id,name,capabilities(canEdit)"},
        )

        last_row = max(1, min(int(preview_rows) + 1, 51))
        a1_range = f"'{sheet_name.replace(chr(39), chr(39) * 2)}'!A1:N{last_row}"
        values = await _get_json(
            client,
            f"https://sheets.googleapis.com/v4/spreadsheets/{encoded_id}/values/{quote(a1_range, safe='')}",
            headers=headers,
            params={"majorDimension": "ROWS", "valueRenderOption": "FORMATTED_VALUE"},
        )
        rows = values.get("values", [])
        if not isinstance(rows, list):
            rows = []
        header_row = [str(cell) for cell in rows[0]] if rows and isinstance(rows[0], list) else []
        preview = [
            [str(cell) for cell in row]
            for row in rows[1:last_row]
            if isinstance(row, list)
        ]
        can_edit = bool((drive.get("capabilities") or {}).get("canEdit"))

        return {
            "connected": True,
            "spreadsheet_id": spreadsheet_id,
            "spreadsheet_title": str((metadata.get("properties") or {}).get("title") or drive.get("name") or ""),
            "sheet_name": sheet_name,
            "sheet_id": selected.get("sheetId"),
            "row_count": int(selected.get("rowCount") or 0),
            "column_count": int(selected.get("columnCount") or 0),
            "can_edit": can_edit,
            "headers": header_row,
            "preview_rows": preview,
            "service_account_email": credentials["client_email"],
        }

    async def _access_token(
        self, client: httpx.AsyncClient, credentials: dict[str, str],
    ) -> str:
        now = int(time.time())
        claims = {
            "iss": credentials["client_email"],
            "scope": GOOGLE_SCOPES,
            "aud": GOOGLE_TOKEN_URI,
            "iat": now,
            "exp": now + 3600,
        }
        assertion = _sign_jwt(credentials, claims)
        try:
            response = await client.post(
                GOOGLE_TOKEN_URI,
                data={
                    "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                    "assertion": assertion,
                },
                headers={"Accept": "application/json"},
            )
        except httpx.HTTPError as exc:
            raise GoogleSheetsError("Could not connect to Google authentication service") from exc
        if response.status_code >= 400:
            raise GoogleSheetsError(_google_error_message(response, "Google rejected the service-account credentials"))
        try:
            payload = response.json()
        except ValueError as exc:
            raise GoogleSheetsError("Google authentication returned an invalid response") from exc
        token = str(payload.get("access_token") or "")
        if not token:
            raise GoogleSheetsError("Google authentication did not return an access token")
        return token

    async def append_rows(
        self,
        *,
        credentials: dict[str, str],
        spreadsheet_id: str,
        sheet_name: str,
        rows: list[list[str]],
    ) -> None:
        normalized = normalize_service_account_credentials(credentials)
        sid = parse_spreadsheet_id(spreadsheet_id)

        async def _do(client: httpx.AsyncClient) -> None:
            token = await self._access_token(client, normalized)
            rng = quote(f"'{sheet_name.replace(chr(39), chr(39) * 2)}'!A1", safe="")
            url = f"https://sheets.googleapis.com/v4/spreadsheets/{quote(sid, safe='')}/values/{rng}:append"
            try:
                resp = await client.post(
                    url,
                    headers={"Authorization": f"Bearer {token}"},
                    params={"valueInputOption": "USER_ENTERED", "insertDataOption": "INSERT_ROWS"},
                    json={"values": rows},
                )
            except httpx.HTTPError as exc:
                raise GoogleSheetsError("Could not connect to Google Sheets") from exc
            if resp.status_code >= 400:
                raise GoogleSheetsError(_google_error_message(resp, "Ghi Google Sheet thất bại"))

        if self._http_client is not None:
            return await _do(self._http_client)
        async with httpx.AsyncClient(timeout=20) as client:
            return await _do(client)

    async def update_cells(
        self,
        *,
        credentials: dict[str, str],
        spreadsheet_id: str,
        sheet_name: str,
        a1_range: str,
        values: list[list[str]],
    ) -> None:
        normalized = normalize_service_account_credentials(credentials)
        sid = parse_spreadsheet_id(spreadsheet_id)

        async def _do(client: httpx.AsyncClient) -> None:
            token = await self._access_token(client, normalized)
            rng = quote(f"'{sheet_name.replace(chr(39), chr(39) * 2)}'!{a1_range}", safe="")
            url = f"https://sheets.googleapis.com/v4/spreadsheets/{quote(sid, safe='')}/values/{rng}"
            try:
                resp = await client.put(
                    url,
                    headers={"Authorization": f"Bearer {token}"},
                    params={"valueInputOption": "USER_ENTERED"},
                    json={"values": values},
                )
            except httpx.HTTPError as exc:
                raise GoogleSheetsError("Could not connect to Google Sheets") from exc
            if resp.status_code >= 400:
                raise GoogleSheetsError(_google_error_message(resp, "Cập nhật Google Sheet thất bại"))

        if self._http_client is not None:
            return await _do(self._http_client)
        async with httpx.AsyncClient(timeout=20) as client:
            return await _do(client)


def _sign_jwt(credentials: dict[str, str], claims: dict) -> str:
    header = {"alg": "RS256", "typ": "JWT"}
    if credentials.get("private_key_id"):
        header["kid"] = credentials["private_key_id"]
    encoded_header = _b64_json(header)
    encoded_claims = _b64_json(claims)
    signing_input = f"{encoded_header}.{encoded_claims}".encode()
    private_key = serialization.load_pem_private_key(
        credentials["private_key"].encode(), password=None,
    )
    signature = private_key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    return f"{encoded_header}.{encoded_claims}.{_b64(signature)}"


def _b64_json(value: dict) -> str:
    return _b64(json.dumps(value, separators=(",", ":")).encode())


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


async def _get_json(
    client: httpx.AsyncClient,
    url: str,
    *,
    headers: dict[str, str],
    params: dict[str, str],
) -> dict:
    try:
        response = await client.get(url, headers=headers, params=params)
    except httpx.HTTPError as exc:
        raise GoogleSheetsError("Could not connect to Google APIs") from exc
    if response.status_code >= 400:
        fallback = "Google Sheets request failed"
        if response.status_code == 403:
            fallback = "The service account does not have permission to access this spreadsheet"
        elif response.status_code == 404:
            fallback = "Spreadsheet was not found or has not been shared with the service account"
        raise GoogleSheetsError(_google_error_message(response, fallback))
    try:
        payload = response.json()
    except ValueError as exc:
        raise GoogleSheetsError("Google API returned an invalid response") from exc
    if not isinstance(payload, dict):
        raise GoogleSheetsError("Google API returned an unexpected response")
    return payload


def _google_error_message(response: httpx.Response, fallback: str) -> str:
    try:
        payload = response.json()
        message = str((payload.get("error") or {}).get("message") or "").strip()
    except (ValueError, AttributeError):
        message = ""
    if not message:
        return fallback
    return message[:500]
