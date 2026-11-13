from core.protocols import AccountsAPI, Repository, CurrencyAPI
from core.events import OperationRejected
from core.utils import cents, now, operation_id

class Plugin:
    name='transfers'
    def initialize(self,ctx):
        self.ctx=ctx
        self.repo=ctx.registry.get(Repository)
        self.accounts=ctx.registry.get(AccountsAPI)
    def perform(self,source,target,amount):
        value=cents(amount)
        try:
            if source==target: raise ValueError('Cannot transfer to the same account')
            a=self.accounts.account(source)
            b=self.accounts.account(target)
            if a['currency']!=b['currency']: raise ValueError('Use same-currency accounts')
            decision=self.ctx.events.publish('transfer.requested',**{'from':source,'to':target},amount=value,currency=a['currency'])
            # Fee plugin enriches request with quote; no concrete plugin calls.
            fee=decision.get('fee',0)
            oid=operation_id()
            with self.repo.transaction():
                self.accounts.debit(source,value+fee)
                self.accounts.credit(target,value)
                self.repo.execute('INSERT INTO operations(id,kind,src,dst,amount,fee,ts) VALUES(?,?,?,?,?,?,?)',(oid,'transfer',source,target,value,fee,now()))
        except (ValueError,OperationRejected) as ex:
            self.ctx.events.notify('transfer.rejected',**{'from':source,'to':target},amount=value,reason=str(ex))
            raise
        self.ctx.events.notify('transfer.completed',operation_id=oid,**{'from':source,'to':target},amount=value,fee=fee,ts=now())
        return oid
    def external(self, source, reference, amount):
        """Simulated external payment: no external bank is contacted."""
        value=cents(amount)
        if not reference.strip(): raise ValueError('External recipient reference required')
        account=self.accounts.account(source)
        try:
            decision=self.ctx.events.publish('transfer.requested',**{'from':source,'to':None},amount=value,currency=account['currency'])
            fee=decision.get('fee',0)
            oid=operation_id()
            with self.repo.transaction():
                self.accounts.debit(source,value+fee)
                self.repo.execute('INSERT INTO operations(id,kind,src,amount,fee,recipient_ref,ts) VALUES(?,?,?,?,?,?,?)',
                    (oid,'external_transfer',source,value,fee,reference,now()))
        except (ValueError,OperationRejected) as exc:
            self.ctx.events.notify('transfer.rejected',**{'from':source,'to':None},amount=value,reason=str(exc))
            raise
        self.ctx.events.notify('transfer.completed',operation_id=oid,**{'from':source,'to':None},amount=value,fee=fee,reference=reference,ts=now())
        return oid
    def exchange(self,source,target,amount):
        value=cents(amount)
        try:
            if source==target: raise ValueError('Same account')
            a,b=self.accounts.account(source),self.accounts.account(target)
            if a['owner_id']!=b['owner_id']: raise ValueError('Exchange only between own accounts')
            converter=self.ctx.registry.get(CurrencyAPI)
            received=converter.convert(value,a['currency'],b['currency'])
            if received<=0: raise ValueError('Amount rounds to zero')
            decision=self.ctx.events.publish('transfer.requested',amount=value,currency=a['currency'],operation_kind='exchange',**{'from':source,'to':target})
            fee=decision.get('fee',0)
            oid=operation_id()
            with self.repo.transaction():
                self.accounts.debit(source,value+fee)
                self.accounts.credit(target,received)
                self.repo.execute('INSERT INTO operations(id,kind,src,dst,amount,fee,received,ts) VALUES(?,?,?,?,?,?,?,?)',
                    (oid,'exchange',source,target,value,fee,received,now()))
        except (ValueError,OperationRejected) as exc:
            self.ctx.events.notify('transfer.rejected',amount=value,reason=str(exc),**{'from':source,'to':target})
            raise
        self.ctx.events.notify('transfer.completed',operation_id=oid,amount=value,received=received,currency=b['currency'],fee=fee,operation_kind='exchange',ts=now(),**{'from':source,'to':target})
        return oid,received
    def register_commands(self, commands):
        commands.register('transfer','transfer SOURCE_ID TARGET_ID AMOUNT',lambda s,a,b,v: f'Операция {self.perform(s.owned(a),int(b),v)}')
        commands.register('external','external SOURCE_ID RECIPIENT_REFERENCE AMOUNT (simulated)',lambda s,a,ref,v: f'Операция {self.external(s.owned(a),ref,v)}')
        if self.ctx.registry.optional(CurrencyAPI):
            commands.register('exchange','exchange SOURCE_ID TARGET_ID AMOUNT',lambda s,a,b,v: f'Обмен: {self.exchange(s.owned(a),s.owned(b),v)}')
