"""Notification business logic."""
import logging
from common.events import DomainEvent
from .repositories import NotificationRepository

log=logging.getLogger(__name__)


class NotificationService:
    def __init__(self,repo:NotificationRepository):
        self.repo=repo

    def handle_event(self,event:DomainEvent):
        result=self.repo.save_event(event)
        if not result["duplicate"]:
            log.info("Notification for task %s: %s",event.task_id,event.message)
        return result
