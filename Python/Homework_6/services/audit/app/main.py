from contextlib import asynccontextmanager
from fastapi import FastAPI
from common.settings import load_settings
from .api import router
from .repositories import AuditRepository
from .services import AuditService


def create_app():
    @asynccontextmanager
    async def lifespan(app:FastAPI):
        settings=load_settings("audit")
        repo=AuditRepository(settings.db_path)
        repo.initialize()
        app.state.settings=settings
        app.state.repo=repo
        app.state.audit_service=AuditService(repo)
        yield
    application=FastAPI(title="Bank Tasks — Audit Service",version="1.0.0",lifespan=lifespan)
    application.include_router(router)
    return application


app=create_app()
