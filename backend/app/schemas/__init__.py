"""Pydantic DTOs — request/response schemas for all API routes."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

from app.config import settings


# ─── Profile ──────────────────────────────────────────────────────────────────

class ProfileResponse(BaseModel):
    uid: str
    masked_token: str
    token_status: str
    task_count: int
    last_error: Optional[str] = None
    created_at: Optional[datetime] = None

    @field_validator("masked_token", mode="before")
    @classmethod
    def _mask_token(cls, v: str) -> str:
        from app.crypto import mask
        return mask(v)

    model_config = {"from_attributes": True}


class ProfileImportResult(BaseModel):
    total: int
    added: int
    duplicate: int
    errors: List[str]


class SavedProfileStateResponse(BaseModel):
    token_status: str = ""
    task_count: int = 0
    last_error: str = ""


# ─── Task ─────────────────────────────────────────────────────────────────────

class DelaySettingsDTO(BaseModel):
    min_seconds: int = 0
    max_seconds: int = 0
    every_rounds: int = 1

    @property
    def enabled(self) -> bool:
        return self.every_rounds > 0 and (self.min_seconds > 0 or self.max_seconds > 0)


class TaskStartRequest(BaseModel):
    action: str = Field(..., pattern="^(edit|delete|new_comment)$")
    raw_uid_text: str = ""
    raw_link_text: str = ""
    raw_post_text: str = ""
    max_threads: int = Field(default=5, ge=1, le=200)
    new_text_input: str = ""
    image_input: str = ""
    delay: DelaySettingsDTO = DelaySettingsDTO()


class TaskRunResponse(BaseModel):
    id: str
    status: str
    action: str
    max_threads: int
    created_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    total: int = 0
    processed: int = 0
    success: int = 0
    failed: int = 0
    waiting_proxy: int = 0

    model_config = {"from_attributes": True}


class TaskLogEntryDTO(BaseModel):
    id: int
    run_id: str
    log_index: int
    uid: Optional[str] = None
    comment_link: str
    action: str
    proxy: str = ""
    status: str
    error: Optional[str] = None
    output_link: Optional[str] = None
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class TaskRunSummary(BaseModel):
    id: str
    status: str
    action: str
    created_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    total: int = 0
    processed: int = 0
    success: int = 0
    failed: int = 0


# ─── Proxy Key ────────────────────────────────────────────────────────────────

class ProxyEndpointDTO(BaseModel):
    host: str = ""
    port: int = 0
    username: Optional[str] = None
    password: Optional[str] = None  # NEVER returned in responses
    display: str = ""
    expires_at: Optional[datetime] = None


class ProxyKeyResponse(BaseModel):
    id: int
    masked_api_key: str
    current_proxy: Optional[str] = None
    remaining_uses: int = 0
    reserved_uses: int = 0
    status: str
    ip_expires_at: Optional[datetime] = None
    last_error: Optional[str] = None
    endpoint: Optional[ProxyEndpointDTO] = None

    model_config = {"from_attributes": True}


class ProxyKeyCreate(BaseModel):
    api_key: str


# ─── Settings ─────────────────────────────────────────────────────────────────

class ProxyUrlsDTO(BaseModel):
    get_new: str = "https://api.kiotproxy.com/api/v1/proxies/new?key={apiKey}"
    get_current: str = "https://api.kiotproxy.com/api/v1/proxies/current?key={apiKey}"


class AppSettingsResponse(BaseModel):
    interaction_threads: int = 5
    posts_per_uid: int = 1
    delay_min_seconds: int = 0
    delay_max_seconds: int = 0
    delay_every_rounds: int = 1
    uses_per_proxy: int = 4
    proxy_check_interval: int = 5
    get_new_url_template: str = ""
    get_current_url_template: str = ""
    kiot_auth_token_masked: str = ""


class AppSettingsUpdate(BaseModel):
    interaction_threads: int = Field(default=5, ge=1, le=200)
    posts_per_uid: int = Field(default=1, ge=1)
    delay_min_seconds: int = 0
    delay_max_seconds: int = 0
    delay_every_rounds: int = Field(default=1, ge=1)
    uses_per_proxy: int = Field(default=4, ge=1)
    proxy_check_interval: int = Field(default=5, ge=1, le=3600)
    get_new_url_template: str = ""
    get_current_url_template: str = ""  # corrected typo from codebase
    kiot_auth_token: Optional[str] = ""


# ─── Graph ────────────────────────────────────────────────────────────────────

class ResolveAuthorRequest(BaseModel):
    comment_link: str
    token: str


class ResolveAuthorResponse(BaseModel):
    uid: Optional[str] = None
    message: str = ""


class GraphEditRequest(BaseModel):
    comment_id: str
    access_token: str
    new_text: str
    image_path: Optional[str] = None
    proxy_host: Optional[str] = None
    proxy_port: Optional[int] = None
    proxy_username: Optional[str] = None
    proxy_password: Optional[str] = None


class GraphDeleteRequest(BaseModel):
    comment_id: str
    access_token: str
    proxy_host: Optional[str] = None
    proxy_port: Optional[int] = None
    proxy_username: Optional[str] = None
    proxy_password: Optional[str] = None


class GraphCreateRequest(BaseModel):
    post_id: str
    access_token: str
    text: str
    image_path: Optional[str] = None
    proxy_host: Optional[str] = None
    proxy_port: Optional[int] = None
    proxy_username: Optional[str] = None
    proxy_password: Optional[str] = None


class GraphActionResponse(BaseModel):
    success: bool
    message: str
    output_link: Optional[str] = None


# ─── SSE Event Payloads ────────────────────────────────────────────────────────

class LogEventData(BaseModel):
    run_id: str
    log_index: int
    uid: Optional[str] = None
    comment_link: str = ""
    action: str = ""
    proxy: str = ""
    status: str = ""
    error: Optional[str] = None
    output_link: Optional[str] = None
    created_at: Optional[datetime] = None


class StatsEventData(BaseModel):
    total: int = 0
    processed: int = 0
    success: int = 0
    failed: int = 0
    waiting_proxy: int = 0


class ProxyEventData(BaseModel):
    key_id: int
    masked_key: str = ""
    status: str = ""
    remaining_uses: int = 0
    reserved_uses: int = 0
    last_error: Optional[str] = None
    endpoint: Optional[ProxyEndpointDTO] = None


class ProfileEventData(BaseModel):
    uid: str
    token_status: str = ""
    last_error: str = ""
    task_count: int = 0


# ─── Health ───────────────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    status: str = "ok"
    postgres: str = "unknown"
    redis: str = "unknown"
    app: str = "running"


class ClipJobCreate(BaseModel):
    source_link: str | None = None
    top_n: int = 10
    clip_min_sec: int = 120
    clip_max_sec: int = 300
    scoring_backend: str = settings.SCORING_BACKEND


class ClipOut(BaseModel):
    id: str
    rank: int
    score: int | None = None
    hook_text: str | None = None
    start_sec: float
    end_sec: float
    status: str
    output_ref: str | None = None
    # The player needs the word timings and style out of clipspec v2; without it
    # the gallery can only show a bare video element.
    clipspec: dict | None = None


class ClipJobOut(BaseModel):
    id: str
    source_type: str
    status: str
    error: str | None = None
    # Backward-compatible field for jobs cleaned by the previous file-only
    # retention policy. New expired jobs are removed from the database.
    purged_at: datetime | None = None
    clips: list[ClipOut] = []


class ClipJobSummary(BaseModel):
    """One row of the job list. Deliberately without clipspec — the list would
    otherwise carry every word timing of every clip of every job."""

    id: str
    source_type: str
    source_name: str
    status: str
    error: str | None = None
    clip_count: int = 0
    created_at: datetime | None = None
    finished_at: datetime | None = None
    purged_at: datetime | None = None


class ClipHeartbeat(BaseModel):
    """"These jobs are still on someone's screen." Anything not heartbeaten for
    CLIP_SESSION_GRACE_SECONDS is deleted from storage and the database."""

    job_ids: list[uuid.UUID] = []


class GenJobIn(BaseModel):
    """Gen video request. No file, so this one is JSON rather than a form."""

    prompt: str = Field(min_length=10, max_length=2000)
    negative_prompt: str | None = Field(default=None, max_length=1000)
    duration_sec: int = Field(default=30, ge=5, le=120)
    voice: str = "vi-female"
    scoring_backend: str | None = None
