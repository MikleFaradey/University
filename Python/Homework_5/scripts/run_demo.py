"""Reproducible non-destructive CLI showcase (uses an isolated temporary database)."""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMMANDS = [
    'register demo_user demo@example.org password123',
    'login demo_user password123',
    'open current RUB',
    'open savings RUB',
    'deposit 1 1000',
    'accounts',
    'transfer 1 2 200',
    'balance 1',
    'balance 2',
    'withdraw 1 5000',
    'balance 1',
    'statement 1',
    'bonuses',
    'expenses',
    'top',
    'quit',
]


def main():
    config = (ROOT / 'config.toml').read_text(encoding='utf-8')
    with tempfile.TemporaryDirectory(prefix='bank-demo-') as tempdir:
        temp = Path(tempdir)
        # Configuration is copied; only database/output paths are replaced.
        config = config.replace('database = "bank.sqlite3"',
                                'database = ' + repr(str(temp / 'demo.sqlite3')).replace("'", '"'))
        (temp / 'demo.toml').write_text(config, encoding='utf-8')
        env = dict(os.environ)
        env.pop('BANK_ADMIN_PASSWORD', None)
        env['PYTHONPATH'] = str(ROOT / 'src') + os.pathsep + env.get('PYTHONPATH', '')
        result = subprocess.run(
            [sys.executable, '-m', 'host.main', '--config', str(temp / 'demo.toml')],
            cwd=temp, env=env, input='\n'.join(COMMANDS) + '\n',
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            encoding='utf-8', timeout=40,
        )
    print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    if result.returncode != 0:
        raise SystemExit(result.returncode)
    for expected in ('Счёт #1', 'Счёт #2', '798 RUB', '200 RUB',
                     'Insufficient balance'):
        if expected not in result.stdout:
            raise SystemExit('MISSING expected output: ' + expected)
    if 'Unknown command:' in result.stdout:
        raise SystemExit('Unexpected unknown command in demo')
    print('DEMO PASSED: operations, fees, balances, rejection and CLI parsing')


if __name__ == '__main__':
    main()
