"""Browser profile helpers for personal Facebook posting."""
from __future__ import annotations

import uuid
from pathlib import Path

from app.config import settings


def profile_path(user_id: uuid.UUID | str, account_id: uuid.UUID | str) -> Path:
    return Path(settings.BROWSER_PROFILE_DIR) / str(user_id) / str(account_id)


def activate_remote_profile(user_id: uuid.UUID | str, account_id: uuid.UUID | str) -> Path:
    path = profile_path(user_id, account_id)
    path.mkdir(parents=True, exist_ok=True)

    control_dir = Path(settings.BROWSER_PROFILE_DIR) / ".remote"
    control_dir.mkdir(parents=True, exist_ok=True)
    active_file = control_dir / "active_profile"
    active_file.write_text(f"{user_id}/{account_id}", encoding="utf-8")
    return path


def profile_exists(user_id: uuid.UUID | str, account_id: uuid.UUID | str) -> bool:
    path = profile_path(user_id, account_id)
    if not path.exists() or not path.is_dir():
        return False
    return any(path.iterdir())


def login_session_url(account_id: uuid.UUID | str) -> str:
    template = settings.REMOTE_BROWSER_URL_TEMPLATE.strip()
    if template:
        return template.replace("{account_id}", str(account_id))
    base_url = settings.REMOTE_BROWSER_BASE_URL.strip().rstrip("/")
    if not base_url:
        return ""
    return f"{base_url}/vnc.html?autoconnect=true&resize=scale"
