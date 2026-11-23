"""Append-only event store enforced by SQL triggers."""
import json
from common.db import connect, transaction, utcnow
from common.events import DomainEvent


class AuditRepository:
    def __init__(self,path: str):
        self.path=path

    def initialize(self):
        with connect(self.path) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL UNIQUE,
                task_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                actor INTEGER NOT NULL,
                department_id INTEGER NOT NULL,
                old_value TEXT,
                new_value TEXT,
                timestamp TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_audit_task ON audit_log(task_id,id);
            CREATE INDEX IF NOT EXISTS idx_audit_actor ON audit_log(actor,id);
            CREATE TRIGGER IF NOT EXISTS audit_no_update
            BEFORE UPDATE ON audit_log BEGIN SELECT RAISE(ABORT,'audit log is immutable'); END;
            CREATE TRIGGER IF NOT EXISTS audit_no_delete
            BEFORE DELETE ON audit_log BEGIN SELECT RAISE(ABORT,'audit log is immutable'); END;
            """)
            db.commit()

    def health(self):
        with connect(self.path) as db:
            db.execute("SELECT 1").fetchone()

    def save(self,event:DomainEvent):
        with transaction(self.path) as db:
            cursor=db.execute("""INSERT OR IGNORE INTO audit_log
                (event_id,task_id,action,actor,department_id,old_value,new_value,timestamp)
                VALUES (?,?,?,?,?,?,?,?)""",(
                str(event.event_id),event.task_id,event.event_type,event.actor_id,
                event.department_id,
                json.dumps(event.old_value,ensure_ascii=False,default=str) if event.old_value is not None else None,
                json.dumps(event.new_value,ensure_ascii=False,default=str) if event.new_value is not None else None,
                event.created_at.isoformat()))
            return {"accepted":True,"duplicate":not bool(cursor.rowcount)}

    def list(self,actor,task_id,employee,limit):
        conditions,params=[],[]
        if actor.role!="admin":
            conditions.append("department_id=?")
            params.append(actor.department_id)
        if task_id is not None:
            conditions.append("task_id=?")
            params.append(task_id)
        if employee is not None:
            conditions.append("actor=?")
            params.append(employee)
        where=" WHERE "+" AND ".join(conditions) if conditions else ""
        with connect(self.path) as db:
            rows=db.execute("SELECT * FROM audit_log"+where+" ORDER BY id DESC LIMIT ?",(*params,limit)).fetchall()
            result=[]
            for row in rows:
                item=dict(row)
                for key in ("old_value","new_value"):
                    item[key]=json.loads(item[key]) if item[key] is not None else None
                result.append(item)
            return result
