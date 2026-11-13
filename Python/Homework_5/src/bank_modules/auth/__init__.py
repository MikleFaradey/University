import hashlib, hmac, secrets, os
from core.protocols import Repository, AuthAPI
from core.utils import now

class Plugin:
    name = 'auth'
    def initialize(self, ctx):
        self.ctx = ctx
        self.repo = ctx.registry.get(Repository)
        ctx.registry.provide(AuthAPI, self)
        # Initial administrator only when the owner explicitly supplies a secret.
        admin_password=os.environ.get('BANK_ADMIN_PASSWORD')
        if admin_password and not self.repo.one("SELECT id FROM users WHERE role='admin'"):
            if len(admin_password)<12: raise ValueError('BANK_ADMIN_PASSWORD must contain 12+ characters')
            salt=secrets.token_hex(16)
            digest=hashlib.pbkdf2_hmac('sha256',admin_password.encode(),bytes.fromhex(salt),300000).hex()
            self.repo.execute("INSERT INTO users(login,email,password_hash,role) VALUES(?,?,?,'admin')",('admin','admin@localhost',salt+':'+digest))
    def register(self, login, email, password, role='client'):
        if role != 'client': raise ValueError('Admin accounts must be provisioned out of band')
        if not login.strip() or '@' not in email or len(password) < 8:
            raise ValueError('Login, valid email and password (8+ chars) required')
        salt = secrets.token_hex(16)
        hashed = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 300000).hex()
        cur = self.repo.execute('INSERT INTO users(login,email,password_hash,role) VALUES(?,?,?,?)', (login.strip(),email.strip(),salt+':'+hashed,role))
        self.ctx.events.notify('user.registered', user_id=cur.lastrowid, login=login, role=role)
        return cur.lastrowid
    def login(self, login, password):
        user = self.repo.one('SELECT * FROM users WHERE login=?', (login,))
        if not user: raise ValueError('Invalid login or password')
        if user['blocked']: raise ValueError('User is blocked')
        salt, digest = user['password_hash'].split(':')
        actual = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 300000)
        if not hmac.compare_digest(actual, bytes.fromhex(digest)):
            raise ValueError('Invalid login or password')
        self.ctx.events.notify('user.logged_in', user_id=user['id'], ts=now())
        return {'id': user['id'], 'login': user['login'], 'role': user['role']}
    def register_commands(self, commands):
        def login(s, login, password):
            s.user=self.login(login,password)
            return f"Вход: {s.user['login']} (роль: {s.user['role']})"
        def logout(s):
            s.user=None
            return 'Выход выполнен'
        commands.register('register','register LOGIN EMAIL PASSWORD',lambda s,a,b,c: f'Новый пользователь #{self.register(a,b,c)}')
        commands.register('login','login LOGIN PASSWORD',login)
        commands.register('logout','logout',logout)
