from datetime import datetime, timedelta, timezone
import pytest


def test_bootstrap_and_authentication(stack):
    t=stack["task"]
    assert t.get("/health").json()=={"status":"ok","service":"task"}
    assert t.get("/tasks").status_code==401
    assert t.post("/auth/login-json",json={"login":"admin","password":"incorrect"}).status_code==401
    assert t.post("/auth/login",data={"username":"admin","password":"test-password-123"}).status_code==200
    departments=t.get("/departments",headers=stack["headers"]).json()
    assert [d["code"] for d in departments]==["CREDIT","COMPLIANCE","OPERATIONS","IT"]


def test_create_task_saves_both_events(stack,make_task):
    task=make_task()
    assert task["status"]=="new" and task["priority"]=="high"
    assert len(stack["notification"].get("/notifications",headers=stack["headers"]).json())==1
    audit=stack["audit"].get("/audit?task_id="+str(task["id"]),headers=stack["headers"]).json()
    assert len(audit)==1 and audit[0]["action"]=="task_created" and audit[0]["new_value"]["id"]==task["id"]
    assert all(e["delivered_at"] for e in stack["task"].get("/outbox",headers=stack["headers"]).json())


def test_full_lifecycle_with_roles(stack,make_user,make_task):
    assignee,h_assignee=make_user("petrov",department=2)
    author,h_author=make_user("ivanov",department=1)
    task=make_task(assignee["id"],department=2,headers=h_author)
    tid=task["id"]
    t=stack["task"]
    assert t.post(f"/tasks/{tid}/status",json={"status":"done"},headers=h_author).status_code==409
    assert t.post(f"/tasks/{tid}/status",json={"status":"in_progress"},headers=h_author).status_code==403
    assert t.post(f"/tasks/{tid}/status",json={"status":"in_progress"},headers=h_assignee).json()["status"]=="in_progress"
    assert t.post(f"/tasks/{tid}/status",json={"status":"on_review"},headers=h_assignee).json()["status"]=="on_review"
    assert t.post(f"/tasks/{tid}/status",json={"status":"done"},headers=h_assignee).status_code==403
    assert t.post(f"/tasks/{tid}/status",json={"status":"done"},headers=h_author).json()["status"]=="done"
    assert t.patch(f"/tasks/{tid}",json={"title":"Изменение после закрытия"},headers=h_author).status_code==409
    assert len(stack["audit"].get(f"/audit?task_id={tid}",headers=stack["headers"]).json())==4


def test_rejection_requires_comment(stack,make_user,make_task):
    user,headers=make_user("nikolay",department=2)
    task=make_task(department=2,assignee=user["id"])
    t=stack["task"]
    assert t.post(f"/tasks/{task['id']}/status",json={"status":"in_progress"},headers=headers).status_code==200
    assert t.post(f"/tasks/{task['id']}/status",json={"status":"rejected"},headers=headers).status_code==422
    assert t.post(f"/tasks/{task['id']}/status",json={"status":"rejected","comment":"Пакет документов неполный"},headers=headers).status_code==200
    comments=t.get(f"/tasks/{task['id']}/comments",headers=headers).json()
    assert len(comments)==1 and "неполный" in comments[0]["text"]


def test_transfer_resets_status_and_records_comment(stack,make_user,make_task):
    user,headers=make_user("sidorov",department=2)
    task=make_task(department=2,assignee=user["id"])
    t=stack["task"]
    assert t.post(f"/tasks/{task['id']}/status",json={"status":"in_progress"},headers=headers).status_code==200
    result=t.post(f"/tasks/{task['id']}/transfer",json={"to_department":3,"comment":"Нужна проверка операций"},headers=stack["headers"])
    assert result.status_code==200,result.text
    assert result.json()["status"]=="new" and result.json()["assignee_department_id"]==3
    assert result.json()["assignee_id"] is None
    assert len(t.get(f"/tasks/{task['id']}/comments",headers=stack["headers"]).json())==1


def test_update_task_and_visibility(stack,make_user,make_task):
    task=make_task()
    outsider,h_out=make_user("outsider",department=2)
    t=stack["task"]
    assert t.get(f"/tasks/{task['id']}",headers=h_out).status_code==403
    assert t.get("/tasks",headers=h_out).json()==[]
    assert t.patch(f"/tasks/{task['id']}",json={"status":"done"},headers=stack["headers"]).status_code==422
    changed=t.patch(f"/tasks/{task['id']}",json={"priority":"critical","title":"Проверка пакета клиента"},headers=stack["headers"])
    assert changed.status_code==200,changed.text
    assert changed.json()["version"]==2
    assert len(t.get("/tasks?priority=critical",headers=stack["headers"]).json())==1
    assert t.get("/tasks?priority=low",headers=stack["headers"]).json()==[]


def test_employee_department_permissions(stack,make_user):
    t=stack["task"]
    user,headers=make_user("userone")
    assert t.post("/departments",json={"name":"Other","code":"OTHER"},headers=headers).status_code==403
    assert t.post("/employees",json={"login":"another","full_name":"A B","password":"abcdefgh","department_id":1},headers=headers).status_code==403
    assert t.post("/departments",json={"name":"Other","code":"OTHER"},headers=stack["headers"]).status_code==201
    assert t.post("/departments",json={"name":"Other","code":"OTHER"},headers=stack["headers"]).status_code==409


def test_invalid_assignee(stack,make_user,make_task):
    user,_=make_user("otherdepartment",department=2)
    resp=stack["task"].post("/tasks",json={"title":"Task for credit","to_department":1,"assignee":user["id"]},headers=stack["headers"])
    assert resp.status_code==422


def test_deadline_scan_deduplicates_events(stack,make_task):
    deadline=(datetime.now(timezone.utc)+timedelta(hours=12)).isoformat()
    task=make_task(deadline=deadline)
    scan=stack["task"].post("/deadlines/scan",headers=stack["headers"])
    assert scan.json()=={"events_created":1}
    assert stack["task"].post("/deadlines/scan",headers=stack["headers"]).json()=={"events_created":0}
    audit=stack["audit"].get(f"/audit?task_id={task['id']}",headers=stack["headers"]).json()
    assert [item["action"] for item in audit].count("deadline_near")==1
