"""Async TeamFlow REST client with transparent login and token rotation.

The MCP server never touches the database; it is a thin, well-behaved API
consumer. Auth mirrors the OAuth2 password flow used by the web app:

  * `POST /auth/login` (form-encoded) issues a 30-minute access token plus a
    rotating refresh token.
  * Access tokens are refreshed proactively ~60s before expiry.
  * A 401 anywhere drops the token pair and re-authenticates once, which also
    covers tokens revoked server-side (logout, password reset).

Name/UUID resolution helpers keep the agent-facing tools ergonomic: tools accept
human names ("Payments API", "me", "alice@example.com") and the client turns
them into the IDs the API expects, raising actionable errors otherwise.
"""

from __future__ import annotations

import asyncio
import base64
import json
import time
import uuid
from pathlib import Path
from typing import Any, Literal

import httpx
from mcp.server.mcpserver.exceptions import ToolError

from .config import Settings, get_settings, project_env_file, shared_env_file

HttpMethod = Literal["GET", "POST", "PATCH", "DELETE"]
_FALSY_PARAMS = (None, "", False, [], {})


class TeamFlowError(ToolError):
    """An anticipated failure (config, transport, or API error).

    Subclassing `ToolError` matters: the MCP SDK returns the message to the
    model as readable tool-error content. Any other exception type would be
    treated as a crash and surface only "Error executing tool <name>".
    """


def _jwt_expiry(token: str) -> float | None:
    """Read `exp` from a JWT without verifying it (we only need the clock)."""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
        return float(claims["exp"]) if claims.get("exp") else None
    except Exception:
        return None


def _error_from(response: httpx.Response) -> TeamFlowError:
    detail: Any = None
    try:
        payload = response.json()
        if isinstance(payload, dict):
            detail = payload.get("detail")
        elif isinstance(payload, list):
            detail = payload
    except ValueError:
        detail = response.text[:400]

    if isinstance(detail, list):
        parts = []
        for item in detail:
            if isinstance(item, dict):
                loc = ".".join(str(p) for p in item.get("loc", []) if p != "body")
                parts.append(f"{loc}: {item.get('msg')}" if loc else str(item.get("msg")))
            else:
                parts.append(str(item))
        detail = "; ".join(parts)

    message = detail or response.reason_phrase or "request failed"

    if response.status_code == 401:
        hint = " Check TEAMFLOW_EMAIL / TEAMFLOW_PASSWORD."
    elif response.status_code == 403:
        hint = " Your membership role does not allow this action."
    elif response.status_code == 404:
        hint = " Not found, or you are not a member of that organization/project."
    elif response.status_code == 409:
        hint = " Conflicting state (duplicate name, or a task moved concurrently)."
    elif response.status_code == 429:
        hint = " Rate limited - retry in a moment."
    else:
        hint = ""

    return TeamFlowError(f"TeamFlow API {response.status_code}: {message}.{hint}")


def _clean(params: dict[str, Any] | None) -> dict[str, Any] | None:
    if not params:
        return None
    cleaned = {
        key: value
        for key, value in params.items()
        if value not in _FALSY_PARAMS and value is not None
    }
    return cleaned or None


class TeamFlowClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._http = httpx.AsyncClient(
            base_url=self._settings.base_url,
            timeout=httpx.Timeout(self._settings.timeout),
            verify=self._settings.verify_ssl,
            trust_env=self._settings.trust_env,
            headers={"User-Agent": "teamflow-mcp/0.1.0"},
        )
        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._expires_at: float = 0.0
        self._lock = asyncio.Lock()

    @property
    def base_url(self) -> str:
        return self._settings.base_url

    async def aclose(self) -> None:
        await self._http.aclose()

    # ------------------------------------------------------------------ auth

    async def _send(
        self,
        method: HttpMethod,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        json_body: Any = None,
        data: Any = None,
    ) -> httpx.Response:
        try:
            return await self._http.request(
                method,
                path,
                headers=headers,
                params=params,
                json=json_body,
                data=data,
            )
        except httpx.HTTPError as exc:
            raise TeamFlowError(
                f"Cannot reach TeamFlow at {self.base_url}: {exc}"
            ) from exc

    def _store_tokens(self, payload: dict[str, Any]) -> None:
        access = payload.get("access_token")
        if not access:
            raise TeamFlowError("TeamFlow login returned no access token.")
        self._access_token = access
        self._refresh_token = payload.get("refresh_token") or self._refresh_token
        expiry = _jwt_expiry(access)
        # Refresh a minute early; fall back to 25 minutes if `exp` is unreadable.
        self._expires_at = (expiry - 60) if expiry else (time.time() + 25 * 60)

    async def _invalidate_access(self) -> None:
        """Drop the access token but keep the refresh token, so a 401 leads to a
        cheap token rotation rather than a fresh login (logins are rate limited)."""
        async with self._lock:
            self._access_token = None
            self._expires_at = 0.0

    async def login(self) -> None:
        if self._settings.credentials_are_placeholders:
            raise TeamFlowError(
                "TEAMFLOW_EMAIL / TEAMFLOW_PASSWORD are still template placeholders. "
                f"Put your real TeamFlow account in the project env file "
                f"({project_env_file() or 'the project .env'}) and retry."
            )
        if not self._settings.credentials_configured:
            raise TeamFlowError(
                "TEAMFLOW_EMAIL and TEAMFLOW_PASSWORD are not set. Add them to the "
                "project's .env (the workspace this MCP server was launched in), to "
                f"{shared_env_file()}, or to the server's environment. "
                f"Working directory: {Path.cwd()}"
            )
        response = await self._send(
            "POST",
            "/auth/login",
            data={"username": self._settings.email, "password": self._settings.password},
        )
        if response.is_error:
            raise _error_from(response)
        self._store_tokens(response.json())

    async def _refresh(self) -> bool:
        if not self._refresh_token:
            return False
        response = await self._send(
            "POST", "/auth/refresh", json_body={"refresh_token": self._refresh_token}
        )
        if response.is_error:
            return False
        self._store_tokens(response.json())
        return True

    async def _ensure_token(self) -> str:
        # Static API token (M3 #24): no login, no refresh, no rate limits on
        # /auth/login. The token carries its own scopes and expiry.
        if self._settings.token:
            return self._settings.token
        async with self._lock:
            if self._access_token and time.time() < self._expires_at:
                return self._access_token
            if not await self._refresh():
                await self.login()
            if not self._access_token:
                raise TeamFlowError("Authentication failed.")
            return self._access_token

    # --------------------------------------------------------------- request

    async def request(
        self,
        method: HttpMethod,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any = None,
        _retry: bool = True,
    ) -> Any:
        token = await self._ensure_token()
        response = await self._send(
            method,
            path,
            headers={"Authorization": f"Bearer {token}"},
            params=_clean(params),
            json_body=json_body,
        )
        if response.status_code == 401 and _retry:
            await self._invalidate_access()
            return await self.request(
                method, path, params=params, json_body=json_body, _retry=False
            )
        return self._parse(response)

    @staticmethod
    def _parse(response: httpx.Response) -> Any:
        if response.is_error:
            raise _error_from(response)
        if response.status_code == 204 or not response.content:
            return None
        try:
            return response.json()
        except ValueError:
            return response.text

    async def get(self, path: str, **params: Any) -> Any:
        return await self.request("GET", path, params=params or None)

    async def post(self, path: str, body: Any = None) -> Any:
        return await self.request("POST", path, json_body=body)

    async def patch(self, path: str, body: Any) -> Any:
        return await self.request("PATCH", path, json_body=body)

    async def delete(self, path: str) -> Any:
        return await self.request("DELETE", path)

    # ------------------------------------------------------------- resolvers

    async def me(self) -> dict[str, Any]:
        return await self.get("/auth/me")

    async def organizations(self) -> list[dict[str, Any]]:
        return await self.get("/organizations", limit=100) or []

    async def resolve_org_slug(self, org: str | None = None) -> str:
        if org:
            return org
        if self._settings.org:
            return self._settings.org
        listing = await self.organizations()
        if len(listing) == 1:
            return listing[0]["organization"]["slug"]
        if not listing:
            raise TeamFlowError(
                "You are not a member of any organization. Create one in TeamFlow "
                "first, or check the account in TEAMFLOW_EMAIL."
            )
        slugs = ", ".join(item["organization"]["slug"] for item in listing)
        raise TeamFlowError(
            f"TEAMFLOW_ORG is not set and this account belongs to "
            f"{len(listing)} organizations: {slugs}. Pass org_slug explicitly."
        )

    async def org_slug_for_id(self, organization_id: str) -> str:
        for item in await self.organizations():
            if item["organization"]["id"] == organization_id:
                return item["organization"]["slug"]
        raise TeamFlowError(
            "That project belongs to an organization you are not a member of."
        )

    async def resolve_project(
        self, project: str | None = None, org: str | None = None
    ) -> tuple[str, dict[str, Any]]:
        """Return (org_slug, project) for a project name or UUID."""
        ref = (project or self._settings.project or "").strip()
        if not ref:
            raise TeamFlowError(
                "No project specified. Pass `project` (name or UUID) or set "
                "TEAMFLOW_PROJECT in the server environment."
            )

        try:
            uuid.UUID(ref)
            by_id = True
        except (ValueError, TypeError):
            by_id = False

        if by_id:
            data = await self.get(f"/projects/{ref}")
            return await self.org_slug_for_id(data["organization_id"]), data

        slug = await self.resolve_org_slug(org)
        projects = await self.get(f"/organizations/{slug}/projects", limit=100) or []
        needle = ref.casefold()
        matches = [p for p in projects if (p.get("name") or "").casefold() == needle]

        if len(matches) == 1:
            return slug, matches[0]
        if not matches:
            available = ", ".join(sorted(p["name"] for p in projects)) or "none"
            raise TeamFlowError(
                f"No project named '{ref}' in organization '{slug}'. "
                f"Available projects: {available}."
            )
        options = ", ".join(f"{p['name']} ({p['id']})" for p in matches)
        raise TeamFlowError(
            f"Project name '{ref}' matches {len(matches)} projects: {options}. "
            "Pass the project UUID to disambiguate."
        )

    async def resolve_user_id(
        self, assignee: str | None, org: str | None = None
    ) -> str | None:
        """Accept 'me', an email, a full name fragment, or a user UUID."""
        if assignee is None:
            return None
        ref = assignee.strip()
        if not ref:
            return None
        if ref.casefold() in {"me", "@me", "self"}:
            return (await self.me())["id"]

        try:
            return str(uuid.UUID(ref))
        except ValueError:
            pass

        slug = await self.resolve_org_slug(org)
        members = await self.get(f"/organizations/{slug}/members", limit=200) or []
        needle = ref.casefold()

        exact = [
            m
            for m in members
            if (m.get("user") or {}).get("email", "").casefold() == needle
        ]
        if len(exact) == 1:
            return exact[0]["user_id"]

        partial = [
            m
            for m in members
            if needle in (m.get("user") or {}).get("full_name", "").casefold()
        ]
        if len(partial) == 1:
            return partial[0]["user_id"]
        if len(partial) > 1:
            who = ", ".join(
                (m.get("user") or {}).get("email", m["user_id"]) for m in partial
            )
            raise TeamFlowError(
                f"Assignee '{ref}' is ambiguous - matches: {who}. Use an email address."
            )

        who = ", ".join((m.get("user") or {}).get("email", m["user_id"]) for m in members)
        raise TeamFlowError(
            f"No member matches '{ref}' in organization '{slug}'. Members: {who or 'none'}."
        )

    async def resolve_labels(
        self, labels: list[str] | None, org: str | None = None
    ) -> list[str] | None:
        """Map label names (or UUIDs) to label IDs, preserving order."""
        if labels is None:
            return None
        slug = await self.resolve_org_slug(org)
        available = await self.get(f"/organizations/{slug}/labels", limit=200) or []
        by_id = {label["id"]: label for label in available}
        by_name = {label["name"].casefold(): label for label in available}

        resolved: list[str] = []
        for raw in labels:
            ref = raw.strip()
            if ref in by_id:
                resolved.append(ref)
                continue
            match = by_name.get(ref.casefold())
            if match:
                resolved.append(match["id"])
                continue
            names = ", ".join(sorted(label["name"] for label in available)) or "none"
            raise TeamFlowError(
                f"No label named '{raw}' in organization '{slug}'. "
                f"Existing labels: {names}. Create it with create_label first."
            )

        seen: set[str] = set()
        return [i for i in resolved if not (i in seen or seen.add(i))]

    async def resolve_label_id(self, label: str, org: str | None = None) -> str:
        resolved = await self.resolve_labels([label], org)
        return resolved[0] if resolved else ""


_client: TeamFlowClient | None = None


def get_client() -> TeamFlowClient:
    global _client
    if _client is None:
        _client = TeamFlowClient()
    return _client
