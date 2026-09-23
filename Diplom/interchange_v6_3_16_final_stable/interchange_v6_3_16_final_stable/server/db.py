import json
import sqlite3
from pathlib import Path

DB_PATH = None


def configure_db(path):
    global DB_PATH
    DB_PATH = str(Path(path).expanduser().resolve())


def get_db():
    if DB_PATH is None:
        raise RuntimeError("Database is not configured")
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def _column_exists(conn, table, column):
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r["name"] == column for r in rows)


def init_db():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    with get_db() as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            ip TEXT,
            role TEXT NOT NULL DEFAULT 'client',
            active INTEGER NOT NULL DEFAULT 0,
            token_id TEXT,
            password_salt TEXT,
            kdf_iterations INTEGER,
            password_verifier TEXT,
            token_verifier TEXT,
            auth_status TEXT NOT NULL DEFAULT 'PENDING',
            approved_at DATETIME,
            last_seen DATETIME,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_id TEXT NOT NULL,
            recipient_id TEXT NOT NULL,
            message_type TEXT NOT NULL DEFAULT 'text',
            text TEXT NOT NULL,
            metadata_json TEXT,
            client_msg_id TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            delivered_at DATETIME,
            FOREIGN KEY(sender_id) REFERENCES users(user_id),
            FOREIGN KEY(recipient_id) REFERENCES users(user_id)
        );

        CREATE TABLE IF NOT EXISTS transfers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_id TEXT NOT NULL,
            recipient_id TEXT NOT NULL,
            item_name TEXT NOT NULL,
            item_type TEXT NOT NULL,
            source_path TEXT NOT NULL,
            stored_archive INTEGER NOT NULL DEFAULT 0,
            delete_after INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'waiting',
            sha256 TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            completed_at DATETIME,
            FOREIGN KEY(sender_id) REFERENCES users(user_id),
            FOREIGN KEY(recipient_id) REFERENCES users(user_id)
        );

        CREATE TABLE IF NOT EXISTS anomaly_scenarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            target_user_id TEXT,
            anomaly_type TEXT NOT NULL,
            params_json TEXT,
            enabled INTEGER NOT NULL DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(target_user_id) REFERENCES users(user_id)
        );

        CREATE TABLE IF NOT EXISTS experiment_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scenario_id INTEGER,
            target_user_id TEXT NOT NULL,
            anomaly_type TEXT NOT NULL,
            params_json TEXT,
            status TEXT NOT NULL DEFAULT 'starting',
            pcap_path TEXT,
            capture_backend TEXT,
            capture_interface TEXT,
            error TEXT,
            started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            finished_at DATETIME,
            experiment_start_epoch REAL,
            experiment_end_epoch REAL,
            FOREIGN KEY(scenario_id) REFERENCES anomaly_scenarios(id),
            FOREIGN KEY(target_user_id) REFERENCES users(user_id)
        );
        """)


        if not _column_exists(conn, "users", "auth_status"):
            conn.execute(
                "ALTER TABLE users ADD COLUMN auth_status TEXT "
                "NOT NULL DEFAULT 'APPROVED'"
            )
        if not _column_exists(conn, "users", "approved_at"):
            conn.execute("ALTER TABLE users ADD COLUMN approved_at DATETIME")
        if not _column_exists(conn, "users", "last_seen"):
            conn.execute("ALTER TABLE users ADD COLUMN last_seen DATETIME")
        if not _column_exists(conn, "users", "token_id"):
            conn.execute("ALTER TABLE users ADD COLUMN token_id TEXT")
        if not _column_exists(conn, "users", "password_salt"):
            conn.execute("ALTER TABLE users ADD COLUMN password_salt TEXT")
        if not _column_exists(conn, "users", "kdf_iterations"):
            conn.execute("ALTER TABLE users ADD COLUMN kdf_iterations INTEGER")
        if not _column_exists(conn, "users", "password_verifier"):
            conn.execute("ALTER TABLE users ADD COLUMN password_verifier TEXT")
        if not _column_exists(conn, "users", "token_verifier"):
            conn.execute("ALTER TABLE users ADD COLUMN token_verifier TEXT")

        if not _column_exists(conn, "messages", "client_msg_id"):
            conn.execute("ALTER TABLE messages ADD COLUMN client_msg_id TEXT")

        if not _column_exists(conn, "experiment_runs", "experiment_start_epoch"):
            conn.execute(
                "ALTER TABLE experiment_runs ADD COLUMN experiment_start_epoch REAL"
            )
        if not _column_exists(conn, "experiment_runs", "experiment_end_epoch"):
            conn.execute(
                "ALTER TABLE experiment_runs ADD COLUMN experiment_end_epoch REAL"
            )

        conn.execute("""
            INSERT OR IGNORE INTO users(
                user_id, name, ip, role, active, auth_status
            )
            VALUES('server', 'Server', NULL, 'server', 1, 'APPROVED')
        """)

        conn.execute("""
            UPDATE users
            SET name = 'Server',
                active = 1,
                auth_status = 'APPROVED'
            WHERE user_id = 'server'
        """)
        conn.execute("""
            UPDATE users
            SET auth_status = 'LEGACY',
                active = 0
            WHERE role = 'client'
              AND (token_id IS NULL
                   OR password_verifier IS NULL
                   OR token_verifier IS NULL)
        """)
        conn.execute("""
            UPDATE users
            SET active = CASE
                WHEN role = 'server' THEN 1
                WHEN auth_status = 'APPROVED' THEN 1
                ELSE 0
            END
        """)
        conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_users_token_id
            ON users(token_id)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_messages_dialog
            ON messages(sender_id, recipient_id, id)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_transfers_recipient_status
            ON transfers(recipient_id, status, id)
        """)
        conn.commit()


TOKEN_ID_HEX_LENGTH = 64


def _validate_token_id(value):
    value = str(value or "").strip().lower()
    if len(value) != TOKEN_ID_HEX_LENGTH:
        raise ValueError("Invalid client token identifier")
    try:
        int(value, 16)
    except Exception:
        raise ValueError("Invalid client token identifier")
    return value


def _new_internal_user_id(conn, token_identifier):
    base = "client_" + token_identifier[:16]
    candidate = base
    suffix = 1
    while conn.execute(
        "SELECT 1 FROM users WHERE user_id = ?",
        (candidate,)
    ).fetchone():
        suffix += 1
        candidate = "%s_%d" % (base, suffix)
    return candidate


def _user_select():
    return """
        SELECT user_id, name, ip, role, active,
               token_id, password_salt, kdf_iterations,
               password_verifier, token_verifier,
               auth_status, approved_at,
               last_seen, created_at
        FROM users
    """


def add_user(user_id, name, ip=None):
    with get_db() as conn:
        conn.execute("""
            INSERT INTO users(
                user_id, name, ip, role, active, auth_status
            )
            VALUES(?, ?, ?, 'client', 0, 'LEGACY')
        """, (user_id, name, ip))
        conn.commit()


def update_user(user_id, name=None, ip=None):
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE user_id = ?",
            (user_id,)
        ).fetchone()
        if not row:
            raise KeyError(user_id)
        conn.execute("""
            UPDATE users
            SET name = ?, ip = ?
            WHERE user_id = ?
        """, (
            name if name is not None else row["name"],
            ip if ip is not None else row["ip"],
            user_id
        ))
        conn.commit()


def get_user(user_id):
    with get_db() as conn:
        return conn.execute(
            _user_select() + " WHERE user_id = ?",
            (user_id,)
        ).fetchone()


def get_user_by_token_id(token_identifier):
    try:
        token_identifier = _validate_token_id(token_identifier)
    except ValueError:
        return None
    with get_db() as conn:
        return conn.execute(
            _user_select() + " WHERE token_id = ?",
            (token_identifier,)
        ).fetchone()


def register_client_access(name, token_identifier, token_verifier,
                           password_salt, kdf_iterations,
                           password_verifier, ip):
    name = str(name or "").strip()
    if not name:
        raise ValueError("Name is required")
    if len(name) > 100:
        raise ValueError("Name is too long")

    token_identifier = _validate_token_id(token_identifier)
    password_salt = str(password_salt or "").strip().lower()
    token_verifier = str(token_verifier or "").strip().lower()
    password_verifier = str(password_verifier or "").strip().lower()
    try:
        bytes.fromhex(password_salt)
    except Exception:
        raise ValueError("Invalid password salt")
    if len(password_salt) != 32:
        raise ValueError("Invalid password salt")
    try:
        int(token_verifier, 16)
        int(password_verifier, 16)
    except Exception:
        raise ValueError("Invalid authentication verifier")
    try:
        kdf_iterations = int(kdf_iterations)
    except Exception:
        raise ValueError("Invalid password KDF parameters")
    if kdf_iterations < 100000 or kdf_iterations > 1000000:
        raise ValueError("Invalid password KDF parameters")

    ip = str(ip or "").strip() or None

    with get_db() as conn:
        row = conn.execute(
            _user_select() + " WHERE token_id = ?",
            (token_identifier,)
        ).fetchone()

        if row:
            return row
        else:
            user_id = _new_internal_user_id(
                conn,
                token_identifier
            )
            conn.execute("""
                INSERT INTO users(
                    user_id, name, ip, role, active,
                    token_id, password_salt, kdf_iterations,
                    password_verifier, token_verifier,
                    auth_status, last_seen
                )
                VALUES(
                    ?, ?, ?, 'client', 0,
                    ?, ?, ?, ?, ?, 'PENDING', CURRENT_TIMESTAMP
                )
            """, (
                user_id,
                name,
                ip,
                token_identifier,
                password_salt,
                kdf_iterations,
                password_verifier,
                token_verifier
            ))
            conn.commit()

        return conn.execute(
            _user_select() + " WHERE token_id = ?",
            (token_identifier,)
        ).fetchone()


def get_client_auth_status(token_identifier):
    return get_user_by_token_id(token_identifier)


def get_auth_user(token_identifier):
    row = get_user_by_token_id(token_identifier)
    if not row or row["role"] != "client":
        return None
    return row


def touch_user(user_id, ip):
    ip = str(ip or "").strip() or None
    with get_db() as conn:
        conn.execute("""
            UPDATE users
            SET ip = ?,
                last_seen = CURRENT_TIMESTAMP
            WHERE user_id = ?
        """, (ip, user_id))
        conn.commit()
        return conn.execute(
            _user_select() + " WHERE user_id = ?",
            (user_id,)
        ).fetchone()


def set_user_auth_status(user_id, status):
    status = str(status or "").strip().upper()
    if user_id == "server":
        raise ValueError("The system user server cannot be modified")
    if status not in ("PENDING", "APPROVED", "REJECTED", "BLOCKED"):
        raise ValueError("Invalid access status")

    with get_db() as conn:
        row = conn.execute(
            "SELECT user_id, password_verifier, token_verifier "
            "FROM users WHERE user_id = ?",
            (user_id,)
        ).fetchone()
        if not row:
            raise KeyError(user_id)
        if status == "APPROVED" and (
            not row["password_verifier"]
            or not row["token_verifier"]
        ):
            raise ValueError("Client has no authorization verifiers")

        if status == "APPROVED":
            conn.execute("""
                UPDATE users
                SET auth_status = 'APPROVED',
                    active = 1,
                    approved_at = CURRENT_TIMESTAMP
                WHERE user_id = ?
            """, (user_id,))
        else:
            conn.execute("""
                UPDATE users
                SET auth_status = ?,
                    active = 0
                WHERE user_id = ?
            """, (status, user_id))
        conn.commit()


def list_users():
    with get_db() as conn:
        return conn.execute(
            _user_select() + """
            WHERE role = 'server'
               OR (active = 1 AND auth_status = 'APPROVED')
            ORDER BY
                CASE WHEN role = 'server' THEN 0 ELSE 1 END,
                name,
                user_id
            """
        ).fetchall()


def list_all_users():
    with get_db() as conn:
        return conn.execute(
            _user_select() + """
            ORDER BY
                CASE WHEN role = 'server' THEN 0 ELSE 1 END,
                CASE
                    WHEN auth_status = 'PENDING' THEN 0
                    WHEN auth_status = 'APPROVED' THEN 1
                    WHEN auth_status = 'BLOCKED' THEN 2
                    WHEN auth_status = 'REJECTED' THEN 3
                    ELSE 4
                END,
                created_at DESC,
                user_id
            """
        ).fetchall()


def set_user_active(user_id, active):
    set_user_auth_status(
        user_id,
        "APPROVED" if active else "BLOCKED"
    )


def create_anomaly_scenario(name, target_user_id, anomaly_type,
                            params=None, enabled=False):
    params_json = json.dumps(params or {}, ensure_ascii=False)
    with get_db() as conn:
        cur = conn.execute("""
            INSERT INTO anomaly_scenarios(
                name, target_user_id, anomaly_type, params_json, enabled
            )
            VALUES(?, ?, ?, ?, ?)
        """, (
            name, target_user_id, anomaly_type,
            params_json, 1 if enabled else 0
        ))
        conn.commit()
        return cur.lastrowid


def list_anomaly_scenarios():
    with get_db() as conn:
        return conn.execute("""
            SELECT id, name, target_user_id, anomaly_type,
                   params_json, enabled, created_at
            FROM anomaly_scenarios
            ORDER BY id DESC
        """).fetchall()


def delete_anomaly_scenario(scenario_id):
    with get_db() as conn:
        conn.execute(
            "DELETE FROM anomaly_scenarios WHERE id = ?",
            (scenario_id,)
        )
        conn.commit()


def set_anomaly_scenario_enabled(scenario_id, enabled):
    with get_db() as conn:
        conn.execute("""
            UPDATE anomaly_scenarios
            SET enabled = ?
            WHERE id = ?
        """, (1 if enabled else 0, scenario_id))
        conn.commit()


def get_anomaly_scenario(scenario_id):
    with get_db() as conn:
        return conn.execute("""
            SELECT id, name, target_user_id, anomaly_type,
                   params_json, enabled, created_at
            FROM anomaly_scenarios
            WHERE id = ?
        """, (scenario_id,)).fetchone()



def create_experiment_run(scenario_id, target_user_id, anomaly_type,
                          params=None):
    params_json = json.dumps(params or {}, ensure_ascii=False)
    with get_db() as conn:
        cur = conn.execute("""
            INSERT INTO experiment_runs(
                scenario_id, target_user_id, anomaly_type,
                params_json, status
            )
            VALUES(?, ?, ?, ?, 'starting')
        """, (
            scenario_id, target_user_id, anomaly_type, params_json
        ))
        conn.commit()
        return cur.lastrowid


def update_experiment_run(run_id, status=None, pcap_path=None,
                          capture_backend=None, capture_interface=None,
                          error=None, experiment_start_epoch=None,
                          experiment_end_epoch=None, finish=False):
    fields = []
    values = []

    if status is not None:
        fields.append("status = ?")
        values.append(status)
    if pcap_path is not None:
        fields.append("pcap_path = ?")
        values.append(pcap_path)
    if capture_backend is not None:
        fields.append("capture_backend = ?")
        values.append(capture_backend)
    if capture_interface is not None:
        fields.append("capture_interface = ?")
        values.append(capture_interface)
    if error is not None:
        fields.append("error = ?")
        values.append(error)
    if experiment_start_epoch is not None:
        fields.append("experiment_start_epoch = ?")
        values.append(float(experiment_start_epoch))
    if experiment_end_epoch is not None:
        fields.append("experiment_end_epoch = ?")
        values.append(float(experiment_end_epoch))
    if finish:
        fields.append("finished_at = CURRENT_TIMESTAMP")

    if not fields:
        return

    values.append(int(run_id))
    with get_db() as conn:
        conn.execute(
            "UPDATE experiment_runs SET %s WHERE id = ?"
            % ", ".join(fields),
            tuple(values)
        )
        conn.commit()


def get_experiment_run(run_id):
    with get_db() as conn:
        return conn.execute("""
            SELECT id, scenario_id, target_user_id, anomaly_type,
                   params_json, status, pcap_path, capture_backend,
                   capture_interface, error, started_at, finished_at,
                   experiment_start_epoch, experiment_end_epoch
            FROM experiment_runs
            WHERE id = ?
        """, (int(run_id),)).fetchone()


def list_experiment_runs(limit=100):
    limit = max(1, min(int(limit), 1000))
    with get_db() as conn:
        return conn.execute("""
            SELECT id, scenario_id, target_user_id, anomaly_type,
                   params_json, status, pcap_path, capture_backend,
                   capture_interface, error, started_at, finished_at,
                   experiment_start_epoch, experiment_end_epoch
            FROM experiment_runs
            ORDER BY id DESC
            LIMIT ?
        """, (limit,)).fetchall()


def get_active_experiment_for_user(user_id):
    with get_db() as conn:
        return conn.execute("""
            SELECT id, scenario_id, target_user_id, anomaly_type,
                   params_json, status, pcap_path, capture_backend,
                   capture_interface, error, started_at, finished_at,
                   experiment_start_epoch, experiment_end_epoch
            FROM experiment_runs
            WHERE target_user_id = ?
              AND status IN ('starting', 'running', 'stopping')
            ORDER BY id DESC
            LIMIT 1
        """, (user_id,)).fetchone()


def delete_experiment_run(run_id):
    """Delete one experiment row and return whether a row existed."""
    with get_db() as conn:
        cur = conn.execute(
            "DELETE FROM experiment_runs WHERE id = ?",
            (int(run_id),)
        )
        conn.commit()
        return bool(cur.rowcount)


def add_message(sender_id, recipient_id, text,
                message_type="text", metadata=None,
                client_msg_id=None):
    metadata_json = json.dumps(metadata, ensure_ascii=False) if metadata else None
    with get_db() as conn:
        cur = conn.execute("""
            INSERT INTO messages(
                sender_id, recipient_id, message_type, text,
                metadata_json, client_msg_id
            )
            VALUES(?, ?, ?, ?, ?, ?)
        """, (
            sender_id, recipient_id, message_type, text,
            metadata_json, client_msg_id
        ))
        conn.commit()
        return cur.lastrowid


def get_message(message_id):
    with get_db() as conn:
        return conn.execute("""
            SELECT id, sender_id, recipient_id, message_type, text,
                   metadata_json, client_msg_id, created_at, delivered_at
            FROM messages WHERE id = ?
        """, (message_id,)).fetchone()


def mark_message_delivered(message_id):
    with get_db() as conn:
        conn.execute("""
            UPDATE messages SET delivered_at = CURRENT_TIMESTAMP WHERE id = ?
        """, (message_id,))
        conn.commit()


def get_history(user_a, user_b, limit=50):
    limit = max(1, min(int(limit), 500))
    with get_db() as conn:
        rows = conn.execute("""
            SELECT id, sender_id, recipient_id, message_type, text,
                   metadata_json, client_msg_id, created_at, delivered_at
            FROM messages
            WHERE (sender_id = ? AND recipient_id = ?)
               OR (sender_id = ? AND recipient_id = ?)
            ORDER BY id DESC
            LIMIT ?
        """, (user_a, user_b, user_b, user_a, limit)).fetchall()
        return list(reversed(rows))


def add_transfer(sender_id, recipient_id, item_name, item_type,
                 source_path, stored_archive=False,
                 delete_after=False, sha256=None):
    with get_db() as conn:
        cur = conn.execute("""
            INSERT INTO transfers(
                sender_id, recipient_id, item_name, item_type, source_path,
                stored_archive, delete_after, sha256
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            sender_id, recipient_id, item_name, item_type, source_path,
            int(stored_archive), int(delete_after), sha256
        ))
        conn.commit()
        return cur.lastrowid


def get_transfer(transfer_id):
    with get_db() as conn:
        return conn.execute("SELECT * FROM transfers WHERE id = ?", (transfer_id,)).fetchone()


def list_waiting_transfers(recipient_id):
    with get_db() as conn:
        return conn.execute("""
            SELECT id, sender_id, recipient_id, item_name, item_type, status, created_at
            FROM transfers
            WHERE recipient_id = ? AND status = 'waiting'
            ORDER BY id
        """, (recipient_id,)).fetchall()


def complete_transfer(transfer_id, recipient_id):
    with get_db() as conn:
        row = conn.execute("""
            SELECT * FROM transfers
            WHERE id = ? AND recipient_id = ? AND status != 'completed'
        """, (transfer_id, recipient_id)).fetchone()
        if not row:
            return None
        conn.execute("""
            UPDATE transfers
            SET status = 'completed', completed_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (transfer_id,))
        conn.commit()
        return row


def repair_file_status_directions():
    """
    Repairs direction of legacy file_status messages.

    Interchange rule:
    - status=uploaded/waiting belongs to the file SENDER;
    - status=received belongs to the file RECIPIENT.

    This automatically repairs history created by versions before 3.2.
    """
    import json

    with get_db() as conn:
        rows = conn.execute("""
            SELECT id, sender_id, recipient_id, text, metadata_json
            FROM messages
            WHERE message_type = 'file_status'
              AND metadata_json IS NOT NULL
        """).fetchall()

        fixed = 0
        for row in rows:
            try:
                meta = json.loads(row["metadata_json"] or "{}")
                transfer_id = meta.get("transfer_id")
                status = meta.get("status")
                if not transfer_id or status not in ("uploaded", "waiting", "received"):
                    continue

                transfer = conn.execute(
                    "SELECT sender_id, recipient_id, item_name FROM transfers WHERE id = ?",
                    (transfer_id,)
                ).fetchone()
                if not transfer:
                    continue

                if status == "received":
                    expected_sender = transfer["recipient_id"]
                    expected_recipient = transfer["sender_id"]
                else:
                    expected_sender = transfer["sender_id"]
                    expected_recipient = transfer["recipient_id"]


                if status == "received":
                    expected_text = "%s: received" % transfer["item_name"]
                else:
                    expected_text = "%s: sent" % transfer["item_name"]

                if (row["sender_id"] != expected_sender or
                        row["recipient_id"] != expected_recipient or
                        row["text"] != expected_text):
                    conn.execute("""
                        UPDATE messages
                        SET sender_id = ?, recipient_id = ?, text = ?
                        WHERE id = ?
                    """, (
                        expected_sender,
                        expected_recipient,
                        expected_text,
                        row["id"]
                    ))
                    fixed += 1
            except Exception:

                continue

        conn.commit()
        return fixed
