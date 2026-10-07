"""Agile reports: burndown, velocity, cumulative flow, cycle/lead time and
sprint reports.

Burndown/velocity/sprint reports derive from task timestamps
(`created_at`, `completed_at`) and estimates; cumulative flow and cycle time
use `TaskStatusHistory` when present and fall back to created/completed
timestamps for pre-M2 data.
"""

import csv
import io
import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.csv_utils import csv_safe
from app.core.exceptions import NotFoundError
from app.models import Sprint, Task, TaskStatus, TaskStatusHistory
from app.repositories import SprintRepository, TaskStatusHistoryRepository

MAX_DAYS = 90


def _points(task: Task) -> float:
    return float(task.estimate or 0)


def _day_end(day: date) -> datetime:
    return datetime.combine(day, datetime.max.time(), tzinfo=UTC)


def _day_start(day: date) -> datetime:
    return datetime.combine(day, datetime.min.time(), tzinfo=UTC)


def _quantile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


async def _project_tasks(db: AsyncSession, project_id: uuid.UUID) -> list[Task]:
    statement = (
        select(Task)
        .where(Task.project_id == project_id, Task.archived_at.is_(None))
        .limit(5000)
    )
    return list((await db.execute(statement)).scalars().all())


async def burndown(db: AsyncSession, sprint: Sprint) -> dict:
    tasks = [
        task
        for task in await _project_tasks(db, sprint.project_id)
        if task.sprint_id == sprint.id
    ]
    total_points = sum(_points(task) for task in tasks)
    total_tasks = len(tasks)

    start = (sprint.start_date or min((t.created_at for t in tasks), default=datetime.now(UTC)))
    end = sprint.end_date or datetime.now(UTC)
    start_day = start.date()
    end_day = max(end.date(), start_day)
    span = min((end_day - start_day).days, MAX_DAYS)
    days = [start_day + timedelta(days=offset) for offset in range(span + 1)]

    points: list[dict] = []
    for index, day in enumerate(days):
        cutoff = _day_end(day)
        remaining = [
            task
            for task in tasks
            if task.created_at <= cutoff
            and not (
                task.completed_at is not None and task.completed_at <= cutoff
            )
        ]
        ideal = None
        if len(days) > 1:
            ideal = total_points * (1 - index / (len(days) - 1))
        points.append(
            {
                "day": day,
                "remaining_points": sum(_points(task) for task in remaining),
                "remaining_tasks": len(remaining),
                "ideal_points": ideal,
            }
        )
    return {
        "sprint_id": sprint.id,
        "sprint_name": sprint.name,
        "start_date": sprint.start_date,
        "end_date": sprint.end_date,
        "total_points": total_points,
        "total_tasks": total_tasks,
        "points": points,
    }


async def velocity(
    db: AsyncSession, org_id: uuid.UUID, project_id: uuid.UUID, limit: int = 6
) -> dict:
    sprints = await SprintRepository(db).list_for_project(org_id, project_id)
    relevant = [sprint for sprint in sprints if sprint.state != "planned"][:limit]
    relevant = list(reversed(relevant))
    tasks = await _project_tasks(db, project_id)

    points: list[dict] = []
    completed_totals: list[float] = []
    for sprint in relevant:
        sprint_tasks = [task for task in tasks if task.sprint_id == sprint.id]
        committed_points = sum(_points(task) for task in sprint_tasks)
        done_tasks = [
            task for task in sprint_tasks if task.status_category == TaskStatus.DONE
        ]
        completed_points = sum(_points(task) for task in done_tasks)
        if sprint.state == "completed":
            completed_totals.append(completed_points)
        points.append(
            {
                "sprint_id": sprint.id,
                "sprint_name": sprint.name,
                "start_date": sprint.start_date,
                "end_date": sprint.end_date,
                "committed_points": committed_points,
                "completed_points": completed_points,
                "committed_tasks": len(sprint_tasks),
                "completed_tasks": len(done_tasks),
            }
        )
    average = (
        sum(completed_totals) / len(completed_totals) if completed_totals else 0.0
    )
    return {
        "project_id": project_id,
        "average_completed_points": round(average, 2),
        "sprints": points,
    }


async def cumulative_flow(
    db: AsyncSession, project_id: uuid.UUID, days: int = 30
) -> dict:
    days = max(1, min(days, MAX_DAYS))
    today = datetime.now(UTC).date()
    start_day = today - timedelta(days=days - 1)
    tasks = await _project_tasks(db, project_id)
    task_ids = [task.id for task in tasks]
    history = await TaskStatusHistoryRepository(db).list_for_tasks(task_ids)
    by_task: dict[uuid.UUID, list[TaskStatusHistory]] = {}
    for entry in history:
        by_task.setdefault(entry.task_id, []).append(entry)

    points: list[dict] = []
    for offset in range(days):
        day = start_day + timedelta(days=offset)
        cutoff = _day_end(day)
        counts = {"todo": 0, "in_progress": 0, "in_review": 0, "done": 0}
        for task in tasks:
            if task.created_at > cutoff:
                continue
            if task.completed_at is not None and task.completed_at <= cutoff:
                counts["done"] += 1
                continue
            category = None
            for entry in by_task.get(task.id, []):
                if entry.changed_at <= cutoff:
                    category = entry.to_category
                else:
                    break
            if category is None:
                # No history yet: infer from created/completed timestamps.
                category = (
                    task.status_category
                    if task.status_category in counts
                    else "in_progress"
                )
            counts[category] = counts.get(category, 0) + 1
        points.append({"day": day, **counts})
    return {"project_id": project_id, "days": days, "points": points}


async def cycle_time(
    db: AsyncSession, project_id: uuid.UUID, days: int = 30
) -> dict:
    days = max(1, min(days, MAX_DAYS))
    cutoff = datetime.now(UTC) - timedelta(days=days)
    tasks = [
        task
        for task in await _project_tasks(db, project_id)
        if task.status_category == TaskStatus.DONE
        and task.completed_at is not None
        and task.completed_at >= cutoff
    ]
    history = await TaskStatusHistoryRepository(db).list_for_tasks(
        [task.id for task in tasks]
    )
    started: dict[uuid.UUID, datetime] = {}
    for entry in history:
        if entry.to_category in (TaskStatus.IN_PROGRESS, TaskStatus.IN_REVIEW):
            started.setdefault(entry.task_id, entry.changed_at)

    items: list[dict] = []
    lead_values: list[float] = []
    cycle_values: list[float] = []
    for task in tasks:
        lead = (task.completed_at - task.created_at).total_seconds() / 86400
        start = started.get(task.id)
        cycle = (
            (task.completed_at - start).total_seconds() / 86400
            if start is not None
            else None
        )
        lead_values.append(lead)
        if cycle is not None:
            cycle_values.append(cycle)
        items.append(
            {
                "task_id": task.id,
                "key": task.key,
                "title": task.title,
                "lead_time_days": round(lead, 2),
                "cycle_time_days": round(cycle, 2) if cycle is not None else None,
                "completed_at": task.completed_at,
            }
        )
    items.sort(key=lambda entry: entry["completed_at"], reverse=True)
    return {
        "project_id": project_id,
        "days": days,
        "count": len(items),
        "avg_lead_time_days": round(sum(lead_values) / len(lead_values), 2)
        if lead_values
        else None,
        "p50_lead_time_days": _quantile(lead_values, 0.5),
        "p85_lead_time_days": _quantile(lead_values, 0.85),
        "avg_cycle_time_days": round(sum(cycle_values) / len(cycle_values), 2)
        if cycle_values
        else None,
        "p50_cycle_time_days": _quantile(cycle_values, 0.5),
        "p85_cycle_time_days": _quantile(cycle_values, 0.85),
        "items": items,
    }


async def sprint_report(db: AsyncSession, org_id: uuid.UUID, sprint: Sprint) -> dict:
    tasks = [
        task
        for task in await _project_tasks(db, sprint.project_id)
        if task.sprint_id == sprint.id
    ]
    committed_points = sum(_points(task) for task in tasks)
    done_tasks = [task for task in tasks if task.status_category == TaskStatus.DONE]
    completed_points = sum(_points(task) for task in done_tasks)
    start = sprint.start_date
    added = (
        sum(1 for task in tasks if start and task.created_at >= start)
        if start
        else 0
    )
    unfinished = len(tasks) - len(done_tasks)

    members: dict[uuid.UUID | None, dict] = {}
    for task in tasks:
        entry = members.setdefault(
            task.assignee_id,
            {
                "user_id": task.assignee_id,
                "name": "",
                "assigned_tasks": 0,
                "completed_tasks": 0,
                "completed_points": 0.0,
            },
        )
        entry["assigned_tasks"] += 1
        if task.status_category == TaskStatus.DONE:
            entry["completed_tasks"] += 1
            entry["completed_points"] += _points(task)

    from app.models import User

    for user_id, entry in members.items():
        if user_id is None:
            entry["name"] = "Unassigned"
            continue
        user = await db.get(User, user_id)
        entry["name"] = (user.full_name or user.email) if user else "(removed)"
    member_list = sorted(members.values(), key=lambda entry: -entry["assigned_tasks"])
    for entry in member_list:
        entry["completed_points"] = round(entry["completed_points"], 2)

    return {
        "sprint_id": sprint.id,
        "sprint_name": sprint.name,
        "state": sprint.state,
        "start_date": sprint.start_date,
        "end_date": sprint.end_date,
        "committed_tasks": len(tasks),
        "committed_points": committed_points,
        "completed_tasks": len(done_tasks),
        "completed_points": completed_points,
        "added_during_sprint": added,
        "carried_over": unfinished,
        "scope_change_pct": round(added / len(tasks) * 100, 1) if tasks else 0.0,
        "members": member_list,
    }


async def get_sprint_for_org(
    db: AsyncSession, sprint_id: uuid.UUID, organization_id: uuid.UUID
) -> Sprint:
    sprint = await SprintRepository(db).get_in_org(sprint_id, organization_id)
    if not sprint:
        raise NotFoundError("Sprint not found")
    return sprint


def rows_to_csv(rows: list[dict], headers: list[str]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=headers, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: csv_safe(row.get(key, "")) for key in headers})
    return buffer.getvalue()
