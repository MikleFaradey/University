"""Audit event reception."""
from common.events import DomainEvent
from .repositories import AuditRepository


class AuditService:
    def __init__(self,repo:AuditRepository):
        self.repo=repo

    def record(self,event:DomainEvent):
        return self.repo.save(event)
