import pytest
from core.events import CONTRACTS, OperationRejected, EventBus
from test_accounts import bank

REQUIRED={
'user.registered','user.logged_in','account.opened','account.closed',
'deposit.requested','money.deposited','withdrawal.requested','money.withdrawn',
'transfer.requested','transfer.completed','transfer.rejected','fee.charged',
'fraud.detected','operation.reversed'
}

def setup_accounts(m):
    uid=m['auth'].register('anna','anna@domain.test','password123')
    first=m['accounts'].open(uid)
    second=m['accounts'].open(uid)
    return uid, first,second

def test_all_14_contracts_and_expected_subscription_graph(bank):
    ctx,m=bank
    assert REQUIRED==set(CONTRACTS)
    expected={
      'user.registered':{'notify','record'},
      'user.logged_in':{'record','check'},
      'account.opened':{'notify','project'},
      'account.closed':{'notify','project'},
      'deposit.requested':{'check'},
      'money.deposited':{'notify','project','award'},
      'withdrawal.requested':{'check'},
      'money.withdrawn':{'notify','project','on_withdrawal'},
      'transfer.requested':{'check','prepare'},
      'transfer.completed':{'notify','project','award','settled'},
      'transfer.rejected':{'notify','record'},
      'fee.charged':{'project'},
      'fraud.detected':{'notify','record'},
      'operation.reversed':{'_reversed','notify','project','record'},
    }
    for event,handlers in expected.items():
        found={handler.__name__ for handler in ctx.events.subscribers(event)}
        assert handlers<=found,(event,handlers-found)

def test_lifecycle_and_payloads_and_fee_publisher(bank):
    ctx,m=bank
    uid,a,b=setup_accounts(m)
    dep=m['deposits'].perform(a,'1000')
    withdrawal=m['withdrawals'].perform(a,'50')
    oid=m['transfers'].perform(a,b,'200')
    assert m['accounts'].account(a)['balance']==74800
    assert m['accounts'].account(b)['balance']==20000
    present={e for e,_ in ctx.events.history}
    for required in ('user.registered','account.opened','deposit.requested','money.deposited',
                     'withdrawal.requested','money.withdrawn','transfer.requested',
                     'transfer.completed','fee.charged'):
        assert required in present
    for event,payload in ctx.events.history:
        if event in CONTRACTS:
            assert set(CONTRACTS[event])<=set(payload),(event,payload)
    assert len([x for x,p in ctx.events.history if x=='fee.charged'])==1
    assert m['reports'].repo.one('SELECT count(*) AS n FROM event_projection')['n']>=5
    assert m['analytics'].withdrawals_seen==1
    assert not ctx.events.errors

def test_transfer_reversal_compensates_balances_and_bonus(bank):
    ctx,m=bank
    uid,a,b=setup_accounts(m)
    m['deposits'].perform(a,'1000')
    previous=m['bonus_points'].points(uid)
    oid=m['transfers'].perform(a,b,'200')
    assert m['bonus_points'].points(uid)>previous
    m['reports'].reverse(oid,'duplicate payment')
    assert m['accounts'].account(a)['balance']==100000
    assert m['accounts'].account(b)['balance']==0
    assert m['bonus_points'].points(uid)==previous
    assert m['reports'].statement(a,kind='transfer')[0]['status']=='reversed'
    assert 'operation.reversed' in [e for e,_ in ctx.events.history]
    with pytest.raises(ValueError,match='already reversed'):
        m['reports'].reverse(oid,'again')

def test_failed_reversal_is_atomic(bank):
    ctx,m=bank
    uid,a,b=setup_accounts(m)
    m['deposits'].perform(a,'1000')
    oid=m['transfers'].perform(a,b,'200')
    m['withdrawals'].perform(b,'200')
    with pytest.raises(ValueError):m['reports'].reverse(oid,'recipient spent funds')
    assert m['accounts'].account(a)['balance']==79800
    assert m['accounts'].account(b)['balance']==0
    assert m['reports'].statement(a,kind='transfer')[0]['status']=='completed'
    assert all(e!='operation.reversed' for e,_ in ctx.events.history)

def test_limits_count_external_and_exchange(bank):
    ctx,m=bank
    uid,a,b=setup_accounts(m)
    m['deposits'].perform(a,'1000')
    m['limits'].daily=15000
    m['transfers'].external(a,'external','100')
    with pytest.raises(OperationRejected):m['transfers'].perform(a,b,'60')
    usd=m['accounts'].open(uid,currency='USD')
    with pytest.raises(OperationRejected):m['transfers'].exchange(a,usd,'60')
    assert m['accounts'].account(a)['balance']==89900

def test_fraud_admin_audit_and_rejection(bank):
    ctx,m=bank
    uid,a,b=setup_accounts(m)
    m['deposits'].perform(a,'50')
    m['fraud_control'].threshold=100
    with pytest.raises(OperationRejected):m['transfers'].perform(a,b,'2')
    assert any(e=='fraud.detected' for e,p in ctx.events.history)
    assert any(e=='transfer.rejected' for e,p in ctx.events.history)
    assert m['accounts'].account(a)['balance']==5000
    assert m['accounts'].account(b)['balance']==0

def test_invalid_payload_rejected():
    bus=EventBus()
    with pytest.raises(ValueError,match='missing payload'):
        bus.notify('transfer.completed',amount=100)

def test_all_14_events_emitted_in_real_scenario():
    from core.loader import load
    cfg={'database':':memory:',
      'modules':['persistence','auth','accounts','fees','limits','fraud_control',
                 'deposits','withdrawals','transfers','reports','notifications',
                 'audit_log','bonus_points','analytics','admin'],
      'daily_limit_cents':10000000,'monthly_limit_cents':50000000,
      'fraud_threshold_cents':10000000,'transfer_fee_basis_points':100}
    ctx,m=load(cfg)
    try:
        uid=m['auth'].register('paul','paul@domain.test','password123')
        m['auth'].login('paul','password123')
        a=m['accounts'].open(uid)
        b=m['accounts'].open(uid)
        c=m['accounts'].open(uid)
        m['accounts'].close(c)
        m['deposits'].perform(a,'1000')
        m['withdrawals'].perform(a,'50')
        oid=m['transfers'].perform(a,b,'200')
        m['reports'].reverse(oid,'correction')
        m['fraud_control'].threshold=100
        with pytest.raises(OperationRejected): m['transfers'].perform(a,b,'2')
        emitted={name for name,payload in ctx.events.history}
        assert REQUIRED<=emitted,REQUIRED-emitted
        assert m['admin'].repo.one("SELECT COUNT(*) AS n FROM audit WHERE event='admin.fraud_alert'")['n']==1
        assert len(ctx.events.errors)==0
    finally:m['persistence'].repository.close()
