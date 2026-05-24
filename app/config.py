"""Application configuration, loaded from environment / .env file.

Using pydantic-settings means every setting is typed and validated at startup.
If a required env var is missing, the app fails fast with a clear error instead
of blowing up later at request time.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # WhatsApp Cloud API
    wa_phone_id: str
    wa_token: str
    wa_verify_token: str
    wa_app_secret: str

    # Anthropic Claude
    anthropic_api_key: str
    claude_model: str = "claude-sonnet-4-6"

    # Database — SQLite by default (zero setup); swap the URL for Postgres in prod.
    database_url: str = "sqlite:///./shopping.db"

    # Message queue.
    #   queue_backend: "redis" (production) or "memory" (zero-dependency local/test)
    #   With "memory", the worker runs in-process inside the web app (single process).
    #   With "redis", run the web app and `python -m app.worker` as separate processes.
    queue_backend: str = "redis"
    redis_url: str = "redis://localhost:6379/0"
    queue_key: str = "shopping:incoming"

    # Misc
    log_level: str = "INFO"


# A single shared instance imported across the app.
settings = Settings()  # type: ignore[call-arg]
