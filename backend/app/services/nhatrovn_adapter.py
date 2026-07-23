from __future__ import annotations

from dataclasses import dataclass, field

from bs4 import BeautifulSoup


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
