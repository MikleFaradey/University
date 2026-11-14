from core.protocols import Repository

class Plugin:
    name = 'admin'

    def initialize(self, ctx):
        self.repo = ctx.registry.get(Repository)
        self.ctx = ctx
        ctx.events.subscribe('fraud.detected', self.fraud_alert)

    def fraud_alert(self, event, p):
        import json
        from core.utils import now
        self.repo.execute('INSERT INTO audit(event,payload,ts) VALUES(?,?,?)', ('admin.fraud_alert', json.dumps(p, ensure_ascii=False), now()))

    def _admin(self, session):
        if session.require_user()['role'] != 'admin':
            raise ValueError('Admin privileges required')

    def register_commands(self, commands):

        def users(s):
            self._admin(s)
            return '\n'.join((f"{u['id']} {u['login']} {u['role']} {('BLOCKED' if u['blocked'] else 'ACTIVE')}" for u in self.repo.all('SELECT id,login,role,blocked FROM users ORDER BY id')))

        def block(s, user_id, flag):
            self._admin(s)
            user = self.repo.one('SELECT * FROM users WHERE id=?', (int(user_id),))
            if not user:
                raise ValueError('Unknown user')
            if user['role'] == 'admin':
                raise ValueError('Admin cannot be blocked')
            self.repo.execute('UPDATE users SET blocked=? WHERE id=?', (flag, int(user_id)))
            self.ctx.events.notify('user.blocked' if flag else 'user.unblocked', user_id=int(user_id))
            return 'Updated'
        commands.register('admin-users', 'admin-users', users)
        commands.register('block-user', 'block-user ID', lambda s, a: block(s, a, 1))
        commands.register('unblock-user', 'unblock-user ID', lambda s, a: block(s, a, 0))
