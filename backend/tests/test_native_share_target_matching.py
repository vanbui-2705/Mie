from __future__ import annotations

import pytest

from app.services import personal_browser


class FakeElement:
    def __init__(self, text: str) -> None:
        self.text = text

    def is_visible(self) -> bool:
        return True

    def inner_text(self, timeout: int = 1000) -> str:
        return self.text


class FakeLocator:
    def __init__(self, items: list[FakeElement]) -> None:
        self.items = items

    def count(self) -> int:
        return len(self.items)

    def nth(self, index: int) -> FakeElement:
        return self.items[index]

    @property
    def first(self) -> FakeElement:
        return self.items[0]


class FakePage:
    def __init__(self, selector: str, item: FakeElement) -> None:
        self.selector = selector
        self.item = item

    def locator(self, selector: str) -> FakeLocator:
        if selector == self.selector:
            return FakeLocator([self.item])
        return FakeLocator([])


@pytest.mark.parametrize("selector", ("div[role='option']", "div[role='menuitem']", "li"))
def test_find_native_share_target_matches_non_link_text_by_url_slug(monkeypatch, selector: str) -> None:
    option = FakeElement("Mèo Mỗi Ngày • 5K thành viên")
    page = FakePage(selector, option)
    monotonic_values = iter((0.0, 0.0, 2.0))

    monkeypatch.setattr(personal_browser.time, "monotonic", lambda: next(monotonic_values))
    monkeypatch.setattr(personal_browser.time, "sleep", lambda _seconds: None)

    found = personal_browser._find_native_share_target(
        page,
        target_name="",
        target_url="https://www.facebook.com/groups/mèo-mỗi-ngày",
        timeout_seconds=1,
    )

    assert found is option
