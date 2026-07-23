from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from urllib.parse import unquote

import httpx
from bs4 import BeautifulSoup

BASE = "https://quanly.nhatrovn.vn"


class NhatrovnError(Exception):
    pass


@dataclass
class Room:
    external_room_id: str
    title: str
    price: str = ""
    area_text: str = ""
    address: str = ""
    district: str | None = None
    ward: str | None = None
    status: str = ""  # "Trống" (vacant) / "Đã thuê" (rented); only vacant rooms get posted
    description: str = ""
    images: list[str] = field(default_factory=list)


def _label_value(card, label: str) -> str:
    """Find <span>label:</span> then return the text of the next <span> sibling."""
    target = label.strip().rstrip(":")
    for span in card.select("span"):
        if span.get_text(strip=True).rstrip(":") == target:
            val = span.find_next_sibling("span")
            return val.get_text(strip=True) if val else ""
    return ""


class NhatrovnAdapter:
    def __init__(self, transport: httpx.BaseTransport | None = None) -> None:
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=self._transport,
            base_url=BASE,
            timeout=30,
            follow_redirects=True,
        )

    @staticmethod
    def parse_rooms(html: str) -> list[Room]:
        soup = BeautifulSoup(html, "html.parser")
        rooms: list[Room] = []

        for card in soup.select("div.content-room"):
            house_spans = card.select("p.text-color-room-caretaker span.span-house")
            room_code = house_spans[0].get_text(strip=True) if house_spans else ""

            address_parts: list[str] = []
            past_separator = False
            for span in house_spans[1:]:
                text = span.get_text(strip=True)
                if not past_separator:
                    if text == "-":
                        past_separator = True
                    continue
                if "d-none" in (span.get("class") or []):
                    continue
                if text:
                    address_parts.append(text)
            address = " ".join(address_parts)

            external_room_id = card.get("data-key") or room_code or ""

            images = [
                src
                for img in card.select("img")
                if (src := img.get("src")) and not src.startswith("data:")
            ]

            rooms.append(
                Room(
                    external_room_id=external_room_id,
                    title=room_code,
                    price=_label_value(card, "Giá cho thuê"),
                    area_text=_label_value(card, "Diện tích"),
                    address=address,
                    status=_label_value(card, "Trạng thái"),
                    description=card.get_text(" ", strip=True)[:1000],
                    images=images,
                )
            )

        return rooms

    async def login(self, username: str, password: str) -> httpx.AsyncClient:
        client = self._client()
        try:
            resp = await client.get("/login")
            soup = BeautifulSoup(resp.text, "html.parser")

            form = None
            for candidate in soup.select("form"):
                if candidate.find("input", attrs={"type": "password"}):
                    form = candidate
                    break
            if form is None:
                form = soup

            for inp in form.select("input"):
                name = (inp.get("name") or "").lower()
                input_id = (inp.get("id") or "").lower()
                if "captcha" in name or "captcha" in input_id or "otp" in name or "otp" in input_id:
                    raise NhatrovnError(
                        "Cổng nhatrovn yêu cầu OTP/captcha — không thể đăng nhập tự động."
                    )
            if "captcha" in resp.text.lower():
                raise NhatrovnError(
                    "Cổng nhatrovn yêu cầu OTP/captcha — không thể đăng nhập tự động."
                )

            token_input = form.find("input", attrs={"name": "_token"})
            token = token_input.get("value", "") if token_input else ""

            username_field = None
            for inp in form.select("input"):
                name = inp.get("name")
                if not name or name == "_token":
                    continue
                input_type = (inp.get("type") or "text").lower()
                if input_type in ("text", "email"):
                    username_field = name
                    break

            password_input = form.find("input", attrs={"type": "password"})
            password_field = password_input.get("name") if password_input else None

            if not username_field or not password_field:
                raise NhatrovnError(
                    "Không thể phân tích form đăng nhập nhatrovn (thiếu trường username/password)."
                )

            payload = {
                "_token": token,
                username_field: username,
                password_field: password,
            }
            resp = await client.post("/login", data=payload)

            final_path = resp.url.path
            has_password_field = bool(
                BeautifulSoup(resp.text, "html.parser").find(
                    "input", attrs={"type": "password"}
                )
            )
            if has_password_field or final_path == "/login":
                raise NhatrovnError(
                    "Đăng nhập nhatrovn thất bại — kiểm tra tài khoản/mật khẩu."
                )

            return client
        except NhatrovnError:
            await client.aclose()
            raise
        except Exception:
            await client.aclose()
            raise

    @staticmethod
    def _b64_codes(codes: list[str] | None) -> str:
        return base64.b64encode(json.dumps(codes or []).encode()).decode()

    async def fetch_rooms(
        self,
        client: httpx.AsyncClient,
        *,
        province_code: str,
        district_codes: list[str] | None = None,
        ward_codes: list[str] | None = None,
        max_pages: int = 10,
    ) -> list[Room]:
        headers = {"X-Requested-With": "XMLHttpRequest"}
        xsrf_cookie = client.cookies.get("XSRF-TOKEN")
        if xsrf_cookie:
            headers["X-XSRF-TOKEN"] = unquote(xsrf_cookie)

        rooms: list[Room] = []
        seen: set[str] = set()
        last_key = ""

        for _ in range(max_pages):
            data = {
                "provincial-code": province_code,
                "district-code": self._b64_codes(district_codes),
                "ward-code": self._b64_codes(ward_codes),
                "has-image": "ALL",
                "sort-by": "1",
                "_lastKey": last_key,
            }
            resp = await client.post(
                "/main/room-sale/search", data=data, headers=headers
            )
            if resp.status_code >= 400:
                raise NhatrovnError(f"Tìm phòng lỗi HTTP {resp.status_code}")

            batch = self.parse_rooms(resp.text)
            new_rooms = [r for r in batch if r.external_room_id not in seen]
            if not new_rooms:
                break

            rooms.extend(new_rooms)
            seen.update(r.external_room_id for r in new_rooms)
            last_key = batch[-1].external_room_id

        return rooms
