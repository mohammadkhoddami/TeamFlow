"""Invitation routes: org-side management + invitee-side accept/decline."""

import uuid

from fastapi import APIRouter, Request, status
from sqlmodel import select

from app import services
from app.api.deps import DB, CurrentUser, OrgMembership
from app.models import Organization
from app.schemas import InvitationCreate, InvitationRead, MembershipRead

router = APIRouter(prefix="/invitations", tags=["invitations"])
org_router = APIRouter(prefix="/organizations/{slug}/invitations", tags=["invitations"])


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@org_router.post("", status_code=status.HTTP_201_CREATED, response_model=InvitationRead)
async def create_invitation(
    data: InvitationCreate,
    membership: OrgMembership,
    current_user: CurrentUser,
    request: Request,
    db: DB,
) -> InvitationRead:
    invitation = await services.invitations.create_invitation(
        db, current_user, membership[0].slug, data, ip=_ip(request)
    )
    return InvitationRead.model_validate(invitation).model_copy(
        update={"organization_name": membership[0].name}
    )


@org_router.get("", response_model=list[InvitationRead])
async def list_org_invitations(
    membership: OrgMembership, current_user: CurrentUser, db: DB
) -> list[InvitationRead]:
    invitations = await services.invitations.list_org_invitations(db, current_user, membership[0].slug)
    return [
        InvitationRead.model_validate(i).model_copy(update={"organization_name": membership[0].name})
        for i in invitations
    ]


@org_router.delete("/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_invitation(
    invitation_id: uuid.UUID,
    membership: OrgMembership,
    current_user: CurrentUser,
    request: Request,
    db: DB,
) -> None:
    await services.invitations.revoke_invitation(
        db, current_user, membership[0].slug, invitation_id, ip=_ip(request)
    )


@router.get("/me", response_model=list[InvitationRead])
async def my_invitations(current_user: CurrentUser, db: DB) -> list[InvitationRead]:
    invitations = await services.invitations.list_my_invitations(db, current_user)
    result = []
    for invitation in invitations:
        org_name = (
            await db.execute(
                select(Organization.name).where(Organization.id == invitation.organization_id)
            )
        ).scalar_one()
        result.append(
            InvitationRead.model_validate(invitation).model_copy(
                update={"organization_name": org_name}
            )
        )
    return result


@router.post("/{invitation_id}/accept", response_model=MembershipRead)
async def accept_invitation(
    invitation_id: uuid.UUID, current_user: CurrentUser, request: Request, db: DB
) -> MembershipRead:
    membership = await services.invitations.accept_invitation(
        db, current_user, invitation_id, ip=_ip(request)
    )
    return MembershipRead.model_validate(membership)


@router.post("/{invitation_id}/decline", status_code=status.HTTP_204_NO_CONTENT)
async def decline_invitation(
    invitation_id: uuid.UUID, current_user: CurrentUser, request: Request, db: DB
) -> None:
    await services.invitations.decline_invitation(
        db, current_user, invitation_id, ip=_ip(request)
    )
