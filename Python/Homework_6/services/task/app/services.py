"""Task domain rules. Writes and queued events commit in one SQLite transaction."""
from datetime import datetime, timedelta, timezone
import json
import logging
from threading import Lock

import httpx
from fastapi import HTTPException

from common.db import row_dict, utcnow
from common.events import DomainEvent
from common.security import Actor, check_password, create_access_token, hash_password
from .repositories import TaskRepository
from .schemas import CommentCreate, DepartmentCreate, EmployeeCreate, TaskCreate, TaskPatch, TaskTransfer, StatusChange

log = logging.getLogger(__name__)


class EventDispatcher:
    """Persistent outbox. Both recipients have independent delivery state."""
    def __init__(self, repo: TaskRepository, settings):
        self.repo, self.settings = repo, settings
        self._lock = Lock()
        self.send_event = self._post

    def _post(self, destination: str, payload: dict) -> None:
        url = {"notification": self.settings.notification_url, "audit": self.settings.audit_url}[destination]
        with httpx.Client(timeout=self.settings.request_timeout_seconds) as client:
            response = client.post(f"{url.rstrip('/')}/events", json=payload,
                                   headers={"X-Service-Token": self.settings.service_api_key})
            response.raise_for_status()

    def deliver_pending(self, limit: int = 20) -> dict:
        if not self._lock.acquire(blocking=False):
            return {"delivered": 0, "failed": 0, "busy": True}
        sent, failed = 0, 0
        try:
            for item in self.repo.pending(limit):
                try:
                    self.send_event(item["destination"], json.loads(item["payload"]))
                    self.repo.mark_delivered(item["id"])
                    sent += 1
                except Exception as exc:  # delivery errors never roll back committed tasks
                    failed += 1
                    log.warning("Event delivery %s to %s failed: %s", item["event_id"], item["destination"], exc)
                    self.repo.mark_failed(item["id"], str(exc))
            return {"delivered": sent, "failed": failed, "busy": False}
        finally:
            self._lock.release()


class TaskService:
    def __init__(self, repo: TaskRepository, dispatcher: EventDispatcher, settings):
        self.repo, self.dispatcher, self.settings = repo, dispatcher, settings

    @staticmethod
    def fail(code: int, text: str):
        raise HTTPException(status_code=code, detail=text)

    def actor(self, claims: Actor) -> Actor:
        employee = self.repo.one("SELECT * FROM employees WHERE id=? AND is_active=1", (claims.id,))
        if not employee or employee["login"] != claims.login:
            self.fail(401, "Account is disabled or does not exist")
        return Actor(id=employee["id"], login=employee["login"],
                     department_id=employee["department_id"], role=employee["role"])

    def login(self, login: str, password: str):
        user = self.repo.one("SELECT * FROM employees WHERE login=?", (login,))
        if not user or not user["is_active"] or not check_password(password, user["password_hash"]):
            self.fail(401, "Invalid login or password")
        actor = Actor(id=user["id"], login=user["login"],
                      department_id=user["department_id"], role=user["role"])
        return {"access_token": create_access_token(actor, self.settings.jwt_secret), "token_type": "bearer"}

    def add_department(self, actor: Actor, info: DepartmentCreate):
        if actor.role != "admin":
            self.fail(403, "Admin role required")
        with self.repo.transaction() as db:
            if db.execute("SELECT 1 FROM departments WHERE code=?", (info.code.upper(),)).fetchone():
                self.fail(409, "Department code already exists")
            cursor = db.execute("INSERT INTO departments(code,name) VALUES (?,?)",
                                (info.code.upper(),info.name))
            return row_dict(db.execute("SELECT * FROM departments WHERE id=?", (cursor.lastrowid,)).fetchone())

    def add_employee(self, actor: Actor, info: EmployeeCreate):
        if actor.role != "admin":
            self.fail(403, "Admin role required")
        with self.repo.transaction() as db:
            if not db.execute("SELECT 1 FROM departments WHERE id=?", (info.department_id,)).fetchone():
                self.fail(404, "Department not found")
            if db.execute("SELECT 1 FROM employees WHERE login=?", (info.login,)).fetchone():
                self.fail(409, "Employee login already exists")
            cursor = db.execute("""INSERT INTO employees(login,full_name,password_hash,department_id,role)
                                   VALUES (?,?,?,?,?)""",
                                (info.login,info.full_name,hash_password(info.password),
                                 info.department_id,info.role))
            return row_dict(db.execute("""SELECT id,login,full_name,department_id,role,is_active
                                          FROM employees WHERE id=?""", (cursor.lastrowid,)).fetchone())

    def assign_manager(self, actor: Actor, department_id: int, manager_id: int):
        if actor.role != "admin":
            self.fail(403, "Admin role required")
        with self.repo.transaction() as db:
            dept = db.execute("SELECT 1 FROM departments WHERE id=?", (department_id,)).fetchone()
            if not dept:
                self.fail(404, "Department not found")
            manager = db.execute("SELECT role,department_id,is_active FROM employees WHERE id=?", (manager_id,)).fetchone()
            if not manager or manager["role"] not in ("manager", "admin") or not manager["is_active"] or manager["department_id"] != department_id:
                self.fail(422, "Manager must be an active manager of this department")
            db.execute("UPDATE departments SET manager_id=? WHERE id=?", (manager_id, department_id))
            return row_dict(db.execute("SELECT * FROM departments WHERE id=?", (department_id,)).fetchone())

    def set_employee_active(self, actor: Actor, employee_id: int, is_active: bool):
        if actor.role != "admin":
            self.fail(403, "Admin role required")
        if employee_id == actor.id and not is_active:
            self.fail(409, "Cannot deactivate your own admin account")
        with self.repo.transaction() as db:
            row = db.execute("SELECT id FROM employees WHERE id=?", (employee_id,)).fetchone()
            if not row:
                self.fail(404, "Employee not found")
            db.execute("UPDATE employees SET is_active=? WHERE id=?", (int(is_active), employee_id))
            return row_dict(db.execute("SELECT id,login,full_name,department_id,role,is_active FROM employees WHERE id=?", (employee_id,)).fetchone())

    def _task(self, db, task_id: int, actor: Actor):
        task = row_dict(db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone())
        if not task:
            self.fail(404, "Task not found")
        if actor.role != "admin" and actor.id != task["author_id"] and actor.department_id not in (
                task["initiator_department_id"], task["assignee_department_id"]):
            self.fail(403, "Task is not visible to this employee")
        return task

    def get_task(self, actor: Actor, task_id: int):
        with self.repo.transaction() as db:
            return self._task(db, task_id, actor)

    def _assignee(self, db, employee_id: int | None, department_id: int):
        if employee_id is None:
            return
        found = db.execute("SELECT department_id,is_active FROM employees WHERE id=?", (employee_id,)).fetchone()
        if not found or not found["is_active"] or found["department_id"] != department_id:
            self.fail(422, "Assignee must be an active employee of the receiving department")

    def _event(self, db, task: dict, actor: Actor, kind: str, before: dict | None, after: dict | None, message: str):
        self.repo.enqueue(db, DomainEvent(event_type=kind, task_id=task["id"], actor_id=actor.id,
            department_id=task["assignee_department_id"], recipient_id=task["assignee_id"],
            message=message, old_value=before, new_value=after))

    def _after_commit(self):
        # A failed request to a downstream service cannot undo a committed task.
        self.dispatcher.deliver_pending(limit=4)

    def create_task(self, actor: Actor, data: TaskCreate):
        with self.repo.transaction() as db:
            if not db.execute("SELECT 1 FROM departments WHERE id=?", (data.to_department,)).fetchone():
                self.fail(404, "Receiving department not found")
            self._assignee(db, data.assignee, data.to_department)
            now = utcnow()
            cursor = db.execute("""INSERT INTO tasks
                (title,description,priority,status,author_id,initiator_department_id,
                 assignee_department_id,assignee_id,due_date,created_at,updated_at)
                 VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (data.title,data.description,data.priority.value,"new",actor.id,actor.department_id,
                 data.to_department,data.assignee,data.deadline.isoformat() if data.deadline else None,now,now))
            task = row_dict(db.execute("SELECT * FROM tasks WHERE id=?", (cursor.lastrowid,)).fetchone())
            self._event(db,task,actor,"task_created",None,task,f"Создана задача №{task['id']}: {data.title}")
        self._after_commit()
        return task

    @staticmethod
    def _manager(actor: Actor, department_id: int) -> bool:
        return actor.role == "admin" or (actor.role == "manager" and actor.department_id == department_id)

    def _can_manage(self, actor: Actor, task):
        if actor.id != task["author_id"] and not self._manager(actor, task["initiator_department_id"]):
            self.fail(403, "Only the author or initiating department manager may change this task")

    def patch_task(self, actor: Actor, task_id: int, info: TaskPatch):
        changes = info.model_dump(exclude_unset=True)
        if not changes:
            self.fail(422, "No changes supplied")
        if "title" in changes and changes["title"] is None:
            self.fail(422, "Title cannot be null")
        if "priority" in changes and changes["priority"] is None:
            self.fail(422, "Priority cannot be null")
        if "description" in changes and changes["description"] is None:
            self.fail(422, "Description cannot be null")
        with self.repo.transaction() as db:
            before = self._task(db,task_id,actor)
            self._can_manage(actor,before)
            if before["status"] in ("done","rejected"):
                self.fail(409, "Closed tasks cannot be edited")
            for k,v in list(changes.items()):
                if hasattr(v, "value"):
                    changes[k] = v.value
                elif isinstance(v, datetime):
                    changes[k] = v.isoformat()
            columns = {"title":"title", "description":"description", "priority":"priority", "deadline":"due_date"}
            clause = ", ".join(f"{columns[k]}=?" for k in changes)
            db.execute(f"UPDATE tasks SET {clause}, updated_at=?, version=version+1 WHERE id=?",
                       (*changes.values(),utcnow(),task_id))
            task = row_dict(db.execute("SELECT * FROM tasks WHERE id=?",(task_id,)).fetchone())
            self._event(db,task,actor,"task_updated",before,task,f"Изменены поля задачи №{task_id}")
        self._after_commit()
        return task

    def _comment(self, db, task_id: int, actor_id: int, text: str) -> dict:
        cursor = db.execute("INSERT INTO comments(task_id,author_id,text,created_at) VALUES (?,?,?,?)",
                            (task_id,actor_id,text,utcnow()))
        return row_dict(db.execute("SELECT * FROM comments WHERE id=?",(cursor.lastrowid,)).fetchone())

    def add_comment(self, actor: Actor, task_id: int, info: CommentCreate):
        with self.repo.transaction() as db:
            task=self._task(db,task_id,actor)
            comment=self._comment(db,task_id,actor.id,info.text)
            self._event(db,task,actor,"comment_added",None,comment,f"Новый комментарий к задаче №{task_id}")
        self._after_commit()
        return comment

    def status(self, actor: Actor, task_id: int, info: StatusChange):
        target = info.status.value
        with self.repo.transaction() as db:
            before=self._task(db,task_id,actor)
            old=before["status"]
            if (old,target) not in {("new","in_progress"),("in_progress","on_review"),
                                    ("on_review","done"),("in_progress","rejected"),
                                    ("on_review","rejected")}:
                self.fail(409,f"Status transition {old} -> {target} is not allowed")
            assigned = before["assignee_id"]
            if target == "in_progress":
                if actor.department_id != before["assignee_department_id"]:
                    self.fail(403,"Only the receiving department may claim the task")
                if assigned not in (None,actor.id) and not self._manager(actor,before["assignee_department_id"]):
                    self.fail(403,"Task is assigned to another employee")
                assigned=actor.id
            elif target == "done":
                if actor.id != before["author_id"] and not self._manager(actor,before["initiator_department_id"]):
                    self.fail(403,"Only the author or initiating department manager may close the task")
            else:
                if actor.id != assigned and not self._manager(actor,before["assignee_department_id"]):
                    self.fail(403,"Only the assignee or receiving department manager may change status")
            if target == "rejected" and not (info.comment or "").strip():
                self.fail(422,"Rejection requires a comment")
            if info.comment and info.comment.strip():
                self._comment(db,task_id,actor.id,info.comment.strip())
            db.execute("UPDATE tasks SET status=?,assignee_id=?,updated_at=?,version=version+1 WHERE id=?",
                       (target,assigned,utcnow(),task_id))
            task=row_dict(db.execute("SELECT * FROM tasks WHERE id=?",(task_id,)).fetchone())
            self._event(db,task,actor,"status_changed",before,task,f"Задача №{task_id}: {old} → {target}")
        self._after_commit()
        return task

    def transfer(self, actor: Actor, task_id: int, info: TaskTransfer):
        with self.repo.transaction() as db:
            before=self._task(db,task_id,actor)
            if before["status"] in ("done","rejected"):
                self.fail(409,"Closed tasks cannot be transferred")
            if actor.id not in (before["author_id"],before["assignee_id"]) and not self._manager(actor,before["initiator_department_id"]):
                self.fail(403,"Only the author, assignee or initiating department manager may transfer a task")
            if info.to_department==before["assignee_department_id"]:
                self.fail(409,"Task already belongs to that department")
            if not db.execute("SELECT 1 FROM departments WHERE id=?",(info.to_department,)).fetchone():
                self.fail(404,"Receiving department not found")
            self._assignee(db,info.assignee,info.to_department)
            self._comment(db,task_id,actor.id,info.comment)
            db.execute("""UPDATE tasks SET assignee_department_id=?,assignee_id=?,status='new',
                          updated_at=?,version=version+1 WHERE id=?""",
                       (info.to_department,info.assignee,utcnow(),task_id))
            task=row_dict(db.execute("SELECT * FROM tasks WHERE id=?",(task_id,)).fetchone())
            self._event(db,task,actor,"status_changed",before,task,
                        f"Задача №{task_id} передана в отдел {info.to_department}; статус new")
        self._after_commit()
        return task

    def scan_deadlines(self, actor: Actor):
        if actor.role not in ("admin","manager"):
            self.fail(403,"Manager or admin role required")
        now=datetime.now(timezone.utc)
        window=(now+timedelta(hours=24)).isoformat()
        created=0
        with self.repo.transaction() as db:
            records=db.execute("""SELECT * FROM tasks WHERE status NOT IN ('done','rejected')
                                   AND due_date IS NOT NULL AND due_date<=?""",(window,)).fetchall()
            for row in records:
                task=row_dict(row)
                try:
                    due=datetime.fromisoformat(task["due_date"])
                    if due.tzinfo is None or due.astimezone(timezone.utc)<now:
                        continue
                except ValueError:
                    continue
                if actor.role!="admin" and task["assignee_department_id"]!=actor.department_id:
                    continue
                cursor=db.execute("INSERT OR IGNORE INTO deadline_alerts(task_id,alert_day) VALUES (?,?)",
                                  (task["id"],now.date().isoformat()))
                if cursor.rowcount:
                    self._event(db,task,actor,"deadline_near",None,task,
                                f"Срок задачи №{task['id']} наступит в течение 24 часов")
                    created+=1
        if created:
            self._after_commit()
        return {"events_created":created}
