"""Only this module manages Task Service SQLite tables and SQL statements."""
import json
import sqlite3

from common.db import connect, row_dict, transaction, utcnow
from common.security import hash_password


class TaskRepository:
    def __init__(self, path: str):
        self.path = path

    def initialize(self, admin_login: str, admin_password: str) -> None:
        with connect(self.path) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
            CREATE TABLE IF NOT EXISTS departments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
                manager_id INTEGER
            );
            CREATE TABLE IF NOT EXISTS employees (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                login TEXT UNIQUE NOT NULL, full_name TEXT NOT NULL,
                password_hash TEXT NOT NULL, department_id INTEGER NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('employee','manager','admin')),
                is_active INTEGER NOT NULL DEFAULT 1,
                FOREIGN KEY(department_id) REFERENCES departments(id)
            );
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
                priority TEXT NOT NULL CHECK(priority IN ('low','medium','high','critical')),
                status TEXT NOT NULL CHECK(status IN ('new','in_progress','on_review','done','rejected')),
                author_id INTEGER NOT NULL, initiator_department_id INTEGER NOT NULL,
                assignee_department_id INTEGER NOT NULL, assignee_id INTEGER,
                due_date TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                version INTEGER NOT NULL DEFAULT 1,
                FOREIGN KEY(author_id) REFERENCES employees(id),
                FOREIGN KEY(assignee_id) REFERENCES employees(id),
                FOREIGN KEY(initiator_department_id) REFERENCES departments(id),
                FOREIGN KEY(assignee_department_id) REFERENCES departments(id)
            );
            CREATE TABLE IF NOT EXISTS comments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL, author_id INTEGER NOT NULL,
                text TEXT NOT NULL, created_at TEXT NOT NULL,
                FOREIGN KEY(task_id) REFERENCES tasks(id),
                FOREIGN KEY(author_id) REFERENCES employees(id)
            );
            CREATE TABLE IF NOT EXISTS outbox (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL, destination TEXT NOT NULL,
                payload TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
                last_error TEXT, created_at TEXT NOT NULL, delivered_at TEXT,
                UNIQUE(event_id,destination)
            );
            CREATE TABLE IF NOT EXISTS deadline_alerts (
                task_id INTEGER NOT NULL, alert_day TEXT NOT NULL,
                PRIMARY KEY(task_id, alert_day),
                FOREIGN KEY(task_id) REFERENCES tasks(id)
            );
            CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
            CREATE INDEX IF NOT EXISTS idx_tasks_departments ON tasks(assignee_department_id);
            CREATE INDEX IF NOT EXISTS idx_outbox_pending ON outbox(delivered_at,id);
            """)
            for code, name in [
                ("CREDIT", "Кредитный отдел"), ("COMPLIANCE", "Комплаенс"),
                ("OPERATIONS", "Операционный отдел"), ("IT", "ИТ-отдел")
            ]:
                db.execute("INSERT OR IGNORE INTO departments(code,name) VALUES (?,?)", (code, name))
            first = db.execute("SELECT count(*) AS n FROM employees").fetchone()["n"]
            if first == 0:
                department = db.execute("SELECT id FROM departments WHERE code='IT'").fetchone()["id"]
                db.execute("INSERT INTO employees(login,full_name,password_hash,department_id,role) VALUES (?,?,?,?,?)",
                           (admin_login, "System Administrator", hash_password(admin_password), department, "admin"))
            db.commit()

    def one(self, sql: str, params=()):
        with connect(self.path) as db:
            return row_dict(db.execute(sql, params).fetchone())

    def all(self, sql: str, params=()):
        with connect(self.path) as db:
            return [dict(row) for row in db.execute(sql, params).fetchall()]

    def transaction(self):
        return transaction(self.path)

    def enqueue(self, db: sqlite3.Connection, event) -> None:
        payload = event.model_dump_json()
        for destination in ("notification", "audit"):
            db.execute("INSERT INTO outbox(event_id,destination,payload,created_at) VALUES (?,?,?,?)",
                       (str(event.event_id), destination, payload, utcnow()))

    def pending(self, limit: int = 20):
        return self.all("SELECT * FROM outbox WHERE delivered_at IS NULL ORDER BY id LIMIT ?", (limit,))

    def mark_delivered(self, item_id: int) -> None:
        with self.transaction() as db:
            db.execute("UPDATE outbox SET delivered_at=?, last_error=NULL, attempts=attempts+1 WHERE id=? AND delivered_at IS NULL", (utcnow(), item_id))

    def mark_failed(self, item_id: int, message: str) -> None:
        with self.transaction() as db:
            db.execute("UPDATE outbox SET attempts=attempts+1,last_error=? WHERE id=? AND delivered_at IS NULL",
                       (message[:300], item_id))

    def list_tasks(self, actor, department, status, priority, assignee, limit, offset):
        conditions, params = [], []
        if actor.role != "admin":
            conditions.append("(author_id=? OR initiator_department_id=? OR assignee_department_id=?)")
            params.extend([actor.id, actor.department_id, actor.department_id])
        for field, value in (("assignee_department_id",department),("status",status),
                             ("priority",priority),("assignee_id",assignee)):
            if value is not None:
                conditions.append(f"{field}=?")
                params.append(value)
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        return self.all("SELECT * FROM tasks"+where+" ORDER BY id DESC LIMIT ? OFFSET ?", (*params,limit,offset))
