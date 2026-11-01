"""Application settings loaded from environment variables and the project .env file."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/core/config.py -> project root is three levels above "app".
PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    # env_ignore_empty: "FONT_PATH=" in .env means "not set", not an empty path or key.
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env", env_file_encoding="utf-8", extra="ignore", env_ignore_empty=True
    )

    app_name: str = "PetMedia AI"
    app_env: str = "development"
    debug: bool = False

    api_host: str = "127.0.0.1"
    api_port: int = 8000
    api_key: SecretStr | None = None
    cors_origins: list[str] = Field(default_factory=list)

    database_url: str = "postgresql+psycopg://petmedia:petmedia@127.0.0.1:5432/petmedia"
    langgraph_database_url: str = "postgresql://petmedia:petmedia@127.0.0.1:5432/petmedia"
    langgraph_schema: str = Field(default="langgraph", pattern=r"^[a-z_][a-z0-9_]*$")

    llm_provider: Literal["mock", "openai_compatible"] = "mock"
    llm_api_key: SecretStr | None = None
    llm_model: str = ""
    llm_base_url: str = "https://api.openai.com/v1"
    llm_timeout_seconds: float = 120
    llm_temperature: float = 0.7
    llm_structured_mode: Literal["json_object", "json_schema"] = "json_object"
    llm_max_structured_retries: int = Field(default=3, ge=1, le=10)
    # Only used by the mock provider: simulates a slow model in crash-recovery tests.
    mock_llm_delay_seconds: float = 0

    image_provider: Literal["mock", "openai_compatible"] = "mock"
    image_api_key: SecretStr | None = None
    image_model: str = ""
    image_base_url: str = "https://api.openai.com/v1"
    image_size: str = Field(default="1024x1536", pattern=r"^\d+x\d+$")
    image_timeout_seconds: float = 180

    storage_root: Path = Path("./storage")
    font_path: Path | None = None

    default_locale: str = "en-US"
    default_target_market: str = "US"
    default_image_count: int = Field(default=4, ge=3, le=5)
    default_topic_count: int = Field(default=5, ge=1, le=10)
    default_target_word_count: int = Field(default=700, ge=100, le=2000)

    worker_poll_interval_seconds: float = 2
    worker_concurrency: int = Field(default=2, ge=1, le=16)
    job_lease_seconds: int = Field(default=60, ge=2)
    job_max_attempts: int = Field(default=3, ge=1)
    max_generation_retries: int = Field(default=3, ge=1, le=10)
    max_copy_auto_fixes: int = Field(default=2, ge=0, le=5)

    max_upload_bytes: int = 10 * 1024 * 1024
    max_image_pixels: int = 40_000_000
    max_output_jpeg_bytes: int = 8_000_000

    log_level: str = "INFO"

    @property
    def resolved_storage_root(self) -> Path:
        root = self.storage_root
        return root if root.is_absolute() else (PROJECT_ROOT / root).resolve()


@lru_cache
def get_settings() -> Settings:
    return Settings()
