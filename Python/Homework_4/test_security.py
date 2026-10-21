import concurrent.futures
import json
from pathlib import Path
import secrets
import socket
import tempfile
import threading
import unittest
from unittest.mock import patch

import main


class SecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.path = Path(cls.temp.name) / 'bank.sqlite3'
        cls.passwords = {u: secrets.token_urlsafe(24) for u in ('admin', 'alice', 'bob')}
        cls.bank = main.Bank(cls.path, cls.passwords)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        self.bank.attempts.clear()
        with self.bank.connect() as db:
            db.execute('DELETE FROM transactions')
            db.execute('UPDATE users SET balance=500000 WHERE id=2')
            db.execute('UPDATE users SET balance=10000 WHERE id=3')

    def balance(self, uid):
        return self.bank.command(uid, 'BALANCE')[1]

    def test_login_and_injection(self):
        self.assertEqual(self.bank.login('alice', self.passwords['alice']), 2)
        self.assertIsNone(self.bank.login("' OR '1'='1", 'x'))
        uid, reply = self.bank.command(2, "LOGIN ' OR '1'='1 x")
        self.assertIsNone(uid)
        self.assertTrue(reply.startswith('FAIL'))

    def test_rate_limit_across_connections(self):
        for _ in range(5):
            self.assertIsNone(self.bank.login('alice', 'invalid'))
        self.assertIsNone(self.bank.login('alice', self.passwords['alice']))

    def test_password_storage(self):
        with self.bank.connect() as db:
            rows = db.execute('SELECT salt,password_hash FROM users').fetchall()
        self.assertEqual(len({r['salt'] for r in rows}), 3)
        self.assertTrue(all(len(r['password_hash']) == 32 for r in rows))

    def test_invalid_amounts(self):
        for amount in ['-100', '0', 'NaN', 'Infinity', '1e9', '0.001', '9' * 100]:
            with self.subTest(amount=amount), self.assertRaises(ValueError):
                self.bank.transfer(2, 3, amount, secrets.token_hex(16), '')
        self.assertEqual(self.balance(2), 'OK|5000.00')

    def test_self_transfer(self):
        with self.assertRaises(ValueError):
            self.bank.transfer(2, 2, '100', secrets.token_hex(16), '')

    def test_idor_and_admin(self):
        self.assertIn('Access denied', self.bank.command(2, 'HISTORY 3')[1])
        self.assertIn('Access denied', self.bank.command(2, 'ADMIN USERS')[1])
        self.assertIn('unsupported', self.bank.command(1, 'ADMIN SELECT * FROM users')[1])
        public = self.bank.command(1, 'ADMIN USERS')[1]
        self.assertNotIn('password', public)
        self.assertNotIn('salt', public)

    def test_replay_survives_restart(self):
        request_id = secrets.token_hex(16)
        first = self.bank.transfer(2, 3, '100', request_id, 'test')
        restarted = main.Bank(self.path)
        repeat = restarted.transfer(2, 3, '100', request_id, 'test')
        self.assertEqual(first.split('tx=')[1], repeat.split('tx=')[1])
        self.assertEqual(self.balance(2), 'OK|4900.00')
        with self.assertRaises(ValueError):
            restarted.transfer(2, 3, '101', request_id, 'test')

    def test_old_transfer_requires_request_id(self):
        with self.assertRaises(ValueError):
            self.bank.command(2, 'TRANSFER 3 1000 stolen')

    def test_concurrent_transfers(self):
        def transfer(_):
            try:
                self.bank.transfer(2, 3, '400', secrets.token_hex(16), '')
                return True
            except ValueError:
                return False
        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as pool:
            successes = sum(pool.map(transfer, range(20)))
        self.assertEqual(successes, 12)
        self.assertEqual(self.balance(2), 'OK|200.00')
        self.assertEqual(self.balance(3), 'OK|4900.00')

    def test_rollback(self):
        with self.assertRaises(ValueError):
            self.bank.transfer(2, 999, '100', secrets.token_hex(16), '')
        self.assertEqual(self.balance(2), 'OK|5000.00')

    def test_json_tampering_ignored(self):
        (self.path.parent / 'bank_db.json').write_text(json.dumps({'users': [{'balance': 999999999}]}))
        restarted = main.Bank(self.path)
        self.assertEqual(restarted.command(2, 'BALANCE')[1], 'OK|5000.00')
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_tcp_framing(self):
        server, client = socket.socketpair()
        worker = threading.Thread(target=main.handle_client, args=(server, self.bank))
        worker.start()
        try:
            client.settimeout(2)
            with client.makefile('rb') as stream:
                self.assertEqual(stream.readline(), b'BANK SERVER READY\n')
                client.sendall(b'HE')
                client.sendall(b'LP\nBALANCE\nQUIT\n')
                self.assertTrue(stream.readline().startswith(b'OK|'))
                self.assertEqual(stream.readline(), b'ERR|Login required\n')
                self.assertEqual(stream.readline(), b'BYE\n')
        finally:
            client.close()
            worker.join(3)
        self.assertFalse(worker.is_alive())

    def test_size_and_encoding(self):
        for data in [b'x' * (main.MAX_LINE + 1), b'\xff\n']:
            server, client = socket.socketpair()
            try:
                client.sendall(data)
                with self.assertRaises(ValueError):
                    main.read_line(server, b'')
            finally:
                server.close()
                client.close()

    def test_slowloris_deadline(self):
        server, client = socket.socketpair()
        try:
            client.sendall(b'L')
            with patch.object(main, 'COMMAND_TIMEOUT', 0.05), self.assertRaises(TimeoutError):
                main.read_line(server, b'')
        finally:
            server.close()
            client.close()


if __name__ == '__main__':
    unittest.main(verbosity=2)
