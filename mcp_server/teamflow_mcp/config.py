"""Environment-driven configuration for the TeamFlow MCP server.

Every setting is read from the environment with a `TEAMFLOW_` prefix, so an
agent can point this server at any TeamFlow deployment without code changes:

    TEAMFLOW_API_URL    http://localhost:8000     # /api/v1 is appended if absent
    TEAMFLOW_TOKEN      tf_...                    # API token (preferred for agents/CI)
    TEAMFLOW_EMAIL      you@example.com           # login identity (fallback)
    TEAMFLOW_PASSWORD   ...                       # login secret (fallback)
    TEAMFLOW_ORG        my-org                    # optional default org slug
    TEAMFLOW_PROJECT    My Board                  # optional default project name or id
    TEAMFLOW_TIMEOUT    30                        # seconds
    TEAMFLOW_VERIFY_SSL true
    TEAMFLOW_TRUST_ENV  true                      # set false to bypass a system proxy

When ``TEAMFLOW_TOKEN`` is set, the server authenticates with the token and
never logs in with a password — create one under *API access* in the web UI
(or ``POST /api/v1/organizations/{slug}/api-tokens``).

Credentials are resolved per project, so one globally registered MCP server can
serve every repository with its own identity. Values for each key come from, in
increasing precedence:

  1. ``~/.config/teamflow/.env``  shared personal defaults (e.g. the API URL)
  2. ``<project>/.env``           the workspace the server was launched in
  3. real environment variables   always win over both files

The project file is discovered as ``<cwd>/.env``, falling back to the nearest
ancestor ``.env`` (up to the git root) that actually defines ``TEAMFLOW_*`` keys
- so a project's unrelated ``.env`` keys (DATABASE_URL, SECRET_KEY, ...) are
ignored rather than mistaken for credentials. ``TEAMFLOW_ENV_FILE`` pins an
explicit path. Nothing here ever logs or returns the password.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_PREFIX = "TEAMFLOW_"
PROJECT_ENV_NAME = ".env"


def shared_env_file() -> Path:
    """User-level defaults shared by every project on this machine."""
    return Path.home() / ".config" / "teamflow" / PROJECT_ENV_NAME


def _defines_teamflow_settings(path: Path) -> bool:
    """True when the file sets at least one TEAMFLOW_* key.

    Guards against treating an unrelated project `.env` (Django, Vite, ...) as
    the credential source, which would also hide a real ancestor file.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(ENV_PREFIX) and "=" in stripped:
            return True
    return False


def _find_git_root(start: Path) -> Path | None:
    for candidate in (start, *start.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def project_env_file(cwd: Path | None = None) -> Path | None:
    """Locate the project-level env file for the current workspace.

    Resolution order:
      1. ``TEAMFLOW_ENV_FILE`` (explicit path, may not exist yet)
      2. ``<cwd>/.env``
      3. nearest ancestor ``.env`` defining TEAMFLOW_* keys, up to the git root
    """
    override = os.environ.get("TEAMFLOW_ENV_FILE", "").strip()
    if override:
        return Path(override).expanduser()

    start = (cwd or Path.cwd()).resolve()
    direct = start / PROJECT_ENV_NAME
    if direct.is_file():
        return direct

    git_root = _find_git_root(start)
    for candidate in (start, *start.parents):
        env_file = candidate / PROJECT_ENV_NAME
        if env_file.is_file() and _defines_teamflow_settings(env_file):
            return env_file
        if git_root is not None and candidate == git_root:
            break
    return None


def env_files(cwd: Path | None = None) -> tuple[Path, ...]:
    """Env files in increasing precedence: shared defaults, then the project."""
    files: list[Path] = []
    shared = shared_env_file()
    if shared.is_file():
        files.append(shared)
    project = project_env_file(cwd)
    if project is not None and project not in files:
        files.append(project)
    return tuple(files)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix=ENV_PREFIX,
        # Fallback for direct ``Settings()`` use outside get_settings(); the
        # discovery logic above supersedes this via the ``_env_file`` argument.
        env_file=PROJECT_ENV_NAME,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    api_url: str = "http://localhost:8000"
    # Personal access token (M3 #24); preferred over email/password for
    # agents, CI and automations.
    token: str = ""
    email: str = ""
    password: str = ""
    org: str = ""
    project: str = ""
    timeout: float = 30.0
    verify_ssl: bool = True
    # Honour HTTP(S)_PROXY / system proxy settings. Set false when the proxy
    # cannot reach the API (typical for a TeamFlow instance on localhost on a
    # machine with a system proxy). Mirrors the API's webhook_httpx_trust_env.
    trust_env: bool = True

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
        return bool(self.token) or bool(self.email and self.password)

    @property
    def credentials_are_placeholders(self) -> bool:
        """Detect an unfilled template so the error is actionable, not a 401."""
        return self.email.startswith("REPLACE_WITH") or self.password.startswith(
            "REPLACE_WITH"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings(_env_file=env_files() or None)


def describe_sources(cwd: Path | None = None) -> dict[str, object]:
    """Non-secret diagnostic: which files/env supplied the configuration."""
    override = os.environ.get("TEAMFLOW_ENV_FILE", "").strip() or None
    project = project_env_file(cwd)
    shared = shared_env_file()
    return {
        "cwd": str((cwd or Path.cwd()).resolve()),
        "project_env_file": str(project) if project else None,
        "project_env_file_exists": bool(project and project.is_file()),
        "shared_env_file": str(shared) if shared.is_file() else None,
        "env_file_override": override,
        "credentials_from_process_env": bool(
            os.environ.get(f"{ENV_PREFIX}EMAIL") or os.environ.get(f"{ENV_PREFIX}PASSWORD")
        ),
    }
