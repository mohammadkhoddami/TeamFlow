# Auth 05 — Authorization

## Concept

Authorization decides what an authenticated identity may do. TeamFlow splits it
in two layers:

1. **Tenant access** (can you touch this org's data at all?) — service/dependency
   checks that produce 404 for non-members.
2. **Role authority** (given access, may you perform this action?) — rank checks
   in services that produce 403.

## The 404-vs-403 doctrine

> If revealing the resource's existence would leak tenant data → **404**.
> If the caller is already authorized to know it exists, but lacks rank → **403**.

| Request | Caller | Result |
| --- | --- | --- |
| `GET /tasks/{id}` of another org's task | non-member | 404 (`TaskAccess`) |
| `GET /organizations/{slug}` of another org | non-member | 404 (`get_org_membership`) |
| `PATCH /organizations/{slug}` | member | 403 (`PermissionDeniedError`) |
| `DELETE /organizations/{slug}` | admin | 403 (owner only) |
| `PATCH /tasks/{id}/move` to `done` from `todo` | member | 422 (business rule, not auth) |

This is a design decision, not an accident: non-members learn *nothing*;
members get precise errors.

## Where authorization lives (and why not in routers)

```
Router    → declares dependencies that establish context (who/what org)
Deps      → tenant access ("is this caller in the org that owns this row?")
Service   → role authority ("does this role allow the action?")
```

Evidence from `app/services/organizations.py`:

```python
async def update_organization(db, actor, slug, data, ip=None) -> Organization:
    org, membership = await get_organization_for_user(db, actor, slug)
    if role_rank(membership.role) < role_rank(MembershipRole.ADMIN):
        raise PermissionDeniedError("Only admins and owners can update an organization")
    ...

async def delete_organization(db, actor, slug, ip=None) -> None:
    org, membership = await get_organization_for_user(db, actor, slug)
    if membership.role != MembershipRole.OWNER:
        raise PermissionDeniedError("Only the owner can delete an organization")
```

Why services and not routers?

- **Programmatic callers get the same rules.** `add_member_direct` is called
  from tests and invitation acceptance; both must enforce rank. If the check
  lived in the router, the service would be a hole.
- **One source of truth per rule.** A reviewer reads `app/services/` top to
  bottom and knows every authorization rule.
- **Routers can't be trusted to remember.** A new endpoint that forgets the
  check is a vulnerability; a service that enforces internally cannot be
  bypassed.

## The authorization surface, exhaustively

| Action | Rule | Enforced in |
| --- | --- | --- |
| Read org/members/projects/tasks | any active member | deps + services |
| Update org | admin+ | `organizations.update_organization` |
| Delete org | owner | `organizations.delete_organization` |
| Invite member | manager+; admin only invites admin; nobody invites owner | `invitations.create_invitation` |
| Add member directly | admin+ | `organizations.add_member_direct` |
| Change role | actor strictly outranks target AND granted role; no self-edit; owner immutable | `organizations.update_member_role` |
| Remove member | outrank target, or self-leave; owner never removable | `organizations.remove_member` |
| Create/update project | manager+ | `projects._require_write` |
| Delete project | manager+ | `projects._require_write` |
| Create/update task | any member | (no gate; collaboration policy) |
| Delete task | manager+ or creator | `tasks._can_delete` |
| Manage labels | manager+ | `labels._require_write` |
| Edit/delete comment | author or manager+ | `comments._can_modify` |
| Delete attachment | uploader or manager+ | `attachments.delete_attachment` route |
| Manage webhooks | admin+ | `webhooks._require_admin` |
| Read audit log | admin+ | `routes/audit.py` |
| View dashboard | any member | route |

Read that table as a spec; the code mirrors it one-to-one. Every row is
covered by `tests/integration/test_organizations_rbac.py`,
`test_tasks.py`, `test_projects.py`, `test_attachments.py`.

## Why some checks live in routes

`routes/audit.py` and `routes/attachments.py` do their rank checks inline:

```python
# app/api/routes/audit.py
_org, m = membership
if m.role not in (MembershipRole.ADMIN, MembershipRole.OWNER):
    raise PermissionDeniedError("Only admins and owners can view audit logs")
```

It is the single purpose of those endpoints, there is no reusable service
function, and the check needs no additional query (membership already resolved).
It is a pragmatic exception to the "services own authorization" rule and is
called out here so reviewers treat it as intentional, not drift.

## Defense in depth: layering example

Deleting a task passes three independent gates:

1. `TaskAccess` — non-member → 404 (tenant gate).
2. `_can_delete(membership, task, actor)` — member but neither manager+ nor
   creator → 403 (authority gate).
3. The DB — FK cascade only fires for the row the service actually loaded.

Any one gate failing stops the operation. Attackers must defeat all three, and
a future endpoint reusing `delete_task` inherits gates 2–3 automatically.

## Django/DRF comparison 🔵

| DRF | TeamFlow |
| --- | --- |
| `permission_classes = [IsAdmin]` | `role_rank(membership.role) < rank(ADMIN)` in service |
| `get_queryset()` scoping | repository `get_in_org` + `TaskAccess` dependency |
| Custom object-level permission class | service function (same code path for all callers) |
| `has_object_permission` per action | per-function checks with documented rank matrix |
| 403 for everything | 404 vs 403 doctrine |

DRF centralizes permissions as classes; TeamFlow centralizes them as service
code. Both are "one place", but TeamFlow's version is callable without HTTP —
which is why invitation acceptance (a service path) can reuse `add_member`
rules.

## Production perspective

- **Every role check is one integer comparison** (`ROLE_RANK` dict lookup) —
  authorization adds no queries beyond the membership row already fetched.
- **Monitoring signal**: 404 spikes on foreign IDs suggest probing; 403 spikes
  suggest a client with stale role assumptions. Both are logged with request id.
- **Role changes take effect immediately** for rank checks (server-side lookup
  per request), unlike JWT-embedded roles which would lag until token refresh.
  This is the reason roles are *not* in the token.

## Common mistakes

1. **Checking permissions on the client.** The token says who you are; the
   server decides what you may do. Nothing in TeamFlow request schemas carries a
   role.
2. **Returning 403 for non-members on id-addressed resources** — confirms
   existence; use 404.
3. **Enforcing rank only in the router** — programmatic callers bypass it.
4. **Comparing roles with `==` for "at least" checks** — admin ≠ manager; use
   the rank map. (`role_rank(a) < role_rank(b)` patterns.)
5. **Forgetting self-edit edge cases** — TeamFlow explicitly forbids changing
   your own role and removing the owner.

## Cheat sheet

```python
ROLE_RANK = {MEMBER: 1, MANAGER: 2, ADMIN: 3, OWNER: 4}
def role_rank(role: str) -> int: return ROLE_RANK.get(role, -1)

if role_rank(membership.role) < role_rank(MembershipRole.ADMIN):
    raise PermissionDeniedError("...")

# tenant gate (404):
task, org, membership = task_access      # dependency did the check
```

## Review questions

1. Why does deleting an org require the *exact* owner role while updating it
   accepts admin?
2. A member calls `PATCH /organizations/other-org` (they're not a member) —
   status and code path?
3. Why are role checks in services rather than routers, given TeamFlow's routers
   already resolve membership?
4. Trace the three gates that protect `DELETE /tasks/{id}` and what an attacker
   must bypass for each.
