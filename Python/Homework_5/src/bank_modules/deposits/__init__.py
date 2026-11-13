from core.protocols import AccountsAPI, Repository
from core.events import OperationRejected
from core.utils import cents, now, operation_id

class Plugin:
    name='deposits'
    def initialize(self,ctx):
        self.ctx=ctx
        self.repo=ctx.registry.get(Repository)
        self.accounts=ctx.registry.get(AccountsAPI)
    def perform(self,account_id,amount):
        value=cents(amount)
        account=self.accounts.account(account_id)
        self.ctx.events.publish('deposit.requested',account_id=account_id,amount=value,currency=account['currency'])
        oid=operation_id()
        with self.repo.transaction():
            self.accounts.credit(account_id,value)
            self.repo.execute('INSERT INTO operations(id,kind,dst,amount,ts) VALUES(?,?,?,?,?)',(oid,'deposit',account_id,value,now()))
        self.ctx.events.notify('money.deposited',operation_id=oid,account_id=account_id,amount=value,currency=account['currency'],ts=now())
        return oid
    def register_commands(self, commands):
        commands.register('deposit','deposit ACCOUNT_ID AMOUNT',lambda s,a,v: f'Операция {self.perform(s.owned(a),v)}')
