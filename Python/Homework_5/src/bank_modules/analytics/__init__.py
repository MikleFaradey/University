import json
from core.protocols import Repository
CATEGORIES = {'withdrawal': 'Снятие наличных', 'transfer': 'Переводы', 'external_transfer': 'Внешние переводы', 'exchange': 'Обмен валют', 'deposit': 'Пополнения'}

class Plugin:
    name = 'analytics'

    def initialize(self, ctx):
        self.repo = ctx.registry.get(Repository)
        self.withdrawals_seen = 0
        ctx.events.subscribe('money.withdrawn', self.on_withdrawal)
        ctx.events.subscribe('operation.reversed', self.on_reversal)

    def on_withdrawal(self, event, payload):
        self.withdrawals_seen += 1

    def on_reversal(self, event, payload):
        operation = self.repo.one('SELECT kind FROM operations WHERE id=?', (payload['operation_id'],))
        if operation and operation['kind'] == 'withdrawal':
            self.withdrawals_seen = max(0, self.withdrawals_seen - 1)

    def stats(self, owner_id):
        rows = self.repo.all("SELECT o.kind, COUNT(*) AS count,\n            COALESCE(SUM(o.amount),0) AS amount_cents,\n            COALESCE(SUM(o.fee),0) AS fees_cents\n            FROM operations o JOIN accounts a ON a.id=COALESCE(o.src,o.dst)\n            WHERE a.owner_id=? AND o.status='completed'\n            GROUP BY o.kind ORDER BY o.kind", (owner_id,))
        return {r['kind']: {'count': r['count'], 'amount_cents': r['amount_cents'], 'fees_cents': r['fees_cents']} for r in rows}

    def expenses(self, owner_id):
        rows = self.repo.all("SELECT o.kind, COUNT(*) AS count,\n            COALESCE(SUM(o.amount + o.fee),0) AS amount_cents\n            FROM operations o JOIN accounts a ON a.id=o.src\n            WHERE a.owner_id=? AND o.status='completed'\n              AND o.kind IN ('withdrawal','transfer','external_transfer','exchange')\n            GROUP BY o.kind ORDER BY amount_cents DESC", (owner_id,))
        return [{'category': CATEGORIES[r['kind']], **r} for r in rows]

    def top(self, owner_id, limit=10):
        return self.repo.all("SELECT o.id,o.kind,o.amount,o.fee,o.ts\n            FROM operations o JOIN accounts a ON a.id=o.src\n            WHERE a.owner_id=? AND o.status='completed'\n              AND o.kind IN ('withdrawal','transfer','external_transfer','exchange')\n            ORDER BY (o.amount+o.fee) DESC,o.ts DESC LIMIT ?", (owner_id, limit))

    def register_commands(self, commands):
        commands.register('stats', 'stats (all operations)', lambda s: json.dumps(self.stats(s.require_user()['id']), ensure_ascii=False, indent=2))
        commands.register('expenses', 'expenses (spending by category)', lambda s: json.dumps(self.expenses(s.require_user()['id']), ensure_ascii=False, indent=2))
        commands.register('top', 'top (10 largest spending operations)', lambda s: json.dumps(self.top(s.require_user()['id']), ensure_ascii=False, indent=2))
