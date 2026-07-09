"""KiotProxy HTTP client — direct port of KiotProxyClient.cs."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Optional
from urllib.parse import quote as _urlquote

import httpx

from app.config import settings

KIOTPROXY_TIMEOUT = httpx.Timeout(connect=5.0, read=20.0, write=5.0, pool=5.0)
GET_NEW_TIMEOUT_SECONDS = 15.0

RETRY_DELAY_RE = re.compile(
    r"(?:Gửi lại sau|Gui lai sau|retry after|try again in)\s*(\d+)\s*(?:giây|giay|s|sec|secs|second|seconds)?",
    re.IGNORECASE,
)

EXPIRY_NAMES = {
    "expire", "expired", "expiration", "timeout", "ttl",
    "timelive", "lifetime", "timeleft", "remain", "duration",
}
SKIP_NAMES = {"change", "next", "request", "retry", "wait", "cooldown"}
DURATION_RE = re.compile(
    r"(\d+)\s*(?:h|hour|hours|giờ|gio|m|min|mins|minute|minutes|phút|phut|s|sec|secs|second|seconds|giây|giay)",
    re.IGNORECASE,
)


class ProxyEndpointData:
    """Parsed proxy endpoint from KiotProxy API response."""

    def __init__(
        self,
        host: str = "",
        http_port: int = 0,
        username: Optional[str] = None,
        password: Optional[str] = None,
        display: str = "",
        expires_at: Optional[datetime] = None,
        api_status: str = "",
        api_message: str = "",
    ):
        self.host = host
        self.http_port = http_port
        self.username = username
        self.password = password
        self.display = display
        self.expires_at = expires_at
        self.api_status = api_status
        self.api_message = api_message

    def proxy_url(self) -> str:
        if not self.host or not self.http_port:
            return ""
        auth = ""
        if self.username:
            pwd = self.password or ""
            auth = f"{self.username}:{pwd}@"
        return f"http://{auth}{self.host}:{self.http_port}"


class KiotProxyClient:
    """HTTP client for KiotProxy API — builds URLs from templates."""

    def _build_url(self, api_key: str, template: str) -> str:
        return template.replace("{apiKey}", _urlquote(api_key, safe=""))

    async def get_new_proxy(
        self,
        api_key: str,
        auth_token: Optional[str],
        url_template: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> ProxyEndpointData:
        template = url_template or settings.KIOT_NEW_URL
        return await self._request(api_key, auth_token, self._build_url(api_key, template), timeout)

    async def get_current_proxy(
        self,
        api_key: str,
        auth_token: Optional[str],
        url_template: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> ProxyEndpointData:
        template = url_template or settings.KIOT_CURRENT_URL
        return await self._request(api_key, auth_token, self._build_url(api_key, template), timeout)

    async def _request(
        self,
        api_key: str,
        auth_token: Optional[str],
        url: str,
        timeout: Optional[float] = None,
    ) -> ProxyEndpointData:
        effective_timeout = GET_NEW_TIMEOUT_SECONDS if timeout is None else timeout
        headers = {}
        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=effective_timeout, write=5.0, pool=5.0),
            follow_redirects=True,
        ) as client:
            resp = await client.get(url, headers=headers)
            body = resp.text

        if resp.status_code != 200:
            raise RuntimeError(self._normalize_error(body, resp.status_code))

        return self._parse_response(body)

    # ─── response parsing ───────────────────────────────────────────────────────

    def _parse_response(self, body: str) -> ProxyEndpointData:
        import json

        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            raise RuntimeError(f"KiotProxy trả về JSON không hợp lệ: {self._trim(body)}")

        # success=false at root
        if not isinstance(data, dict):
            raise RuntimeError(self._trim(f"Response không phải JSON object: {body}"))
        if data.get("success") is False:
            msg = data.get("message", "KiotProxy trả về success=false")
            raise RuntimeError(self._normalize_error_on_dict(data, msg))

        inner = data.get("data", data)
        if not isinstance(inner, dict):
            raise RuntimeError(f"Không tìm thấy 'data' trong response KiotProxy.")

        api_status = str(inner.get("status", "") or data.get("status", "") or "")
        api_message = (
            str(inner.get("message", "") or "")
            or str(inner.get("msg", "") or "")
            or str(data.get("message", "") or "")
            or str(data.get("msg", "") or "")
        )

        host = str(inner.get("host", "") or "")
        port = self._get_int(inner, "httpPort")
        username = self._get_str(inner, "proxyUser") or None
        password = self._get_str(inner, "proxyPass") or None
        http_raw = self._get_str(inner, "http") or self._get_str(inner, "httpStaticProxy") or ""
        expires_at = self._parse_expiry(inner)

        if not host or port <= 0:
            parsed = self._parse_proxy_text(http_raw)
            if parsed:
                host = host or parsed.host
                port = port or parsed.http_port
                username = username or parsed.username
                password = password or parsed.password
                expires_at = expires_at or parsed.expires_at

        if not host or port <= 0:
            raise RuntimeError("Không tìm thấy host/httpPort trong phản hồi KiotProxy.")

        display = http_raw if http_raw else f"{host}:{port}"
        return ProxyEndpointData(
            host=host,
            http_port=port,
            username=username,
            password=password,
            display=display,
            expires_at=expires_at,
            api_status=api_status,
            api_message=api_message,
        )

    # ─── text proxy fallback parsing ────────────────────────────────────────────

    @staticmethod
    def _parse_proxy_text(text: str) -> Optional[ProxyEndpointData]:
        text = text.strip()
        if not text:
            return None
        if text.lower().startswith("http://"):
            text = text[len("http://"):]
        parts = text.split(":")
        if len(parts) < 2:
            return None
        try:
            port = int(parts[1])
        except ValueError:
            return None
        return ProxyEndpointData(
            host=parts[0],
            http_port=port,
            username=parts[2] if len(parts) >= 3 else None,
            password=":".join(parts[3:]) if len(parts) >= 4 else None,
            display=text,
        )

    # ─── expiry extraction ──────────────────────────────────────────────────────
    # Recursively scans all JSON properties for expiry-like field names.

    def _parse_expiry(self, data, now: Optional[datetime] = None) -> Optional[datetime]:
        if now is None:
            now = datetime.now()
        best: Optional[datetime] = None
        for name, value in self._enumerate_props(data):
            parsed = self._try_parse_expiry_value(name, value, now)
            if parsed is None:
                continue
            if parsed <= now:
                continue
            if best is None or parsed < best:
                best = parsed
        return best

    def _enumerate_props(self, data):
        if isinstance(data, dict):
            for k, v in data.items():
                yield k, v
                yield from self._enumerate_props(v)
        elif isinstance(data, list):
            for item in data:
                yield from self._enumerate_props(item)

    def _try_parse_expiry_value(self, name: str, value, now: datetime) -> Optional[datetime]:
        import re as _re
        n = _re.sub(r"[^a-zA-Z]", "", name).lower()
        if any(s in n for s in SKIP_NAMES):
            return None
        if not any(s in n for s in EXPIRY_NAMES):
            return None
        if isinstance(value, (int, float)):
            return self._parse_numeric(n, float(value), now)
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return None
            try:
                return self._parse_numeric(n, float(text), now)
            except ValueError:
                pass
            try:
                dt = datetime.fromisoformat(text)
                return dt.astimezone().replace(tzinfo=None) if dt.tzinfo else dt
            except (ValueError, TypeError):
                pass
            dur = self._parse_duration_text(text)
            if dur:
                return now + dur
        return None

    def _parse_numeric(self, name: str, number: float, now: datetime) -> Optional[datetime]:
        if number <= 0:
            return None
        if number > 10_000_000_000:
            from datetime import timezone
            return datetime.fromtimestamp(number / 1000.0)
        if number > 1_000_000_000:
            from datetime import timezone
            return datetime.fromtimestamp(number)
        if "ms" in name or number > 86_400:
            return now.__add__(__import__("datetime").timedelta(milliseconds=number))
        if "minute" in name or "min" in name:
            return now.__add__(__import__("datetime").timedelta(minutes=number))
        if "hour" in name:
            return now.__add__(__import__("datetime").timedelta(hours=number))
        return now.__add__(__import__("datetime").timedelta(seconds=number))

    @staticmethod
    def _parse_duration_text(text: str) -> Optional["datetime.timedelta"]:
        from datetime import timedelta
        n = text.lower()
        h = _match_dur(n, r"(\d+)\s*(?:h|hour|hours|giờ|gio)")
        m = _match_dur(n, r"(\d+)\s*(?:m|min|mins|minute|minutes|phút|phut)")
        s = _match_dur(n, r"(\d+)\s*(?:s|sec|secs|second|seconds|giây|giay)")
        total = timedelta(hours=h, minutes=m, seconds=s)
        return total if total.total_seconds() > 0 else None

    # ─── error normalization ────────────────────────────────────────────────────

    @staticmethod
    def _normalize_error(body: str, status_code: int) -> str:
        try:
            import json
            data = json.loads(body)
            msg = str(data.get("message", "")) or KiotProxyClient._trim(body)
            normalized = KiotProxyClient._normalize_dict_error(data, msg)
            if KiotProxyClient._is_retry_msg(normalized):
                return normalized
            return f"KiotProxy HTTP {status_code}: {normalized}"
        except (json.JSONDecodeError, Exception):
            rd = KiotProxyClient._try_retry_delay(body)
            if rd:
                return rd
            return f"KiotProxy HTTP {status_code}: {KiotProxyClient._trim(body)}"

    @staticmethod
    def _normalize_error_on_dict(data: dict, message: str) -> str:
        normalized = KiotProxyClient._normalize_dict_error(data, message)
        if KiotProxyClient._is_retry_msg(normalized):
            return normalized
        return KiotProxyClient._trim(normalized)

    @staticmethod
    def _normalize_dict_error(data: dict, message: str) -> str:
        retry_after = KiotProxyClient._get_int(data, "retryAfter")
        retry_after = retry_after or KiotProxyClient._get_int(data, "retry_after")
        if retry_after > 0:
            return f"Gửi lại sau {retry_after}s"
        rd = KiotProxyClient._try_retry_delay(message)
        return rd if rd else KiotProxyClient._trim(message)

    @staticmethod
    def _try_retry_delay(value: str) -> Optional[str]:
        m = RETRY_DELAY_RE.search(value)
        return f"Gửi lại sau {m.group(1)}s" if m else None

    @staticmethod
    def _is_retry_msg(value: str) -> bool:
        return value.lower().startswith("gửi lại sau ") and value.endswith("s")

    # ─── helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _trim(value: str, max_len: int = 180) -> str:
        v = value.replace("\r", " ").replace("\n", " ").strip()
        return v[:max_len] if len(v) > max_len else v

    @staticmethod
    def _get_str(d, name: str) -> str:
        v = d.get(name)
        return "" if v is None else str(v)

    @staticmethod
    def _get_int(d, name: str) -> int:
        v = d.get(name)
        if v is None:
            return 0
        try:
            return int(v)
        except (ValueError, TypeError):
            return 0


# ─── regex helper used outside class ─────────────────────────────────────────

def _match_dur(text: str, pattern: str) -> int:
    m = re.search(pattern, text, re.IGNORECASE)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            pass
    return 0
