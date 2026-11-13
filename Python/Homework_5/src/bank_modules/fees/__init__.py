from core.protocols import FeesAPI

class Plugin:
    name='fees'
    def initialize(self,ctx):
        self.ctx=ctx
        ctx.registry.provide(FeesAPI,self)
        self.percent=int(ctx.config.get('transfer_fee_basis_points',100))
        ctx.events.subscribe('transfer.requested',self.prepare)
        ctx.events.subscribe('transfer.completed',self.settled)
        ctx.events.subscribe('transfer.rejected',self.rejected)
    def calculate(self,amount):
        return (amount*self.percent+9999)//10000
    def prepare(self,event,p):
        # Policy module participates in request phase, but debit occurs in transfers.
        if p['amount']<=0: raise ValueError('Invalid transfer amount')
        p['fee']=self.calculate(p['amount'])
    def settled(self,event,p):
        if p['fee']:
            self.ctx.events.notify('fee.charged',operation_id=p['operation_id'],account_id=p['from'],fee=p['fee'])
    def rejected(self,event,p):
        pass
    def register_commands(self,commands): pass
