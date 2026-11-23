"""ASGI application and background outbox retry process."""
import asyncio
from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlite3 import OperationalError

from common.settings import load_settings
from .api import router
from .repositories import TaskRepository
from .services import EventDispatcher, TaskService
from common.security import Actor

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


async def retry_loop(dispatcher: EventDispatcher, interval: float):
    while True:
        await asyncio.sleep(interval)
        try:
            await asyncio.to_thread(dispatcher.deliver_pending, 30)
        except Exception:
            log.exception("Unexpected outbox retry failure")


async def deadline_loop(task_service: TaskService, interval: float):
    """Schedule reminders; unique(task_id, day) makes periodic scans idempotent."""
    while True:
        await asyncio.sleep(interval)
        try:
            admin = task_service.repo.one("SELECT id,login,department_id,role FROM employees WHERE login=? AND role='admin' AND is_active=1", (task_service.settings.bootstrap_admin_login,))
            if admin:
                await asyncio.to_thread(task_service.scan_deadlines, Actor(**admin))
        except Exception:
            log.exception("Unexpected deadline scan failure")


def create_app():
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings = load_settings("task")
        repo = TaskRepository(settings.db_path)
        repo.initialize(settings.bootstrap_admin_login, settings.bootstrap_admin_password)
        dispatcher = EventDispatcher(repo, settings)
        app.state.settings = settings
        app.state.repo = repo
        app.state.dispatcher = dispatcher
        app.state.task_service = TaskService(repo, dispatcher, settings)
        worker = (asyncio.create_task(retry_loop(dispatcher,settings.retry_interval_seconds))
                  if settings.retry_interval_seconds > 0 else None)
        deadline_worker = (asyncio.create_task(deadline_loop(app.state.task_service,settings.deadline_scan_seconds))
                           if settings.deadline_scan_seconds > 0 else None)
        try:
            yield
        finally:
            for background_task in (worker,deadline_worker):
                if background_task:
                    background_task.cancel()
                    try:
                        await background_task
                    except asyncio.CancelledError:
                        pass

    instance = FastAPI(title="Bank Tasks — Task Service", version="1.0.0", lifespan=lifespan)
    instance.include_router(router)
    return instance


app = create_app()
