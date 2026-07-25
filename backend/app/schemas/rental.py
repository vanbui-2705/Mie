from __future__ import annotations

import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator


class RentalCredentials(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=320)
    password: str = Field(min_length=1, max_length=1024)

    @field_validator("username", "password")
    @classmethod
    def strip_required(cls, value: str) -> str:
        parsed = value.strip()
        if not parsed:
            raise ValueError("must not be blank")
        return parsed


class RentalConfigCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    credentials: RentalCredentials
    province_code: str = Field(min_length=1, max_length=32)
    province_name: str = Field(min_length=1, max_length=128)
    district_code: str = Field(min_length=1, max_length=32)
    district_name: str = Field(min_length=1, max_length=128)
    ward_code: str | None = Field(default=None, max_length=32)
    ward_name: str | None = Field(default=None, max_length=128)
    caption_template: str = Field(default="", max_length=10000)
    contact_phone: str = Field(default="", max_length=32)
    post_spacing_seconds: int = Field(default=480, ge=30, le=86400)
    post_delay_seconds: int = Field(default=0, ge=0, le=86400)
    poll_interval_seconds: int = Field(default=300, ge=60, le=86400)
    auto_post: StrictBool = True
    google_sheet_connection_id: uuid.UUID | None = None
    timezone: str = Field(default="Asia/Ho_Chi_Minh", max_length=64)

    @field_validator(
        "name",
        "province_code",
        "province_name",
        "district_code",
        "district_name",
        "ward_code",
        "ward_name",
        "caption_template",
        "contact_phone",
        mode="before",
    )
    @classmethod
    def strip_strings(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        parsed = value.strip()
        try:
            ZoneInfo(parsed)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("unsupported timezone") from exc
        return parsed


class RentalConfigUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=255)
    credentials: RentalCredentials | None = None
    province_code: str | None = Field(default=None, min_length=1, max_length=32)
    province_name: str | None = Field(default=None, min_length=1, max_length=128)
    district_code: str | None = Field(default=None, min_length=1, max_length=32)
    district_name: str | None = Field(default=None, min_length=1, max_length=128)
    ward_code: str | None = Field(default=None, max_length=32)
    ward_name: str | None = Field(default=None, max_length=128)
    caption_template: str | None = Field(default=None, max_length=10000)
    contact_phone: str | None = Field(default=None, max_length=32)
    post_spacing_seconds: int | None = Field(default=None, ge=30, le=86400)
    post_delay_seconds: int | None = Field(default=None, ge=0, le=86400)
    poll_interval_seconds: int | None = Field(default=None, ge=60, le=86400)
    auto_post: StrictBool | None = None
    google_sheet_connection_id: uuid.UUID | None = None
    timezone: str | None = Field(default=None, max_length=64)

    @field_validator(
        "name",
        "province_code",
        "province_name",
        "district_code",
        "district_name",
        "ward_code",
        "ward_name",
        "caption_template",
        "contact_phone",
        mode="before",
    )
    @classmethod
    def strip_strings(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = value.strip()
        try:
            ZoneInfo(parsed)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("unsupported timezone") from exc
        return parsed


class AssignRentalGroups(BaseModel):
    model_config = ConfigDict(extra="forbid")

    group_ids: list[str] = Field(min_length=1, max_length=200)

    @field_validator("group_ids")
    @classmethod
    def valid_group_ids(cls, values: list[str]) -> list[str]:
        normalized = [str(value).strip() for value in values if str(value).strip()]
        if not normalized:
            raise ValueError("at least one group_id is required")
        return list(dict.fromkeys(normalized))
