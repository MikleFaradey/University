"""Notification storage; no direct access to any other service's database."""
from common.db import connect, row_dict, transaction, utcnow
from common.events import DomainEvent


class NotificationRepository:
    def __init__(self,path: str):
        self.path=path

    def initialize(self):
        with connect(self.path) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
            CREATE TABLE IF NOT EXISTS received_events (
                event_id TEXT PRIMARY KEY,
                event_type TEXT NOT NULL, received_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL UNIQUE, task_id INTEGER NOT NULL,
                event_type TEXT NOT NULL, recipient_id INTEGER,
                department_id INTEGER NOT NULL, text TEXT NOT NULL,
                is_read INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_notifications_department ON notifications(department_id,id);
            CREATE INDEX IF NOT EXISTS idx_notifications_recipient ON notifications(recipient_id,id);
            """)
            db.commit()

    def health(self):
        with connect(self.path) as db:
            db.execute("SELECT 1").fetchone()

    def save_event(self,event: DomainEvent):
        with transaction(self.path) as db:
            seen=db.execute("INSERT OR IGNORE INTO received_events(event_id,event_type,received_at) VALUES (?,?,?)",
                            (str(event.event_id),event.event_type,utcnow()))
            if not seen.rowcount:
                return {"accepted":True,"duplicate":True}
            db.execute("""INSERT INTO notifications
                (event_id,task_id,event_type,recipient_id,department_id,text,created_at)
                VALUES (?,?,?,?,?,?,?)""",
                (str(event.event_id),event.task_id,event.event_type,event.recipient_id,
                 event.department_id,event.message,event.created_at.isoformat()))
            return {"accepted":True,"duplicate":False}

    def list(self, actor, department, employee, unread, limit):
        conditions,params=[],[]
        if actor.role!="admin":
            conditions.append("((recipient_id IS NULL AND department_id=?) OR recipient_id=?)")
            params.extend([actor.department_id,actor.id])
        if department is not None:
            conditions.append("department_id=?")
            params.append(department)
        if employee is not None:
            conditions.append("recipient_id=?")
            params.append(employee)
        if unread:
            conditions.append("is_read=0")
        where=" WHERE "+" AND ".join(conditions) if conditions else ""
        with connect(self.path) as db:
            return [dict(x) for x in db.execute("SELECT * FROM notifications"+where+" ORDER BY id DESC LIMIT ?",
                                               (*params,limit)).fetchall()]

    def mark_read(self,actor,notification_id:int):
        with transaction(self.path) as db:
            item=row_dict(db.execute("SELECT * FROM notifications WHERE id=?",(notification_id,)).fetchone())
            if not item:
                return None
            if actor.role!="admin" and actor.id!=item["recipient_id"] and (item["recipient_id"] is not None or actor.department_id!=item["department_id"]):
                return False
            db.execute("UPDATE notifications SET is_read=1 WHERE id=?",(notification_id,))
            item["is_read"]=1
            return item
