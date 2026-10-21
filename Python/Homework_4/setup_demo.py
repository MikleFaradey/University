"""Создаёт отдельные случайные пароли и локальный TLS-сертификат."""
import json
import os
from pathlib import Path
import secrets
import subprocess


def main():
    os.umask(0o077)
    root = Path('secrets')
    root.mkdir(mode=0o700, exist_ok=True)
    if any(root.iterdir()):
        raise SystemExit('secrets is not empty; existing credentials will not be replaced')
    (root / 'users.json').write_text(json.dumps({name: secrets.token_urlsafe(24)
                                               for name in ('admin', 'alice', 'bob')}, indent=2))
    subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:3072', '-sha256',
                    '-noenc', '-days', '30', '-keyout', str(root / 'server.key'),
                    '-out', str(root / 'server.crt'), '-subj', '/CN=localhost',
                    '-addext', 'subjectAltName=DNS:localhost,IP:127.0.0.1'], check=True)
    print('Created secrets/users.json and local TLS certificate. Do not commit secrets.')


if __name__ == '__main__':
    main()
