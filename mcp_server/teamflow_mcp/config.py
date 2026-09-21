"""Environment-driven configuration for the TeamFlow MCP server.

Every setting is read from the environment with a `TEAMFLOW_` prefix, so an
agent can point this server at any TeamFlow deployment without code changes:

    TEAMFLOW_API_URL    http://localhost:8000     # /api/v1 is appended if absent
    TEAMFLOW_EMAIL      you@example.com           # login identity
    TEAMFLOW_PASSWORD   ...                       # login secret
    TEAMFLOW_ORG        my-org                    # optional default org slug
    TEAMFLOW_PROJECT    My Board                  # optional default project name or id
    TEAMFLOW_TIMEOUT    30                        # seconds
    TEAMFLOW_VERIFY_SSL true

A `.env` file in the server's working directory is also honoured, which keeps
secrets out of the agent's config file if you prefer.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="TEAMFLOW_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    api_url: str = "http://localhost:8000"
    email: str = ""
    password: str = ""
    org: str = ""
    project: str = ""
    timeout: float = 30.0
    verify_ssl: bool = True

    @property
    def base_url(self) -> str:
        """Normalised API root; tolerates users passing a bare host URL."""
        url = self.api_url.strip().rstrip("/")
        if not url:
            url = "http://localhost:8000"
        if not url.endswith("/api/v1"):
            url = f"{url}/api/v1"
        return url

    @property
    def credentials_configured(self) -> bool:
        return bool(self.email and self.password)


@lru_cache
def get_settings() -> Settings:
    return Settings()
