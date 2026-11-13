import pytest
from test_accounts import bank
from core.events import OperationRejected

def seed(m):
    u=m['auth'].register('bob','bob@example.org','password123')
    a=m['accounts'].open(u)
    b=m['accounts'].open(u)
    m['deposits'].perform(a,'1000')
    return u,a,b

def test_transfer_fee_statement_and_bonus(bank):
    ctx,m=bank
    u,a,b=seed(m)
    oid=m['transfers'].perform(a,b,'200')
    assert m['accounts'].account(a)['balance']==79800
    assert m['accounts'].account(b)['balance']==20000
    assert m['reports'].statement(a,kind='transfer')[0]['fee']==200
    assert m['bonus_points'].points(u)>=12
    assert 'transfer.completed' in [event for event,_ in ctx.events.history]
    assert oid

def test_transfer_rollback_if_target_invalid_or_insufficient(bank):
    _,m=bank
    _,a,b=seed(m)
    with pytest.raises(ValueError): m['transfers'].perform(a,b,'10000')
    with pytest.raises(ValueError): m['transfers'].perform(a,999,'5')
    assert m['accounts'].account(a)['balance']==100000
    assert m['accounts'].account(b)['balance']==0
    assert m['reports'].statement(a,kind='transfer')==[]

def test_limits_and_fraud(bank):
    ctx,m=bank
    _,a,b=seed(m)
    with pytest.raises(OperationRejected): m['transfers'].perform(a,b,'11000')
    assert m['accounts'].account(a)['balance']==100000
    # override threshold to exercise fraud as distinct from limits
    m['fraud_control'].threshold=100
    with pytest.raises(OperationRejected): m['transfers'].perform(a,b,'2')
    assert any(event=='fraud.detected' for event,_ in ctx.events.history)

def test_external_transfer_and_exchange(bank):
    _,m=bank
    u,a,_=seed(m)
    m['transfers'].external(a,'external-bank-ref','100')
    assert m['accounts'].account(a)['balance']==89900
    usd=m['accounts'].open(u,'current','USD')
    oid,credited=m['transfers'].exchange(a,usd,'90')
    assert credited==100
    assert m['accounts'].account(usd)['balance']==100
    assert m['accounts'].account(a)['balance']==80810
    assert oid

def test_cross_currency_same_currency_transfer_denied(bank):
    _,m=bank
    u,a,_=seed(m)
    usd=m['accounts'].open(u,'current','USD')
    with pytest.raises(ValueError): m['transfers'].perform(a,usd,'10')
