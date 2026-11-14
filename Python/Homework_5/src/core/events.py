from collections import defaultdict
from dataclasses import dataclass
from typing import Callable
from uuid import uuid4

class OperationRejected(ValueError):
    pass
CONTRACTS = {'user.registered': ('user_id', 'login', 'role'), 'user.logged_in': ('user_id', 'ts'), 'account.opened': ('account_id', 'owner_id', 'type', 'currency'), 'account.closed': ('account_id',), 'deposit.requested': ('account_id', 'amount', 'currency'), 'money.deposited': ('operation_id', 'account_id', 'amount', 'currency', 'ts'), 'withdrawal.requested': ('account_id', 'amount'), 'money.withdrawn': ('operation_id', 'account_id', 'amount', 'ts'), 'transfer.requested': ('from', 'to', 'amount', 'currency'), 'transfer.completed': ('operation_id', 'from', 'to', 'amount', 'fee', 'ts'), 'transfer.rejected': ('from', 'to', 'amount', 'reason'), 'fee.charged': ('operation_id', 'account_id', 'fee'), 'fraud.detected': ('user_id', 'operation', 'reason'), 'operation.reversed': ('operation_id', 'reason')}
REQUESTS = frozenset(('deposit.requested', 'withdrawal.requested', 'transfer.requested', 'operation.reverse.requested'))

class EventBus:

    def __init__(self):
        self._subscribers: dict[str, list[Callable]] = defaultdict(list)
        self.history = []
        self.errors = []

    def subscribe(self, event, handler):
        if handler not in self._subscribers[event]:
            self._subscribers[event].append(handler)

    def subscribers(self, event):
        return tuple(self._subscribers[event])

    def _validate(self, event, payload):
        required = CONTRACTS.get(event, ())
        missing = [name for name in required if name not in payload]
        if missing:
            raise ValueError(f'Event {event}: missing payload fields {missing}')

    def publish(self, event: str, **payload):
        self._validate(event, payload)
        self.history.append((event, dict(payload)))
        for handler in tuple(self._subscribers[event]):
            handler(event, payload)
        return payload

    def notify(self, event: str, **payload):
        self._validate(event, payload)
        self.history.append((event, dict(payload)))
        for handler in tuple(self._subscribers[event]):
            try:
                handler(event, payload)
            except Exception as exc:
                failure = {'event': event, 'handler': getattr(handler, '__qualname__', str(handler)), 'error': str(exc)}
                self.errors.append(failure)
                self.history.append(('notification.error', failure))
