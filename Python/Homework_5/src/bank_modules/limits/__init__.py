from datetime import datetime, timezone
from core.protocols import Repository
from core.events import OperationRejected

class Plugin:
    name = 'limits'

    def initialize(self, ctx):
        self.repo = ctx.registry.get(Repository)
        self.daily = int(ctx.config.get('daily_limit_cents', 10000000))
        self.monthly = int(ctx.config.get('monthly_limit_cents', 50000000))
        self.deposit_max = int(ctx.config.get('single_deposit_limit_cents', 100000000))
        for name in ('deposit.requested', 'withdrawal.requested', 'transfer.requested'):
            ctx.events.subscribe(name, self.check)

    def check(self, name, p):
        amount = p['amount']
        if amount <= 0:
            raise OperationRejected('Amount must be positive')
        if name == 'deposit.requested':
            if amount > self.deposit_max:
                raise OperationRejected('Deposit maximum exceeded')
            return
        src = p['account_id'] if name == 'withdrawal.requested' else p['from']
        now = datetime.now(timezone.utc)
        start_day = now.strftime('%Y-%m-%d')
        start_month = now.strftime('%Y-%m')
        kinds = "('withdrawal','transfer','external_transfer','exchange')"
        sql = f"SELECT COALESCE(SUM(amount),0) AS total FROM operations WHERE src=? AND status='completed' AND kind IN {kinds} AND substr(ts,1,?)=?"
        day = self.repo.one(sql, (src, 10, start_day))['total']
        month = self.repo.one(sql, (src, 7, start_month))['total']
        if day + amount > self.daily or month + amount > self.monthly:
            raise OperationRejected('Daily or monthly limit exceeded')

    def register_commands(self, commands):
        pass
