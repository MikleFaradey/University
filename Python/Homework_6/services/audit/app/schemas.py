from pydantic import BaseModel
from common.events import DomainEvent


class AuditEvent(DomainEvent):
    pass


class AuditItem(BaseModel):
    id: int
    event_id: str
    task_id: int
    action: str
    actor: int
    old_value: str | None
    new_value: str | None
    timestamp: str
