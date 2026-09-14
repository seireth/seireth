"""Application configuration loaded from environment variables."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings for the API and persistence layer."""

    api_host: str
    api_port: int

    database_url: str = "sqlite:///./seireth.db"

    environment: str
    sandbox_backend: str

    docker_runner_image: str = "python:3.14-slim"
    docker_target_image: str
    docker_allowed_target_images: list[str]

    docker_memory: str = "256m"
    docker_cpus: float = 0.5
    docker_pids_limit: int = 64
    docker_timeout_seconds: float = 15

    model_config = SettingsConfigDict(
        env_prefix="SEIRETH_",
        env_file=".env",
    )

    @property
    def api_base_url(self) -> str:
        """Build the local API URL from the configured host and port."""

        host = self.api_host
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        return f"http://{host}:{self.api_port}"


settings = Settings()
