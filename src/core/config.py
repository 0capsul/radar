"""Configuration settings for the Reddit Interpreter Monitor."""

import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings

_IGNORE_EXTRA = {"extra": "ignore"}

PROJECT_ROOT = Path(__file__).parent.parent.parent


def _load_env() -> None:
    """Load .env from project root, falling back to working directory."""
    for candidate in [PROJECT_ROOT / ".env", Path(".env")]:
        if candidate.exists():
            load_dotenv(candidate)
            return


_load_env()


DEFAULT_SUBREDDITS = [
    "anonymousinterpreters",
    "spanishinterpreters",
    "interprete_medico",
    "TranslationStudies",
    "medicalinterpreters",
]


class RedditConfig(BaseSettings):
    """Reddit configuration (public JSON endpoints, no API keys needed)."""

    model_config = _IGNORE_EXTRA

    user_agent: str = Field(
        default="reddit-interpreter-monitor:v1.0 (by script)",
        validation_alias="REDDIT_USER_AGENT",
    )


class WebhookConfig(BaseSettings):
    """Webhook configuration."""

    model_config = _IGNORE_EXTRA

    telegram_url: str | None = Field(None, validation_alias="TELEGRAM_WEBHOOK_URL")

    @field_validator("telegram_url")
    @classmethod
    def validate_telegram_url(cls, v: str | None) -> str | None:
        if v and not v.startswith(("http://", "https://")):
            raise ValueError("Telegram webhook URL must be a valid HTTP/HTTPS URL")
        return v


def _load_gemini_api_keys() -> list[str]:
    """Load numbered GEMINI_API_KEY1..N from environment, falling back to GEMINI_API_KEY."""
    keys: list[str] = []
    i = 1
    while key := os.getenv(f"GEMINI_API_KEY{i}"):
        keys.append(key.strip())
        i += 1
    if not keys:
        single_key = os.getenv("GEMINI_API_KEY")
        if single_key:
            keys.append(single_key.strip())
    return keys


class GeminiConfig(BaseSettings):
    """Gemini AI configuration."""

    model_config = _IGNORE_EXTRA

    api_keys: list[str] = Field(default_factory=list)
    model_name: str = Field(
        default="gemini-3-flash-preview", validation_alias="GEMINI_MODEL_NAME"
    )
    base_url: str = Field(
        default="https://generativelanguage.googleapis.com/v1beta/models",
        validation_alias="GEMINI_BASE_URL",
    )
    requests_per_minute: int = Field(
        default=15, validation_alias="GEMINI_REQUESTS_PER_MINUTE"
    )
    timeout: float = Field(default=30.0, validation_alias="GEMINI_TIMEOUT")

    @model_validator(mode="after")
    def populate_api_keys_from_env(self) -> "GeminiConfig":
        if not self.api_keys:
            self.api_keys = _load_gemini_api_keys()
        return self


class MonitoringConfig(BaseSettings):
    """Monitoring configuration."""

    model_config = _IGNORE_EXTRA

    max_posts_per_subreddit: int = Field(
        default=5, validation_alias="MAX_POSTS_PER_SUBREDDIT"
    )
    post_age_limit_minutes: int = Field(
        default=30, validation_alias="POST_AGE_LIMIT_MINUTES"
    )
    min_confidence_score: int = Field(
        default=5, validation_alias="MIN_CONFIDENCE_SCORE"
    )
    min_relevance_score: int = Field(default=5, validation_alias="MIN_RELEVANCE_SCORE")
    subreddits: list[str] = Field(default_factory=lambda: list(DEFAULT_SUBREDDITS))

    @field_validator("max_posts_per_subreddit", "post_age_limit_minutes")
    @classmethod
    def validate_positive_integers(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("Value must be positive")
        return v


class Settings(BaseSettings):
    """Main application settings."""

    model_config = {"case_sensitive": False, "extra": "ignore"}

    reddit: RedditConfig = Field(default_factory=RedditConfig)
    webhook: WebhookConfig = Field(default_factory=WebhookConfig)
    gemini: GeminiConfig = Field(default_factory=GeminiConfig)
    monitoring: MonitoringConfig = Field(default_factory=MonitoringConfig)


_settings: Settings | None = None


def get_settings() -> Settings:
    """Get or create the lazily-initialized global settings instance."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
