"""Naming-symmetry alias for the Face module app.

Face is the existing app.main:app, left untouched. Run either name:
    uvicorn app.main:app     --port 8000
    uvicorn app.face_app:app --port 8000
"""
from __future__ import annotations

from app.main import app

__all__ = ["app"]
