from core.protocols import Repository
from core.events import OperationRejected

class Plugin:
    name='fraud_control'
    def initialize(self,ctx):
        self.ctx=ctx
        self.repo=ctx.registry.get(Repository)
        self.threshold=int(ctx.config.get('fraud_threshold_cents',20000000))
        self.logins={}
        for name in ('deposit.requested','withdrawal.requested','transfer.requested','user.logged_in'):
            ctx.events.subscribe(name,self.check)
    def check(self,name,p):
        if name=='user.logged_in':
            uid=p['user_id'];self.logins[uid]=self.logins.get(uid,0)+1
            return
        if p['amount']<=self.threshold: return
        src=p['account_id'] if name!='transfer.requested' else p['from']
        acct=self.repo.one('SELECT owner_id FROM accounts WHERE id=?',(src,))
        self.ctx.events.notify('fraud.detected',user_id=acct['owner_id'] if acct else None,operation=name,reason='Large transaction')
        raise OperationRejected('Fraud screening rejected large transaction')
    def register_commands(self,commands): pass
