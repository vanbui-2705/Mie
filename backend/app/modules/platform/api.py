"""Public HTTP routers owned by the platform module."""

from app.routers import health
from app.routers import settings as settings_router

__all__ = ["health", "settings_router"]

