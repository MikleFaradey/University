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
    pass

class UserStore:

    def __init__(self, path: str | Path='users.sqlite3'):
        self.path = str(path)
        self._keeper = None
        self._uri = False
        if self.path == ':memory:':
            self.path = f'file:cve_userstore_{uuid.uuid4().hex}?mode=memory&cache=shared'
            self._uri = True
            self._keeper = sqlite3.connect(self.path, uri=True, timeout=10)
        else:
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS users (\n                id INTEGER PRIMARY KEY,\n                login TEXT NOT NULL COLLATE NOCASE UNIQUE,\n                email TEXT NOT NULL COLLATE NOCASE UNIQUE,\n                salt TEXT NOT NULL,\n                password_hash TEXT NOT NULL,\n                settings TEXT NOT NULL DEFAULT '{}'\n            )")

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.path, uri=self._uri, timeout=10)
        connection.execute('PRAGMA busy_timeout = 10000')
        try:
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def close(self):
        if self._keeper is not None:
            self._keeper.close()
            self._keeper = None

    @staticmethod
    def _hash(password: str, salt: bytes) -> str:
        return hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 310000).hex()

    def register(self, login: str, email: str, password: str, confirm: str) -> int:
        login, email = (login.strip(), email.strip().lower())
        if not re.fullmatch('[\\w.-]{3,32}', login, re.UNICODE):
            raise AuthError('Логин: 3–32 символа (буквы, цифры, _, ., -).')
        if not re.fullmatch('[^\\s@]+@[^\\s@]+\\.[^\\s@]+', email):
            raise AuthError('Укажите корректный e-mail.')
        if not 8 <= len(password) <= 128:
            raise AuthError('Пароль должен содержать от 8 до 128 символов.')
        if password != confirm:
            raise AuthError('Пароли не совпадают.')
        salt = secrets.token_bytes(16)
        try:
            with self._connect() as connection:
                cursor = connection.execute('INSERT INTO users(login,email,salt,password_hash) VALUES(?,?,?,?)', (login, email, salt.hex(), self._hash(password, salt)))
                return cursor.lastrowid
        except sqlite3.IntegrityError as exc:
            raise AuthError('Логин или e-mail уже зарегистрирован.') from exc

    def authenticate(self, login: str, password: str) -> dict:
        with self._connect() as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute('SELECT * FROM users WHERE login=?', (login.strip(),)).fetchone()
        if row is None or not hmac.compare_digest(self._hash(password, bytes.fromhex(row['salt'])) if row is not None else '', row['password_hash'] if row is not None else ''):
            raise AuthError('Неверный логин или пароль.')
        return {'id': row['id'], 'login': row['login']}

    def save_settings(self, user_id: int, settings: dict) -> None:
        payload = json.dumps(settings, ensure_ascii=False, allow_nan=False)
        with self._connect() as connection:
            cursor = connection.execute('UPDATE users SET settings=? WHERE id=?', (payload, user_id))
            if cursor.rowcount != 1:
                raise AuthError('Пользователь не найден.')

    def load_settings(self, user_id: int) -> dict:
        with self._connect() as connection:
            row = connection.execute('SELECT settings FROM users WHERE id=?', (user_id,)).fetchone()
        if row is None:
            raise AuthError('Пользователь не найден.')
        try:
            data = json.loads(row[0])
            return data if isinstance(data, dict) else {}
        except (ValueError, TypeError):
            return {}
