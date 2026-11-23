from pydantic import BaseModel
from common.events import DomainEvent


class NotificationEvent(DomainEvent):
    pass


class NotificationItem(BaseModel):
    id: int
    task_id: int
    event_type: str
    recipient_id: int | None
    department_id: int
    text: str
    is_read: bool
    created_at: str
