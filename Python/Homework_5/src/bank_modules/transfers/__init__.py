from core.protocols import AccountsAPI, Repository, CurrencyAPI
from core.events import OperationRejected
from core.utils import cents, now, operation_id

class Plugin:
    name = 'transfers'

    def initialize(self, ctx):
        self.ctx = ctx
        self.repo = ctx.registry.get(Repository)
        self.accounts = ctx.registry.get(AccountsAPI)

    def perform(self, source, target, amount):
        value = cents(amount)
        try:
            if source == target:
                raise ValueError('Cannot transfer to the same account')
            source_account = self.accounts.account(source)
            target_account = self.accounts.account(target)
            if source_account['currency'] != target_account['currency']:
                raise ValueError('Use same-currency accounts')
            decision = self.ctx.events.publish('transfer.requested', **{'from': source, 'to': target}, amount=value, currency=source_account['currency'])
            fee = decision.get('fee', 0)
            transaction_id = operation_id()
            with self.repo.transaction():
                self.accounts.debit(source, value + fee)
                self.accounts.credit(target, value)
                self.repo.execute('INSERT INTO operations(id,kind,src,dst,amount,fee,ts) VALUES(?,?,?,?,?,?,?)', (transaction_id, 'transfer', source, target, value, fee, now()))
        except (ValueError, OperationRejected) as error:
            self.ctx.events.notify('transfer.rejected', **{'from': source, 'to': target}, amount=value, reason=str(error))
            raise
        self.ctx.events.notify('transfer.completed', operation_id=transaction_id, **{'from': source, 'to': target}, amount=value, fee=fee, ts=now())
        return transaction_id

    def external(self, source, reference, amount):
        value = cents(amount)
        if not reference.strip():
            raise ValueError('External recipient reference required')
        account = self.accounts.account(source)
        try:
            decision = self.ctx.events.publish('transfer.requested', **{'from': source, 'to': None}, amount=value, currency=account['currency'])
            fee = decision.get('fee', 0)
            transaction_id = operation_id()
            with self.repo.transaction():
                self.accounts.debit(source, value + fee)
                self.repo.execute('INSERT INTO operations(id,kind,src,amount,fee,recipient_ref,ts) VALUES(?,?,?,?,?,?,?)', (transaction_id, 'external_transfer', source, value, fee, reference, now()))
        except (ValueError, OperationRejected) as error:
            self.ctx.events.notify('transfer.rejected', **{'from': source, 'to': None}, amount=value, reason=str(error))
            raise
        self.ctx.events.notify('transfer.completed', operation_id=transaction_id, **{'from': source, 'to': None}, amount=value, fee=fee, reference=reference, ts=now())
        return transaction_id

    def exchange(self, source, target, amount):
        value = cents(amount)
        try:
            if source == target:
                raise ValueError('Same account')
            source_account, target_account = (self.accounts.account(source), self.accounts.account(target))
            if source_account['owner_id'] != target_account['owner_id']:
                raise ValueError('Exchange only between own accounts')
            converter = self.ctx.registry.get(CurrencyAPI)
            received = converter.convert(value, source_account['currency'], target_account['currency'])
            if received <= 0:
                raise ValueError('Amount rounds to zero')
            decision = self.ctx.events.publish('transfer.requested', amount=value, currency=source_account['currency'], operation_kind='exchange', **{'from': source, 'to': target})
            fee = decision.get('fee', 0)
            transaction_id = operation_id()
            with self.repo.transaction():
                self.accounts.debit(source, value + fee)
                self.accounts.credit(target, received)
                self.repo.execute('INSERT INTO operations(id,kind,src,dst,amount,fee,received,ts) VALUES(?,?,?,?,?,?,?,?)', (transaction_id, 'exchange', source, target, value, fee, received, now()))
        except (ValueError, OperationRejected) as error:
            self.ctx.events.notify('transfer.rejected', amount=value, reason=str(error), **{'from': source, 'to': target})
            raise
        self.ctx.events.notify('transfer.completed', operation_id=transaction_id, amount=value, received=received, currency=target_account['currency'], fee=fee, operation_kind='exchange', ts=now(), **{'from': source, 'to': target})
        return (transaction_id, received)

    def register_commands(self, commands):
        commands.register('transfer', 'transfer SOURCE_ID TARGET_ID AMOUNT', lambda s, a, b, v: f'Операция {self.perform(s.owned(a), int(b), v)}')
        commands.register('external', 'external SOURCE_ID RECIPIENT_REFERENCE AMOUNT (simulated)', lambda s, a, ref, v: f'Операция {self.external(s.owned(a), ref, v)}')
        if self.ctx.registry.optional(CurrencyAPI):
            commands.register('exchange', 'exchange SOURCE_ID TARGET_ID AMOUNT', lambda s, a, b, v: f'Обмен: {self.exchange(s.owned(a), s.owned(b), v)}')
