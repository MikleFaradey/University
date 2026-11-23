import sqlite3
from uuid import uuid4

import pytest
from common.db import connect


def event_payload(event_id=None):
    return {"event_id":str(event_id or uuid4()),"event_type":"task_created","task_id":42,
            "actor_id":1,"department_id":1,"recipient_id":None,"message":"Создана задача №42",
            "old_value":None,"new_value":{"status":"new"}}


def test_service_token_protection(stack):
    for service in ("notification","audit"):
        response=stack[service].post("/events",json=event_payload())
        assert response.status_code==403
        assert stack[service].get("/health").json()["status"]=="ok"


def test_notifications_idempotence_and_read(stack,make_user):
    n=stack["notification"]
    p=event_payload()
    key={"X-Service-Token":"test-service-token-very-long"}
    assert n.post("/events",json=p,headers=key).json()["duplicate"] is False
    assert n.post("/events",json=p,headers=key).json()["duplicate"] is True
    notes=n.get("/notifications?department=1&unread=true",headers=stack["headers"]).json()
    assert len(notes)==1 and notes[0]["is_read"]==0
    assert n.post(f"/notifications/{notes[0]['id']}/read",headers=stack["headers"]).status_code==200
    assert n.get("/notifications?unread=true",headers=stack["headers"]).json()==[]
    _,other=make_user("otherdept",department=2)
    assert n.get("/notifications",headers=other).json()==[]
    assert n.post(f"/notifications/{notes[0]['id']}/read",headers=other).status_code==403


def test_audit_idempotence_and_db_triggers(stack):
    audit=stack["audit"]
    p=event_payload()
    key={"X-Service-Token":"test-service-token-very-long"}
    assert audit.post("/events",json=p,headers=key).json()["duplicate"] is False
    assert audit.post("/events",json=p,headers=key).json()["duplicate"] is True
    rows=audit.get("/audit?task_id=42",headers=stack["headers"]).json()
    assert len(rows)==1 and rows[0]["new_value"]=={"status":"new"}
    with connect(str(stack["data"]/"audit.db")) as db:
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("DELETE FROM audit_log WHERE id=?",(rows[0]["id"],))
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("UPDATE audit_log SET action='bad' WHERE id=?",(rows[0]["id"],))


def test_audit_requires_manager_or_admin(stack,make_user,make_task):
    user,headers=make_user("employeez")
    make_task()
    assert stack["audit"].get("/audit",headers=headers).status_code==403


def test_outbox_recovers_after_notification_failure(stack,make_task):
    dispatcher=stack["task"].app.state.dispatcher
    good=stack["relay"]
    def network_outage(destination,payload):
        if destination=="notification":
            raise OSError("notification temporarily offline")
        good(destination,payload)
    dispatcher.send_event=network_outage
    task=make_task()
    assert task["id"]>0
    items=stack["task"].get("/outbox",headers=stack["headers"]).json()
    assert any(item["destination"]=="notification" and not item["delivered_at"] for item in items)
    assert any(item["destination"]=="audit" and item["delivered_at"] for item in items)
    dispatcher.send_event=good
    retry=stack["task"].post("/outbox/retry",headers=stack["headers"])
    assert retry.status_code==200 and retry.json()["delivered"]==1
    assert stack["task"].post("/outbox/retry",headers=stack["headers"]).json()["delivered"]==0
    assert len(stack["notification"].get("/notifications",headers=stack["headers"]).json())==1
    assert all(x["delivered_at"] for x in stack["task"].get("/outbox",headers=stack["headers"]).json())


def test_outbox_recovers_after_audit_failure(stack,make_task):
    dispatcher=stack["task"].app.state.dispatcher
    good=stack["relay"]
    def offline(destination,payload):
        if destination=="audit":raise OSError("audit unavailable")
        good(destination,payload)
    dispatcher.send_event=offline
    task=make_task()
    assert len(stack["notification"].get("/notifications",headers=stack["headers"]).json())==1
    assert stack["audit"].get("/audit",headers=stack["headers"]).json()==[]
    dispatcher.send_event=good
    assert stack["task"].post("/outbox/retry",headers=stack["headers"]).json()["delivered"]==1
    assert len(stack["audit"].get(f"/audit?task_id={task['id']}",headers=stack["headers"]).json())==1


def test_separate_database_files(stack,make_task):
    make_task()
    files=[stack["data"]/f for f in ["tasks.db","notifications.db","audit.db"]]
    assert all(f.exists() for f in files)
    with connect(str(files[1])) as db:
        names=[x[0] for x in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        assert "tasks" not in names and "notifications" in names
    with connect(str(files[2])) as db:
        names=[x[0] for x in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        assert "tasks" not in names and "audit_log" in names
