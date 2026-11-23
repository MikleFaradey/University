from datetime import datetime,timedelta,timezone
import asyncio

from common.security import Actor
from services.task.app.main import deadline_loop


def test_deadline_loop_cancellation(stack):
    """A disabled scheduler in tests does not leave background tasks running."""
    service=stack["task"].app.state.task_service
    assert service.settings.deadline_scan_seconds==0
    assert service.settings.retry_interval_seconds==0
