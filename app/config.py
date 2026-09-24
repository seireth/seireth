"""Application configuration loaded from environment variables."""

from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings for the API and persistence layer."""

    api_host: str
    api_port: int = Field(ge=1, le=65535)

    database_url: str
    sandbox_backend: Literal["inmemory", "docker"]
    assessment_timeout_seconds: float = Field(default=60, gt=0, allow_inf_nan=False)

    docker_runner_image: str = "python:3.14-slim"
    docker_target_image: str
    docker_allowed_target_images: list[str]

    docker_memory: str = "256m"
    docker_cpus: float = 0.5
    docker_pids_limit: int = 64
    docker_timeout_seconds: float = Field(default=15, gt=0, allow_inf_nan=False)

    model_config = SettingsConfigDict(
        env_prefix="SEIRETH_",
        env_file=".env",
        extra="ignore",  # Compose also reads POSTGRES_* values from this file.
    )

    @field_validator("database_url")
    @classmethod
    def require_postgres(cls, value: str) -> str:
        if not value.startswith("postgresql+psycopg://"):
            raise ValueError("DATABASE_URL must use postgresql+psycopg://")
        return value

    @property
    def api_base_url(self) -> str:
        """Build the local API URL from the configured host and port."""

        host = self.api_host.strip("[]")
        host = {"0.0.0.0": "127.0.0.1", "::": "::1"}.get(host, host)
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        return f"https://{host}:{self.api_port}"


settings = Settings()
