"""Graph API router — direct passthrough to Facebook Graph API."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import current_user
from app.rbac import require_permission
from app.crypto import decrypt
from app.db.postgres import get_session
from app.models.sqlmodels import Profile, User
from app.services.facebook_graph import (
    execute_comment_action,
    resolve_author_uid,
)

router = APIRouter(prefix="/api/graph", tags=["graph"])


@router.get("/resolve-author", response_model=dict)
async def resolve_author(
    comment_link: str,
    token: str,
    user: User = Depends(require_permission("facebook_account:read")),
):
    """Resolve author UID from a Facebook comment link via Graph API."""
    try:
        result = await resolve_author_uid(comment_link, token)
        return result
    except RuntimeError as ex:
        raise HTTPException(status_code=400, detail=str(ex))
    except Exception as ex:
        raise HTTPException(status_code=500, detail=str(ex))


@router.post("/edit", response_model=dict)
async def graph_edit(request: dict, user: User = Depends(require_permission("task:create"))):
    try:
        result = await execute_comment_action(
            action="edit",
            comment_link=request["comment_id"],
            token=request["access_token"],
            new_text=request.get("new_text"),
            image_path=request.get("image_path"),
            proxy_url=_build_proxy_url(request),
        )
        return result
    except KeyError as ex:
        raise HTTPException(status_code=400, detail=f"Missing field: {ex}")
    except Exception as ex:
        raise HTTPException(status_code=500, detail=str(ex))


@router.delete("/delete", response_model=dict)
async def graph_delete(
    request: dict,
    user: User = Depends(require_permission("task:create")),
):
    try:
        result = await execute_comment_action(
            action="delete",
            comment_link=request["comment_id"],
            token=request["access_token"],
            proxy_url=_build_proxy_url(request),
        )
        return result
    except KeyError as ex:
        raise HTTPException(status_code=400, detail=f"Missing field: {ex}")
    except Exception as ex:
        raise HTTPException(status_code=500, detail=str(ex))


@router.post("/create", response_model=dict)
async def graph_create(
    request: dict,
    user: User = Depends(require_permission("task:create")),
):
    try:
        result = await execute_comment_action(
            action="new_comment",
            comment_link=request["post_id"],
            token=request["access_token"],
            new_text=request.get("text"),
            image_path=request.get("image_path"),
            proxy_url=_build_proxy_url(request),
        )
        return result
    except KeyError as ex:
        raise HTTPException(status_code=400, detail=f"Missing field: {ex}")
    except Exception as ex:
        raise HTTPException(status_code=500, detail=str(ex))


def _build_proxy_url(request: dict) -> str | None:
    host = request.get("proxy_host", "")
    port = request.get("proxy_port")
    user = request.get("proxy_username")
    pwd = request.get("proxy_password")
    if not host:
        return None
    auth = ""
    if user:
        p = pwd or ""
        auth = f"{user}:{p}@"
    p_str = f":{port}" if port else ""
    return f"http://{auth}{host}{p_str}"
