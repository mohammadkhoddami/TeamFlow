"""Plugin routes (M4 ecosystem): directory, install/uninstall, config.

Mutations are admin/owner only; reads are available to any org member. The
signing secret is returned once, at install time.
"""

import uuid

from fastapi import APIRouter, Request, status

from app.api.deps import DB, CurrentUser, OrgMembership
from app.core.exceptions import PermissionDeniedError
from app.models import MembershipRole
from app.schemas.plugin import (
    PluginCreated,
    PluginDirectoryEntry,
    PluginInstall,
    PluginRead,
    PluginUpdate,
)
from app.services import plugins as plugin_service

router = APIRouter(prefix="/organizations/{slug}/plugins", tags=["plugins"])


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _require_admin(membership) -> None:
    if membership.role not in (MembershipRole.ADMIN, MembershipRole.OWNER):
        raise PermissionDeniedError("Only admins and owners can manage plugins")


@router.get("/directory", response_model=list[PluginDirectoryEntry])
async def plugin_directory(membership: OrgMembership, db: DB) -> list[PluginDirectoryEntry]:
    org, _m = membership
    installed = await plugin_service.installed_catalog_ids(db, org.id)
    return [
        PluginDirectoryEntry(**entry, installed=entry["id"] in installed)
        for entry in plugin_service.DIRECTORY
    ]


@router.get("", response_model=list[PluginRead])
async def list_plugins(membership: OrgMembership, db: DB) -> list[PluginRead]:
    org, _m = membership
    plugins = await plugin_service.list_plugins(db, org.id)
    return [PluginRead.model_validate(plugin) for plugin in plugins]


@router.post("", status_code=status.HTTP_201_CREATED, response_model=PluginCreated)
async def install_plugin(
    data: PluginInstall,
    membership: OrgMembership,
    current_user: CurrentUser,
    request: Request,
    db: DB,
) -> PluginCreated:
    org, m = membership
    _require_admin(m)
    plugin, secret = await plugin_service.install(
        db,
        current_user,
        org,
        catalog_id=data.catalog_id,
        manifest=data.manifest,
        webhook_url=data.webhook_url,
        events=data.events,
        name=data.name,
        description=data.description,
        ip=_ip(request),
    )
    payload = PluginCreated(**PluginRead.model_validate(plugin).model_dump())
    payload.secret = secret
    return payload


@router.patch("/{plugin_id}", response_model=PluginRead)
async def update_plugin(
    plugin_id: uuid.UUID,
    data: PluginUpdate,
    membership: OrgMembership,
    current_user: CurrentUser,
    request: Request,
    db: DB,
) -> PluginRead:
    org, m = membership
    _require_admin(m)
    plugin = await plugin_service.get_plugin_for_org(db, plugin_id, org.id)
    updated = await plugin_service.update_plugin(
        db,
        current_user,
        org,
        plugin,
        name=data.name,
        description=data.description,
        webhook_url=data.webhook_url,
        events=data.events,
        is_active=data.is_active,
        ip=_ip(request),
    )
    return PluginRead.model_validate(updated)


@router.delete("/{plugin_id}", status_code=status.HTTP_204_NO_CONTENT)
async def uninstall_plugin(
    plugin_id: uuid.UUID,
    membership: OrgMembership,
    current_user: CurrentUser,
    request: Request,
    db: DB,
) -> None:
    org, m = membership
    _require_admin(m)
    plugin = await plugin_service.get_plugin_for_org(db, plugin_id, org.id)
    await plugin_service.uninstall(db, current_user, org, plugin, ip=_ip(request))
