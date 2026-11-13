"""Additional failure-injection checks for the event-driven banking workflow."""
from copy import deepcopy

import pytest

from core.events import EventBus, OperationRejected
from core.loader import load


def make_bank(tmp_path):
    config = {
        'database': str(tmp_path / 'fault-test.sqlite3'),
        'modules': [
            'persistence', 'auth', 'accounts', 'fees', 'limits', 'fraud_control',
            'deposits', 'withdrawals', 'transfers', 'reports', 'notifications',
            'audit_log', 'bonus_points', 'analytics'
        ],
        'transfer_fee_basis_points': 100,
        'daily_limit_cents': 5000000,
        'monthly_limit_cents': 30000000,
        'fraud_threshold_cents': 10000000,
    }
    ctx, modules = load(config)
    user_id = modules['auth'].register('sample', 'sample@example.org', 'password123')
    source = modules['accounts'].open(user_id)
    target = modules['accounts'].open(user_id)
    modules['deposits'].perform(source, '1000')
    return ctx, modules, source, target


def test_request_veto_leaves_accounts_and_operations_unchanged(tmp_path):
    ctx, mods, source, target = make_bank(tmp_path)
    try:
        before = deepcopy(mods['reports'].statement(source))
        balances = (mods['accounts'].account(source)['balance'],
                    mods['accounts'].account(target)['balance'])

        def reject(_event, _payload):
            raise OperationRejected('simulated blocking rule')

        ctx.events.subscribe('transfer.requested', reject)
        with pytest.raises(OperationRejected, match='simulated blocking rule'):
            mods['transfers'].perform(source, target, '100')
        assert (mods['accounts'].account(source)['balance'],
                mods['accounts'].account(target)['balance']) == balances
        assert mods['reports'].statement(source) == before
        assert any(name == 'transfer.rejected' for name, _ in ctx.events.history)
    finally:
        mods['persistence'].repository.close()


def test_observer_exception_does_not_cancel_committed_transfer(tmp_path):
    ctx, mods, source, target = make_bank(tmp_path)
    try:
        reached = []

        def broken(_event, _payload):
            raise RuntimeError('simulated broken observer')

        def healthy(_event, payload):
            reached.append(payload['operation_id'])

        ctx.events.subscribe('transfer.completed', broken)
        ctx.events.subscribe('transfer.completed', healthy)
        operation_id = mods['transfers'].perform(source, target, '100')
        assert operation_id in reached
        assert mods['accounts'].account(source)['balance'] == 89900
        assert mods['accounts'].account(target)['balance'] == 10000
        assert any(x['event'] == 'transfer.completed' and
                   'simulated broken observer' in x['error'] for x in ctx.events.errors)
    finally:
        mods['persistence'].repository.close()


def test_malformed_required_event_payload_is_rejected():
    bus = EventBus()
    with pytest.raises(ValueError, match='missing payload fields'):
        bus.notify('money.deposited', account_id=1, amount=100)


def test_reversed_event_cannot_claim_unreversed_operation(tmp_path):
    ctx, mods, source, target = make_bank(tmp_path)
    try:
        operation_id = mods['transfers'].perform(source, target, '100')
        ctx.events.notify('operation.reversed', operation_id=operation_id,
                          reason='simulated invalid acknowledgement')
        assert any(x['event'] == 'operation.reversed' and
                   'without committed compensating posting' in x['error']
                   for x in ctx.events.errors)
        assert mods['accounts'].account(source)['balance'] == 89900
        assert mods['accounts'].account(target)['balance'] == 10000
    finally:
        mods['persistence'].repository.close()
