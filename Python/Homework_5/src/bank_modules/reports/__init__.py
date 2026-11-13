import csv, json
from core.protocols import Repository, ReportsAPI

class Plugin:
    name='reports'
    def initialize(self,ctx):
        self.repo=ctx.registry.get(Repository)
        self.ctx=ctx
        ctx.registry.provide(ReportsAPI,self)
        for event in ('account.opened','account.closed','money.deposited','money.withdrawn',
                      'transfer.completed','fee.charged'):
            ctx.events.subscribe(event,self.project)
        ctx.events.subscribe('operation.reversed',self.project)
    def project(self,event,payload):
        import json
        from core.utils import now
        self.repo.execute('INSERT INTO event_projection(event,payload,ts) VALUES(?,?,?)',
                          (event,json.dumps(payload,ensure_ascii=False),now()))
    def reverse(self,operation_id,reason):
        if not reason.strip(): raise ValueError('Reason is required')
        # Handler in accounts executes compensating postings in one DB transaction.
        self.ctx.events.publish('operation.reverse.requested',operation_id=operation_id,reason=reason)
        from core.utils import now
        self.ctx.events.notify('operation.reversed',operation_id=operation_id,reason=reason,ts=now())
        return operation_id
    def statement(self,account_id,since=None,until=None,kind=None):
        sql='SELECT * FROM operations WHERE (src=? OR dst=?)'
        args=[account_id,account_id]
        if since: sql+=' AND substr(ts,1,10)>=?'; args.append(since)
        if until: sql+=' AND substr(ts,1,10)<=?'; args.append(until)
        if kind: sql+=' AND kind=?'; args.append(kind)
        return self.repo.all(sql+' ORDER BY ts, id',tuple(args))
    def export(self,account_id,path,fmt='csv',**filters):
        rows=self.statement(account_id,**filters)
        if fmt=='json':
            with open(path,'w',encoding='utf-8') as out: json.dump(rows,out,ensure_ascii=False,indent=2)
        elif fmt=='csv':
            with open(path,'w',newline='',encoding='utf-8') as out:
                writer=csv.DictWriter(out,fieldnames=['id','kind','src','dst','amount','fee','received','recipient_ref','ts','status'])
                writer.writeheader(); writer.writerows(rows)
        else: raise ValueError('Unknown export format')
    def register_commands(self, commands):
        import json
        def statement(s,account,*filters):
            if len(filters) not in (0,2,3): raise ValueError('statement ID [FROM TO [KIND]]')
            kw=dict(zip(('since','until','kind'),filters))
            return json.dumps(self.statement(s.owned(account),**kw),ensure_ascii=False,indent=2)
        commands.register('statement','statement ACCOUNT_ID [FROM TO [KIND]]',statement)
        commands.register('export','export ACCOUNT_ID csv|json PATH',lambda s,a,fmt,path: self.export(s.owned(a),path,fmt) or f'Сохранено: {path}')
        def reverse(s,oid,*reason):
            if s.require_user()['role']!='admin': raise ValueError('Admin privileges required')
            return 'Операция отменена: '+self.reverse(oid,' '.join(reason))
        commands.register('reverse','reverse OPERATION_ID REASON (admin only)',reverse)
