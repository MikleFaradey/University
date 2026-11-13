"""Extensible CLI: no knowledge of specific bank modules."""
import shlex

class Session:
    def __init__(self, ctx):
        self.ctx = ctx
        self.user = None
    def require_user(self):
        if self.user is None: raise ValueError('Log in first')
        from .protocols import Repository
        repo=self.ctx.registry.optional(Repository)
        if repo is not None:
            current=repo.one('SELECT blocked,role FROM users WHERE id=?',(self.user['id'],))
            if current is None or current['blocked']:
                self.user=None
                raise ValueError('User session expired or blocked')
            self.user['role']=current['role']
        return self.user
    def owned(self, account_id):
        from .protocols import AccountsAPI
        user = self.require_user()
        account_id = int(account_id)
        account = self.ctx.registry.get(AccountsAPI).account(account_id)
        if account['owner_id'] != user['id'] and user['role'] != 'admin':
            raise ValueError('Access denied: account owned by another user')
        return account_id

class CommandRegistry:
    def __init__(self): self._commands={}
    def register(self, name, usage, callback):
        if name in self._commands: raise ValueError('Duplicate command: '+name)
        self._commands[name]=(usage,callback)
    def execute(self, line, session):
        args=shlex.split(line)
        if not args: return None
        command=args.pop(0)
        if command == 'help': return '\n'.join(f'{k:15} {v[0]}' for k,v in sorted(self._commands.items()))
        if command in ('quit','exit'): return 'EXIT'
        if command not in self._commands: raise ValueError('Unknown command: '+command)
        return self._commands[command][1](session,*args)

def run_shell(ctx):
    session=Session(ctx)
    print('Модульный банк. help — команды; quit — выход')
    while True:
        try:
            result=ctx.commands.execute(input('bank> '),session)
            if result == 'EXIT': break
            if result is not None: print(result)
        except (EOFError,KeyboardInterrupt):
            print(); break
        except Exception as exc:
            print('Ошибка:',exc)
