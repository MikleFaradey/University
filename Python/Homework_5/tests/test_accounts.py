import pytest
from core.loader import load

@pytest.fixture
def bank():
    config={'database':':memory:', 'modules':['persistence','auth','accounts','fees','currency','limits','fraud_control','deposits','withdrawals','transfers','reports','notifications','audit_log','bonus_points','analytics'], 'daily_limit_cents':1000000,'monthly_limit_cents':5000000,'fraud_threshold_cents':2000000,'transfer_fee_basis_points':100,'currency_rates':{'RUB':1,'USD':90,'EUR':100}}
    ctx,plugins=load(config)
    yield ctx,plugins
    plugins['persistence'].repository.close()

def test_register_and_accounts(bank):
    ctx,m=bank
    user=m['auth'].register('bob','bob@example.org','password123')
    assert m['auth'].login('bob','password123')['id']==user
    with pytest.raises(ValueError): m['auth'].login('bob','wrong')
    a=m['accounts'].open(user,'current','RUB')
    assert m['accounts'].account(a)['balance']==0
    m['accounts'].close(a)
    with pytest.raises(ValueError): m['accounts'].account(a)

def test_positive_amounts_and_insufficient_balance(bank):
    _,m=bank
    u=m['auth'].register('bob','bob@example.org','password123')
    a=m['accounts'].open(u)
    for amount in ('0','-1','0.001','nan'):
        with pytest.raises(ValueError): m['deposits'].perform(a,amount)
    with pytest.raises(ValueError): m['withdrawals'].perform(a,'1')
    assert m['accounts'].account(a)['balance']==0

def test_account_closure_requires_zero(bank):
    _,m=bank
    u=m['auth'].register('a','a@b.c','password123')
    a=m['accounts'].open(u)
    m['deposits'].perform(a,'15')
    with pytest.raises(ValueError): m['accounts'].close(a)
    assert m['accounts'].account(a)['closed']==0
