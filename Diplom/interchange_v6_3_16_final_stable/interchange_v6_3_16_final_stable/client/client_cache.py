import sqlite3
from pathlib import Path

CACHE_LIMIT_PER_PEER = 50


class ClientCache:
    def __init__(self, path):
        self.path = str(Path(path).expanduser().resolve())
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.init()

    def connect(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 3000")
        return conn

    def init(self):
        with self.connect() as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS contacts (
                user_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'client',
                last_activity_at TEXT,
                last_preview TEXT
            );

            CREATE TABLE IF NOT EXISTS cached_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                server_message_id INTEGER UNIQUE,
                peer_id TEXT NOT NULL,
                sender_id TEXT NOT NULL,
                recipient_id TEXT NOT NULL,
                message_type TEXT NOT NULL,
                text TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_cache_peer_time
            ON cached_messages(peer_id, created_at DESC, id DESC);
            """)
            conn.commit()

    def upsert_contact(self, user_id, name, role="client"):

        with self.connect() as conn:
            row = conn.execute(
                "SELECT user_id FROM contacts WHERE user_id = ?",
                (user_id,)
            ).fetchone()
            if row:
                conn.execute(
                    "UPDATE contacts SET name = ?, role = ? WHERE user_id = ?",
                    (name, role, user_id)
                )
            else:
                conn.execute(
                    "INSERT INTO contacts(user_id, name, role) VALUES(?, ?, ?)",
                    (user_id, name, role)
                )
            conn.commit()

    def touch_contact(self, user_id, created_at, preview):
        with self.connect() as conn:
            conn.execute("""
                UPDATE contacts
                SET last_activity_at = ?, last_preview = ?
                WHERE user_id = ?
            """, (created_at, preview, user_id))
            conn.commit()

    def list_contacts(self):
        with self.connect() as conn:
            return conn.execute("""
                SELECT user_id, name, role, last_activity_at, last_preview
                FROM contacts
                ORDER BY
                    CASE WHEN last_activity_at IS NULL THEN 1 ELSE 0 END,
                    last_activity_at DESC,
                    CASE WHEN role='server' THEN 0 ELSE 1 END,
                    name COLLATE NOCASE
            """).fetchall()

    def add_message(self, server_message_id, peer_id, sender_id, recipient_id,
                    message_type, text, created_at):
        with self.connect() as conn:



            existing = None
            if server_message_id is not None:
                existing = conn.execute(
                    "SELECT id FROM cached_messages WHERE server_message_id = ?",
                    (server_message_id,)
                ).fetchone()

            if existing:
                conn.execute("""
                    UPDATE cached_messages
                    SET peer_id = ?, sender_id = ?, recipient_id = ?,
                        message_type = ?, text = ?, created_at = ?
                    WHERE id = ?
                """, (
                    peer_id, sender_id, recipient_id,
                    message_type, text, created_at, existing["id"]
                ))
            else:
                conn.execute("""
                    INSERT INTO cached_messages(
                        server_message_id, peer_id, sender_id, recipient_id,
                        message_type, text, created_at
                    )
                    VALUES(?, ?, ?, ?, ?, ?, ?)
                """, (
                    server_message_id, peer_id, sender_id, recipient_id,
                    message_type, text, created_at
                ))


            conn.execute("""
                DELETE FROM cached_messages
                WHERE peer_id = ?
                  AND id NOT IN (
                      SELECT id FROM cached_messages
                      WHERE peer_id = ?
                      ORDER BY created_at DESC, id DESC
                      LIMIT ?
                  )
            """, (peer_id, peer_id, CACHE_LIMIT_PER_PEER))

            preview = self._preview(message_type, text)
            conn.execute("""
                UPDATE contacts
                SET last_activity_at =
                    CASE
                        WHEN last_activity_at IS NULL OR last_activity_at < ?
                        THEN ?
                        ELSE last_activity_at
                    END,
                    last_preview =
                    CASE
                        WHEN last_activity_at IS NULL OR last_activity_at <= ?
                        THEN ?
                        ELSE last_preview
                    END
                WHERE user_id = ?
            """, (created_at, created_at, created_at, preview, peer_id))
            conn.commit()


    def add_messages_batch(self, messages):
        """Merge many cached messages in one SQLite transaction.

        Each item is a dict with the same logical fields accepted by
        ``add_message``.  This is used after history sync so the Qt GUI thread
        does not open/commit one database connection per message.
        """
        if not messages:
            return

        peer_ids = set()
        with self.connect() as conn:
            for item in messages:
                server_message_id = item.get("server_message_id")
                peer_id = item["peer_id"]
                sender_id = item["sender_id"]
                recipient_id = item["recipient_id"]
                message_type = item["message_type"]
                text = item.get("text", "")
                created_at = item["created_at"]
                peer_ids.add(peer_id)

                existing = None
                if server_message_id is not None:
                    existing = conn.execute(
                        "SELECT id FROM cached_messages "
                        "WHERE server_message_id = ?",
                        (server_message_id,)
                    ).fetchone()

                if existing:
                    conn.execute("""
                        UPDATE cached_messages
                        SET peer_id = ?, sender_id = ?, recipient_id = ?,
                            message_type = ?, text = ?, created_at = ?
                        WHERE id = ?
                    """, (
                        peer_id, sender_id, recipient_id, message_type,
                        text, created_at, existing["id"]
                    ))
                else:
                    conn.execute("""
                        INSERT INTO cached_messages(
                            server_message_id, peer_id, sender_id, recipient_id,
                            message_type, text, created_at
                        )
                        VALUES(?, ?, ?, ?, ?, ?, ?)
                    """, (
                        server_message_id, peer_id, sender_id, recipient_id,
                        message_type, text, created_at
                    ))

                preview = self._preview(message_type, text)
                conn.execute("""
                    UPDATE contacts
                    SET last_activity_at =
                        CASE
                            WHEN last_activity_at IS NULL OR last_activity_at < ?
                            THEN ?
                            ELSE last_activity_at
                        END,
                        last_preview =
                        CASE
                            WHEN last_activity_at IS NULL OR last_activity_at <= ?
                            THEN ?
                            ELSE last_preview
                        END
                    WHERE user_id = ?
                """, (
                    created_at, created_at, created_at, preview, peer_id
                ))

            for peer_id in peer_ids:
                conn.execute("""
                    DELETE FROM cached_messages
                    WHERE peer_id = ?
                      AND id NOT IN (
                          SELECT id FROM cached_messages
                          WHERE peer_id = ?
                          ORDER BY created_at DESC, id DESC
                          LIMIT ?
                      )
                """, (peer_id, peer_id, CACHE_LIMIT_PER_PEER))

            conn.commit()

    def get_messages(self, peer_id):
        with self.connect() as conn:
            return conn.execute("""
                SELECT server_message_id, peer_id, sender_id, recipient_id,
                       message_type, text, created_at
                FROM cached_messages
                WHERE peer_id = ?
                ORDER BY created_at, id
            """, (peer_id,)).fetchall()

    @staticmethod
    def _preview(message_type, text):
        if message_type == "file_status":
            return text
        return text
