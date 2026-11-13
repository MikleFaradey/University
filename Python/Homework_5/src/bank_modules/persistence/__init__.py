import sqlite3
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from core.protocols import Repository

SCHEMA = '''
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, login TEXT UNIQUE NOT NULL, email TEXT NOT NULL, password_hash TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'client', blocked INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS accounts(id INTEGER PRIMARY KEY, owner_id INTEGER NOT NULL REFERENCES users(id), kind TEXT NOT NULL, currency TEXT NOT NULL, balance INTEGER NOT NULL DEFAULT 0, closed INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS operations(id TEXT PRIMARY KEY, kind TEXT NOT NULL, src INTEGER, dst INTEGER, amount INTEGER NOT NULL, fee INTEGER NOT NULL DEFAULT 0, received INTEGER, recipient_ref TEXT, ts TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'completed');
CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, event TEXT NOT NULL, payload TEXT NOT NULL, ts TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY, event TEXT NOT NULL, message TEXT NOT NULL, ts TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS bonuses(owner_id INTEGER PRIMARY KEY, points INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS bonus_awards(operation_id TEXT PRIMARY KEY, owner_id INTEGER NOT NULL, points INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS event_projection(id INTEGER PRIMARY KEY, event TEXT NOT NULL, payload TEXT NOT NULL, ts TEXT NOT NULL);
'''

class SQLiteRepository:
    def __init__(self, path):
        if path != ':memory:': Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.execute('PRAGMA busy_timeout=5000')
        self.db.executescript(SCHEMA)
    def close(self): self.db.close()
    def execute(self, sql, args=()): return self.db.execute(sql, args)
    def one(self, sql, args=()):
        row = self.db.execute(sql, args).fetchone()
        return dict(row) if row else None
    def all(self, sql, args=()): return [dict(x) for x in self.db.execute(sql, args).fetchall()]
    @contextmanager
    def transaction(self):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            yield
            self.db.execute('COMMIT')
        except Exception:
            self.db.execute('ROLLBACK')
            raise

class JSONRepository(SQLiteRepository):
    """JSON-file snapshot adapter, with SQLite as the in-memory query engine.

    The JSON file contains a SQL dump for exact round-trip of the educational
    relational schema. Commit uses atomic os.replace; no database file on disk.
    """
    def __init__(self, path):
        self.path=Path(path)
        self.path.parent.mkdir(parents=True,exist_ok=True)
        super().__init__(':memory:')
        if self.path.exists():
            data=json.loads(self.path.read_text(encoding='utf-8'))
            if data.get('format')!='bank-json-sql-v1':
                raise ValueError('Unsupported JSON repository format')
            # Rebuild from scratch: the dump contains its own CREATE TABLE statements.
            self.db.close()
            self.db=sqlite3.connect(':memory:',isolation_level=None)
            self.db.row_factory=sqlite3.Row
            self.db.execute('PRAGMA foreign_keys=OFF')
            self.db.executescript(data['sql'])
            self.db.execute('PRAGMA foreign_keys=ON')
            assert self.db.execute('PRAGMA foreign_key_check').fetchone() is None, 'Invalid JSON snapshot foreign keys'

    def _save(self):
        payload={'format':'bank-json-sql-v1','sql':'\n'.join(self.db.iterdump())}
        fd,temporary=tempfile.mkstemp(prefix='.bank-',suffix='.json',dir=self.path.parent)
        try:
            with os.fdopen(fd,'w',encoding='utf-8') as stream:
                json.dump(payload,stream,ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary,self.path)
        finally:
            if os.path.exists(temporary): os.unlink(temporary)

    def execute(self,sql,args=()):
        result=super().execute(sql,args)
        if not self.db.in_transaction and sql.lstrip().split(None,1)[0].upper() not in ('SELECT','PRAGMA','WITH'):
            self._save()
        return result

    @contextmanager
    def transaction(self):
        with super().transaction():
            yield
        self._save()

    def close(self):
        self._save()
        super().close()

class Plugin:
    name = 'persistence'
    def initialize(self, ctx):
        backend=ctx.config.get('storage_backend','sqlite')
        filename=ctx.config.get('database','bank.sqlite3')
        if backend=='sqlite': self.repository=SQLiteRepository(filename)
        elif backend=='memory': self.repository=SQLiteRepository(':memory:')
        elif backend=='json': self.repository=JSONRepository(ctx.config.get('json_database','bank.json'))
        else: raise ValueError('Unknown storage_backend: '+str(backend))
        ctx.registry.provide(Repository, self.repository)
    def register_commands(self, commands):
        pass
