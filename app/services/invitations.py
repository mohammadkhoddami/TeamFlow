"""Invitation service: create, list, accept/decline, revoke.

Invitations are email-keyed: the invite row carries the target email, and only
a logged-in user with that exact (lowercased) email can accept. This avoids
magic-link tokens while keeping acceptance strictly scoped.
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.exceptions import (
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    ValidationFailedError,
)
from app.models import (
    AuditAction,
    Invitation,
    InvitationStatus,
    Membership,
    MembershipRole,
    User,
)
from app.repositories import (
    InvitationRepository,
    MembershipRepository,
    OrganizationRepository,
    UserRepository,
)
from app.schemas import InvitationCreate
from app.services import audit, events
from app.services.organizations import get_organization_for_user, role_rank


def _is_expired(invitation: Invitation) -> bool:
    return (
        invitation.expires_at is not None
        and invitation.expires_at <= datetime.now(UTC)
    )


async def create_invitation(
    db: AsyncSession,
    actor: User,
    slug: str,
    data: InvitationCreate,
    ip: str | None = None,
) -> Invitation:
    org, actor_membership = await get_organization_for_user(db, actor, slug)
    if role_rank(actor_membership.role) < role_rank(MembershipRole.MANAGER):
        raise PermissionDeniedError("Only managers and above can invite members")
    if data.role == MembershipRole.OWNER:
        raise ValidationFailedError("Cannot invite someone as owner")
    if data.role == MembershipRole.ADMIN and role_rank(actor_membership.role) < role_rank(
        MembershipRole.ADMIN
    ):
        raise PermissionDeniedError("Only admins can invite admins")

    email = data.email.lower()
    user = await UserRepository(db).get_by_email(email)
    if user:
        existing = await MembershipRepository(db).get_for_user(user.id, org.id)
        if existing:
            raise ConflictError("User is already a member of this organization")

    invitation_repo = InvitationRepository(db)
    pending = await invitation_repo.get_pending_for_email(org.id, email)
    if pending is not None:
        if _is_expired(pending):
            # A stale invite must not block a fresh one.
            pending.status = InvitationStatus.EXPIRED
            await invitation_repo.update(pending)
        else:
            raise ConflictError("A pending invitation already exists for this email")

    invitation = await invitation_repo.add(
        Invitation(
            email=email,
            organization_id=org.id,
            role=data.role,
            invited_by_id=actor.id,
            expires_at=datetime.now(UTC)
            + timedelta(days=settings.invitation_ttl_days),
        )
    )
    await audit.log(
        db, AuditAction.INVITATION_CREATED, actor_id=actor.id,
        organization_id=org.id, target_type="invitation", target_id=invitation.id,
        ip=ip, meta={"email": email, "role": data.role},
    )
    if user:
        # In-app notification rides in the same transaction as the invitation.
        await events.notify(
            db,
            user_id=user.id,
            type="invitation",
            title=f"You were invited to {org.name}",
            organization_id=org.id,
            data={"organization_id": str(org.id), "slug": org.slug},
        )
    await db.commit()

    from starlette.concurrency import run_in_threadpool

    from app.workers.celery_app import celery_app

    await run_in_threadpool(
        celery_app.send_task,
        "teamflow.send_email",
        [email, "organization_invite", {"organization": org.name, "role": data.role}],
    )
    return invitation


async def list_org_invitations(
    db: AsyncSession, actor: User, slug: str, *, status: str | None = None
) -> list[Invitation]:
    org, _membership = await get_organization_for_user(db, actor, slug)
    return await InvitationRepository(db).list_for_org(org.id, status=status)


async def list_my_invitations(db: AsyncSession, user: User) -> list[Invitation]:
    return await InvitationRepository(db).list_pending_for_user(user.email)


async def accept_invitation(
    db: AsyncSession, user: User, invitation_id: uuid.UUID, ip: str | None = None
) -> Membership:
    invitation = await InvitationRepository(db).get(invitation_id)
    if not invitation or invitation.email != user.email:
        # 404 hides invitations addressed to other users.
        raise NotFoundError("Invitation not found")
    if invitation.status != InvitationStatus.PENDING:
        raise ValidationFailedError(f"Invitation is {invitation.status}")
    if _is_expired(invitation):
        invitation.status = InvitationStatus.EXPIRED
        await InvitationRepository(db).update(invitation)
        await db.commit()
        raise ValidationFailedError("Invitation has expired")

    org = await OrganizationRepository(db).get(invitation.organization_id)
    if not org or not org.is_active:
        raise NotFoundError("Organization not found")

    membership_repo = MembershipRepository(db)
    if await membership_repo.get_for_user(user.id, org.id):
        raise ConflictError("You are already a member of this organization")

    membership = await membership_repo.add(
        Membership(user_id=user.id, organization_id=org.id, role=invitation.role)
    )
    invitation.status = InvitationStatus.ACCEPTED
    await InvitationRepository(db).update(invitation)
    await audit.log(
        db, AuditAction.INVITATION_ACCEPTED, actor_id=user.id,
        organization_id=org.id, target_type="membership", target_id=membership.id, ip=ip,
    )
    await events.notify_member_joined(db, org.id, user.id, org.name)
    await db.commit()
    await events.dispatch_webhooks(
        db,
        organization_id=org.id,
        event="member.joined",
        data={
            "user_id": str(user.id),
            "email": user.email,
            "role": membership.role,
            "organization_id": str(org.id),
            "organization_slug": org.slug,
        },
    )
    return (
        await db.execute(select(Membership).where(Membership.id == membership.id))
    ).scalar_one()


async def decline_invitation(
    db: AsyncSession, user: User, invitation_id: uuid.UUID, ip: str | None = None
) -> None:
    invitation = await InvitationRepository(db).get(invitation_id)
    if not invitation or invitation.email != user.email:
        raise NotFoundError("Invitation not found")
    if invitation.status != InvitationStatus.PENDING:
        raise ValidationFailedError(f"Invitation is {invitation.status}")
    if _is_expired(invitation):
        invitation.status = InvitationStatus.EXPIRED
        await InvitationRepository(db).update(invitation)
        await db.commit()
        raise ValidationFailedError("Invitation has expired")
    invitation.status = InvitationStatus.DECLINED
    await InvitationRepository(db).update(invitation)
    await audit.log(
        db, AuditAction.INVITATION_DECLINED, actor_id=user.id,
        organization_id=invitation.organization_id,
        target_type="invitation", target_id=invitation.id, ip=ip,
    )
    await db.commit()


async def revoke_invitation(
    db: AsyncSession, actor: User, slug: str, invitation_id: uuid.UUID, ip: str | None = None
) -> None:
    org, membership = await get_organization_for_user(db, actor, slug)
    if role_rank(membership.role) < role_rank(MembershipRole.MANAGER):
        raise PermissionDeniedError("Only managers and above can revoke invitations")
    invitation = await InvitationRepository(db).get(invitation_id)
    if not invitation or invitation.organization_id != org.id:
        raise NotFoundError("Invitation not found")
    if invitation.status != InvitationStatus.PENDING:
        raise ValidationFailedError(f"Invitation is {invitation.status}")
    invitation.status = InvitationStatus.REVOKED
    await InvitationRepository(db).update(invitation)
    await db.commit()
