"""Shared schema helpers used by the initial workflow contracts."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp for event and artifact metadata."""

    return datetime.now(UTC)


class StrictBaseModel(BaseModel):
    """Base model that rejects undeclared fields to keep workflow state explicit."""

    model_config = ConfigDict(extra="forbid")
