from core.protocols import Repository, BonusAPI

class Plugin:
    name = 'bonus_points'

    def initialize(self, ctx):
        self.repo = ctx.registry.get(Repository)
        ctx.registry.provide(BonusAPI, self)
        for event in ('money.deposited', 'transfer.completed'):
            ctx.events.subscribe(event, self.award)
        ctx.events.subscribe('operation.reversed', self.reverse_award)

    def award(self, event, p):
        account_id = p['account_id'] if event == 'money.deposited' else p['from']
        account = self.repo.one('SELECT owner_id FROM accounts WHERE id=?', (account_id,))
        if not account:
            return
        points = p['amount'] // 10000
        if not points:
            return
        op_id = p['operation_id']
        if self.repo.one('SELECT 1 AS ok FROM bonus_awards WHERE operation_id=?', (op_id,)):
            return
        self.repo.execute('INSERT INTO bonus_awards(operation_id,owner_id,points) VALUES(?,?,?)', (op_id, account['owner_id'], points))
        self.repo.execute('INSERT INTO bonuses(owner_id,points) VALUES(?,?) ON CONFLICT(owner_id) DO UPDATE SET points=points+excluded.points', (account['owner_id'], points))

    def reverse_award(self, event, p):
        entry = self.repo.one('SELECT * FROM bonus_awards WHERE operation_id=?', (p['operation_id'],))
        if not entry:
            return
        self.repo.execute('UPDATE bonuses SET points=points-? WHERE owner_id=?', (entry['points'], entry['owner_id']))
        self.repo.execute('DELETE FROM bonus_awards WHERE operation_id=?', (p['operation_id'],))

    def points(self, owner_id):
        row = self.repo.one('SELECT points FROM bonuses WHERE owner_id=?', (owner_id,))
        return row['points'] if row else 0

    def register_commands(self, commands):
        commands.register('bonuses', 'bonuses', lambda s: f"Бонусы: {self.points(s.require_user()['id'])}")
