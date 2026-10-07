"""Shared schema primitives."""

from typing import Generic, TypeVar

from pydantic import BaseModel

ItemT = TypeVar("ItemT")


class Page(BaseModel, Generic[ItemT]):
    """Offset-based page envelope used by every list endpoint."""

    items: list[ItemT]
    total: int
    offset: int
    limit: int


class CursorPage(BaseModel, Generic[ItemT]):
    """Keyset envelope for cursor-paginated, hot-path lists (M3 #37).

    `next_cursor` is opaque; pass it back verbatim. It is None on the last
    page. Keysets eliminate the deep-offset scan that makes OFFSET slow on
    million-row tables.
    """

    items: list[ItemT]
    next_cursor: str | None = None
    limit: int
