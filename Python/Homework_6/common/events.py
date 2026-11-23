"""Versioned inter-service HTTP event contract."""
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class DomainEvent(BaseModel):
    event_id: UUID = Field(default_factory=uuid4)
    event_type: str = Field(min_length=1)
    task_id: int = Field(gt=0)
    actor_id: int = Field(gt=0)
    department_id: int = Field(gt=0)
    recipient_id: int | None = None
    message: str = Field(min_length=1)
    old_value: dict[str, Any] | None = None
    new_value: dict[str, Any] | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
