import ast
from pathlib import Path
import pytest
from core.loader import load
from core.cli import Session

MODULES=Path(__file__).resolve().parents[1]/'src'/'bank_modules'

def test_core_never_imports_plugins():
    core=MODULES.parent/'core'
    for path in core.glob('*.py'):
        tree=ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node,ast.Import):
                assert all(not x.name.startswith('bank_modules') for x in node.names)
            if isinstance(node,ast.ImportFrom):
                assert not (node.module or '').startswith('bank_modules')

def test_plugins_do_not_import_each_other():
    for path in MODULES.glob('*/__init__.py'):
        tree=ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node,ast.Import):
                assert all(not x.name.startswith('bank_modules') for x in node.names),path
            if isinstance(node,ast.ImportFrom):
                assert not (node.module or '').startswith('bank_modules'),path

def test_disabling_optional_modules_preserves_operations():
    cfg={'modules':['persistence','auth','accounts','deposits','withdrawals','transfers','reports'], 'database':':memory:'}
    ctx,m=load(cfg)
    try:
        s=Session(ctx)
        ctx.commands.execute('register ann ann@example.org password123',s)
        ctx.commands.execute('login ann password123',s)
        ctx.commands.execute('open current RUB',s)
        ctx.commands.execute('open current RUB',s)
        ctx.commands.execute('deposit 1 100',s)
        ctx.commands.execute('transfer 1 2 20',s)
        assert m['accounts'].account(1)['balance']==8000
        assert m['accounts'].account(2)['balance']==2000
        with pytest.raises(ValueError): ctx.commands.execute('bonuses',s)
        assert 'fees' not in m
    finally:
        m['persistence'].repository.close()

def test_disabled_operation_disappears_from_cli():
    ctx,m=load({'database':':memory:','modules':['persistence','auth','accounts']})
    try:
        assert 'deposit' not in ctx.commands._commands
        assert 'open' in ctx.commands._commands
    finally: m['persistence'].repository.close()

def test_bad_plugin_is_rejected():
    with pytest.raises(ValueError): load({'modules':['nonexistent']})
