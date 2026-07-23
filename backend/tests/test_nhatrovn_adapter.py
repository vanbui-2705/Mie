import base64
import json
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest

from app.services.nhatrovn_adapter import NhatrovnAdapter, NhatrovnError, Room

FIXTURE = Path(__file__).parent / "fixtures" / "nhatrovn_room_sale.html"

LOGIN_FORM_HTML = """
<html><body>
<form method="POST" action="/login">
  <input type="hidden" name="_token" value="tok123">
  <input type="text" name="email">
  <input type="password" name="password">
</form>
</body></html>
"""

OTP_LOGIN_FORM_HTML = """
<html><body>
<form method="POST" action="/login">
  <input type="hidden" name="_token" value="tok123">
  <input type="text" name="email">
  <input type="password" name="password">
  <input type="text" name="otp_code">
</form>
</body></html>
"""

DASHBOARD_HTML = "<html><body><div id=\"dashboard\">Welcome</div></body></html>"


def test_parse_rooms_extracts_all_cards():
    rooms = NhatrovnAdapter.parse_rooms(FIXTURE.read_text(encoding="utf-8"))
    assert len(rooms) == 2

    r0 = rooms[0]
    assert isinstance(r0, Room)
    assert r0.external_room_id == "a1a1a1a1a1a1a1a1a1a1a1a1"
    assert r0.title == "B311"
    assert r0.price == "3,200,000"
    assert r0.area_text == "20m2"
    assert r0.status == "Trống"
    assert "VÕ VĂN HÁT" in r0.address
    assert "0900000000" not in r0.address

    r1 = rooms[1]
    assert r1.status == "Đã thuê"
    assert r1.price == "2,800,000"
    assert "0900000000" not in r1.address

    assert len(r0.images) >= 1
    assert not any(img.startswith("data:") for r in rooms for img in r.images)


def test_parse_rooms_falls_back_to_room_code_when_data_key_absent():
    html = """
    <div class="content-room">
      <p class="text-color-room-caretaker text-center fs-13 p-t-5 p-b-5">
        <span class="span-house">C204</span>
        <span class="span-house">-</span>
        <span class="span-house">1 Test St</span>
      </p>
    </div>
    """
    rooms = NhatrovnAdapter.parse_rooms(html)
    assert len(rooms) == 1
    assert rooms[0].external_room_id == "C204"
    assert rooms[0].external_room_id != ""


def _search_batches():
    """Returns (call_count_list, handler) where handler serves the fixture on the
    first /main/room-sale/search call and an empty batch afterwards."""
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/login" and request.method == "GET":
            return httpx.Response(
                200,
                text=LOGIN_FORM_HTML,
                headers={"set-cookie": "XSRF-TOKEN=csrf-abc%3D%3D; Path=/"},
            )
        if path == "/login" and request.method == "POST":
            # success -> Laravel redirects away from /login
            return httpx.Response(302, headers={"location": "/home"})
        if path == "/home" and request.method == "GET":
            return httpx.Response(200, text=DASHBOARD_HTML)
        if path == "/main/room-sale/search" and request.method == "POST":
            calls.append(request)
            if len(calls) == 1:
                return httpx.Response(200, text=FIXTURE.read_text(encoding="utf-8"))
            return httpx.Response(200, text="<div class='row'></div>")
        raise AssertionError(f"unexpected request {request.method} {path}")

    return calls, handler


@pytest.mark.asyncio
async def test_login_then_fetch_rooms_paginates():
    calls, handler = _search_batches()
    transport = httpx.MockTransport(handler)
    adapter = NhatrovnAdapter(transport=transport)

    client = await adapter.login("user", "pass")
    rooms = await adapter.fetch_rooms(
        client, province_code="79", district_codes=["785"], max_pages=3
    )

    assert len(rooms) == 2
    assert {r.external_room_id for r in rooms} == {
        "a1a1a1a1a1a1a1a1a1a1a1a1",
        "c3c3c3c3c3c3c3c3c3c3c3c3",
    }
    assert len(calls) == 2  # fixture batch + empty batch, then stop

    await client.aclose()


@pytest.mark.asyncio
async def test_login_failure_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/login" and request.method == "GET":
            return httpx.Response(
                200,
                text=LOGIN_FORM_HTML,
                headers={"set-cookie": "XSRF-TOKEN=csrf-abc%3D%3D; Path=/"},
            )
        if request.url.path == "/login" and request.method == "POST":
            # login failed -> the form is re-rendered
            return httpx.Response(200, text=LOGIN_FORM_HTML)
        raise AssertionError("unexpected request")

    transport = httpx.MockTransport(handler)
    adapter = NhatrovnAdapter(transport=transport)

    with pytest.raises(NhatrovnError):
        await adapter.login("user", "wrongpass")


@pytest.mark.asyncio
async def test_login_detects_otp():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/login" and request.method == "GET":
            return httpx.Response(200, text=OTP_LOGIN_FORM_HTML)
        raise AssertionError("unexpected request")

    transport = httpx.MockTransport(handler)
    adapter = NhatrovnAdapter(transport=transport)

    with pytest.raises(NhatrovnError):
        await adapter.login("user", "pass")


@pytest.mark.asyncio
async def test_fetch_rooms_sends_base64_district():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/login" and request.method == "GET":
            return httpx.Response(
                200,
                text=LOGIN_FORM_HTML,
                headers={"set-cookie": "XSRF-TOKEN=csrf-abc%3D%3D; Path=/"},
            )
        if path == "/login" and request.method == "POST":
            # success -> Laravel redirects away from /login
            return httpx.Response(302, headers={"location": "/home"})
        if path == "/home" and request.method == "GET":
            return httpx.Response(200, text=DASHBOARD_HTML)
        if path == "/main/room-sale/search" and request.method == "POST":
            if "body" not in captured:
                captured["body"] = request.content.decode()
                captured["headers"] = dict(request.headers)
            return httpx.Response(200, text="<div class='row'></div>")
        raise AssertionError(f"unexpected request {request.method} {path}")

    transport = httpx.MockTransport(handler)
    adapter = NhatrovnAdapter(transport=transport)

    client = await adapter.login("user", "pass")
    await adapter.fetch_rooms(
        client, province_code="79", district_codes=["785"], max_pages=3
    )

    body = parse_qs(captured["body"])
    district_b64 = body["district-code"][0]
    decoded = json.loads(base64.b64decode(district_b64).decode())
    assert decoded == ["785"]
    assert body["provincial-code"][0] == "79"
    assert "x-xsrf-token" in captured["headers"]

    await client.aclose()
