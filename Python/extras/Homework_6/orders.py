import json
import os
import re
import sqlite3
from contextlib import closing
from catalog import SHOPS, ADDRESSES
from common import Handler, Problem, serve

DB = os.getenv("DB_PATH", "orders.db")


class Orders(Handler):
    def handle_request(self, path, data):
        with closing(sqlite3.connect(DB)) as db, db:
            if path == "/orders" and self.command == "GET":
                owner = self.headers.get("X-Owner")
                query = "SELECT id, stage, details, finished FROM orders"
                params = ()
                if owner:
                    query += " WHERE owner=?"
                    params = (owner,)
                rows = db.execute(query + " ORDER BY id DESC", params)
                return self.send(200, [dict(json.loads(d), id=i, stage=s, finished=f) for i, s, d, f in rows])
            if path == "/orders" and self.command == "POST":
                key = data["token"]
                if not re.fullmatch(r"[a-zA-Z0-9-]{8,80}", key):
                    raise ValueError()
                owner = self.headers["X-Owner"]
                if not owner:
                    raise Problem(400, "Требуется клиент")
                key = owner + ":" + key
                shop = SHOPS[data["shop"]]
                items = data["items"]
                if not isinstance(items, dict) or not items or any(
                    name not in shop["menu"] or type(q) is not int or not 1 <= q <= 20
                    for name, q in items.items()
                ):
                    raise ValueError()
                if data["address"] not in ADDRESSES or not isinstance(data["comment"], str) or len(data["comment"]) > 300:
                    raise ValueError()
                details = dict(shop=data["shop"], pickup=shop["address"], address=data["address"],
                               items=items, comment=data["comment"],
                               total=sum(shop["menu"][name] * q for name, q in items.items()))
                encoded = json.dumps(details, sort_keys=True)
                db.execute("INSERT INTO orders(token,details,owner) VALUES (?,?,?) ON CONFLICT(token) DO NOTHING", (key, encoded, owner))
                number, original = db.execute("SELECT id,details FROM orders WHERE token=?", (key,)).fetchone()
                if original != encoded:
                    raise Problem(409, "Этот запрос уже использован")
                db.commit()
                return self.send(200, {"id": number})
            match = re.fullmatch(r"/orders/(\d+)/advance", path)
            if match and self.command == "POST":
                stage = data["stage"]
                if type(stage) is not int or stage not in range(3):
                    raise ValueError()
                db.execute("BEGIN IMMEDIATE")
                if stage == 0 and db.execute("SELECT 1 FROM orders WHERE stage IN (1,2)").fetchone():
                    raise Problem(409, "Сначала завершите активную доставку")
                changed = db.execute("UPDATE orders SET finished=CASE WHEN stage=2 THEN (SELECT coalesce(max(finished),0)+1 FROM orders) ELSE finished END, stage=stage+1 WHERE id=? AND stage=?", (match[1], stage))
                if not changed.rowcount:
                    raise Problem(409, "Статус заказа уже изменился")
                db.commit()
                return self.send(200, {"stage": stage + 1})
        raise Problem(404, "Ресурс не найден")


if __name__ == "__main__":
    with closing(sqlite3.connect(DB)) as db:
        db.execute("CREATE TABLE IF NOT EXISTS orders(id INTEGER PRIMARY KEY, token TEXT UNIQUE, stage INTEGER DEFAULT 0, finished INTEGER DEFAULT 0, details TEXT NOT NULL)")
        if "owner" not in {row[1] for row in db.execute("PRAGMA table_info(orders)")} :
            db.execute("ALTER TABLE orders ADD COLUMN owner TEXT")
    serve(Orders)
