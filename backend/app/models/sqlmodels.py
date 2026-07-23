"""SQLAlchemy 2.0 ORM models — full schema with indexes."""
from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum as PyEnum
from typing import ClassVar, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import CITEXT, JSONB, UUID as PG_UUID
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    MappedAsDataclass,
    declared_attr,
    mapped_column,
    relationship,
)


class Base(DeclarativeBase):
    """Base declarative class — non-ORM annotations need ClassVar."""
    __allow_unmapped__ = True


# ─── Enums ────────────────────────────────────────────────────────────────────

class CommentAction(str, PyEnum):
    EDIT = "edit"
    DELETE = "delete"
    NEW_COMMENT = "new_comment"
    POST_PAGE = "post_page"
    POST_GROUP = "post_group"
    SHARE_PAGE = "share_page"


class TokenStatus(str, PyEnum):
    NOT_CHECKED = "Chua kiem tra"
    LIVE = "Live"
    DIE = "Die"
    CHECKPOINT = "Checkpoint"
    TOKEN_OUT = "Token out"
    DA_NAP = "Da nap"
    DA_REFRESH = "Da refresh token"


class ProxyStatus(str, PyEnum):
    STOPPED = "Stopped"
    STARTING = "Starting"
    READY = "Ready"
    GETTING_NEW = "GettingNew"
    WAITING = "Waiting"
    ERROR = "Error"


class TaskRunStatus(str, PyEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELED = "canceled"
    STOPPED = "stopped"  # legacy
    DONE = "done"  # legacy
    ERROR = "error"  # legacy


class TaskItemStatus(str, PyEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    PENDING_REVIEW = "pending_review"
    FAILED = "failed"
    CANCELED = "canceled"


class UserStatus(str, PyEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


class ShareMode(str, PyEnum):
    SHARE_LINK = "share_link"
    COPY_CONTENT = "copy_content"
    CUSTOM_CONTENT = "custom_content"


class BrowserSessionStatus(str, PyEnum):
    STARTING = "starting"
    READY = "ready"
    STOPPED = "stopped"
    EXPIRED = "expired"
    ERROR = "error"


# ─── Profiles ────────────────────────────────────────────────────────────────

class Profile(Base):
    __tablename__ = "profiles"

    uid: Mapped[str] = mapped_column(
        CITEXT, primary_key=True, nullable=False,
        comment="Facebook UID, case-insensitive PK",
    )
    token_enc: Mapped[str] = mapped_column(
        Text, nullable=False,
        comment="Fernet-encrypted Facebook access token",
    )
    token_status: Mapped[TokenStatus] = mapped_column(
        Enum(TokenStatus, name="token_status", native_enum=False),
        nullable=False,
        default=TokenStatus.NOT_CHECKED,
    )
    last_error: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, default=None,
    )
    task_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        server_default=func.now(), onupdate=func.now(),
    )

    __table_args__ = (
        Index("idx_profiles_uid_ci", func.lower(uid), unique=True),
    )

    @property
    def masked_token(self) -> str:
        from app.crypto import mask
        return mask(self.token_enc)


# ─── Multi-user Facebook account model ────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    username: Mapped[str] = mapped_column(CITEXT, nullable=False, unique=True)
    email: Mapped[Optional[str]] = mapped_column(CITEXT, nullable=True, unique=True)
    full_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    avatar_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    password_hash: Mapped[Optional[str]] = mapped_column(Text, nullable=True, default=None)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="user")
    status: Mapped[UserStatus] = mapped_column(
        Enum(UserStatus, name="user_status", native_enum=False),
        nullable=False,
        default=UserStatus.ACTIVE,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )


class Permission(Base):
    __tablename__ = "permissions"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    code: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    resource: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )


class RolePermission(Base):
    __tablename__ = "role_permissions"

    role_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True,
    )
    permission_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True,
    )


class UserRole(Base):
    __tablename__ = "user_roles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True,
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True,
    )
    assigned_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )

    __table_args__ = (Index("idx_user_roles_role", role_id),)


class OAuthAccount(Base):
    __tablename__ = "oauth_accounts"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid())
    user_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[Optional[str]] = mapped_column(CITEXT, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("provider", "provider_user_id", name="uq_oauth_provider_identity"),
        Index("idx_oauth_accounts_user", user_id),
    )


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid())
    user_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (Index("idx_password_reset_user", user_id),)


class FacebookAccount(Base):
    __tablename__ = "facebook_accounts"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
    )
    uid: Mapped[str] = mapped_column(CITEXT, nullable=False)
    name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, default=None)
    user_token_enc: Mapped[str] = mapped_column(Text, nullable=False)
    token_status: Mapped[TokenStatus] = mapped_column(
        Enum(TokenStatus, name="facebook_account_token_status", native_enum=False),
        nullable=False,
        default=TokenStatus.NOT_CHECKED,
    )
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True, default=None)
    last_checked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None,
    )
    token_expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None,
    )
    token_last_refreshed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None,
    )
    token_is_long_lived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    browser_status: Mapped[str] = mapped_column(String(32), nullable=False, default="not_configured")
    browser_last_checked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None,
    )
    browser_last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        server_default=func.now(), onupdate=func.now(),
    )

    __table_args__ = (
        UniqueConstraint("user_id", "uid", name="uq_facebook_accounts_user_uid"),
        Index("idx_facebook_accounts_user_uid", user_id, func.lower(uid)),
    )


class FacebookPage(Base):
    __tablename__ = "facebook_pages"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
    )
    facebook_account_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("facebook_accounts.id", ondelete="CASCADE"), nullable=False,
    )
    page_id: Mapped[str] = mapped_column(String(64), nullable=False)
    page_name: Mapped[str] = mapped_column(String(255), nullable=False)
    page_access_token_enc: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, default=None)
    permissions: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True, default=None)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        server_default=func.now(), onupdate=func.now(),
    )

    __table_args__ = (
        UniqueConstraint("user_id", "page_id", name="uq_facebook_pages_user_page"),
        Index("idx_facebook_pages_user", user_id),
    )


class FacebookGroup(Base):
    __tablename__ = "facebook_groups"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
    )
    facebook_account_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("facebook_accounts.id", ondelete="CASCADE"), nullable=False,
    )
    group_url: Mapped[str] = mapped_column(Text, nullable=False)
    group_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, default=None)
    group_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, default=None)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="not_checked")
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        server_default=func.now(), onupdate=func.now(),
    )

    __table_args__ = (
        UniqueConstraint("user_id", "facebook_account_id", "group_url", name="uq_facebook_groups_user_account_url"),
        Index("idx_facebook_groups_user", user_id),
    )


class ExternalPage(Base):
    __tablename__ = "external_pages"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
    )
    facebook_account_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("facebook_accounts.id", ondelete="CASCADE"), nullable=False,
    )
    page_url: Mapped[str] = mapped_column(Text, nullable=False)
    page_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, default=None)
    page_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, default=None)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="not_checked")
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        server_default=func.now(), onupdate=func.now(),
    )

    __table_args__ = (
        UniqueConstraint("user_id", "facebook_account_id", "page_url", name="uq_external_pages_user_account_url"),
        Index("idx_external_pages_user", user_id),
    )


class BrowserSession(Base):
    __tablename__ = "browser_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
    )
    facebook_account_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("facebook_accounts.id", ondelete="CASCADE"), nullable=False,
    )
    status: Mapped[BrowserSessionStatus] = mapped_column(
        Enum(BrowserSessionStatus, name="browser_session_status", native_enum=False),
        nullable=False,
        default=BrowserSessionStatus.STARTING,
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="kasm")
    container_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, default=None)
    session_key: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, default=None)
    remote_url: Mapped[str] = mapped_column(Text, nullable=False)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True, default=None)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None,
    )
    stopped_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None,
    )

    __table_args__ = (
        Index("idx_browser_sessions_user_status", user_id, status),
        Index("idx_browser_sessions_account_status", facebook_account_id, status),
        Index("idx_browser_sessions_expires_at", expires_at),
    )


class SourcePost(Base):
    __tablename__ = "source_posts"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
    )
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_post_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_post_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, default=None)
    message_snapshot: Mapped[Optional[str]] = mapped_column(Text, nullable=True, default=None)
    media_snapshot: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )


class ShareCampaign(Base):
    __tablename__ = "share_campaigns"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
    )
    source_post_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("source_posts.id", ondelete="SET NULL"), nullable=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    mode: Mapped[ShareMode] = mapped_column(
        Enum(ShareMode, name="share_mode", native_enum=False),
        nullable=False,
        default=ShareMode.SHARE_LINK,
    )
    custom_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True, default=None)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )


class ScheduledPost(Base):
    __tablename__ = "scheduled_posts"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, comment="Human-readable label")
    action: Mapped[CommentAction] = mapped_column(
        Enum(CommentAction, name="comment_action", native_enum=False),
        nullable=False,
        default=CommentAction.POST_PAGE,
    )
    targets_json: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, default=None, comment="JSON-encoded target IDs list"
    )
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True, default=None)
    link: Mapped[Optional[str]] = mapped_column(Text, nullable=True, default=None)
    media_paths_json: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, default=None, comment="JSON array of saved media file paths"
    )
    post_items_json: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, default=None, comment="JSON array of scheduled post content/media packages"
    )
    next_item_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_threads: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    start_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None, comment="First fire time"
    )
    interval_seconds: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, default=None, comment="Seconds between fires; NULL means one-shot"
    )
    next_fire_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None, index=True,
    )
    last_fired_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None,
    )
    stop_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="paused")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (Index("idx_scheduled_posts_user_next_fire", user_id, next_fire_at),)


class GoogleSheetConnection(Base):
    __tablename__ = "google_sheet_connections"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    spreadsheet_id: Mapped[str] = mapped_column(String(255), nullable=False)
    sheet_name: Mapped[str] = mapped_column(String(255), nullable=False, default="Posts")
    credentials_enc: Mapped[str] = mapped_column(
        Text, nullable=False, comment="Fernet-encrypted Google service-account JSON",
    )
    service_account_email: Mapped[str] = mapped_column(String(320), nullable=False)
    poll_interval_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Asia/Ho_Chi_Minh")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="connected")
    last_synced_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None,
    )
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        server_default=func.now(), onupdate=func.now(),
    )

    __table_args__ = (
        UniqueConstraint(
            "user_id", "spreadsheet_id", "sheet_name",
            name="uq_google_sheet_connections_user_sheet",
        ),
        Index("idx_google_sheet_connections_user", user_id),
    )


class RentalConfig(Base):
    __tablename__ = "rental_configs"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False, default="nhatrovn")
    source_credentials_enc: Mapped[str] = mapped_column(Text, nullable=False)
    province_code: Mapped[str] = mapped_column(String(32), nullable=False)
    province_name: Mapped[str] = mapped_column(String(128), nullable=False)
    district_code: Mapped[str] = mapped_column(String(32), nullable=False)
    district_name: Mapped[str] = mapped_column(String(128), nullable=False)
    ward_code: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, default=None)
    ward_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, default=None)
    extra_filters_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True, default=None)
    auto_post: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    post_spacing_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=480)
    post_delay_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    caption_template: Mapped[str] = mapped_column(Text, nullable=False, default="")
    contact_phone: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    group_match_level: Mapped[str] = mapped_column(String(16), nullable=False, default="district")
    poll_interval_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=300)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Asia/Ho_Chi_Minh")
    google_sheet_connection_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("google_sheet_connections.id", ondelete="SET NULL"),
        nullable=True, default=None,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    last_synced_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None,
    )
    last_post_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None,
    )
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        server_default=func.now(), onupdate=func.now(),
    )

    __table_args__ = (
        Index("idx_rental_configs_user", user_id),
    )


class RentalRoom(Base):
    __tablename__ = "rental_rooms"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    config_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("rental_configs.id", ondelete="CASCADE"), nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
    )
    external_room_id: Mapped[str] = mapped_column(String(128), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False, default="")
    price: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    area_text: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    address: Mapped[str] = mapped_column(Text, nullable=False, default="")
    district: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, default=None)
    ward: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, default=None)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    images_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    caption: Mapped[str] = mapped_column(Text, nullable=False, default="")
    matched_group_ids_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True, default=None)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="new")
    post_urls_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True, default=None)
    posted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None,
    )
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        server_default=func.now(), onupdate=func.now(),
    )

    __table_args__ = (
        UniqueConstraint("config_id", "external_room_id", name="uq_rental_rooms_config_room"),
        Index("idx_rental_rooms_user", user_id),
    )


class ShareTarget(Base):
    __tablename__ = "share_targets"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("share_campaigns.id", ondelete="CASCADE"), nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
    )
    target_type: Mapped[str] = mapped_column(String(32), nullable=False, default="page")
    facebook_page_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("facebook_pages.id", ondelete="CASCADE"), nullable=True, default=None,
    )
    facebook_group_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("facebook_groups.id", ondelete="CASCADE"), nullable=True, default=None,
    )
    external_page_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("external_pages.id", ondelete="CASCADE"), nullable=True, default=None,
    )
    facebook_account_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("facebook_accounts.id", ondelete="CASCADE"), nullable=True, default=None,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    output_post_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, default=None)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True, default=None)


# ─── Task Runs ────────────────────────────────────────────────────────────────

class TaskRun(Base):
    __tablename__ = "task_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
    )
    status: Mapped[TaskRunStatus] = mapped_column(
        Enum(TaskRunStatus, name="task_run_status", native_enum=False),
        nullable=False,
        default=TaskRunStatus.RUNNING,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None,
    )
    action: Mapped[CommentAction] = mapped_column(
        Enum(CommentAction, name="comment_action", native_enum=False),
        nullable=False,
    )
    max_threads: Mapped[int] = mapped_column(
        Integer, nullable=False,
    )
    delay_min: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
    )
    delay_max: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
    )
    delay_every_rounds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1,
    )
    text_input_enc: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, default=None,
    )
    image_path: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, default=None,
    )

    logs: Mapped[list["TaskLog"]] = relationship(
        "TaskLog", back_populates="run",
        cascade="all, delete-orphan", order_by="TaskLog.created_at",
    )
    items: Mapped[list["TaskItem"]] = relationship(
        "TaskItem", back_populates="run",
        cascade="all, delete-orphan", order_by="TaskItem.item_index",
    )

    __table_args__ = (
        Index("idx_task_runs_created_at", created_at.desc()),
        Index("idx_task_runs_user_created_at", user_id, created_at.desc()),
    )


# ─── Task Logs ────────────────────────────────────────────────────────────────

class TaskItem(Base):
    __tablename__ = "task_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("task_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
    )
    item_index: Mapped[int] = mapped_column(Integer, nullable=False)
    uid: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, default=None)
    target_link: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[TaskItemStatus] = mapped_column(
        Enum(TaskItemStatus, name="task_item_status", native_enum=False),
        nullable=False,
        default=TaskItemStatus.PENDING,
    )
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True, default=None)
    output_link: Mapped[Optional[str]] = mapped_column(Text, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        server_default=func.now(), onupdate=func.now(),
    )

    run: Mapped[TaskRun] = relationship("TaskRun", back_populates="items")

    __table_args__ = (
        UniqueConstraint("run_id", "item_index", name="uq_task_items_run_index"),
        Index("idx_task_items_run_status", run_id, status),
    )


class TaskLog(Base):
    __tablename__ = "task_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("task_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    log_index: Mapped[int] = mapped_column(Integer, nullable=False)
    uid: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, default=None,
    )
    comment_link: Mapped[str] = mapped_column(
        Text, nullable=False,
    )
    action: Mapped[str] = mapped_column(
        String(32), nullable=False,
    )
    proxy: Mapped[str] = mapped_column(
        String(128), nullable=False, default="",
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False,
    )
    error: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, default=None,
    )
    output_link: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, default=None,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )

    run: Mapped[TaskRun] = relationship("TaskRun", back_populates="logs")

    __table_args__ = (
        Index("idx_task_logs_run_id", run_id, log_index),
    )


# ─── Proxy Keys ───────────────────────────────────────────────────────────────

class ProxyKey(Base):
    __tablename__ = "proxy_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
    )
    api_key_enc: Mapped[str] = mapped_column(
        Text, nullable=False,
        comment="Fernet-encrypted KiotProxy API key",
    )
    masked_key: Mapped[str] = mapped_column(
        String(32), nullable=False,
        comment="Display-safe abbreviation of api_key",
    )
    current_proxy: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True, default=None,
    )
    remaining_uses: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
    )
    reserved_uses: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
    )
    status: Mapped[ProxyStatus] = mapped_column(
        Enum(ProxyStatus, name="proxy_status", native_enum=False),
        nullable=False,
        default=ProxyStatus.STOPPED,
    )
    last_error: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, default=None,
    )
    # Denormalized prefix fields
    endpoint_host: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, default=None,
    )
    endpoint_port: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, default=None,
    )
    endpoint_username_enc: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, default=None,
    )
    endpoint_password_enc: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, default=None,
    )
    endpoint_display: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, default=None,
    )
    endpoint_expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None,
    )
    api_status: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, default=None,
    )
    api_message: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, default=None,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        server_default=func.now(), onupdate=func.now(),
    )

    __table_args__ = (
        UniqueConstraint("user_id", "masked_key", name="uq_proxy_keys_user_masked"),
        Index("idx_proxy_keys_user", user_id),
    )


# ─── App Settings ─────────────────────────────────────────────────────────────

class AppSetting(Base):
    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True,
    )
    kiot_auth_token_enc: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, default=None,
    )
    proxy_api_keys_enc: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, default=None,
    )
    get_new_url_template: Mapped[str] = mapped_column(
        String(512), nullable=False,
        default="https://api.kiotproxy.com/api/v1/proxies/new?key={apiKey}",
    )
    get_current_url_template: Mapped[str] = mapped_column(
        String(512), nullable=False,
        default="https://api.kiotproxy.com/api/v1/proxies/current?key={apiKey}",
    )
    uses_per_proxy: Mapped[int] = mapped_column(
        Integer, nullable=False, default=4,
    )
    proxy_check_interval: Mapped[int] = mapped_column(
        Integer, nullable=False, default=5,
    )
    interaction_threads: Mapped[int] = mapped_column(
        Integer, nullable=False, default=5,
    )
    posts_per_uid: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1,
    )
    delay_min_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
    )
    delay_max_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
    )
    delay_every_rounds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        server_default=func.now(), onupdate=func.now(),
    )
