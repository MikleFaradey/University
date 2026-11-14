import json
from core.protocols import Repository
from core.utils import now

class Plugin:
    name = 'audit_log'

    def initialize(self, ctx):
        self.repo = ctx.registry.get(Repository)
        self.ctx = ctx
        for event in ('user.registered', 'user.logged_in', 'account.opened', 'account.closed', 'deposit.requested', 'money.deposited', 'withdrawal.requested', 'money.withdrawn', 'transfer.requested', 'transfer.completed', 'transfer.rejected', 'fee.charged', 'fraud.detected', 'operation.reversed'):
            ctx.events.subscribe(event, self.record)

    def record(self, event, payload):
        self.repo.execute('INSERT INTO audit(event,payload,ts) VALUES(?,?,?)', (event, json.dumps(payload, ensure_ascii=False), now()))

    def register_commands(self, commands):
        import json
        commands.register('audit', 'audit (admin only)', lambda s: json.dumps(self.repo.all('SELECT * FROM audit ORDER BY id DESC LIMIT 30'), ensure_ascii=False, indent=2) if s.require_user()['role'] == 'admin' else (_ for _ in ()).throw(ValueError('Только администратор')))

        def events(s):
            if s.require_user()['role'] != 'admin':
                raise ValueError('Admin privileges required')
            return json.dumps([{'event': e, 'payload': p} for e, p in self.ctx.events.history[-50:]], ensure_ascii=False, indent=2)
        commands.register('events', 'events (admin only; recent EventBus events)', events)
