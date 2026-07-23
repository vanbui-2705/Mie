from pathlib import Path

from app.services.nhatrovn_adapter import NhatrovnAdapter, Room

FIXTURE = Path(__file__).parent / "fixtures" / "nhatrovn_room_sale.html"


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
