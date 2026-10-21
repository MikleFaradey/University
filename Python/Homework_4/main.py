"""Учебный TCP-банк: TLS, SQLite-транзакции и ограниченные ресурсы."""
import hashlib
import hmac
import json
import logging
import os
from pathlib import Path
import re
import secrets
import socket
import sqlite3
import ssl
import threading
import time
from contextlib import contextmanager
from decimal import Decimal

LOG = logging.getLogger("bank")
MAX_LINE = 2048
COMMAND_TIMEOUT = 10
MAX_CONNECTIONS = 32
MAX_BALANCE = 100_000_000_000  # копейки
LOGIN_RE = re.compile(r"[a-zA-Z0-9_]{1,32}\Z")
REQUEST_RE = re.compile(r"[a-zA-Z0-9_-]{16,64}\Z")


def password_hash(password, salt):
    return hashlib.scrypt(password.encode(), salt=salt, n=2**15, r=8,
                          p=1, dklen=32, maxmem=64 * 1024 * 1024)


def money(value):
    if not re.fullmatch(r"[0-9]{1,9}(?:\.[0-9]{1,2})?", value):
        raise ValueError("Invalid amount")
    cents = int(Decimal(value) * 100)
    if not 0 < cents <= MAX_BALANCE:
        raise ValueError("Invalid amount")
    return cents


def display(cents):
    return f"{cents // 100}.{cents % 100:02d}"


class Bank:
    def __init__(self, path, credentials=None):
        self.path = str(path)
        self.auth_lock = threading.Lock()
        self.attempts = {}  # только три известных аккаунта; не растёт от чужих логинов
        self.auth_slots = threading.BoundedSemaphore(2)
        self.dummy_salt = secrets.token_bytes(16)
        self.dummy_hash = password_hash(secrets.token_urlsafe(32), self.dummy_salt)
        Path(path).parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY, login TEXT UNIQUE NOT NULL,
                    salt BLOB NOT NULL, password_hash BLOB NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('admin','user')),
                    balance INTEGER NOT NULL CHECK(balance >= 0 AND balance <= 100000000000)
                );
                CREATE TABLE IF NOT EXISTS transactions (
                    id INTEGER PRIMARY KEY, ts TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    from_id INTEGER NOT NULL REFERENCES users(id),
                    to_id INTEGER NOT NULL REFERENCES users(id),
                    amount INTEGER NOT NULL CHECK(amount > 0),
                    request_id TEXT NOT NULL, comment TEXT NOT NULL,
                    UNIQUE(from_id, request_id), CHECK(from_id != to_id)
                );
            ''')
            if db.execute('SELECT count(*) FROM users').fetchone()[0] == 0:
                if credentials is None or set(credentials) != {'admin', 'alice', 'bob'}:
                    raise ValueError('Initial credentials for admin, alice and bob required')
                for uid, (login, balance) in enumerate(
                        [('admin', 100000000), ('alice', 500000), ('bob', 10000)], 1):
                    password = credentials[login]
                    if not isinstance(password, str) or not 16 <= len(password) <= 128 or any(c.isspace() for c in password):
                        raise ValueError('Passwords must have 16–128 non-whitespace characters')
                    salt = secrets.token_bytes(16)
                    db.execute('INSERT INTO users VALUES (?, ?, ?, ?, ?, ?)',
                               (uid, login, salt, password_hash(password, salt),
                                'admin' if uid == 1 else 'user', balance))
        os.chmod(self.path, 0o600)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys = ON')
        try:
            with db:
                yield db
        finally:
            db.close()

    def login(self, login, password):
        if not LOGIN_RE.fullmatch(login) or not 1 <= len(password) <= 128:
            return None
        if not self.auth_slots.acquire(blocking=False):
            return None
        try:
            with self.connect() as db:
                row = db.execute('SELECT * FROM users WHERE login = ?', (login,)).fetchone()
            # Учитываем попытку ДО дорогого хеширования, в том числе при параллельном входе.
            if row:
                with self.auth_lock:
                    now = time.monotonic()
                    attempts = [t for t in self.attempts.get(login, []) if now - t < 60]
                    if len(attempts) >= 5:
                        return None
                    self.attempts[login] = attempts + [now]
            salt = row['salt'] if row else self.dummy_salt
            expected = row['password_hash'] if row else self.dummy_hash
            valid = hmac.compare_digest(password_hash(password, salt), expected)
            return row['id'] if row and valid else None
        finally:
            self.auth_slots.release()

    def transfer(self, uid, to_id, amount, request_id, comment):
        if not REQUEST_RE.fullmatch(request_id) or len(comment) > 200:
            raise ValueError('Invalid request ID or comment')
        cents = money(amount)
        if to_id == uid:
            raise ValueError('Self-transfer forbidden')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            previous = db.execute('SELECT * FROM transactions WHERE from_id=? AND request_id=?',
                                  (uid, request_id)).fetchone()
            if previous:
                if (previous['to_id'], previous['amount'], previous['comment']) != (to_id, cents, comment):
                    raise ValueError('Request ID conflict')
                return f"OK|Already processed|tx={previous['id']}"
            receiver = db.execute('SELECT balance FROM users WHERE id=?', (to_id,)).fetchone()
            if receiver is None or receiver['balance'] + cents > MAX_BALANCE:
                raise ValueError('Invalid recipient or balance limit')
            changed = db.execute('UPDATE users SET balance=balance-? WHERE id=? AND balance>=?',
                                 (cents, uid, cents)).rowcount
            if changed != 1:
                raise ValueError('Insufficient funds')
            db.execute('UPDATE users SET balance=balance+? WHERE id=?', (cents, to_id))
            tx = db.execute('INSERT INTO transactions(from_id,to_id,amount,request_id,comment) VALUES (?,?,?,?,?)',
                            (uid, to_id, cents, request_id, comment))
            tx_id = tx.lastrowid
        LOG.info('transfer committed uid=%d tx=%d', uid, tx_id)
        return f'OK|Transfer completed|tx={tx_id}'

    def command(self, uid, line):
        if any(ord(c) < 32 or ord(c) == 127 for c in line):
            raise ValueError('Control characters forbidden')
        parts = line.split()
        if not parts:
            raise ValueError('Empty command')
        cmd, args = parts[0].upper(), parts[1:]
        if cmd == 'QUIT' and not args:
            return uid, 'BYE'
        if cmd == 'HELP' and not args:
            return uid, 'OK|LOGIN login password; BALANCE; TRANSFER to amount request_id [comment]; HISTORY [uid]; ADMIN USERS; QUIT'
        if cmd == 'LOGIN':
            # Любая неудачная повторная авторизация сбрасывает предыдущую сессию.
            new_uid = self.login(*args) if len(args) == 2 else None
            LOG.info('login result=%s', 'success' if new_uid else 'denied')
            return new_uid, 'OK|Logged in' if new_uid else 'FAIL|Invalid credentials or rate limit'
        if uid is None:
            return None, 'ERR|Login required'
        with self.connect() as db:
            user = db.execute('SELECT id, role, balance FROM users WHERE id=?', (uid,)).fetchone()
            if cmd == 'BALANCE' and not args:
                return uid, 'OK|' + display(user['balance'])
            if cmd == 'HISTORY' and len(args) <= 1:
                target = int(args[0]) if args else uid
                if target != uid:
                    return uid, 'ERR|Access denied'
                rows = db.execute('SELECT id,ts,from_id,to_id,amount,comment FROM transactions WHERE from_id=? OR to_id=? ORDER BY id DESC LIMIT 100', (uid, uid)).fetchall()
                return uid, 'OK|' + json.dumps([dict(r) for r in rows], ensure_ascii=True)
            if cmd == 'ADMIN':
                if user['role'] != 'admin' or args != ['USERS']:
                    return uid, 'ERR|Access denied or unsupported admin operation'
                rows = db.execute('SELECT id,login,role,balance FROM users').fetchall()
                return uid, 'OK|' + json.dumps([dict(r) for r in rows])
        if cmd == 'TRANSFER' and len(args) >= 3:
            return uid, self.transfer(uid, int(args[0]), args[1], args[2], ' '.join(args[3:]))
        raise ValueError('Invalid command format')


def read_line(conn, buffer):
    deadline = time.monotonic() + COMMAND_TIMEOUT
    while b'\n' not in buffer:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('Line deadline')
        conn.settimeout(remaining)
        chunk = conn.recv(min(1024, MAX_LINE + 1 - len(buffer)))
        if not chunk:
            raise EOFError
        buffer += chunk
        if len(buffer) > MAX_LINE and b'\n' not in buffer:
            raise ValueError('Line too long')
    raw, buffer = buffer.split(b'\n', 1)
    if len(raw) > MAX_LINE:
        raise ValueError('Line too long')
    return raw.decode('utf-8'), buffer


def handle_client(conn, bank):
    uid, buffer = None, b''
    try:
        conn.settimeout(COMMAND_TIMEOUT)
        conn.sendall(b'BANK SERVER READY\n')
        started = time.monotonic()
        for _ in range(200):  # конечный бюджет команд и срок жизни сессии
            if time.monotonic() - started > 300:
                break
            line, buffer = read_line(conn, buffer)
            try:
                uid, reply = bank.command(uid, line)
            except ValueError:
                # Не возвращаем исключения, SQL, пароль или содержимое запроса.
                reply = 'ERR|Invalid request'
            except sqlite3.Error:
                LOG.error('database operation failed')
                reply = 'ERR|Storage unavailable'
            LOG.info('request uid=%s result=%s', uid, reply.split('|', 1)[0])
            conn.settimeout(COMMAND_TIMEOUT)
            conn.sendall((reply + '\n').encode())
            if reply == 'BYE':
                break
    except (OSError, EOFError, ValueError):
        LOG.info('connection closed or invalid frame')
    finally:
        conn.close()


def run_server():
    os.umask(0o077)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    data_path = Path(os.environ.get('BANK_DB', 'data/bank.sqlite3'))
    credentials = None
    if not data_path.exists():
        credentials = json.loads(Path(os.environ.get('BANK_CREDENTIALS_FILE', 'secrets/users.json')).read_text())
    bank = Bank(data_path, credentials)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(os.environ.get('BANK_CERT', 'secrets/server.crt'),
                            os.environ.get('BANK_KEY', 'secrets/server.key'))
    slots = threading.BoundedSemaphore(MAX_CONNECTIONS)

    def worker(raw):
        try:
            raw.settimeout(5)
            with context.wrap_socket(raw, server_side=True) as conn:
                handle_client(conn, bank)
        except OSError:
            LOG.info('TLS connection rejected')
        finally:
            raw.close()
            slots.release()

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((os.environ.get('BANK_HOST', '127.0.0.1'), 9999))
        srv.listen(32)
        LOG.info('TLS bank ready port=9999')
        while True:
            conn, _ = srv.accept()
            if not slots.acquire(blocking=False):
                conn.close()
                continue
            threading.Thread(target=worker, args=(conn,), daemon=True).start()


if __name__ == '__main__':
    run_server()
