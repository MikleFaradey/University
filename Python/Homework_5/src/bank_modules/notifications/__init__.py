import json
from core.protocols import Repository
from core.utils import now

class Plugin:
    name='notifications'
    def initialize(self,ctx):
        self.repo=ctx.registry.get(Repository)
        # Transport selection is independent of business modules.
        self.channels=ctx.config.get('notification_channels',['log','email','sms'])
        for name in ('user.registered','account.opened','account.closed','money.deposited','money.withdrawn','transfer.completed','transfer.rejected','fraud.detected','operation.reversed'):
            ctx.events.subscribe(name,self.notify)
    def email_stub(self,event,payload):
        return {'channel':'email-stub','event':event,'delivered':False}
    def sms_stub(self,event,payload):
        return {'channel':'sms-stub','event':event,'delivered':False}
    def notify(self,event,payload):
        for channel in self.channels:
            if channel=='email': result=self.email_stub(event,payload)
            elif channel=='sms': result=self.sms_stub(event,payload)
            elif channel=='log': result={'channel':'log','event':event,'payload':payload,'delivered':True}
            else: raise ValueError('Unknown notification transport: '+str(channel))
            # Stub is recorded explicitly: no external messages are sent.
            self.repo.execute('INSERT INTO notifications(event,message,ts) VALUES(?,?,?)',
                              (event,json.dumps(result,ensure_ascii=False),now()))
    def register_commands(self, commands):
        def inbox(s):
            if s.require_user()['role'] != 'admin': raise ValueError('Only administrator can inspect global notifications')
            rows=self.repo.all('SELECT * FROM notifications ORDER BY id DESC LIMIT 20')
            return '\n'.join(f"{r['ts']} {r['event']}: {r['message']}" for r in rows) or 'Нет уведомлений'
        commands.register('notifications','notifications (последние общие события)',inbox)
