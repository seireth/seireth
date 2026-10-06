"""Application configuration loaded from environment variables."""

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .constraints import TargetImage


class Settings(BaseSettings):
    """Runtime settings for the API and persistence layer."""

    api_host: str
    api_port: int = Field(ge=1, le=65535)

    database_url: str = Field(pattern=r"^postgresql\+psycopg://")
    sandbox_backend: Literal["inmemory", "docker"]
    assessment_timeout_seconds: float = Field(default=60, gt=0, allow_inf_nan=False)

    docker_runner_image: TargetImage = "python:3.14-slim"

    docker_memory: str = "256m"
    docker_cpus: float = Field(default=0.5, gt=0, allow_inf_nan=False)
    docker_pids_limit: int = Field(default=64, gt=0)
    docker_timeout_seconds: float = Field(default=15, gt=0, allow_inf_nan=False)

    model_config = SettingsConfigDict(
        env_prefix="SEIRETH_",
        env_file=".env",
        extra="ignore",  # Compose also reads POSTGRES_* values from this file.
    )

    @property
    def api_base_url(self) -> str:
        """Build the local API URL used by verification."""

        host = self.api_host.strip("[]")
        host = {"0.0.0.0": "127.0.0.1", "::": "::1"}.get(host, host)
        if ":" in host:
            host = f"[{host}]"

        # Matches the development server, which does not configure TLS.
        return f"http://{host}:{self.api_port}"


settings = Settings()
