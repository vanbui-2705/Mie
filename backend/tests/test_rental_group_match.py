from types import SimpleNamespace
from app.services.rental_group_match import normalize_vn, match_group_ids

def test_normalize_strips_accents():
    assert normalize_vn("Gò Vấp") == "go vap"

def test_match_by_district_contains():
    groups = [
        SimpleNamespace(group_id="1", group_name="Thuê trọ Gò Vấp giá rẻ"),
        SimpleNamespace(group_id="2", group_name="Nhà trọ Bình Thạnh"),
        SimpleNamespace(group_id="3", group_name="Phòng trọ GÒ VẤP - HCM"),
    ]
    ids = match_group_ids("Gò Vấp", groups)
    assert set(ids) == {"1", "3"}

def test_no_match_returns_empty():
    groups = [SimpleNamespace(group_id="2", group_name="Nhà trọ Bình Thạnh")]
    assert match_group_ids("Gò Vấp", groups) == []
