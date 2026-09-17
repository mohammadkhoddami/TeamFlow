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
