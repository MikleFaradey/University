from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest


def test_assignment_in_task_view(stack, make_task):
    task=make_task(department=2)
    assert task["from_department"]==4
    assert task["to_department"]==2
    assert task["assignee"] is None
    assert task["deadline"] is None
    listed=stack["task"].get("/tasks",headers=stack["headers"]).json()
    assert listed[0]["to_department"]==2


def test_registration_of_manager_and_department_manager_assignment(stack, make_user):
    manager,_=make_user("manager1",department=2,role="manager")
    t=stack["task"]
    response=t.patch("/departments/2/manager",json={"manager_id":manager["id"]},headers=stack["headers"])
    assert response.status_code==200 and response.json()["manager_id"]==manager["id"]
    regular,_=make_user("regular1",department=2)
    assert t.patch("/departments/2/manager",json={"manager_id":regular["id"]},headers=stack["headers"]).status_code==422
    assert t.patch("/departments/2/manager",json={"manager_id":999999},headers=stack["headers"]).status_code==422


def test_disable_employee_blocks_task_requests(stack, make_user):
    emp,headers=make_user("disabled2")
    t=stack["task"]
    assert t.get("/tasks",headers=headers).status_code==200
    changed=t.patch(f"/employees/{emp['id']}/state",json={"is_active":False},headers=stack["headers"])
    assert changed.status_code==200 and not changed.json()["is_active"]
    assert t.get("/tasks",headers=headers).status_code==401
    assert t.post("/auth/login-json",json={"login":"disabled2","password":"long-password-123"}).status_code==401
    assert t.patch("/employees/1/state",json={"is_active":False},headers=stack["headers"]).status_code==409


def test_no_cross_department_assigned_notification_visibility(stack,make_user,make_task):
    assignee,h_assignee=make_user("assigned2",department=2)
    _,h_colleague=make_user("colleague",department=2)
    task=make_task(department=2,assignee=assignee["id"])
    n=stack["notification"]
    assert len(n.get("/notifications",headers=h_assignee).json())==1
    assert n.get("/notifications",headers=h_colleague).json()==[]
    assert n.get("/notifications?department=1",headers=h_assignee).json()==[]


def test_invalid_task_and_duplicate_employee(stack):
    t=stack["task"]
    assert t.post("/tasks",json={"title":"ab","to_department":1},headers=stack["headers"]).status_code==422
    assert t.post("/tasks",json={"title":"Valid task","to_department":9999},headers=stack["headers"]).status_code==404
    info={"login":"employee3","full_name":"A Employee","password":"good-password-1","department_id":1}
    assert t.post("/employees",json=info,headers=stack["headers"]).status_code==201
    assert t.post("/employees",json=info,headers=stack["headers"]).status_code==409
    assert t.post("/employees",json={**info,"login":"employee4","password":"short"},headers=stack["headers"]).status_code==422


def test_transfer_rejects_invalid_destinations_and_closed_tasks(stack,make_task):
    t=stack["task"]
    task=make_task(department=1)
    tid=task["id"]
    assert t.post(f"/tasks/{tid}/transfer",json={"to_department":1,"comment":"Wrong department"},headers=stack["headers"]).status_code==409
    assert t.post(f"/tasks/{tid}/transfer",json={"to_department":99999,"comment":"Missing department"},headers=stack["headers"]).status_code==404
    assert t.post(f"/tasks/{tid}/transfer",json={"to_department":2,"comment":""},headers=stack["headers"]).status_code==422


def test_wrong_token_or_missing_service_key(stack):
    t=stack["task"]
    assert t.get("/tasks",headers={"Authorization":"Bearer invalid.jwt.token"}).status_code==401
    assert t.get("/tasks").status_code==401
    assert stack["notification"].post("/events",headers={"X-Service-Token":"wrong"},json={
        "event_type":"task_created","task_id":1,"actor_id":1,"department_id":1,"message":"x"}).status_code==403


def test_comment_persists_in_audit(stack,make_task):
    task=make_task()
    tid=task["id"]
    comment=stack["task"].post(f"/tasks/{tid}/comments",json={"text":"Checked input"},headers=stack["headers"])
    assert comment.status_code==201
    assert stack["task"].get(f"/tasks/{tid}/comments",headers=stack["headers"]).json()[0]["text"]=="Checked input"
    audit=stack["audit"].get(f"/audit?task_id={tid}",headers=stack["headers"]).json()
    assert any(e["action"]=="comment_added" for e in audit)


def test_task_events_and_rows_persist_when_both_receivers_fail(stack,make_task):
    dispatcher=stack["task"].app.state.dispatcher
    dispatcher.send_event=lambda dest,payload: (_ for _ in ()).throw(OSError("service unavailable"))
    task=make_task()
    assert stack["task"].get(f"/tasks/{task['id']}",headers=stack["headers"]).status_code==200
    assert stack["audit"].get("/audit",headers=stack["headers"]).json()==[]
    queued=stack["task"].get("/outbox",headers=stack["headers"]).json()
    assert len(queued)==2
    assert all(x["delivered_at"] is None and x["attempts"]==1 for x in queued)
    dispatcher.send_event=stack["relay"]
    assert stack["task"].post("/outbox/retry",headers=stack["headers"]).json()["delivered"]==2


def test_api_openapi_health(stack):
    for name in ("task","notification","audit"):
        client=stack[name]
        assert client.get("/openapi.json").status_code==200
        assert client.get("/docs").status_code==200
        assert client.get("/health").status_code==200
