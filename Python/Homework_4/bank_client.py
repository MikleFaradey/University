"""Клиент с проверкой TLS-сертификата; совместим с cmd() из ДЗ-3."""
import os
import socket
import ssl


class BankClient:
    def __init__(self, host='localhost', port=9999, timeout=15):
        context = ssl.create_default_context(cafile=os.environ.get('BANK_CA', 'secrets/server.crt'))
        raw = socket.create_connection((host, port), timeout=timeout)
        try:
            self.sock = context.wrap_socket(raw, server_hostname=host)
        except Exception:
            raw.close()
            raise
        self.file = self.sock.makefile('rb')
        self._read()

    def _read(self):
        line = self.file.readline(131073)
        if not line.endswith(b'\n') or len(line) > 131072:
            raise ConnectionError('Invalid response or closed connection')
        return line.decode('utf-8').rstrip('\n')

    def cmd(self, line):
        if '\n' in line or '\r' in line or len(line.encode()) > 2048:
            raise ValueError('Invalid command')
        self.sock.sendall(line.encode() + b'\n')
        return self._read()

    def close(self):
        self.file.close()
        self.sock.close()


if __name__ == '__main__':
    import getpass
    client = BankClient()
    try:
        print(client.cmd('LOGIN ' + input('Login: ') + ' ' + getpass.getpass('Password: ')))
        print(client.cmd('HELP'))
        while True:
            command = input('> ')
            print(client.cmd(command))
            if command.upper() == 'QUIT':
                break
    finally:
        client.close()
