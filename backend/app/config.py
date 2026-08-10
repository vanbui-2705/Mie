"""Application settings loaded from environment variables."""
from __future__ import annotations

import os
from pathlib import Path

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

    # HMAC secret for session tokens. Read through Settings (not os.environ) so a
    # process configured from .env signs with the same key as the containers.
    FLOWMETA_TOKEN_SECRET: str = ""
    FLOWMETA_DEFAULT_USER: str = "admin"

    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    SCHEDULER_ENABLED: bool = True
    SCHEDULER_INTERVAL_SECONDS: int = 60

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
    TOKEN_REFRESH_THRESHOLD_DAYS: int = 14
    FACEBOOK_OAUTH_REDIRECT_URI: str = "http://localhost:8000/api/facebook/oauth/callback"
    FACEBOOK_OAUTH_SCOPES: str = "pages_show_list,pages_read_engagement,pages_manage_posts"
    FACEBOOK_OAUTH_SUCCESS_URL: str = "http://localhost:3000/accounts"

    # Application sign-in OAuth (separate from Facebook page-management OAuth)
    AUTH_GOOGLE_CLIENT_ID: str = ""
    AUTH_GOOGLE_CLIENT_SECRET: str = ""
    AUTH_GOOGLE_REDIRECT_URI: str = "http://localhost:8000/api/auth/oauth/google/callback"
    AUTH_FACEBOOK_APP_ID: str = ""
    AUTH_FACEBOOK_APP_SECRET: str = ""
    AUTH_FACEBOOK_REDIRECT_URI: str = "http://localhost:8000/api/auth/oauth/facebook/callback"
    AUTH_FRONTEND_CALLBACK_URL: str = "http://localhost:3000/auth/callback"
    PASSWORD_RESET_URL: str = "http://localhost:3000/reset-password"
    EXPOSE_PASSWORD_RESET_TOKEN: bool = False

    # AI APIs
    GEMINI_API_KEY: str = ""
    # Pinned rather than gemini-flash-latest so the JSON contract cannot shift
    # under the scorer without a code change.
    GEMINI_MODEL: str = "gemini-3.5-flash"
    GEMINI_MAX_OUTPUT_TOKENS: int = 8192
    GEMINI_THINKING_LEVEL: str = "minimal"
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "llama3"
    ANTHROPIC_API_KEY: str = ""
    ANTHROPIC_MODEL: str = "claude-opus-5"
    LLM_TIMEOUT_SECONDS: float = 120.0
    # Retry only transient upstream failures. Total attempts are retries + 1.
    LLM_MAX_RETRIES: int = 2
    LLM_RETRY_BASE_SECONDS: float = 0.75

    # Browser worker / personal profile posting
    BROWSER_PROFILE_DIR: str = "/app/browser-profiles"
    UPLOAD_DIR: str = "/app/uploads"
    COMMENT_IMAGE_MAX_BYTES: int = 10 * 1024 * 1024

    # Flow Studio (clip module)
    CLIP_UPLOAD_DIR: str = "/app/uploads/clips"
    CLIP_MAX_UPLOAD_BYTES: int = 4 * 1024 * 1024 * 1024  # 4 GB
    FLOW_PORT: int = 8001

    # SSE fan-out. The process that publishes an event (a worker) is not the
    # process holding the browser's stream (an API), so events are mirrored on
    # Redis pub/sub and each API relays what the others published.
    SSE_REDIS_FANOUT: bool = True
    SSE_REDIS_PREFIX: str = "sse:"

    # Flow Studio retention. The browser is the only thing that wants these
    # files: the page beats every CLIP_HEARTBEAT hint and anything unseen for
    # longer than the grace window is deleted, so a refresh keeps its clips and
    # a closed tab does not fill the disk.
    CLIP_RETENTION_ENABLED: bool = True
    CLIP_SESSION_GRACE_SECONDS: int = 24 * 60 * 60
    CLIP_SWEEP_INTERVAL_SECONDS: int = 60
    CLIP_CANCEL_POLL_SECONDS: int = 10

    # Flow Studio AI pipeline
    ASR_BACKEND: str = "local"          # local | cloud
    ASR_WHISPER_MODEL: str = "small"    # faster-whisper model size or local path
    ASR_COMPUTE_TYPE: str = "int8"
    ASR_CPU_THREADS: int = 8
    ASR_BEAM_SIZE: int = 1
    SCORING_BACKEND: str = "gemini"     # gemini | ollama | claude | heuristic
    CLIP_PREFILTER_MAX_REGIONS: int = 30
    CLIP_PREFILTER_MIN_REGION_SEC: float = 20.0
    CLIP_PREFILTER_MAX_REGION_SEC: float = 90.0
    # Derived from this file, not hard-coded to the container's /app: the same
    # default then resolves for a local run (backend/assets/fonts) and inside the
    # image, so a dev run does not silently fall back to DejaVu.
    CLIP_FONT_DIR: str = str(Path(__file__).resolve().parents[1] / "assets" / "fonts")
    CLIP_SUBTITLE_FONT: str = "Be Vietnam Pro"
    CLIP_PIPELINE_VERSION: str = "ai-v1"
    # Vietnamese voice-over. "edge" needs no key but calls an undocumented
    # Microsoft endpoint, so a failure downgrades to the source audio instead of
    # failing the clip; "none" turns the feature off for the whole deployment.
    TTS_BACKEND: str = "edge"           # edge | none
    TTS_DEFAULT_VOICE: str = "vi-female"
    TTS_TIMEOUT_SECONDS: float = 30.0
    TTS_MAX_RETRIES: int = 1
    TTS_RETRY_BASE_SECONDS: float = 0.5
    # Speech that overruns its cue is sped up, never past this — beyond ~1.6x
    # Vietnamese stops being comfortable to follow.
    TTS_MAX_TEMPO: float = 1.6
    # Gen video. Without a Pexels key every scene falls back to a generated
    # gradient — the feature still works, it just looks plainer.
    PEXELS_API_KEY: str = ""
    STOCK_TIMEOUT_SECONDS: float = 20.0
    GEN_SCENE_PAD_SEC: float = 0.4      # breath after each narration
    GEN_MAX_DURATION_SEC: int = 120
    GEN_MAX_UPLOAD_IMAGES: int = 12
    GEN_MAX_IMAGE_BYTES: int = 15 * 1024 * 1024
    FFMPEG_BIN: str = "ffmpeg"
    FFPROBE_BIN: str = "ffprobe"
    YTDLP_BIN: str = "yt-dlp"

    # --- Flow pipeline resource slots -----------------------------------
    # Work is split by the resource it actually consumes. Before this, a job
    # waiting on the edge-TTS endpoint held the whole pipeline, and so did an
    # ffmpeg burn — one sequential lane for three different kinds of waiting.
    FLOW_CPU_SLOTS: int = 0             # 0 = auto: cores - 1
    FLOW_NET_SLOTS: int = 8
    FLOW_TTS_SLOTS: int = 4             # edge-tts is unofficial; stay polite

    # Cross-module peer endpoints (used only when the peer is up)
    FACE_BASE_URL: str = "http://localhost:8000"
    FLOW_BASE_URL: str = "http://localhost:8001"
    PEER_HEALTH_TIMEOUT_SECONDS: float = 2.0
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
