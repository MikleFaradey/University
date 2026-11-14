from core.protocols import Repository, AccountsAPI

class Plugin:
    name = 'accounts'

    def initialize(self, ctx):
        self.ctx = ctx
        self.repo = ctx.registry.get(Repository)
        ctx.registry.provide(AccountsAPI, self)
        ctx.events.subscribe('operation.reverse.requested', self._reverse)
        ctx.events.subscribe('operation.reversed', self._reversed)

    def _reverse(self, event, p):
        operation_identifier = p['operation_id']
        with self.repo.transaction():
            op = self.repo.one('SELECT * FROM operations WHERE id=?', (operation_identifier,))
            if op is None:
                raise ValueError('Operation not found')
            if op['status'] != 'completed':
                raise ValueError('Operation already reversed or not completed')
            kind = op['kind']
            amount = op['amount']
            fee = op['fee']
            if kind == 'deposit':
                self.debit(op['dst'], amount)
            elif kind == 'withdrawal':
                self.credit(op['src'], amount)
            elif kind == 'transfer':
                self.debit(op['dst'], amount)
                self.credit(op['src'], amount + fee)
            elif kind == 'external_transfer':
                self.credit(op['src'], amount + fee)
            elif kind == 'exchange':
                self.debit(op['dst'], op['received'])
                self.credit(op['src'], amount + fee)
            else:
                raise ValueError('Unsupported reversal kind: ' + kind)
            self.repo.execute("UPDATE operations SET status='reversed' WHERE id=? AND status='completed'", (operation_identifier,))

    def _reversed(self, event, p):
        operation = self.repo.one('SELECT status FROM operations WHERE id=?', (p['operation_id'],))
        if operation is None or operation['status'] != 'reversed':
            raise RuntimeError('Reversal completion without committed compensating posting')

    def open(self, owner_id, kind='current', currency='RUB'):
        if kind not in ('current', 'savings') or currency not in ('RUB', 'USD', 'EUR'):
            raise ValueError('Unknown account type or currency')
        if not self.repo.one('SELECT id FROM users WHERE id=?', (owner_id,)):
            raise ValueError('Unknown user')
        cursor = self.repo.execute('INSERT INTO accounts(owner_id,kind,currency) VALUES(?,?,?)', (owner_id, kind, currency))
        self.ctx.events.notify('account.opened', account_id=cursor.lastrowid, owner_id=owner_id, type=kind, currency=currency)
        return cursor.lastrowid

    def account(self, account_id):
        value = self.repo.one('SELECT * FROM accounts WHERE id=?', (account_id,))
        if value is None or value['closed']:
            raise ValueError('Account missing or closed')
        return value

    def debit(self, account_id, value):
        if value <= 0:
            raise ValueError('Debit must be positive')
        cursor = self.repo.execute('UPDATE accounts SET balance=balance-? WHERE id=? AND closed=0 AND balance>=?', (value, account_id, value))
        if cursor.rowcount != 1:
            raise ValueError('Insufficient balance or account unavailable')

    def credit(self, account_id, value):
        if value <= 0:
            raise ValueError('Credit must be positive')
        cursor = self.repo.execute('UPDATE accounts SET balance=balance+? WHERE id=? AND closed=0', (value, account_id))
        if cursor.rowcount != 1:
            raise ValueError('Account unavailable')

    def close(self, account_id):
        a = self.account(account_id)
        if a['balance'] != 0:
            raise ValueError('Balance must equal zero')
        self.repo.execute('UPDATE accounts SET closed=1 WHERE id=?', (account_id,))
        self.ctx.events.notify('account.closed', account_id=account_id)

    def list(self, owner_id):
        return self.repo.all('SELECT * FROM accounts WHERE owner_id=? AND closed=0', (owner_id,))

    def register_commands(self, commands):
        from core.utils import money
        commands.register('open', 'open current|savings RUB|USD|EUR', lambda s, k, c: f"Счёт #{self.open(s.require_user()['id'], k, c)}")
        commands.register('accounts', 'accounts', lambda s: '\n'.join((f"{a['id']}: {a['kind']} {a['currency']} {money(a['balance'])}" for a in self.list(s.require_user()['id']))) or 'Нет счетов')
        commands.register('balance', 'balance ACCOUNT_ID', lambda s, a: f"{money(self.account(s.owned(a))['balance'])} {self.account(s.owned(a))['currency']}")
        commands.register('close', 'close ACCOUNT_ID', lambda s, a: self.close(s.owned(a)) or 'Счёт закрыт')
