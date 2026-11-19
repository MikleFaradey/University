from core.loader import load

def test_sqlite_persists_between_runs(tmp_path):
    config={'database':str(tmp_path/'bank.sqlite3'),'modules':['persistence','auth','accounts','deposits']}
    _,m=load(config)
    uid=m['auth'].register('user','user@example.org','password123')
    account=m['accounts'].open(uid)
    m['deposits'].perform(account,'15.50')
    m['persistence'].repository.close()
    _,m2=load(config)
    try:
        assert m2['accounts'].account(account)['balance']==1550
    finally: m2['persistence'].repository.close()
