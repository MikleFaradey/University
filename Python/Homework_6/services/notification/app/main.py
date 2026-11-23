from contextlib import asynccontextmanager
from fastapi import FastAPI
from common.settings import load_settings
from .api import router
from .repositories import NotificationRepository
from .services import NotificationService


def create_app():
    @asynccontextmanager
    async def lifespan(app:FastAPI):
        settings=load_settings("notification")
        repo=NotificationRepository(settings.db_path)
        repo.initialize()
        app.state.settings=settings
        app.state.repo=repo
        app.state.notification_service=NotificationService(repo)
        yield
    application=FastAPI(title="Bank Tasks — Notification Service",version="1.0.0",lifespan=lifespan)
    application.include_router(router)
    return application


app=create_app()
