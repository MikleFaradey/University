import json
import pytest
from core.loader import load
from core.events import EventBus
from test_accounts import bank

BASE=['persistence','auth','accounts','fees','currency','limits','fraud_control','deposits','withdrawals','transfers','reports','notifications','audit_log','bonus_points','analytics']
def config(**extra):
    data={'database':':memory:', 'modules':BASE, 'transfer_fee_basis_points':100,
          'daily_limit_cents':10000000,'monthly_limit_cents':50000000,
          'fraud_threshold_cents':10000000,'currency_rates':{'RUB':1,'USD':90,'EUR':100}}
    data.update(extra)
    return data

def test_exchange_fee_event_and_reversal(bank):
    ctx,m=bank
    user=m['auth'].register('fxuser','fx@example.org','password123')
    rub=m['accounts'].open(user,currency='RUB')
    usd=m['accounts'].open(user,currency='USD')
    m['deposits'].perform(rub,'1000')
    oid,received=m['transfers'].exchange(rub,usd,'90')
    op=m['reports'].statement(rub,kind='exchange')[0]
    assert op['fee']==90 and op['received']==100
    assert m['accounts'].account(rub)['balance']==90910
    assert m['accounts'].account(usd)['balance']==100
    fees=[v for e,v in ctx.events.history if e=='fee.charged' and v['operation_id']==oid]
    assert fees and fees[0]['fee']==90
    m['reports'].reverse(oid,'FX correction')
    assert m['accounts'].account(rub)['balance']==100000
    assert m['accounts'].account(usd)['balance']==0
    assert not ctx.events.errors

def test_exchange_debit_fee_insufficient_rolls_back(bank):
    ctx,m=bank
    uid=m['auth'].register('low','low@example.org','password123')
    rub=m['accounts'].open(uid,currency='RUB')
    usd=m['accounts'].open(uid,currency='USD')
    m['deposits'].perform(rub,'90')
    with pytest.raises(ValueError): m['transfers'].exchange(rub,usd,'90')
    assert m['accounts'].account(rub)['balance']==9000
    assert m['accounts'].account(usd)['balance']==0
    assert m['reports'].statement(rub,kind='exchange')==[]

def test_analytics_expenses_top_excludes_reversed(bank):
    _,m=bank
    u=m['auth'].register('sam','sam@example.org','password123')
    a=m['accounts'].open(u)
    b=m['accounts'].open(u)
    m['deposits'].perform(a,'1000')
    trans=m['transfers'].perform(a,b,'200')
    m['withdrawals'].perform(a,'50')
    spending=m['analytics'].expenses(u)
    assert {r['kind'] for r in spending}=={'transfer','withdrawal'}
    assert len(m['analytics'].top(u))==2
    m['reports'].reverse(trans,'wrong transfer')
    assert {r['kind'] for r in m['analytics'].expenses(u)}=={'withdrawal'}
    assert len(m['analytics'].top(u))==1

def test_json_backend_persists_and_memory_does_not(tmp_path):
    path=tmp_path/'bank.json'
    cfg=config(storage_backend='json',json_database=str(path))
    _,mods=load(cfg)
    uid=mods['auth'].register('jess','jess@example.org','password123')
    acct=mods['accounts'].open(uid)
    mods['deposits'].perform(acct,'42')
    mods['persistence'].repository.close()
    doc=json.loads(path.read_text(encoding='utf8'))
    assert doc['format']=='bank-json-sql-v1'
    _,mods=load(cfg)
    assert mods['accounts'].account(acct)['balance']==4200
    assert mods['auth'].login('jess','password123')['id']==uid
    mods['persistence'].repository.close()
    cfg=config(storage_backend='memory')
    _,mods=load(cfg)
    mods['auth'].register('temporary','t@example.org','password123')
    mods['persistence'].repository.close()
    _,mods=load(cfg)
    assert mods['persistence'].repository.one("SELECT * FROM users WHERE login='temporary'") is None
    mods['persistence'].repository.close()

def test_reversal_completion_cannot_be_faked(bank):
    ctx,m=bank
    ctx.events.notify('operation.reversed',operation_id='not-an-operation',reason='fake')
    assert any(err['event']=='operation.reversed' for err in ctx.events.errors)
