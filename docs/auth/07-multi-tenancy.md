# Auth 07 — Multi-Tenancy

## Concept

Multi-tenancy: one application instance serves many organizations, and no user
of one tenant may read or write another tenant's data. TeamFlow implements
**row-level tenancy with a shared schema**: every tenant-owned row carries
`organization_id`, and every query is filtered by the caller's server-resolved
membership.

## Why this shape

Alternatives, ranked by cost:

| Model | Isolation | Cost |
| --- | --- | --- |
| Database per tenant | strongest | migrations/backups ×N, connection sprawl |
| Schema per tenant | strong | search_path gymnastics, migration ×N |
| **Shared tables + `organization_id`** (chosen) | application-enforced | every query must filter correctly |
| Row Level Security (RLS) in Postgres | DB-enforced backstop | per-connection `SET app.tenant`, ops complexity |

For TeamFlow's scale, shared tables with disciplined filtering is the pragmatic
choice — and the discipline is exactly what a reviewer must verify.

## The three enforcement points

Tenant isolation is not one check; it is three layers:

### 1. The dependency layer — resolve, don't trust

`app/api/deps.py`:

```python
async def get_org_membership(slug, current_user: CurrentUser, db: DB
) -> tuple[Organization, Membership]:
    org = await OrganizationRepository(db).get_by_slug(slug)
    if not org:
        raise NotFoundError("Organization not found")
    membership = await MembershipRepository(db).get_for_user(current_user.id, org.id)
    if not membership or not membership.is_active:
        # 404 (not 403) so non-members cannot even confirm the org exists.
        raise NotFoundError("Organization not found")
    org_id_ctx.set(str(org.id))
    return org, membership
```

Id-addressed resources mirror it (`get_task_access`, `get_project_access`,
`get_attachment_access`, `get_comment_access`, `get_label_access`): load the
row, then check the caller's membership in **the row's** org.

The critical property: **the tenant id always comes from the database**, never
from the client. No request schema in `app/schemas/` accepts
`organization_id`; the only way to reach a resource is through a path/id whose
tenant is resolved server-side.

### 2. The repository layer — org-first queries

```python
# app/repositories/task.py
conds = [Task.organization_id == organization_id, *filters.conditions()]
```

```python
# app/repositories/project.py
async def get_in_org(self, project_id, organization_id) -> Project | None:
    statement = select(Project).where(
        Project.id == project_id,
        Project.organization_id == organization_id,
    )
```

Every list/read method that could span tenants takes `organization_id` as a
required argument. The `_in_org` naming makes an audit mechanical:
`grep -n "def get" app/repositories/*.py` and check each signature.

### 3. The write paths — validated references

Cross-tenant writes are blocked by validating referenced ids:

```python
# app/services/tasks.py — assignee must be an org member
async def _assert_assignee_in_org(db, org_id, assignee_id) -> None:
    membership = await MembershipRepository(db).get_for_user(assignee_id, org_id)
    if not membership or not membership.is_active:
        raise ValidationFailedError("Assignee must be an active member of this organization")

# labels must belong to the same org
async def _resolve_label_ids(db, org_id, label_ids) -> list[uuid.UUID]:
    for label_id in label_ids:
        label = await LabelRepository(db).get_in_org(label_id, org_id)
        if not label:
            raise ValidationFailedError(f"Label {label_id} not found in this organization")
```

Without these, a member could assign a task in their org to a *user from
another org* (confused-deputy data flow) or attach another org's label — the
classic "IDOR through references" bug.

## The IDOR test matrix (what "no leakage" means)

`tests/integration/test_tasks.py::test_task_tenant_isolation_idor` and friends
assert, for a non-member:

| Attack | Expected |
| --- | --- |
| `GET /tasks/{id}` | 404 |
| `PATCH /tasks/{id}` | 404 |
| `DELETE /tasks/{id}` | 404 |
| `GET /tasks/{id}/comments` | 404 |
| `GET /projects/{id}` | 404 |
| `GET /organizations/{slug}` / `/members` / `/tasks` | 404 |
| `DELETE /projects/{id}` | 404 |
| `POST /attachments/{id}/download-url` | 404 |
| WS connect to project | close 4404 |
| `POST /invitations/{id}/accept` (not your email) | 404 |

404 uniformly — the API never distinguishes "doesn't exist" from "not yours".

## Where tenant context surfaces

- **Logging**: `org_id_ctx.set(str(org.id))` in the org dependency
  (`app/api/deps.py`) — every subsequent log line carries the tenant id, making
  cross-tenant incidents traceable.
- **Audit**: every tenant-scoped audit row stores `organization_id`; the admin
  trail is filterable per org.
- **Events**: WS rooms are keyed `project:{id}`; notifications carry
  `organization_id` so clients can route them.
- **Cache**: dashboard keys embed `org_id`
  (`teamflow:cache:dashboard:{org_id}`) — one tenant can never read another's
  cached stats.

## Deletion semantics (a tenant boundary too)

Org deletion is one DB statement; `ON DELETE CASCADE` wipes memberships,
projects, tasks, comments, attachments (rows), labels, links, notifications,
webhooks, audit. Two honest consequences:

1. **Attachment **objects** in S3 are not cascaded** — the rows vanish, the
   bytes remain until a cleanup job catches orphana. The sweeper handles stale
   *pending* uploads only; full orphan reaping on org delete is a known gap
   (`mastery/10-what-i-actually-master.md`).
2. **Audit rows cascade with the org.** For compliance-sensitive systems you'd
   retain audit logs (e.g., `ON DELETE SET NULL` + a separate retention store).
   Documented trade-off, not an accident.

## Django/DRF comparison 🔵

| Django/DRF | TeamFlow |
| --- | --- |
| `get_queryset().filter(tenant=request.tenant)` | org-first repository signatures |
| django-tenants / django-organizations | hand-rolled membership model |
| Middleware setting `request.tenant` | `OrgMembership` dependency |
| `TenantModel.objects` default manager scoping | no manager; explicit `organization_id` args |
| 403 on object permission | 404 doctrine |

Django multi-tenant apps often rely on a tenant middleware + manager chaining;
the danger is identical (a queryset that forgets the tenant filter). TeamFlow's
defense is structural: the query methods *require* the org argument.

## Production perspective

- **RLS as a backstop**: enabling Postgres RLS with a session variable set by
  the connection pool would catch any forgotten filter at the database level.
  It's the strongest possible addition and is listed in
  `production/07-security.md` as the recommended hardening.
- **Cross-tenant cache keys** must embed the tenant (TeamFlow's do). A shared
  cache key across tenants is the multi-tenant version of an IDOR.
- **Incident response**: 404 spikes on foreign ids are logged; audit rows let
  you reconstruct attempts (actor, org they *do* belong to, target id).
- **Rate limits are per user/IP**, not per tenant — a noisy tenant cannot be
  throttled separately in the current design (noted for scale).

## Common mistakes

1. **Accepting `organization_id` in a request body.** Then a client can claim
   any tenant. TeamFlow never does; grep the schemas to confirm.
2. **Filtering in the router only.** Services called from other paths (invites,
   workers) bypass it. Services take `org`/`organization_id` as inputs.
3. **Returning 403 for foreign resources** — existence oracle.
4. **Trusting client-provided `assignee_id`/`label_id` without org checks** —
   IDOR through references; `_assert_assignee_in_org`/`_resolve_label_ids` exist
   precisely for this.
5. **Forgetting the tenant in a new query** — the only real risk left. The
   `_in_org` naming and the review checklist (`mastery/05`) exist to catch it.

## Cheat sheet

```
Tenant id source:  server (membership lookup) — NEVER the client
Dependency:        OrgMembership / TaskAccess / ...
Repository:        methods take organization_id, named *_in_org
Writes:            validate referenced ids belong to the org
Failure mode:      404 everywhere (no existence oracle)
```

## Review questions

1. Name the three enforcement layers and give one concrete code location for
   each.
2. Why is `POST /organizations/{slug}/projects` with a slug the user isn't in
   answered with 404 rather than 403?
3. A member sends `assignee_id` of a user in another org. Which function blocks
   it, and what status does the client see?
4. What are the two tenant-related deletion gaps at org delete time, and how
   would you close each?
