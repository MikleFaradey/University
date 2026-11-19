import pytest
from core.events import EventBus, OperationRejected

def test_subscriber_can_veto_request():
    bus=EventBus()
    bus.subscribe('withdrawal.requested',lambda n,p: (_ for _ in ()).throw(OperationRejected('blocked')))
    with pytest.raises(OperationRejected): bus.publish('withdrawal.requested',account_id=1,amount=999)

def test_observer_failure_cannot_undo_completion():
    bus=EventBus()
    called=[]
    bus.subscribe('transfer.completed',lambda n,p: (_ for _ in ()).throw(RuntimeError('mail down')))
    bus.subscribe('transfer.completed',lambda n,p: called.append(p['amount']))
    bus.notify('transfer.completed',operation_id='op1',amount=123,fee=0,ts='2026-11-13',**{'from':1,'to':2})
    assert called==[123]
    assert any(event=='notification.error' for event,_ in bus.history)
