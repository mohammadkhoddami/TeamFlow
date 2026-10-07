"""Project/task templates: built-ins, snapshots and one-click project creation."""

import uuid

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, PermissionDeniedError
from app.models import (
    Board,
    Membership,
    MembershipRole,
    Organization,
    Project,
    ProjectTemplate,
    Task,
    TaskStatus,
    TaskTemplate,
    User,
)
from app.repositories import (
    BoardRepository,
    CustomFieldRepository,
    LabelRepository,
    ProjectRepository,
    ProjectTemplateRepository,
    TaskRepository,
    TaskTemplateRepository,
    WorkflowStatusRepository,
)
from app.schemas import (
    CustomFieldCreate,
    LabelCreate,
    ProjectCreate,
    ProjectFromTemplate,
    SaveProjectTemplate,
    TaskCreate,
    TaskFromTemplate,
    TaskTemplateCreate,
    WorkflowStatusCreate,
    WorkflowUpdate,
)
from app.services import custom_fields as custom_field_service
from app.services import labels as label_service
from app.services import projects as project_service
from app.services import tasks as task_service
from app.services import workflows

BUILTIN_TEMPLATES: dict[str, dict] = {
    "builtin:scrum": {
        "name": "Scrum",
        "description": "Two-week sprints with the classic four-column workflow, feature/bug labels and a sample hierarchy.",
        "config": {
            "workflow": [
                {"key": "todo", "name": "To do", "category": TaskStatus.TODO,
                 "transitions": ["in_progress"], "wip_limit": None},
                {"key": "in_progress", "name": "In progress", "category": TaskStatus.IN_PROGRESS,
                 "transitions": ["todo", "in_review"], "wip_limit": None},
                {"key": "in_review", "name": "In review", "category": TaskStatus.IN_REVIEW,
                 "transitions": ["in_progress", "done"], "wip_limit": None},
                {"key": "done", "name": "Done", "category": TaskStatus.DONE,
                 "transitions": ["in_progress"], "wip_limit": None},
            ],
            "labels": [
                {"name": "feature", "color": "#3B82F6"},
                {"name": "bug", "color": "#EF4444"},
                {"name": "tech-debt", "color": "#8B5CF6"},
            ],
            "hierarchy": [
                {"type": "epic", "title": "First epic", "children": [
                    {"type": "story", "title": "First story", "children": [
                        {"type": "task", "title": "First task"},
                    ]},
                ]},
            ],
        },
    },
    "builtin:kanban": {
        "name": "Kanban",
        "description": "Continuous flow with To do / In progress / Done and WIP limits on work in progress.",
        "config": {
            "workflow": [
                {"key": "todo", "name": "To do", "category": TaskStatus.TODO,
                 "transitions": ["in_progress"], "wip_limit": None},
                {"key": "in_progress", "name": "In progress", "category": TaskStatus.IN_PROGRESS,
                 "transitions": ["todo", "done"], "wip_limit": 5},
                {"key": "done", "name": "Done", "category": TaskStatus.DONE,
                 "transitions": ["in_progress"], "wip_limit": None},
            ],
            "labels": [
                {"name": "expedite", "color": "#F59E0B"},
                {"name": "standard", "color": "#64748B"},
            ],
            "hierarchy": [],
        },
    },
    "builtin:bug-triage": {
        "name": "Bug triage",
        "description": "Triage flow: New / Triaged / Fixing / Verified with bug labels.",
        "config": {
            "workflow": [
                {"key": "new", "name": "New", "category": TaskStatus.TODO,
                 "transitions": ["triaged", "wont_fix"], "wip_limit": None},
                {"key": "triaged", "name": "Triaged", "category": TaskStatus.TODO,
                 "transitions": ["fixing", "wont_fix"], "wip_limit": None},
                {"key": "fixing", "name": "Fixing", "category": TaskStatus.IN_PROGRESS,
                 "transitions": ["verified", "triaged"], "wip_limit": 10},
                {"key": "verified", "name": "Verified", "category": TaskStatus.DONE,
                 "transitions": ["fixing"], "wip_limit": None},
                {"key": "wont_fix", "name": "Won't fix", "category": TaskStatus.DONE,
                 "transitions": ["triaged"], "wip_limit": None},
            ],
            "labels": [
                {"name": "bug", "color": "#EF4444"},
                {"name": "regression", "color": "#F97316"},
                {"name": "needs-info", "color": "#64748B"},
            ],
            "hierarchy": [
                {"type": "epic", "title": "Bugs", "children": []},
            ],
        },
    },
}


def _require_manage(membership: Membership) -> None:
    if membership.role == MembershipRole.MEMBER:
        raise PermissionDeniedError("Only managers and above can manage templates")


async def list_project_templates(
    db: AsyncSession, org_id: uuid.UUID
) -> list[dict]:
    builtins = [
        {
            "id": key,
            "name": value["name"],
            "description": value["description"],
            "is_builtin": True,
            "project_id": None,
        }
        for key, value in BUILTIN_TEMPLATES.items()
    ]
    custom = [
        {
            "id": str(template.id),
            "name": template.name,
            "description": template.description,
            "is_builtin": False,
            "project_id": None,
        }
        for template in await ProjectTemplateRepository(db).list_for_org(org_id)
    ]
    return builtins + custom


async def _apply_config(
    db: AsyncSession,
    actor: User,
    org: Organization,
    project: Project,
    membership: Membership,
    config: dict,
) -> None:
    workflow_entries = config.get("workflow") or []
    if workflow_entries:
        await workflows.save_workflow(
            db,
            actor,
            org,
            project,
            membership,
            WorkflowUpdate(
                statuses=[
                    WorkflowStatusCreate(
                        key=entry["key"],
                        name=entry["name"],
                        category=entry["category"],
                        transitions=entry.get("transitions") or [],
                        wip_limit=entry.get("wip_limit"),
                    )
                    for entry in workflow_entries
                ],
                wip_enforced=False,
            ),
        )

    label_ids: dict[str, uuid.UUID] = {}
    label_repo = LabelRepository(db)
    for entry in config.get("labels") or []:
        existing = await label_repo.get_by_name(org.id, entry["name"])
        if existing:
            label_ids[entry["name"]] = existing.id
            continue
        label = await label_service.create_label(
            db, actor, org, membership, LabelCreate(name=entry["name"], color=entry.get("color"))
        )
        label_ids[entry["name"]] = label.id

    for field_config in config.get("custom_fields") or []:
        await custom_field_service.create_field(
            db,
            actor,
            org,
            project,
            membership,
            CustomFieldCreate(
                name=field_config["name"],
                key=field_config.get("key"),
                field_type=field_config["field_type"],
                options=field_config.get("options") or [],
                is_required=bool(field_config.get("is_required")),
            ),
        )

    for board_config in config.get("boards") or []:
        board = Board(
            organization_id=org.id,
            project_id=project.id,
            name=board_config.get("name", "Board"),
            is_default=bool(board_config.get("is_default")),
            swimlane_by=board_config.get("swimlane_by", "none"),
            filter_query=board_config.get("filter_query"),
            columns=board_config.get("columns"),
            created_by_id=actor.id,
        )
        db.add(board)
    await db.flush()

    async def create_nodes(nodes: list[dict], parent_id: uuid.UUID | None) -> None:
        for node in nodes:
            task = await task_service.create_task(
                db,
                actor,
                org,
                project,
                TaskCreate(
                    title=node["title"],
                    type=node.get("type", "task"),
                    parent_id=parent_id,
                ),
            )
            await create_nodes(node.get("children") or [], task.id)

    await create_nodes(config.get("hierarchy") or [], None)


async def create_project_from_template(
    db: AsyncSession,
    actor: User,
    org: Organization,
    membership: Membership,
    data: ProjectFromTemplate,
    ip: str | None = None,
) -> Project:
    _require_manage(membership)
    if data.template_id in BUILTIN_TEMPLATES:
        template_name = BUILTIN_TEMPLATES[data.template_id]["name"]
        config = BUILTIN_TEMPLATES[data.template_id]["config"]
    else:
        try:
            template_uuid = uuid.UUID(data.template_id)
        except ValueError:
            raise NotFoundError("Template not found") from None
        template = await ProjectTemplateRepository(db).get_in_org(template_uuid, org.id)
        if template is None:
            raise NotFoundError("Template not found")
        template_name = template.name
        config = template.config

    project = await project_service.create_project(
        db,
        actor,
        org,
        membership,
        ProjectCreate(
            name=data.name,
            description=data.description or f"Created from the '{template_name}' template",
            key=data.key,
        ),
        ip=ip,
    )
    await _apply_config(db, actor, org, project, membership, config)
    return project


async def save_project_as_template(
    db: AsyncSession,
    actor: User,
    org: Organization,
    project: Project,
    membership: Membership,
    data: SaveProjectTemplate,
) -> ProjectTemplate:
    _require_manage(membership)
    repo = ProjectTemplateRepository(db)
    if await repo.get_by_name(org.id, data.name):
        raise ConflictError("A project template with this name already exists")

    workflow_rows = await WorkflowStatusRepository(db).list_for_project(project.id)
    if workflow_rows:
        workflow_config = [
            {
                "key": row.key,
                "name": row.name,
                "category": row.category,
                "transitions": row.transitions,
                "wip_limit": row.wip_limit,
            }
            for row in workflow_rows
        ]
    else:
        workflow_config = [
            {
                "key": row.key,
                "name": row.name,
                "category": row.category,
                "transitions": row.transitions,
                "wip_limit": row.wip_limit,
            }
            for row in workflows.default_workflow()
        ]
    labels_config = [
        {"name": label.name, "color": label.color}
        for label in await LabelRepository(db).list_for_org(org.id, limit=500)
    ]
    fields_config = [
        {
            "name": field.name,
            "key": field.key,
            "field_type": field.field_type,
            "options": field.options,
            "is_required": field.is_required,
        }
        for field in await CustomFieldRepository(db).list_for_project(project.id)
    ]
    boards_config = [
        {
            "name": board.name,
            "is_default": board.is_default,
            "swimlane_by": board.swimlane_by,
            "filter_query": board.filter_query,
            "columns": board.columns,
        }
        for board in await BoardRepository(db).list_for_project(org.id, project.id)
    ]
    tasks = await TaskRepository(db).list_for_project(org.id, project.id)
    children: dict[uuid.UUID | None, list[Task]] = {}
    for task in tasks:
        children.setdefault(task.parent_id, []).append(task)

    def serialize_nodes(parent_id: uuid.UUID | None, depth: int = 0) -> list[dict]:
        if depth > 4:
            return []
        return [
            {
                "type": task.type,
                "title": task.title,
                "children": serialize_nodes(task.id, depth + 1),
            }
            for task in children.get(parent_id, [])
        ]

    config = {
        "workflow": workflow_config,
        "labels": labels_config,
        "custom_fields": fields_config,
        "boards": boards_config,
        "hierarchy": serialize_nodes(None),
    }
    template = await repo.add(
        ProjectTemplate(
            organization_id=org.id,
            name=data.name,
            description=data.description,
            config=config,
            created_by_id=actor.id,
        )
    )
    await db.commit()
    return template


async def delete_project_template(
    db: AsyncSession, actor: User, org: Organization, membership: Membership, template: ProjectTemplate
) -> None:
    _require_manage(membership)
    await ProjectTemplateRepository(db).delete(template)
    await db.commit()


async def get_project_template_for_org(
    db: AsyncSession, template_id: uuid.UUID, org_id: uuid.UUID
) -> ProjectTemplate:
    template = await ProjectTemplateRepository(db).get_in_org(template_id, org_id)
    if not template:
        raise NotFoundError("Template not found")
    return template


# ------------------------------------------------------------- task templates


async def list_task_templates(
    db: AsyncSession, org_id: uuid.UUID, project_id: uuid.UUID | None = None
) -> list[TaskTemplate]:
    return await TaskTemplateRepository(db).list_for_org(org_id, project_id)


async def create_task_template(
    db: AsyncSession,
    actor: User,
    org: Organization,
    membership: Membership,
    data: TaskTemplateCreate,
) -> TaskTemplate:
    _require_manage(membership)
    repo = TaskTemplateRepository(db)
    if await repo.get_by_name(org.id, data.name):
        raise ConflictError("A task template with this name already exists")
    template = await repo.add(
        TaskTemplate(
            organization_id=org.id,
            project_id=data.project_id,
            name=data.name,
            title=data.title,
            description=data.description,
            priority=data.priority,
            type=data.type,
            estimate=data.estimate,
            label_ids=[str(label_id) for label_id in data.label_ids],
            checklist=list(data.checklist),
        )
    )
    await db.commit()
    return template


async def delete_task_template(
    db: AsyncSession, actor: User, org: Organization, membership: Membership, template: TaskTemplate
) -> None:
    _require_manage(membership)
    await TaskTemplateRepository(db).delete(template)
    await db.commit()


async def get_task_template_for_org(
    db: AsyncSession, template_id: uuid.UUID, org_id: uuid.UUID
) -> TaskTemplate:
    template = await TaskTemplateRepository(db).get_in_org(template_id, org_id)
    if not template:
        raise NotFoundError("Task template not found")
    return template


async def apply_task_template(
    db: AsyncSession,
    actor: User,
    org: Organization,
    membership: Membership,
    template: TaskTemplate,
    data: TaskFromTemplate,
    ip: str | None = None,
) -> Task:
    project = await ProjectRepository(db).get_in_org(data.project_id, org.id)
    if project is None:
        raise NotFoundError("Project not found")
    task = await task_service.create_task(
        db,
        actor,
        org,
        project,
        TaskCreate(
            title=template.title,
            description=template.description,
            priority=template.priority,
            type=template.type,
            estimate=template.estimate,
            parent_id=data.parent_id,
            label_ids=[uuid.UUID(str(label_id)) for label_id in template.label_ids],
            checklist=list(template.checklist),
        ),
        ip=ip,
    )
    return task
