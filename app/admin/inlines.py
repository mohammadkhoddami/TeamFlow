"""Tabular inlines for admin detail pages (Django-admin-style, read-only).

sqladmin has no native inline support, so a `ModelView` opts in by inheriting
`InlineDetailsMixin` and declaring `inlines = [Inline(...)]`. The shared
`details_context` loads the related rows with a single query per inline and
`templates/inline_details.html` renders them under the standard details table.

The queries reuse the ModelView's own session maker (`self._run_query`), so
they hit the same database as the panel and stay read-only by construction.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, ClassVar

from sqladmin.helpers import get_object_identifier
from sqlalchemy import String, cast
from sqlalchemy.sql.expression import desc
from sqlmodel import select
from starlette.requests import Request

Column = tuple[str, str, Callable[[Any], Any] | None]


@dataclass(frozen=True)
class Inline:
    """One related-records table rendered on a details page."""

    title: str
    model: type
    columns: tuple[Column, ...]
    fk_field: str
    identity: str
    order_by: str = "created_at"
    limit: int = 25


def human_size(size: int | None) -> str:
    value = float(size or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


def truncate(value: Any, limit: int = 60) -> str:
    text = "" if value is None else str(value)
    return text if len(text) <= limit else f"{text[:limit]}..."


def _format_value(value: Any, formatter: Callable[[Any], Any] | None) -> str:
    if formatter is not None:
        value = formatter(value)
    if value is None or value == "":
        return "—"
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    if isinstance(value, bool):
        return "Yes" if value else "No"
    return str(value)


class InlineDetailsMixin:
    """Adds `inlines` tables to a ModelView's details page."""

    inlines: ClassVar[list[Inline]] = []
    details_template = "inline_details.html"

    async def details_context(self, request: Request) -> dict[str, Any]:
        context = await super().details_context(request)
        context["inlines"] = [
            (inline, await self._load_inline(inline, request))
            for inline in self.inlines
        ]
        return context

    async def _load_inline(self, inline: Inline, request: Request) -> list[dict]:
        pk = str(request.path_params["pk"])
        fk = getattr(inline.model, inline.fk_field)
        stmt = (
            select(inline.model)
            .where(cast(fk, String) == pk)
            .order_by(desc(getattr(inline.model, inline.order_by)))
            .limit(inline.limit)
        )
        rows = await self._run_query(stmt)

        rendered = []
        for row in rows:
            rendered.append(
                {
                    "cells": [
                        _format_value(getattr(row, attr), formatter)
                        for attr, _label, formatter in inline.columns
                    ],
                    "url": str(
                        request.url_for(
                            "admin:details",
                            identity=inline.identity,
                            pk=get_object_identifier(row),
                        )
                    ),
                }
            )
        return rendered
