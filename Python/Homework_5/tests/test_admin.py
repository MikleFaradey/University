import pytest
from core.loader import load
from core.cli import Session

def test_admin_can_block_and_user_cannot(monkeypatch):
    monkeypatch.setenv('BANK_ADMIN_PASSWORD','super_secure_1234')
    ctx,m=load({'database':':memory:','modules':['persistence','auth','accounts','admin']})
    try:
        user_id=m['auth'].register('user','user@test.org','password123')
        regular=Session(ctx)
        regular.user=m['auth'].login('user','password123')
        with pytest.raises(ValueError): ctx.commands.execute(f'block-user {user_id}',regular)
        admin=Session(ctx)
        admin.user=m['auth'].login('admin','super_secure_1234')
        ctx.commands.execute(f'block-user {user_id}',admin)
        with pytest.raises(ValueError): m['auth'].login('user','password123')
        ctx.commands.execute(f'unblock-user {user_id}',admin)
        assert m['auth'].login('user','password123')['id']==user_id
    finally: m['persistence'].repository.close()
