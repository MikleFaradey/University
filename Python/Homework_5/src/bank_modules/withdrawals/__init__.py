from core.protocols import AccountsAPI, Repository
from core.utils import cents, now, operation_id

class Plugin:
    name='withdrawals'
    def initialize(self,ctx):
        self.ctx=ctx
        self.repo=ctx.registry.get(Repository)
        self.accounts=ctx.registry.get(AccountsAPI)
    def perform(self,account_id,amount):
        value=cents(amount)
        self.accounts.account(account_id)
        self.ctx.events.publish('withdrawal.requested',account_id=account_id,amount=value)
        oid=operation_id()
        with self.repo.transaction():
            self.accounts.debit(account_id,value)
            self.repo.execute('INSERT INTO operations(id,kind,src,amount,ts) VALUES(?,?,?,?,?)',(oid,'withdrawal',account_id,value,now()))
        self.ctx.events.notify('money.withdrawn',operation_id=oid,account_id=account_id,amount=value,ts=now())
        return oid
    def register_commands(self, commands):
        commands.register('withdraw','withdraw ACCOUNT_ID AMOUNT',lambda s,a,v: f'Операция {self.perform(s.owned(a),v)}')
