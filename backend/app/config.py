"""Application settings loaded from environment variables."""
from __future__ import annotations

import os
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_NAME: str = "FlowMeta API"
    APP_VERSION: str = "1.0.0"

    # CORS
    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:5173"

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://flowmeta:flowmeta@localhost:5432/flowmeta"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # Encryption key for Fernet (sensitive fields in DB)
    FERNET_KEY: str = ""

    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # Defaults (overridden by app_settings table)
    USES_PER_PROXY_DEFAULT: int = 4
    PROXY_CHECK_INTERVAL_DEFAULT: int = 5
    INTERACTION_THREADS_DEFAULT: int = 5
    POSTS_PER_UID_DEFAULT: int = 1
    DELAY_MIN_DEFAULT: int = 0
    DELAY_MAX_DEFAULT: int = 0
    DELAY_EVERY_ROUNDS_DEFAULT: int = 1

    # Graph API
    GRAPH_API_VERSION: str = "v19.0"
    GRAPH_API_BASE: str = "https://graph.facebook.com/v19.0"
    META_APP_ID: str = ""
    META_APP_SECRET: str = ""
    AUTO_EXCHANGE_LONG_LIVED_TOKEN: bool = True

    # Browser worker / personal profile posting
    BROWSER_PROFILE_DIR: str = "/app/browser-profiles"
    UPLOAD_DIR: str = "/app/uploads"
    BROWSER_WORKER_CONCURRENCY: int = 1
    BROWSER_PROVIDER: str = "kasm"
    BROWSERLESS_WS_URL: str = ""
    BROWSER_SESSION_TTL_SECONDS: int = 1800
    MAX_BROWSER_SESSIONS_PER_USER: int = 1
    MAX_BROWSER_SESSIONS_GLOBAL: int = 10
    REMOTE_BROWSER_PUBLIC_BASE_URL: str = "http://localhost:8000"
    KASM_IMAGE: str = "kasmweb/chrome:1.19.0"
    KASM_DOCKER_NETWORK: str = "comment_edit_delete_default"
    KASM_BROWSER_PROFILES_VOLUME: str = "comment_edit_delete_browser-profiles"
    KASM_PUBLIC_SCHEME: str = "https"
    KASM_PUBLIC_HOST: str = "localhost"
    KASM_VNC_PASSWORD: str = "flowmeta-session"
    KASM_EMBED_CREDENTIALS_IN_URL: bool = True
    KASM_CONTAINER_LABEL: str = "flowmeta.browser_session"
    REMOTE_BROWSER_BASE_URL: str = ""
    REMOTE_BROWSER_URL_TEMPLATE: str = ""

    # KiotProxy URL templates
    KIOT_NEW_URL: str = "https://api.kiotproxy.com/api/v1/proxies/new?key={apiKey}"
    KIOT_CURRENT_URL: str = "https://api.kiotproxy.com/api/v1/proxies/current?key={apiKey}"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


settings = Settings()
