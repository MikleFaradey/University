"""Thread-safe SQLite-backed users, password hashing, isolated preferences."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import hmac
import json
from pathlib import Path
import re
import secrets
import sqlite3
import uuid


class AuthError(ValueError):
    """Expected user-facing input or authentication error."""


class UserStore:
    def __init__(self, path: str | Path = 'users.sqlite3'):
        self.path = str(path)
        self._keeper = None
        self._uri = False
        if self.path == ':memory:':
            # Separate sqlite3.connect(':memory:') calls create different databases.
            # Keep a shared named in-memory database alive for this instance.
            self.path = f'file:cve_userstore_{uuid.uuid4().hex}?mode=memory&cache=shared'
            self._uri = True
            self._keeper = sqlite3.connect(self.path, uri=True, timeout=10)
        else:
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as con:
            con.execute('''CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                login TEXT NOT NULL COLLATE NOCASE UNIQUE,
                email TEXT NOT NULL COLLATE NOCASE UNIQUE,
                salt TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                settings TEXT NOT NULL DEFAULT '{}'
            )''')

    @contextmanager
    def _connect(self):
        con = sqlite3.connect(self.path, uri=self._uri, timeout=10)
        con.execute('PRAGMA busy_timeout = 10000')
        try:
            yield con
            con.commit()
        except BaseException:
            con.rollback()
            raise
        finally:
            con.close()

    def close(self):
        if self._keeper is not None:
            self._keeper.close()
            self._keeper = None

    @staticmethod
    def _hash(password: str, salt: bytes) -> str:
        return hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 310000).hex()

    def register(self, login: str, email: str, password: str, confirm: str) -> int:
        login, email = login.strip(), email.strip().lower()
        if not re.fullmatch(r'[\w.-]{3,32}', login, re.UNICODE):
            raise AuthError('Логин: 3–32 символа (буквы, цифры, _, ., -).')
        if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email):
            raise AuthError('Укажите корректный e-mail.')
        if not 8 <= len(password) <= 128:
            raise AuthError('Пароль должен содержать от 8 до 128 символов.')
        if password != confirm:
            raise AuthError('Пароли не совпадают.')
        salt = secrets.token_bytes(16)
        try:
            with self._connect() as con:
                cur = con.execute(
                    'INSERT INTO users(login,email,salt,password_hash) VALUES(?,?,?,?)',
                    (login, email, salt.hex(), self._hash(password, salt)))
                return cur.lastrowid
        except sqlite3.IntegrityError as exc:
            raise AuthError('Логин или e-mail уже зарегистрирован.') from exc

    def authenticate(self, login: str, password: str) -> dict:
        with self._connect() as con:
            con.row_factory = sqlite3.Row
            row = con.execute('SELECT * FROM users WHERE login=?', (login.strip(),)).fetchone()
        if row is None or not hmac.compare_digest(
            self._hash(password, bytes.fromhex(row['salt'])) if row is not None else '',
            row['password_hash'] if row is not None else '',
        ):
            raise AuthError('Неверный логин или пароль.')
        return {'id': row['id'], 'login': row['login']}

    def save_settings(self, user_id: int, settings: dict) -> None:
        payload = json.dumps(settings, ensure_ascii=False, allow_nan=False)
        with self._connect() as con:
            cur = con.execute('UPDATE users SET settings=? WHERE id=?', (payload, user_id))
            if cur.rowcount != 1:
                raise AuthError('Пользователь не найден.')

    def load_settings(self, user_id: int) -> dict:
        with self._connect() as con:
            row = con.execute('SELECT settings FROM users WHERE id=?', (user_id,)).fetchone()
        if row is None:
            raise AuthError('Пользователь не найден.')
        try:
            data = json.loads(row[0])
            return data if isinstance(data, dict) else {}
        except (ValueError, TypeError):
            return {}
