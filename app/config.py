"""Application configuration loaded from environment variables."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings for the API and persistence layer."""

    api_host: str = "127.0.0.1"
    api_port: int = 8000
    api_base_url: str = "http://127.0.0.1:8000"
    database_url: str = "sqlite:///./seireth.db"
    api_key: str | None = None
    sandbox_backend: str = "inmemory"
    docker_runner_image: str = "python:3.12-slim"
    docker_memory: str = "256m"
    docker_cpus: float = 0.5
    docker_pids_limit: int = 64
    docker_timeout_seconds: float = 15
    model_config = SettingsConfigDict(env_prefix="SEIRETH_", env_file=".env")


settings = Settings()
