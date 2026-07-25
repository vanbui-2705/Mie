from __future__ import annotations

import re
import uuid
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator


TARGET_RE = re.compile(
    r"^(page|group|personal):"
    r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
    r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12})$"
)
SLOT_RE = re.compile(r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")


class SheetCampaignCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    connection_id: uuid.UUID
    name: str = Field(min_length=1, max_length=255)
    default_targets: list[str] = Field(min_length=1, max_length=200)
    default_schedule_mode: Literal["NOW", "EXACT", "AUTO"] = "NOW"
    schedule_slots: list[str] = Field(default_factory=list, max_length=48)
    active_weekdays: list[int] = Field(
        default_factory=lambda: [0, 1, 2, 3, 4, 5, 6],
        min_length=1,
        max_length=7,
    )
    timezone: str = Field(default="Asia/Ho_Chi_Minh", max_length=64)
    max_posts_per_day: int = Field(default=20, ge=1, le=200)
    min_post_gap_seconds: int = Field(default=300, ge=30, le=86400)
    late_policy: Literal["publish_now", "miss"] = "publish_now"
    max_retries: int = Field(default=3, ge=1, le=10)
    enabled: StrictBool = True

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        return value.strip()

    @field_validator("default_targets")
    @classmethod
    def valid_targets(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values]
        invalid = [value for value in normalized if not TARGET_RE.fullmatch(value)]
        if invalid:
            raise ValueError(f"invalid targets: {invalid}")
        return list(dict.fromkeys(normalized))

    @field_validator("schedule_slots")
    @classmethod
    def valid_slots(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values]
        invalid = [value for value in normalized if not SLOT_RE.fullmatch(value)]
        if invalid:
            raise ValueError(f"invalid schedule slots: {invalid}")
        return sorted(set(normalized))

    @field_validator("active_weekdays")
    @classmethod
    def valid_weekdays(cls, values: list[int]) -> list[int]:
        if any(value < 0 or value > 6 for value in values):
            raise ValueError("active weekdays must be between 0 and 6")
        return sorted(set(values))

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        parsed = value.strip()
        try:
            ZoneInfo(parsed)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("unsupported timezone") from exc
        return parsed


class SheetCampaignUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=255)
    default_targets: list[str] | None = Field(default=None, min_length=1, max_length=200)
    default_schedule_mode: Literal["NOW", "EXACT", "AUTO"] | None = None
    schedule_slots: list[str] | None = Field(default=None, max_length=48)
    active_weekdays: list[int] | None = Field(default=None, min_length=1, max_length=7)
    timezone: str | None = Field(default=None, max_length=64)
    max_posts_per_day: int | None = Field(default=None, ge=1, le=200)
    min_post_gap_seconds: int | None = Field(default=None, ge=30, le=86400)
    late_policy: Literal["publish_now", "miss"] | None = None
    max_retries: int | None = Field(default=None, ge=1, le=10)
    enabled: StrictBool | None = None

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None

    @field_validator("default_targets")
    @classmethod
    def valid_targets(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
        return SheetCampaignCreate.valid_targets(values)

    @field_validator("schedule_slots")
    @classmethod
    def valid_slots(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
        return SheetCampaignCreate.valid_slots(values)

    @field_validator("active_weekdays")
    @classmethod
    def valid_weekdays(cls, values: list[int] | None) -> list[int] | None:
        if values is None:
            return None
        return SheetCampaignCreate.valid_weekdays(values)

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return SheetCampaignCreate.valid_timezone(value)
