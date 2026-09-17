# Auth 06 — RBAC (Role-Based Access Control)

## Concept

RBAC assigns permissions to roles and roles to users. TeamFlow's model is
per-organization: a user's role in Org A says nothing about Org B. The roles are
`owner > admin > manager > member`, implemented as a **rank integer**, not a
permission matrix.

## Why rank instead of permissions

A permission matrix (Django-style `has_perm("org.change")`) is the right tool
when permissions are combinatorially rich. TeamFlow's rules are strictly
hierarchical — "admin can do everything manager can" — so a total order
expresses them with one comparison:

```python
ROLE_RANK = {
    MembershipRole.MEMBER: 1,
    MembershipRole.MANAGER: 2,
    MembershipRole.ADMIN: 3,
    MembershipRole.OWNER: 4,
}

def role_rank(role: str) -> int:
    return ROLE_RANK.get(role, -1)     # unknown role sorts below everything
```

`-1` for unknown roles is a fail-closed default: garbage in the DB (or a future
role constant added without a rank) cannot accidentally pass `>=` checks.

## The model — `app/models/organization.py`

```python
class MembershipRole:
    """String constants instead of an Enum for simpler DB serialization."""
    OWNER = "owner"
    ADMIN = "admin"
    MANAGER = "manager"
    MEMBER = "member"
    ALL = (OWNER, ADMIN, MANAGER, MEMBER)

class Membership(UUIDMixin, TimeStampedMixin, SQLModel, table=True):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("user_id", "organization_id",
                                       name="uq_membership_user_org"),)
    user_id: uuid.UUID = Field(...)
    organization_id: uuid.UUID = Field(...)
    role: str = Field(sa_column=Column(String(32), nullable=False))
    is_active: bool = Field(sa_column=Column(Boolean, nullable=False))

    user: "User" = Relationship(sa_relationship_kwargs={"lazy": "joined"})
```

Why strings, not a DB enum?

| Approach | TeamFlow choice | Note |
| --- | --- | --- |
| Python `Enum` + SA `Enum` column | string constants | adding a role = no DB migration for the type |
| DB enum type | VARCHAR(32) | migration-free role additions |
| `CheckConstraint` on allowed values | **absent** | honest gap: a typo could store an invalid role; it would fail closed (rank −1) but pollute data |

The comment in the model says "simpler DB serialization" — the trade-off is
accepted and documented.

## How rank rules express themselves

### "At least X"

```python
# app/services/projects.py
def _require_write(membership: Membership) -> None:
    if membership.role == MembershipRole.MEMBER:
        raise PermissionDeniedError("Only managers and above can manage projects")
```

(Direct `== MEMBER` check — the only role below the bar — is equivalent to
`rank < MANAGER` and cheaper to read.)

### "Strictly outranks the target and the granted role"

`app/services/organizations.py`:

```python
if role_rank(actor_membership.role) <= max(role_rank(target.role), role_rank(new_role)):
    raise PermissionDeniedError("Not enough permissions to assign that role")
```

This single line encodes a genuine security invariant: **you cannot create a
peer or a superior**. An admin (3) cannot promote a member to admin (equal), but
can promote to manager (2). A manager (2) cannot promote anyone to admin (3).
Only the owner (4) can mint admins.

### "Invite authority depends on the invited role"

`app/services/invitations.py`:

```python
if data.role == MembershipRole.OWNER:
    raise ValidationFailedError("Cannot invite someone as owner")
if data.role == MembershipRole.ADMIN and role_rank(actor_membership.role) < role_rank(MembershipRole.ADMIN):
    raise PermissionDeniedError("Only admins can invite admins")
```

Invitations are the back door to role assignment; the same outrank discipline
applies there.

### Immutable owner invariants

```python
if target.role == MembershipRole.OWNER:
    raise PermissionDeniedError("The owner's role cannot be changed")
...
if target.role == MembershipRole.OWNER:
    raise PermissionDeniedError("The owner cannot be removed")
```

There is deliberately **no ownership transfer** in scope. The consequence:
an org's owner can never leave or be demoted. As a product decision that's
limiting; as a security/default-correctness decision it prevents an org from
ending up ownerless. Documented as a scope limit.

### Self-actions

```python
if target.user_id == actor.id:
    raise PermissionDeniedError("You cannot change your own role")
```

Prevents both privilege escalation (obviously) and foot-guns (demoting
yourself). Self-removal *is* allowed (`remove_member` has an explicit
`target.user_id != actor.id` branch) — leaving an org must be possible.

## Role change on the wire

```
PATCH /organizations/{slug}/members/{user_id}
{"role": "manager"}
```

The route takes `MembershipUpdate` (`role: RoleLiteral`); everything else
(rank arithmetic, target lookup) is in the service
(`update_member_role`). Tests in `tests/integration/test_organizations_rbac.py`
cover: manager cannot promote to admin, admin can promote to manager, admin
cannot touch owner, self-edit 403, manager cannot demote admin.

## Django/DRF comparison 🔵

| Django | TeamFlow |
| --- | --- |
| `django.contrib.auth` Groups + Permissions (global) | per-org `memberships.role` (row-scoped) |
| `user.has_perm("app.change_thing")` | `role_rank(m.role) >= role_rank(ADMIN)` |
| `IsAdminUser` (global staff flag) | owner/admin checks per org |
| `django-guardian` (object-level perms) | membership row = object-level scope |
| `User.is_superuser` | exists (`is_superuser` column) but **unused in authorization** — deliberate |

⚠️ `is_superuser` exists on `users` but no endpoint consults it. It is a
reserved field for future platform-admin tooling. Do not assume it grants
anything today; a reviewer should flag it as unused rather than a back door.

## Production perspective

- **Role checks are integer comparisons** on data already loaded for the tenant
  gate — zero extra queries.
- **Role changes are immediate**: the next request reads the new row. No token
  re-issue needed (roles are not in JWTs — `auth/03`).
- **Audit trail**: `MEMBER_ROLE_CHANGED` and `MEMBER_REMOVED` rows record old
  and new roles (`meta`), so privilege changes are forensically visible in
  `GET /organizations/{slug}/audit-logs`.
- **Promotion paths are bounded**: only someone strictly above grants a role;
  only owner mints admins. An admin compromise cannot mint another admin.

## Common mistakes

1. **Storing the role in the JWT** — then role changes lag until refresh, and
   revoked roles persist. TeamFlow resolves roles per request.
2. **`>=` vs `>` confusion**: granting a role requires *strict* outrank
   (`<=` fails). Using `>=` in the check silently allows creating peers — a
   classic privilege-escalation bug.
3. **Checking only the target's current role, not the granted role**: "admin
   can demote manager" doesn't imply "admin can promote member to admin". The
   `max(...)` handles both.
4. **Forgetting the self-edit case** — users demoting themselves or, worse,
   promoting themselves via a crafted request.
5. **Permission logic outside the service** — e.g., only in the router — making
   invitation acceptance and direct-add diverge.

## Cheat sheet

```python
ROLE_RANK = {MEMBER: 1, MANAGER: 2, ADMIN: 3, OWNER: 4}
role_rank(r)  # -1 for unknown -> fail closed

# at least:
role_rank(m.role) >= role_rank(ADMIN)
# outrank target AND granted role:
role_rank(actor.role) > max(role_rank(target.role), role_rank(new_role))
# immutable:
target.role == OWNER -> forbid change/removal
target.user_id == actor.id -> forbid self role change
```

## Review questions

1. Why does `role_rank` return `-1` for unknown roles instead of raising?
2. Write the boolean that lets a manager give another member the manager role.
   Now write the one that stops a manager from granting admin.
3. Why are roles stored on the membership row rather than the user?
4. What product limitation comes from "no ownership transfer", and what
   alternative models exist (hint: ownership as a flag, handover flow)?
