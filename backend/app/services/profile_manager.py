"""ProfileManager — DB-backed profile CRUD. Direct port of ProfileManager.cs."""
from __future__ import annotations

from typing import Dict, List, Optional

from sqlalchemy import select, delete, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import CITEXT

from app.crypto import decrypt, encrypt, mask
from app.models.sqlmodels import Profile, TokenStatus


class ParseResult:
    """Result of parsing/importing profile text."""

    def __init__(self, total: int, errors: List[str], duplicate_count: int, added_count: int):
        self.total = total
        self.errors = errors
        self.duplicate_count = duplicate_count
        self.added_count = added_count


class ProfileManager:
    """Manages profile (uid|token) CRUD in PostgreSQL."""

    def __init__(self) -> None:
        self._profiles_by_uid: Dict[str, Profile] = {}
        self._next_index: int = 0

    # -- in-memory cache refresh -------------------------------------------------

    async def reload_cache(self, session: AsyncSession) -> None:
        """Load all profiles from DB into in-memory cache."""
        result = await session.execute(select(Profile).order_by(Profile.uid))
        rows = result.scalars().all()
        self._profiles_by_uid.clear()
        for row in rows:
            self._profiles_by_uid[row.uid.lower()] = row
        self._next_index = len(rows)

    # -- import / merge ----------------------------------------------------------

    async def import_text(self, session: AsyncSession, raw_text: str) -> ParseResult:
        """
        Parse raw 'uid|token' lines, insert new profiles and update duplicates.
        Dedup by UID (case-insensitive): same UID → refresh token.
        """
        lines = raw_text.replace("\r\n", "\n").split("\n")
        errors: List[str] = []
        duplicate_count = 0
        added_count = 0

        existing_by_lower = {
            uid: p for uid, p in self._profiles_by_uid.items()
        }

        for raw_line in lines:
            line = raw_line.strip()
            if not line:
                continue
            parts = line.split("|", 1)
            if len(parts) != 2 or not parts[0].strip() or not parts[1].strip():
                errors.append(f"Sai định dạng: {line}")
                continue

            uid = parts[0].strip()
            token = parts[1].strip()
            uid_lower = uid.lower()

            if uid_lower in existing_by_lower:
                existing = existing_by_lower[uid_lower]
                existing.token_enc = encrypt(token)
                existing.token_status = TokenStatus.DA_REFRESH
                existing.last_error = ""
                duplicate_count += 1
            else:
                profile = Profile(
                    uid=uid,
                    token_enc=encrypt(token),
                    token_status=TokenStatus.DA_NAP,
                )
                session.add(profile)
                # don't add to cache yet — flush happens in commit
                added_count += 1
                existing_by_lower[uid_lower] = profile

        await session.commit()
        # refresh cache
        await self.reload_cache(session)
        return ParseResult(
            total=len(self._profiles_by_uid),
            errors=errors,
            duplicate_count=duplicate_count,
            added_count=added_count,
        )

    # -- remove ------------------------------------------------------------------

    async def remove_by_uids(self, session: AsyncSession, uids: List[str]) -> int:
        """Remove profiles by UID list. Returns count removed."""
        if not uids:
            return 0
        normalized = [u.strip() for u in uids if u.strip()]
        if not normalized:
            return 0
        stmt = delete(Profile).where(func.lower(Profile.uid).in_([u.lower() for u in normalized]))
        result = await session.execute(stmt)
        await session.commit()
        count = result.row_count if result.row_count is not None else 0
        await self.reload_cache(session)
        return count

    # -- export ------------------------------------------------------------------

    def export_text(self) -> str:
        """Export all cached profiles as 'uid|token' lines."""
        lines = []
        for uid, profile in self._profiles_by_uid.items():
            token = decrypt(profile.token_enc)
            lines.append(f"{profile.uid}|{token}")
        return "\n".join(lines)

    def export_states(self) -> Dict[str, Dict[str, any]]:
        return {
            profile.uid: {
                "token_status": profile.token_status.value,
                "task_count": profile.task_count,
                "last_error": profile.last_error or "",
            }
            for profile in self._profiles_by_uid.values()
        }

    async def apply_states(self, session: AsyncSession, states: Dict[str, Dict]) -> int:
        """Apply saved states (token_status, task_count, last_error) to cached profiles."""
        applied = 0
        for uid_key, state in states.items():
            uid_lower = uid_key.lower()
            profile = self._profiles_by_uid.get(uid_lower)
            if profile is None:
                continue
            ts = state.get("token_status", "")
            if ts:
                try:
                    profile.token_status = TokenStatus(ts)
                except ValueError:
                    profile.token_status = TokenStatus.NOT_CHECKED
            profile.task_count = state.get("task_count", 0)
            profile.last_error = state.get("last_error", "")
            applied += 1
        if applied > 0:
            await session.commit()
        return applied

    # -- lookup ------------------------------------------------------------------

    async def find_by_uid(self, session: AsyncSession, uid: str) -> Optional[Profile]:
        """Find a profile by UID (case-insensitive), checking cache first then DB."""
        uid_lower = uid.strip().lower()
        profile = self._profiles_by_uid.get(uid_lower)
        if profile is not None:
            return profile
        # cache miss — try DB
        result = await session.execute(
            select(Profile).where(func.lower(Profile.uid) == uid_lower)
        )
        row = result.scalar_one_or_none()
        if row:
            self._profiles_by_uid[uid_lower] = row
        return row

    def list_profiles(self) -> List[Dict]:
        """Return profiles for API response (masked tokens, no raw tokens)."""
        return [
            {
                "uid": p.uid,
                "masked_token": mask(decrypt(p.token_enc)),
                "token_status": p.token_status.value,
                "task_count": p.task_count,
                "last_error": p.last_error or "",
                "created_at": p.created_at.isoformat() if p.created_at else None,
            }
            for p in self._profiles_by_uid.values()
        ]

    # -- block (token issue, in-memory only) -------------------------------------

    def block_profile(self, uid: str, token_issue: Dict[str, any]) -> None:
        """Mark profile as blocked — used during task execution (in-memory only)."""
        uid_lower = uid.strip().lower()
        profile = self._profiles_by_uid.get(uid_lower)
        if profile is not None:
            profile.token_status = _token_issue_to_status(token_issue)
            profile.last_error = token_issue.get("status", "")


def _token_issue_to_status(issue: Dict[str, any]) -> str:
    """Convert a token issue dict to a TokenStatus enum value string."""
    kind = issue.get("kind", "")
    if kind == "Checkpoint":
        return "Checkpoint"
    if kind == "Token out":
        return "Token out"
    return "Die"
