# Flow Studio — Backend Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up Flow Studio as an independent module that runs in its own process (`app.flow_app:app` + `app.flow_worker`) alongside the existing Face module (`app.main:app`), sharing the same repo, Postgres, and Redis, so either can run alone and they call each other over HTTP only when both are up.

**Architecture:** Modular monolith, two deployables. The **Face** app is the existing `app.main:app` — left byte-for-byte untouched so it keeps running standalone with zero regression. The **Flow** app is a new standalone FastAPI (`app/flow_app.py`) with its own minimal lifespan, its own SSE endpoint (via a shared `app/sse.py` helper), and the clip-jobs router. Flow jobs ride a **separate Redis queue** (`flowmeta:clip_queue`) drained by a **separate worker** (`app/flow_worker.py`), so the two workers never steal each other's jobs. Cross-module calls go through a health-gated peer client (`app/services/peer_client.py`) that returns `None` when the peer is down — "call each other only if both on."

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0 (async), Alembic, Redis (`redis.asyncio`), in-memory `EventBus` SSE, `httpx` for peer calls, Postgres (JSONB), pytest + pytest-asyncio (SQLite in-memory for unit tests).

## Global Constraints

- **Do not modify `app/main.py`, `app/worker.py`, or `app/services/task_queue.py`.** Face module must stay exactly as-is. Flow reuses shared infra by importing it, never by editing Face's entrypoints. (Shared modules that are additive-only — `sqlmodels.py`, `rbac_catalog.py`, `config.py`, `schemas.py`, `conftest.py` — may be appended to.)
- CPU-only target — no GPU/CUDA/NVENC assumptions anywhere in code or config.
- Two processes share ONE Postgres and ONE Redis. Flow jobs use queue key `flowmeta:clip_queue`; comment jobs keep `flowmeta:task_queue`. Never enqueue a clip job onto the comment queue.
- Each app runs its own in-memory `EventBus`; each serves only its own SSE channels (Flow serves `clip`). This mirrors the existing Face worker/app boundary — do not attempt cross-process event delivery in this plan.
- Cross-module calls MUST be health-gated: check the peer's `/api/health` first; if unreachable, degrade (return `None`), never raise into the caller.
- Models inherit `Base` from `app.models.sqlmodels`; match `TaskRun` style verbatim (`Mapped[...] = mapped_column(...)`, `PG_UUID(as_uuid=True)`, `Enum(..., native_enum=False)`, `JSONB`, `server_default=func.now()`).
- Enum values are lowercase strings (e.g. `"queued"`), mirroring `TaskRunStatus`.
- New permission codes go in `app/rbac_catalog.py::PERMISSIONS`; non-`:any` resource codes are auto-granted to base roles via `OWN_RESOURCE_PERMISSIONS`.
- Tests use the `session` fixture (SQLite); every new model MUST be added to the table-creation list in `backend/tests/conftest.py`.
- All new backend code lives under `backend/app/`; tests under `backend/tests/`.

---

## Runtime Topology

```
Postgres  <-- shared -->  Redis (flowmeta:task_queue | flowmeta:clip_queue)
   ^                                   ^                    ^
   |                                   |                    |
FACE app (app.main:app :8000)   FACE worker (app.worker)   |
   |  serves face SSE + routers      drains task_queue      |
   |                                                        |
FLOW app (app.flow_app:app :8001) - serves clip SSE + clip router
FLOW worker (app.flow_worker) - drains clip_queue ----------+

Cross-calls (only when peer /api/health OK):
  FLOW --HTTP--> FACE   at settings.FACE_BASE_URL
  FACE --HTTP--> FLOW   at settings.FLOW_BASE_URL   (wired later; seam built now)
```

Run commands (documented, not executed by tests):
```bash
# Face (unchanged)
uvicorn app.main:app --host 0.0.0.0 --port 8000
python -m app.worker
# Flow (new)
uvicorn app.flow_app:app --host 0.0.0.0 --port 8001
python -m app.flow_worker
```

---

## File Structure

- `backend/app/models/sqlmodels.py` — **append** `ClipSourceType`, `ClipJobStatus`, `ClipStatus`, `ClipEditSource` enums + `ClipJob`, `Clip`, `ClipEdit` models.
- `backend/alembic/versions/20260724_0008_clip_jobs.py` — migration creating the three tables.
- `backend/app/rbac_catalog.py` — **append** `clip:*` permission codes.
- `backend/app/schemas.py` — **append** `ClipJobCreate`, `ClipJobOut`, `ClipOut` DTOs.
- `backend/app/config.py` — **append** clip + peer settings.
- `backend/app/services/clip_storage.py` (new) — `save_upload()` / `sanitize_link()`.
- `backend/app/services/clip_queue.py` (new) — separate Redis queue: `enqueue_clip_job()`, `dequeue_clip_job()`, `build_clip_job()`.
- `backend/app/services/clip_runner.py` (new) — `ClipRunner.run()` stub pipeline + `clip` SSE.
- `backend/app/services/peer_client.py` (new) — `peer_available()`, `call_peer()`.
- `backend/app/routers/clip_jobs.py` (new) — REST endpoints + peer-health endpoint.
- `backend/app/sse.py` (new) — `register_sse_endpoint(app)` shared SSE helper (Face's inline copy in `main.py` stays; dedup deferred).
- `backend/app/flow_app.py` (new) — standalone Flow FastAPI.
- `backend/app/face_app.py` (new) — `from app.main import app` alias for naming symmetry.
- `backend/app/flow_worker.py` (new) — Flow worker process draining `clip_queue`.
- `backend/tests/conftest.py` — register new models for SQLite table creation.
- New tests: `test_clip_models.py`, `test_clip_rbac.py`, `test_clip_schemas.py`, `test_clip_storage.py`, `test_clip_queue.py`, `test_clip_runner.py`, `test_peer_client.py`, `test_flow_app.py`.

---

### Task 1: Data model + migration

**Files:**
- Modify: `backend/app/models/sqlmodels.py` (append enums near the other enums; append models after `TaskLog`)
- Create: `backend/alembic/versions/20260724_0008_clip_jobs.py`
- Modify: `backend/tests/conftest.py` (register new models)
- Test: `backend/tests/test_clip_models.py`

**Interfaces:**
- Produces:
  - `ClipSourceType(str, PyEnum)`: `UPLOAD="upload"`, `LINK="link"`
  - `ClipJobStatus(str, PyEnum)`: `QUEUED="queued"`, `ANALYZING="analyzing"`, `SCORING="scoring"`, `RENDERING="rendering"`, `DONE="done"`, `ERROR="error"`
  - `ClipStatus(str, PyEnum)`: `PENDING="pending"`, `RENDERING="rendering"`, `READY="ready"`, `ERROR="error"`
  - `ClipEditSource(str, PyEnum)`: `AUTO="auto"`, `OPENCUT="opencut"`
  - `ClipJob(id, user_id, source_type, source_ref, status, params, source_sha256, error, created_at, finished_at)`
  - `Clip(id, job_id, rank, score, hook_text, start_sec, end_sec, clipspec, output_ref, status, created_at)`
  - `ClipEdit(id, clip_id, version, clipspec, source, created_at)`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_clip_models.py`:

```python
from __future__ import annotations

import uuid

from app.models.sqlmodels import (
    Clip, ClipEdit, ClipEditSource, ClipJob, ClipJobStatus, ClipSourceType, ClipStatus,
)


def test_clip_job_defaults_to_queued() -> None:
    job = ClipJob(
        user_id=uuid.uuid4(),
        source_type=ClipSourceType.LINK,
        source_ref="https://youtu.be/abc123",
        params={"top_n": 10},
    )
    assert job.status == ClipJobStatus.QUEUED
    assert job.params["top_n"] == 10


def test_clip_and_edit_link_to_job() -> None:
    clip = Clip(
        job_id=uuid.uuid4(),
        rank=1,
        score=87,
        hook_text="Bi mat la...",
        start_sec=12.5,
        end_sec=190.0,
        clipspec={"bounds": [12.5, 190.0]},
        status=ClipStatus.PENDING,
    )
    edit = ClipEdit(
        clip_id=uuid.uuid4(),
        version=1,
        clipspec={"bounds": [12.5, 190.0]},
        source=ClipEditSource.AUTO,
    )
    assert clip.rank == 1
    assert clip.status == ClipStatus.PENDING
    assert edit.source == ClipEditSource.AUTO
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_clip_models.py -v`
Expected: FAIL with `ImportError: cannot import name 'ClipJob'`

- [ ] **Step 3: Add enums and models**

In `backend/app/models/sqlmodels.py`, add these enums alongside the other `class X(str, PyEnum)` definitions (e.g. after `BrowserSessionStatus`):

```python
class ClipSourceType(str, PyEnum):
    UPLOAD = "upload"
    LINK = "link"


class ClipJobStatus(str, PyEnum):
    QUEUED = "queued"
    ANALYZING = "analyzing"
    SCORING = "scoring"
    RENDERING = "rendering"
    DONE = "done"
    ERROR = "error"


class ClipStatus(str, PyEnum):
    PENDING = "pending"
    RENDERING = "rendering"
    READY = "ready"
    ERROR = "error"


class ClipEditSource(str, PyEnum):
    AUTO = "auto"
    OPENCUT = "opencut"
```

Add these models after `TaskLog`. If `Float` is not already in the top `from sqlalchemy import (...)` block, add it there.

```python
class ClipJob(Base):
    __tablename__ = "clip_jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True,
        default=uuid.uuid4, server_default=func.gen_random_uuid(),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
    )
    source_type: Mapped[ClipSourceType] = mapped_column(
        Enum(ClipSourceType, name="clip_source_type", native_enum=False), nullable=False,
    )
    source_ref: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[ClipJobStatus] = mapped_column(
        Enum(ClipJobStatus, name="clip_job_status", native_enum=False),
        nullable=False, default=ClipJobStatus.QUEUED,
    )
    params: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    source_sha256: Mapped[Optional[str]] = mapped_column(Text, nullable=True, default=None)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None,
    )

    clips: Mapped[list["Clip"]] = relationship(
        "Clip", back_populates="job",
        cascade="all, delete-orphan", order_by="Clip.rank",
    )

    __table_args__ = (
        Index("idx_clip_jobs_user_created_at", user_id, created_at.desc()),
    )


class Clip(Base):
    __tablename__ = "clips"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True,
        default=uuid.uuid4, server_default=func.gen_random_uuid(),
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("clip_jobs.id", ondelete="CASCADE"), nullable=False,
    )
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=None)
    hook_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True, default=None)
    start_sec: Mapped[float] = mapped_column(Float, nullable=False)
    end_sec: Mapped[float] = mapped_column(Float, nullable=False)
    clipspec: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    output_ref: Mapped[Optional[str]] = mapped_column(Text, nullable=True, default=None)
    status: Mapped[ClipStatus] = mapped_column(
        Enum(ClipStatus, name="clip_status", native_enum=False),
        nullable=False, default=ClipStatus.PENDING,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )

    job: Mapped["ClipJob"] = relationship("ClipJob", back_populates="clips")

    __table_args__ = (
        Index("idx_clips_job_rank", job_id, rank),
    )


class ClipEdit(Base):
    __tablename__ = "clip_edits"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True,
        default=uuid.uuid4, server_default=func.gen_random_uuid(),
    )
    clip_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("clips.id", ondelete="CASCADE"), nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    clipspec: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    source: Mapped[ClipEditSource] = mapped_column(
        Enum(ClipEditSource, name="clip_edit_source", native_enum=False),
        nullable=False, default=ClipEditSource.AUTO,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )

    __table_args__ = (
        Index("idx_clip_edits_clip_version", clip_id, version),
    )
```

- [ ] **Step 4: Register models in test conftest**

In `backend/tests/conftest.py`, add `ClipJob, Clip, ClipEdit` to BOTH the `from app.models.sqlmodels import (...)` tuple AND the `for tbl in (...)` table-creation tuple (find the existing block that lists `TaskRun, TaskItem, TaskLog, ...` and append the three names to each). Example of the creation loop after editing:

```python
    for tbl in (
        User, Role, Permission, RolePermission, UserRole,
        # ... existing entries unchanged ...
        ClipJob, Clip, ClipEdit,
    ):
        await conn.run_sync(tbl.__table__.create, checkfirst=True)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_clip_models.py -v`
Expected: PASS (2 passed)

- [ ] **Step 6: Write the Alembic migration**

Open `backend/alembic/versions/20260723_0007_sheet_campaign_pipeline.py` and copy its `revision` string. Create `backend/alembic/versions/20260724_0008_clip_jobs.py` with `down_revision` set to that exact value:

```python
"""clip jobs

Revision ID: 20260724_0008
Revises: 20260723_0007
Create Date: 2026-07-24
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID

revision = "20260724_0008"
down_revision = "20260723_0007"  # <-- replace with the real id from 0007 if it differs
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "clip_jobs",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", PG_UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_type", sa.String(length=16), nullable=False),
        sa.Column("source_ref", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="queued"),
        sa.Column("params", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("source_sha256", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_clip_jobs_user_created_at", "clip_jobs", ["user_id", sa.text("created_at DESC")])

    op.create_table(
        "clips",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("job_id", PG_UUID(as_uuid=True), sa.ForeignKey("clip_jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("score", sa.Integer(), nullable=True),
        sa.Column("hook_text", sa.Text(), nullable=True),
        sa.Column("start_sec", sa.Float(), nullable=False),
        sa.Column("end_sec", sa.Float(), nullable=False),
        sa.Column("clipspec", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("output_ref", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_clips_job_rank", "clips", ["job_id", "rank"])

    op.create_table(
        "clip_edits",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("clip_id", PG_UUID(as_uuid=True), sa.ForeignKey("clips.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("clipspec", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("source", sa.String(length=16), nullable=False, server_default="auto"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_clip_edits_clip_version", "clip_edits", ["clip_id", "version"])


def downgrade() -> None:
    op.drop_table("clip_edits")
    op.drop_table("clips")
    op.drop_table("clip_jobs")
```

- [ ] **Step 7: Commit**

```bash
git add backend/app/models/sqlmodels.py backend/alembic/versions/20260724_0008_clip_jobs.py backend/tests/conftest.py backend/tests/test_clip_models.py
git commit -m "feat(flow-studio): add ClipJob/Clip/ClipEdit models + migration"
```

---

### Task 2: RBAC permissions

**Files:**
- Modify: `backend/app/rbac_catalog.py` (append codes to `PERMISSIONS`)
- Test: `backend/tests/test_clip_rbac.py`

**Interfaces:**
- Produces permission codes: `clip:read`, `clip:create`, `clip:cancel`, `clip:delete`, `clip:read:any`, `clip:cancel:any`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_clip_rbac.py`:

```python
from app.rbac_catalog import OWN_RESOURCE_PERMISSIONS, PERMISSIONS, ROLE_DEFINITIONS


def test_clip_permissions_registered() -> None:
    for code in ("clip:read", "clip:create", "clip:cancel", "clip:delete"):
        assert code in PERMISSIONS
    assert "clip:read:any" in PERMISSIONS


def test_clip_own_permissions_granted_to_base_user() -> None:
    assert "clip:create" in OWN_RESOURCE_PERMISSIONS
    assert "clip:create" in ROLE_DEFINITIONS["user"]["permissions"]
    assert "clip:read:any" not in OWN_RESOURCE_PERMISSIONS
```

> If the base role in `ROLE_DEFINITIONS` is not keyed `"user"`, open `rbac_catalog.py` and use the actual base-role key; adjust the assertion accordingly.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_clip_rbac.py -v`
Expected: FAIL with `assert 'clip:read' in PERMISSIONS`

- [ ] **Step 3: Add permission codes**

In `backend/app/rbac_catalog.py`, add inside the `PERMISSIONS` tuple (after the `task:*` block):

```python
    "clip:read", "clip:create", "clip:cancel", "clip:delete",
    "clip:read:any", "clip:cancel:any",
```

`OWN_RESOURCE_PERMISSIONS` and the super-admin role pick these up automatically — no other change needed.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_clip_rbac.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/rbac_catalog.py backend/tests/test_clip_rbac.py
git commit -m "feat(flow-studio): add clip RBAC permission codes"
```

---

### Task 3: Config + schemas

**Files:**
- Modify: `backend/app/config.py` (append settings)
- Modify: `backend/app/schemas.py` (append DTOs)
- Test: `backend/tests/test_clip_schemas.py`

**Interfaces:**
- Produces settings: `settings.CLIP_UPLOAD_DIR: str`, `settings.CLIP_MAX_UPLOAD_BYTES: int`, `settings.FACE_BASE_URL: str`, `settings.FLOW_BASE_URL: str`, `settings.PEER_HEALTH_TIMEOUT_SECONDS: float`, `settings.FLOW_PORT: int`
- Produces DTOs:
  - `ClipJobCreate(source_link: str | None = None, top_n: int = 10, clip_min_sec: int = 120, clip_max_sec: int = 300, scoring_backend: str = "ollama")`
  - `ClipOut(id: str, rank: int, score: int | None, hook_text: str | None, start_sec: float, end_sec: float, status: str, output_ref: str | None)`
  - `ClipJobOut(id: str, source_type: str, status: str, error: str | None, clips: list[ClipOut])`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_clip_schemas.py`:

```python
from app.config import settings
from app.schemas import ClipJobCreate, ClipJobOut, ClipOut


def test_clip_settings_present() -> None:
    assert isinstance(settings.CLIP_UPLOAD_DIR, str)
    assert settings.CLIP_MAX_UPLOAD_BYTES > 0


def test_peer_settings_present() -> None:
    assert settings.FACE_BASE_URL.startswith("http")
    assert settings.FLOW_BASE_URL.startswith("http")
    assert settings.PEER_HEALTH_TIMEOUT_SECONDS > 0


def test_clip_job_create_defaults() -> None:
    body = ClipJobCreate()
    assert body.top_n == 10
    assert body.clip_min_sec == 120
    assert body.clip_max_sec == 300
    assert body.scoring_backend == "ollama"


def test_clip_job_out_serializes_clips() -> None:
    out = ClipJobOut(
        id="j1", source_type="link", status="done", error=None,
        clips=[ClipOut(id="c1", rank=1, score=90, hook_text="hi",
                       start_sec=1.0, end_sec=120.0, status="ready", output_ref="/x.mp4")],
    )
    assert out.clips[0].rank == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_clip_schemas.py -v`
Expected: FAIL with `AttributeError: 'Settings' object has no attribute 'CLIP_UPLOAD_DIR'`

- [ ] **Step 3: Add settings and DTOs**

In `backend/app/config.py`, add inside `class Settings` after `COMMENT_IMAGE_MAX_BYTES` (line 66):

```python
    # Flow Studio (clip module)
    CLIP_UPLOAD_DIR: str = "/app/uploads/clips"
    CLIP_MAX_UPLOAD_BYTES: int = 4 * 1024 * 1024 * 1024  # 4 GB
    FLOW_PORT: int = 8001

    # Cross-module peer endpoints (used only when the peer is up)
    FACE_BASE_URL: str = "http://localhost:8000"
    FLOW_BASE_URL: str = "http://localhost:8001"
    PEER_HEALTH_TIMEOUT_SECONDS: float = 2.0
```

In `backend/app/schemas.py`, append (match the file's existing Pydantic `BaseModel` import — it is already imported there):

```python
class ClipJobCreate(BaseModel):
    source_link: str | None = None
    top_n: int = 10
    clip_min_sec: int = 120
    clip_max_sec: int = 300
    scoring_backend: str = "ollama"


class ClipOut(BaseModel):
    id: str
    rank: int
    score: int | None = None
    hook_text: str | None = None
    start_sec: float
    end_sec: float
    status: str
    output_ref: str | None = None


class ClipJobOut(BaseModel):
    id: str
    source_type: str
    status: str
    error: str | None = None
    clips: list[ClipOut] = []
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_clip_schemas.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/config.py backend/app/schemas.py backend/tests/test_clip_schemas.py
git commit -m "feat(flow-studio): add clip + peer config settings and API DTOs"
```

---

### Task 4: Storage service

**Files:**
- Create: `backend/app/services/clip_storage.py`
- Test: `backend/tests/test_clip_storage.py`

**Interfaces:**
- Consumes: `settings.CLIP_UPLOAD_DIR` (Task 3)
- Produces:
  - `sanitize_link(link: str) -> str` — strip/validate an http(s) URL, raise `ValueError` otherwise
  - `save_upload(user_id: str, filename: str, content: bytes) -> str` — write to `CLIP_UPLOAD_DIR/<user_id>/<uuid>_<safe_name>` and return the absolute path string

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_clip_storage.py`:

```python
import pytest

from app.services.clip_storage import sanitize_link, save_upload


def test_sanitize_link_accepts_https() -> None:
    assert sanitize_link("  https://youtu.be/abc  ") == "https://youtu.be/abc"


def test_sanitize_link_rejects_non_http() -> None:
    with pytest.raises(ValueError):
        sanitize_link("javascript:alert(1)")


def test_save_upload_writes_file(tmp_path, monkeypatch) -> None:
    from app.config import settings
    monkeypatch.setattr(settings, "CLIP_UPLOAD_DIR", str(tmp_path))
    path = save_upload("user-1", "My Video.mp4", b"data-bytes")
    with open(path, "rb") as fh:
        assert fh.read() == b"data-bytes"
    assert path.endswith(".mp4")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_clip_storage.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.clip_storage'`

- [ ] **Step 3: Implement the storage service**

Create `backend/app/services/clip_storage.py`:

```python
"""Filesystem storage for Flow Studio source uploads."""
from __future__ import annotations

import re
import uuid
from pathlib import Path
from urllib.parse import urlparse

from app.config import settings


def sanitize_link(link: str) -> str:
    cleaned = (link or "").strip()
    parsed = urlparse(cleaned)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("source_link must be an http(s) URL")
    return cleaned


def save_upload(user_id: str, filename: str, content: bytes) -> str:
    stem = Path(filename or "video").stem
    safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._")[:80] or "video"
    suffix = Path(filename or "").suffix.lower()
    if not re.fullmatch(r"\.[A-Za-z0-9]{1,5}", suffix):
        suffix = ".mp4"
    directory = Path(settings.CLIP_UPLOAD_DIR) / str(user_id)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{uuid.uuid4().hex}_{safe_stem}{suffix}"
    path.write_bytes(content)
    return str(path)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_clip_storage.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/clip_storage.py backend/tests/test_clip_storage.py
git commit -m "feat(flow-studio): add clip source storage service"
```

---

### Task 5: Separate clip queue + stub runner

**Files:**
- Create: `backend/app/services/clip_queue.py`
- Create: `backend/app/services/clip_runner.py`
- Test: `backend/tests/test_clip_queue.py`, `backend/tests/test_clip_runner.py`

**Interfaces:**
- Consumes: `ClipJob`, `Clip`, `ClipJobStatus`, `ClipStatus` (Task 1); `get_redis` (existing `app.db.redis`)
- Produces:
  - `CLIP_QUEUE_KEY = "flowmeta:clip_queue"`
  - `build_clip_job(job_id: str) -> dict` -> `{"type": "clip_job", "job_id": job_id}`
  - `async enqueue_clip_job(payload: dict) -> int` — `rpush` to `CLIP_QUEUE_KEY`, returns queue length
  - `async dequeue_clip_job(timeout_seconds: int = 5) -> dict | None` — `blpop` from `CLIP_QUEUE_KEY`
  - `ClipRunner(session_factory, publish)` with `async def run(self, job_id: str) -> None` — walks job through `analyzing->scoring->rendering->done`, publishes one `clip`-channel event per phase (`event_type="phase"`, `data={"user_id","job_id","phase"}`), writes ONE stub `Clip` row, sets job `status=DONE` + `finished_at`; on exception sets `status=ERROR`, stores `error`, publishes `event_type="error"`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_clip_queue.py`:

```python
from app.services.clip_queue import CLIP_QUEUE_KEY, build_clip_job


def test_build_clip_job_shape() -> None:
    assert build_clip_job("abc") == {"type": "clip_job", "job_id": "abc"}


def test_clip_queue_key_is_separate() -> None:
    # Must NOT collide with the comment worker's queue.
    from app.services.task_queue import QUEUE_KEY
    assert CLIP_QUEUE_KEY == "flowmeta:clip_queue"
    assert CLIP_QUEUE_KEY != QUEUE_KEY
```

Create `backend/tests/test_clip_runner.py`:

```python
import pytest
from sqlalchemy import select

from app.models.sqlmodels import Clip, ClipJob, ClipJobStatus, ClipSourceType
from app.services.clip_runner import ClipRunner


@pytest.mark.asyncio
async def test_runner_completes_job_and_writes_clip(session, session_factory, user_id, _ensure_user) -> None:
    job = ClipJob(
        user_id=user_id, source_type=ClipSourceType.LINK,
        source_ref="https://youtu.be/x", params={"clip_min_sec": 120},
    )
    session.add(job)
    await session.flush()
    job_id = str(job.id)

    events: list[tuple] = []

    async def publish(channel, event_type, data):
        events.append((channel, event_type, data))

    runner = ClipRunner(session_factory=session_factory, publish=publish)
    await runner.run(job_id)

    refreshed = (await session.execute(select(ClipJob).where(ClipJob.id == job.id))).scalar_one()
    clips = (await session.execute(select(Clip).where(Clip.job_id == job.id))).scalars().all()

    assert refreshed.status == ClipJobStatus.DONE
    assert len(clips) == 1
    assert any(evt[1] == "phase" for evt in events)
    assert all(evt[0] == "clip" for evt in events)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_clip_queue.py tests/test_clip_runner.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.clip_queue'`

- [ ] **Step 3: Implement the queue**

Create `backend/app/services/clip_queue.py`:

```python
"""Redis-backed queue for Flow Studio clip jobs.

Deliberately a SEPARATE key from the comment worker's queue so the Face
worker and the Flow worker never steal each other's jobs.
"""
from __future__ import annotations

import json
from typing import Any

from app.db.redis import get_redis

CLIP_QUEUE_KEY = "flowmeta:clip_queue"


def build_clip_job(job_id: str) -> dict[str, Any]:
    return {"type": "clip_job", "job_id": job_id}


async def enqueue_clip_job(payload: dict[str, Any]) -> int:
    redis = await get_redis()
    return int(await redis.rpush(CLIP_QUEUE_KEY, json.dumps(payload, ensure_ascii=False)))


async def dequeue_clip_job(timeout_seconds: int = 5) -> dict[str, Any] | None:
    redis = await get_redis()
    item = await redis.blpop(CLIP_QUEUE_KEY, timeout=timeout_seconds)
    if item is None:
        return None
    _, raw_payload = item
    return json.loads(raw_payload)
```

- [ ] **Step 4: Implement the stub runner**

Create `backend/app/services/clip_runner.py`:

```python
"""Flow Studio clip pipeline runner.

STUB in the foundation plan: walks the job through phases and writes one
placeholder clip. Plan 2 replaces the body of `_process` with the real
prefilter -> ASR -> score -> cut -> subtitle pipeline. The public surface
(constructor + `run`) is fixed so Plan 2 is a drop-in.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from app.models.sqlmodels import Clip, ClipJob, ClipJobStatus, ClipStatus

PHASES = (ClipJobStatus.ANALYZING, ClipJobStatus.SCORING, ClipJobStatus.RENDERING)


class ClipRunner:
    def __init__(self, session_factory, publish) -> None:
        self._session_factory = session_factory
        self._publish = publish

    async def run(self, job_id: str) -> None:
        try:
            await self._process(job_id)
        except Exception as exc:  # noqa: BLE001 — persist failure, never crash worker
            await self._mark_error(job_id, str(exc))
            raise

    async def _process(self, job_id: str) -> None:
        job_uuid = uuid.UUID(job_id)
        async with self._session_factory() as session:
            job = (await session.execute(select(ClipJob).where(ClipJob.id == job_uuid))).scalar_one()
            user_id = str(job.user_id)

            for phase in PHASES:
                job.status = phase
                await session.commit()
                await self._publish("clip", "phase", {
                    "user_id": user_id, "job_id": job_id, "phase": phase.value,
                })

            clip = Clip(
                job_id=job.id, rank=1, score=0, hook_text=None,
                start_sec=0.0, end_sec=float(job.params.get("clip_min_sec", 120)),
                clipspec={"stub": True}, status=ClipStatus.READY,
            )
            session.add(clip)
            job.status = ClipJobStatus.DONE
            job.finished_at = datetime.now(timezone.utc)
            await session.commit()

            await self._publish("clip", "done", {"user_id": user_id, "job_id": job_id})

    async def _mark_error(self, job_id: str, message: str) -> None:
        job_uuid = uuid.UUID(job_id)
        async with self._session_factory() as session:
            job = (await session.execute(select(ClipJob).where(ClipJob.id == job_uuid))).scalar_one_or_none()
            if job is None:
                return
            job.status = ClipJobStatus.ERROR
            job.error = message[:2000]
            job.finished_at = datetime.now(timezone.utc)
            await session.commit()
            await self._publish("clip", "error", {
                "user_id": str(job.user_id), "job_id": job_id, "error": message[:500],
            })
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_clip_queue.py tests/test_clip_runner.py -v`
Expected: PASS (3 passed)

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/clip_queue.py backend/app/services/clip_runner.py backend/tests/test_clip_queue.py backend/tests/test_clip_runner.py
git commit -m "feat(flow-studio): add separate clip queue + stub pipeline runner"
```

---

### Task 6: Health-gated peer client

**Files:**
- Create: `backend/app/services/peer_client.py`
- Test: `backend/tests/test_peer_client.py`

**Interfaces:**
- Consumes: `settings.PEER_HEALTH_TIMEOUT_SECONDS` (Task 3); `httpx`
- Produces:
  - `async peer_available(base_url: str) -> bool` — `GET {base_url}/api/health` with `PEER_HEALTH_TIMEOUT_SECONDS`; True only on 2xx; any exception/timeout -> False
  - `async call_peer(base_url: str, method: str, path: str, *, json: dict | None = None, token: str | None = None) -> dict | None` — returns `None` immediately if `peer_available` is False; otherwise issues the request and returns the parsed JSON dict, or `None` on any error

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_peer_client.py`:

```python
import pytest

from app.services import peer_client


class _FakeResp:
    def __init__(self, status_code: int, payload: dict | None = None) -> None:
        self.status_code = status_code
        self._payload = payload or {}

    def json(self) -> dict:
        return self._payload


class _FakeClient:
    def __init__(self, resp=None, boom=False) -> None:
        self._resp = resp
        self._boom = boom

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, **kw):
        if self._boom:
            raise RuntimeError("connection refused")
        return self._resp

    async def request(self, method, url, **kw):
        if self._boom:
            raise RuntimeError("connection refused")
        return self._resp


@pytest.mark.asyncio
async def test_peer_available_true_on_200(monkeypatch) -> None:
    monkeypatch.setattr(peer_client.httpx, "AsyncClient", lambda *a, **k: _FakeClient(_FakeResp(200)))
    assert await peer_client.peer_available("http://face") is True


@pytest.mark.asyncio
async def test_peer_available_false_when_down(monkeypatch) -> None:
    monkeypatch.setattr(peer_client.httpx, "AsyncClient", lambda *a, **k: _FakeClient(boom=True))
    assert await peer_client.peer_available("http://face") is False


@pytest.mark.asyncio
async def test_call_peer_returns_none_when_down(monkeypatch) -> None:
    monkeypatch.setattr(peer_client.httpx, "AsyncClient", lambda *a, **k: _FakeClient(boom=True))
    result = await peer_client.call_peer("http://face", "POST", "/api/x", json={"a": 1})
    assert result is None


@pytest.mark.asyncio
async def test_call_peer_returns_json_when_up(monkeypatch) -> None:
    monkeypatch.setattr(
        peer_client.httpx, "AsyncClient",
        lambda *a, **k: _FakeClient(_FakeResp(200, {"ok": True})),
    )
    result = await peer_client.call_peer("http://face", "GET", "/api/health")
    assert result == {"ok": True}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_peer_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.peer_client'`

- [ ] **Step 3: Implement the peer client**

Create `backend/app/services/peer_client.py`:

```python
"""Health-gated cross-module HTTP client.

Face and Flow run as separate processes. Either may be down. Every
cross-call first pings the peer's /api/health; if the peer is unreachable
the call degrades to None instead of raising — "call each other only if
both on."
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger("flowmeta.peer")


async def peer_available(base_url: str) -> bool:
    timeout = settings.PEER_HEALTH_TIMEOUT_SECONDS
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(f"{base_url.rstrip('/')}/api/health")
            return 200 <= resp.status_code < 300
    except Exception:
        return False


async def call_peer(
    base_url: str,
    method: str,
    path: str,
    *,
    json: dict[str, Any] | None = None,
    token: str | None = None,
) -> dict[str, Any] | None:
    if not await peer_available(base_url):
        logger.info("peer %s unavailable; skipping %s %s", base_url, method, path)
        return None
    headers = {"Authorization": f"Bearer {token}"} if token else None
    url = f"{base_url.rstrip('/')}{path}"
    try:
        async with httpx.AsyncClient(timeout=settings.PEER_HEALTH_TIMEOUT_SECONDS) as client:
            resp = await client.request(method, url, json=json, headers=headers)
            if 200 <= resp.status_code < 300:
                return resp.json()
            logger.warning("peer %s %s returned %s", method, url, resp.status_code)
            return None
    except Exception:
        logger.exception("peer call %s %s failed", method, url)
        return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_peer_client.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/peer_client.py backend/tests/test_peer_client.py
git commit -m "feat(flow-studio): add health-gated cross-module peer client"
```

---

### Task 7: Flow app + router + SSE + worker

**Files:**
- Create: `backend/app/sse.py`
- Create: `backend/app/routers/clip_jobs.py`
- Create: `backend/app/flow_app.py`
- Create: `backend/app/face_app.py`
- Create: `backend/app/flow_worker.py`
- Test: `backend/tests/test_flow_app.py`

**Interfaces:**
- Consumes: `ClipJobOut`, `ClipOut` (Task 3); `sanitize_link`, `save_upload` (Task 4); `build_clip_job`, `enqueue_clip_job`, `dequeue_clip_job` (Task 5); `ClipRunner` (Task 5); `peer_available` (Task 6); `require_permission` (existing `app.rbac`); `get_session`, `session_context` (existing `app.db.postgres`); `event_bus` (existing); `parse_token`, `_load_user_by_id` (existing `app.auth`)
- Produces:
  - `register_sse_endpoint(app, *, channels_default="clip")` — mounts `GET /api/events/stream` on the given app, reusing `event_bus` + token auth
  - Router endpoints:
    - `POST /api/clip-jobs` (multipart: `file` OR form `source_link`) -> `{"job_id","status"}`, perm `clip:create`
    - `GET /api/clip-jobs/{job_id}` -> `ClipJobOut`, perm `clip:read`
    - `GET /api/clips/{clip_id}/download` -> `FileResponse`, perm `clip:read`
    - `GET /api/flow/peers/face` -> `{"face_available": bool}`, perm `clip:read` (proves the peer seam)
  - `app.flow_app:app` — standalone Flow FastAPI
  - `app.face_app:app` — alias re-export of `app.main:app`
  - `app.flow_worker.run_flow_worker()`, `app.flow_worker.process_clip_job(job)`, `main()` — drains `clip_queue`, dispatches `clip_job` to `ClipRunner`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_flow_app.py`:

```python
import pytest


def test_flow_app_has_clip_routes() -> None:
    from app.flow_app import app
    paths = {r.path for r in app.routes}
    assert "/api/clip-jobs" in paths
    assert "/api/clip-jobs/{job_id}" in paths
    assert "/api/clips/{clip_id}/download" in paths
    assert "/api/flow/peers/face" in paths
    assert "/api/events/stream" in paths


def test_flow_app_excludes_face_routes() -> None:
    # Flow must be independent — no comment/task endpoints leak in.
    from app.flow_app import app
    paths = {r.path for r in app.routes}
    assert not any(p.startswith("/api/comment-tasks") for p in paths)
    assert not any(p.startswith("/api/tasks") for p in paths)


def test_face_app_alias_is_main_app() -> None:
    from app import face_app, main
    assert face_app.app is main.app


@pytest.mark.asyncio
async def test_flow_worker_dispatches_clip_job(monkeypatch) -> None:
    import app.flow_worker as fw

    called = {}

    class _FakeRunner:
        def __init__(self, **kw):
            pass

        async def run(self, job_id):
            called["job_id"] = job_id

    monkeypatch.setattr(fw, "ClipRunner", _FakeRunner)
    handled = await fw.process_clip_job({"type": "clip_job", "job_id": "j-42"})
    assert handled is True
    assert called["job_id"] == "j-42"


@pytest.mark.asyncio
async def test_flow_worker_skips_foreign_job() -> None:
    import app.flow_worker as fw
    handled = await fw.process_clip_job({"type": "comment_task", "run_id": "x"})
    assert handled is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_flow_app.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.flow_app'`

- [ ] **Step 3: Implement the shared SSE helper**

Create `backend/app/sse.py`. This lifts the SSE handler so the Flow app can serve its own channels; Face's inline copy in `main.py` is intentionally left as-is (dedup deferred to a later cleanup).

```python
"""Shared SSE endpoint factory — mounts /api/events/stream on any app."""
from __future__ import annotations

import asyncio
import json

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.auth import parse_token, _load_user_by_id
from app.db.postgres import session_context
from app.event_bus import event_bus
from app.models.sqlmodels import UserStatus


def _json(data) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)


def register_sse_endpoint(app: FastAPI, *, channels_default: str = "clip") -> None:
    @app.get("/api/events/stream")
    async def stream_events(
        request: Request,
        channels: str = channels_default,
        last_id: str | None = None,
        token: str | None = None,
    ):
        if not token:
            raise HTTPException(status_code=401, detail="Authentication token is required")
        try:
            user_id = parse_token(token)
            if user_id is None:
                raise HTTPException(status_code=401, detail="Invalid or expired token")
            async with session_context() as session:
                user = await _load_user_by_id(session, user_id)
                if user is None or user.status != UserStatus.ACTIVE:
                    raise HTTPException(status_code=401, detail="User not found or disabled")
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(status_code=401, detail="Authentication failed")

        wanted = [c.strip() for c in channels.split(",") if c.strip()]

        async def event_stream():
            merge_q: asyncio.Queue = asyncio.Queue(maxsize=500)
            consumers: list[asyncio.Task] = []

            async def _forward(channel: str) -> None:
                gen = event_bus.subscribe(channel, last_id, user_id=user_id)
                try:
                    async for event_id, event_type, data in gen:
                        if event_type == "ping":
                            await merge_q.put(("", "ping", None))
                        elif event_type == "reset":
                            await merge_q.put(("", "reset", {"reason": "stale"}))
                        else:
                            await merge_q.put((event_id, event_type, data))
                except Exception:
                    pass

            for ch in wanted:
                consumers.append(asyncio.ensure_future(_forward(ch)))
            try:
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        event_id, event_type, data = await asyncio.wait_for(merge_q.get(), timeout=30)
                    except asyncio.TimeoutError:
                        yield ": ping\n\n"
                        continue
                    if event_type == "ping":
                        yield ": ping\n\n"
                    elif event_type == "reset":
                        yield f"event: reset\ndata: {_json({'reason': 'stale_event_id'})}\n\n"
                    else:
                        payload = _json(data) if data is not None else ""
                        yield f"event: {event_type}\nid: {event_id}\ndata: {payload}\n\n"
            finally:
                for task in consumers:
                    task.cancel()
                await asyncio.gather(*consumers, return_exceptions=True)

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
        )
```

- [ ] **Step 4: Implement the clip-jobs router**

Create `backend/app/routers/clip_jobs.py`:

```python
"""Flow Studio clip job endpoints."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.postgres import get_session
from app.models.sqlmodels import Clip, ClipJob, ClipJobStatus, ClipSourceType, User
from app.rbac import require_permission
from app.schemas import ClipJobOut, ClipOut
from app.services.clip_queue import build_clip_job, enqueue_clip_job
from app.services.clip_storage import sanitize_link, save_upload
from app.services.peer_client import peer_available

router = APIRouter(tags=["clip-jobs"])


@router.post("/api/clip-jobs", response_model=dict)
async def create_clip_job(
    source_link: str | None = Form(default=None),
    top_n: int = Form(default=10),
    clip_min_sec: int = Form(default=120),
    clip_max_sec: int = Form(default=300),
    scoring_backend: str = Form(default="ollama"),
    file: UploadFile | None = File(default=None),
    user: User = Depends(require_permission("clip:create")),
    session: AsyncSession = Depends(get_session),
):
    params = {
        "top_n": top_n, "clip_min_sec": clip_min_sec,
        "clip_max_sec": clip_max_sec, "scoring_backend": scoring_backend,
    }
    if file is not None:
        content = await file.read(settings.CLIP_MAX_UPLOAD_BYTES + 1)
        await file.close()
        if not content:
            raise HTTPException(status_code=400, detail="Uploaded file is empty")
        if len(content) > settings.CLIP_MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="File exceeds the upload limit")
        source_ref = save_upload(str(user.id), file.filename or "video.mp4", content)
        source_type = ClipSourceType.UPLOAD
    elif source_link:
        try:
            source_ref = sanitize_link(source_link)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        source_type = ClipSourceType.LINK
    else:
        raise HTTPException(status_code=400, detail="Provide either a file or source_link")

    job = ClipJob(user_id=user.id, source_type=source_type, source_ref=source_ref, params=params)
    session.add(job)
    await session.commit()
    await session.refresh(job)

    try:
        await enqueue_clip_job(build_clip_job(str(job.id)))
    except Exception as exc:
        job.status = ClipJobStatus.ERROR
        job.error = "Could not enqueue job"
        await session.commit()
        raise HTTPException(status_code=503, detail=f"Could not enqueue job: {exc}") from exc

    return {"job_id": str(job.id), "status": job.status.value}


@router.get("/api/clip-jobs/{job_id}", response_model=ClipJobOut)
async def get_clip_job(
    job_id: uuid.UUID,
    user: User = Depends(require_permission("clip:read")),
    session: AsyncSession = Depends(get_session),
):
    job = (await session.execute(select(ClipJob).where(ClipJob.id == job_id))).scalar_one_or_none()
    if job is None or job.user_id != user.id:
        raise HTTPException(status_code=404, detail="Job not found")
    clips = (await session.execute(select(Clip).where(Clip.job_id == job_id).order_by(Clip.rank))).scalars().all()
    return ClipJobOut(
        id=str(job.id), source_type=job.source_type.value, status=job.status.value, error=job.error,
        clips=[ClipOut(
            id=str(c.id), rank=c.rank, score=c.score, hook_text=c.hook_text,
            start_sec=c.start_sec, end_sec=c.end_sec, status=c.status.value, output_ref=c.output_ref,
        ) for c in clips],
    )


@router.get("/api/clips/{clip_id}/download")
async def download_clip(
    clip_id: uuid.UUID,
    user: User = Depends(require_permission("clip:read")),
    session: AsyncSession = Depends(get_session),
):
    clip = (await session.execute(select(Clip).where(Clip.id == clip_id))).scalar_one_or_none()
    if clip is None:
        raise HTTPException(status_code=404, detail="Clip not found")
    job = (await session.execute(select(ClipJob).where(ClipJob.id == clip.job_id))).scalar_one_or_none()
    if job is None or job.user_id != user.id:
        raise HTTPException(status_code=404, detail="Clip not found")
    if not clip.output_ref:
        raise HTTPException(status_code=409, detail="Clip has no rendered output yet")
    return FileResponse(clip.output_ref, media_type="video/mp4", filename=f"clip-{clip.rank}.mp4")


@router.get("/api/flow/peers/face", response_model=dict)
async def face_peer_status(
    user: User = Depends(require_permission("clip:read")),
):
    return {"face_available": await peer_available(settings.FACE_BASE_URL)}
```

- [ ] **Step 5: Implement the Flow app**

Create `backend/app/flow_app.py`:

```python
"""Flow Studio standalone FastAPI app (runs independently of Face).

    uvicorn app.flow_app:app --host 0.0.0.0 --port 8001
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db.postgres import close_db
from app.db.redis import close_redis
from app.routers import clip_jobs, health
from app.sse import register_sse_endpoint


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # Flow needs no proxy/profile/scheduler machinery — just shared DB + Redis.
    try:
        yield
    finally:
        await close_redis()
        await close_db()


app = FastAPI(title="Flow Studio API", version=settings.APP_VERSION, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(clip_jobs.router)
register_sse_endpoint(app, channels_default="clip")
```

> Confirm `app.routers.health` exposes `router` with `GET /api/health` (it is registered first in `main.py`, so it exists). Both apps must expose `/api/health` because `peer_available` targets that path. If Face's health path differs, keep whatever `health.router` defines and point `peer_client.peer_available` at that path instead — note the change in the commit.

- [ ] **Step 6: Implement the Face alias**

Create `backend/app/face_app.py`:

```python
"""Naming-symmetry alias for the Face module app.

Face is the existing app.main:app, left untouched. Run either name:
    uvicorn app.main:app     --port 8000
    uvicorn app.face_app:app --port 8000
"""
from __future__ import annotations

from app.main import app

__all__ = ["app"]
```

- [ ] **Step 7: Implement the Flow worker**

Create `backend/app/flow_worker.py`:

```python
"""Flow Studio worker — drains the clip queue only.

    python -m app.flow_worker

Separate from app.worker so Flow runs without the Face worker, and the two
never contend for each other's jobs (distinct Redis keys).
"""
from __future__ import annotations

import asyncio
import logging

from app.db.postgres import close_db, session_context
from app.db.redis import close_redis
from app.event_bus import event_bus
from app.services.clip_queue import dequeue_clip_job
from app.services.clip_runner import ClipRunner

logger = logging.getLogger("flowmeta.flow_worker")


async def process_clip_job(job: dict) -> bool:
    if job.get("type") != "clip_job":
        logger.warning("Flow worker skipping non-clip job: %s", job.get("type"))
        return False
    runner = ClipRunner(session_factory=session_context, publish=event_bus.publish)
    try:
        await runner.run(str(job["job_id"]))
    except Exception:
        logger.exception("Clip job %s failed", job.get("job_id"))
        return False
    return True


async def run_flow_worker() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logger.info("Flow Studio worker started")
    try:
        while True:
            job = await dequeue_clip_job(timeout_seconds=5)
            if job is None:
                continue
            await process_clip_job(job)
    finally:
        await close_redis()
        await close_db()


def main() -> None:
    asyncio.run(run_flow_worker())


if __name__ == "__main__":
    main()
```

- [ ] **Step 8: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_flow_app.py -v`
Expected: PASS (5 passed)

- [ ] **Step 9: Run the full clip suite**

Run: `cd backend && python -m pytest tests/test_clip_models.py tests/test_clip_rbac.py tests/test_clip_schemas.py tests/test_clip_storage.py tests/test_clip_queue.py tests/test_clip_runner.py tests/test_peer_client.py tests/test_flow_app.py -v`
Expected: all PASS

- [ ] **Step 10: Confirm Face app still imports (no regression)**

Run: `cd backend && python -c "import app.main; print('face ok', len(app.main.app.routes))"`
Expected: prints `face ok <N>` with no error (Face routes unchanged from before this plan).

- [ ] **Step 11: Commit**

```bash
git add backend/app/sse.py backend/app/routers/clip_jobs.py backend/app/flow_app.py backend/app/face_app.py backend/app/flow_worker.py backend/tests/test_flow_app.py
git commit -m "feat(flow-studio): standalone flow app + router + SSE + worker"
```

---

## Self-Review

- **Spec coverage (foundation subset):** data model §9 -> Task 1; RBAC §11 -> Task 2; config §8 + DTOs §10 -> Task 3; storage §7 -> Task 4; queue/worker/SSE §2 -> Task 5 + Task 7; API §10 (POST/GET/download) -> Task 7. Module isolation (the new requirement) -> separate app (Task 7 `flow_app.py`), separate queue (Task 5 `CLIP_QUEUE_KEY`), separate worker (Task 7 `flow_worker.py`), health-gated cross-call (Task 6 + `/api/flow/peers/face`). Scoring/ASR/render/editor (§5–6, §12–13) out of scope — Plan 2 / Plan 3.
- **Isolation guarantees:** `test_flow_app_excludes_face_routes` proves Flow carries no Face endpoints; the Global Constraint forbids touching `main.py`/`worker.py`/`task_queue.py`; `test_clip_queue_key_is_separate` proves the queues can't collide; Step 10 proves Face still imports unchanged.
- **Type consistency:** `ClipRunner(session_factory, publish)` identical across Task 5 test, runner, and Task 7 worker. `build_clip_job` -> `{"type":"clip_job","job_id":...}` produced in Task 5, dispatched in Task 7 (`process_clip_job` checks `type == "clip_job"`). Enum value strings (`"queued"`,`"done"`,`"ready"`) match models (Task 1) and DTO/asserts (Task 3/5). `peer_available(base_url)` signature identical in Task 6 and its Task 7 caller.
- **Placeholder scan:** no TBD/TODO; the two "confirm the real value" notes (0007 revision id in Task 1; health path in Task 5/Task 7) are explicit verification instructions with a concrete fallback, not deferred work.

---

## Next Plans (separate specs → separate plans)

Not in this plan; each needs a short spike + its own writing-plans pass.

**Plan 2 — AI pipeline (replaces `ClipRunner._process`).** Spike: fork `SamurAIGPT/AI-Youtube-Shorts-Generator`, verify PhoWhisper int8 + Ollama run CPU-only. Tasks: prefilter (audio hot-zones) -> ASR (PhoWhisper int8 + punctuation) -> score (pluggable `ollama`/`claude`/`heuristic`) -> cut (FFmpeg stream-copy + keyframe∩silence snap -> clipspec) -> subtitle (ASS, Be Vietnam Pro) -> eval harness. The runner constructor + `run` surface from Task 5 stays fixed, so this drops in behind the Flow worker.

**Plan 3 — Frontend + OpenCut + real cross-calls.** Spike: OpenCut classic project format + embedding. Tasks: Flow job-create page (upload/link) -> job page with `clip` SSE progress + clip list -> embed OpenCut classic -> `clipspec <-> OpenCut` adapter (round-trip tested) -> `POST /clips/{id}/render` -> **first real peer call**: Flow -> Face "publish this clip as a post" via `call_peer(settings.FACE_BASE_URL, ...)`, guarded by the seam from Task 6.

---

## Execution Handoff

Two execution options:

1. **Subagent-Driven (recommended)** — fresh subagent per task, review between tasks.
2. **Inline Execution** — execute in this session with checkpoints.
