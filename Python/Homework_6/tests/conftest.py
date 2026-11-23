"""Three independently initialized applications with isolated temporary databases."""
from contextlib import ExitStack
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from services.task.app.main import create_app as task_app
from services.notification.app.main import create_app as notification_app
from services.audit.app.main import create_app as audit_app


@pytest.fixture
def stack(tmp_path, monkeypatch):
    monkeypatch.setenv("TASK_DB_PATH",str(tmp_path/"tasks.db"))
    monkeypatch.setenv("NOTIFICATION_DB_PATH",str(tmp_path/"notifications.db"))
    monkeypatch.setenv("AUDIT_DB_PATH",str(tmp_path/"audit.db"))
    monkeypatch.setenv("JWT_SECRET","test-jwt-secret-string-very-long")
    monkeypatch.setenv("SERVICE_API_KEY","test-service-token-very-long")
    monkeypatch.setenv("BOOTSTRAP_ADMIN_LOGIN","admin")
    monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD","test-password-123")
    monkeypatch.setenv("OUTBOX_RETRY_SECONDS","0")
    monkeypatch.setenv("DEADLINE_SCAN_SECONDS","0")
    with ExitStack() as contexts:
        task=contexts.enter_context(TestClient(task_app()))
        notification=contexts.enter_context(TestClient(notification_app()))
        audit=contexts.enter_context(TestClient(audit_app()))
        def relay(destination,payload):
            destination_client={"notification":notification,"audit":audit}[destination]
            response=destination_client.post("/events",json=payload,
                                             headers={"X-Service-Token":"test-service-token-very-long"})
            response.raise_for_status()
        task.app.state.dispatcher.send_event=relay
        login=task.post("/auth/login-json",json={"login":"admin","password":"test-password-123"})
        assert login.status_code==200,login.text
        yield {
            "task":task,"notification":notification,"audit":audit,
            "headers":{"Authorization":"Bearer "+login.json()["access_token"]},
            "data":tmp_path,"relay":relay,
        }


@pytest.fixture
def make_user(stack):
    def create(login,department=1,role="employee"):
        response=stack["task"].post("/employees",json={
            "login":login,"full_name":f"User {login}","password":"long-password-123",
            "department_id":department,"role":role},headers=stack["headers"])
        assert response.status_code==201,response.text
        token=stack["task"].post("/auth/login-json",json={"login":login,"password":"long-password-123"})
        assert token.status_code==200
        return response.json(),{"Authorization":"Bearer "+token.json()["access_token"]}
    return create


@pytest.fixture
def make_task(stack):
    def create(assignee=None,department=1,headers=None,deadline=None):
        data={"title":"Проверить документы","description":"Сверить комплект","to_department":department,
              "priority":"high","assignee":assignee}
        if deadline is not None:data["deadline"]=deadline
        response=stack["task"].post("/tasks",json=data,headers=headers or stack["headers"])
        assert response.status_code==201,response.text
        return response.json()
    return create
