"""HTTP API for tasks, departments, employees and login."""
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.security import OAuth2PasswordRequestForm

from common.security import Actor, current_actor
from .schemas import (
    AssignManager, EmployeeState, CommentCreate, DepartmentCreate, EmployeeCreate, LoginRequest,
    Priority, Status, StatusChange, TaskCreate, TaskPatch, TaskTransfer,
)

router = APIRouter()


def service(request: Request):
    return request.app.state.task_service


def actor(request: Request, claims: Actor = Depends(current_actor)) -> Actor:
    return service(request).actor(claims)


@router.get("/health", tags=["Состояние"])
def health(request: Request):
    # Verify that the database is available, not just that the ASGI worker is alive.
    request.app.state.repo.one("SELECT 1 AS ok")
    return {"status": "ok", "service": "task"}


@router.post("/auth/login", tags=["Авторизация"])
def login(request: Request, form: OAuth2PasswordRequestForm = Depends()):
    return service(request).login(form.username, form.password)


@router.post("/auth/login-json", tags=["Авторизация"])
def login_json(request: Request, payload: LoginRequest):
    return service(request).login(payload.login, payload.password)


@router.get("/auth/me", tags=["Авторизация"])
def me(user: Actor = Depends(actor)):
    return user


@router.get("/departments", tags=["Справочник"])
def departments(request: Request, user: Actor = Depends(actor)):
    return request.app.state.repo.all("SELECT * FROM departments ORDER BY id")


@router.post("/departments", status_code=201, tags=["Справочник"])
def create_department(request: Request, data: DepartmentCreate, user: Actor = Depends(actor)):
    return service(request).add_department(user, data)


@router.patch("/departments/{department_id}/manager", tags=["Справочник"])
def set_manager(request: Request, department_id: int, data: AssignManager, user: Actor = Depends(actor)):
    return service(request).assign_manager(user, department_id, data.manager_id)


@router.get("/employees", tags=["Справочник"])
def employees(request: Request, department: int | None = Query(None, gt=0), user: Actor = Depends(actor)):
    if department is None:
        return request.app.state.repo.all(
            "SELECT id,login,full_name,department_id,role,is_active FROM employees ORDER BY id")
    return request.app.state.repo.all(
        "SELECT id,login,full_name,department_id,role,is_active FROM employees WHERE department_id=? ORDER BY id",
        (department,))


@router.post("/employees", status_code=201, tags=["Справочник"])
def create_employee(request: Request, data: EmployeeCreate, user: Actor = Depends(actor)):
    return service(request).add_employee(user, data)


@router.patch("/employees/{employee_id}/state", tags=["Справочник"])
def set_employee_state(request: Request, employee_id: int, data: EmployeeState, user: Actor = Depends(actor)):
    return service(request).set_employee_active(user, employee_id, data.is_active)


def task_view(row: dict) -> dict:
    """Public contract supports both ER and endpoint field names from the assignment."""
    return {**row, "from_department": row["initiator_department_id"],
            "to_department": row["assignee_department_id"],
            "assignee": row["assignee_id"], "deadline": row["due_date"]}


@router.post("/tasks", status_code=201, tags=["Задачи"])
def create_task(request: Request, data: TaskCreate, user: Actor = Depends(actor)):
    return task_view(service(request).create_task(user, data))


@router.get("/tasks", tags=["Задачи"])
def list_tasks(request: Request, department: int | None = Query(None,gt=0),
               status: Status | None = None, priority: Priority | None = None,
               assignee: int | None = Query(None,gt=0),
               limit: int = Query(100,ge=1,le=500), offset: int = Query(0,ge=0),
               user: Actor = Depends(actor)):
    rows = request.app.state.repo.list_tasks(user,department,status.value if status else None,
                                             priority.value if priority else None,assignee,limit,offset)
    return [task_view(row) for row in rows]


@router.get("/tasks/{task_id}", tags=["Задачи"])
def get_task(request: Request, task_id: int, user: Actor = Depends(actor)):
    return task_view(service(request).get_task(user,task_id))


@router.patch("/tasks/{task_id}", tags=["Задачи"])
def patch_task(request: Request, task_id: int, data: TaskPatch, user: Actor = Depends(actor)):
    return task_view(service(request).patch_task(user,task_id,data))


@router.post("/tasks/{task_id}/status", tags=["Жизненный цикл"])
def change_status(request: Request, task_id: int, data: StatusChange, user: Actor = Depends(actor)):
    return task_view(service(request).status(user,task_id,data))


@router.post("/tasks/{task_id}/transfer", tags=["Жизненный цикл"])
def transfer(request: Request, task_id: int, data: TaskTransfer, user: Actor = Depends(actor)):
    return task_view(service(request).transfer(user,task_id,data))


@router.get("/tasks/{task_id}/comments", tags=["Комментарии"])
def list_comments(request: Request, task_id: int, user: Actor = Depends(actor)):
    service(request).get_task(user,task_id)
    return request.app.state.repo.all("SELECT * FROM comments WHERE task_id=? ORDER BY id",(task_id,))


@router.post("/tasks/{task_id}/comments", status_code=201, tags=["Комментарии"])
def add_comment(request: Request, task_id: int, data: CommentCreate, user: Actor = Depends(actor)):
    return service(request).add_comment(user,task_id,data)


@router.post("/deadlines/scan", tags=["События"])
def deadlines_scan(request: Request, user: Actor = Depends(actor)):
    return service(request).scan_deadlines(user)


@router.get("/outbox", tags=["События"])
def outbox(request: Request, user: Actor = Depends(actor)):
    if user.role!="admin":
        raise HTTPException(status_code=403,detail="Admin role required")
    return request.app.state.repo.all("""SELECT id,event_id,destination,attempts,last_error,created_at,delivered_at
                                        FROM outbox ORDER BY id DESC LIMIT 200""")


@router.post("/outbox/retry", tags=["События"])
def retry_outbox(request: Request, user: Actor = Depends(actor)):
    if user.role!="admin":
        raise HTTPException(status_code=403,detail="Admin role required")
    return request.app.state.dispatcher.deliver_pending(limit=100)
