"""Automated, opt-in defense demo using the real TLS bank client."""
import json
from decimal import Decimal
from pathlib import Path
import secrets
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from bank_client import BankClient  # noqa: E402


def run(client, command, expected):
    print(f"> {command}", flush=True)
    reply = client.cmd(command)
    print(reply, flush=True)
    if not reply.startswith(expected):
        raise RuntimeError(f"Unexpected response for {command}: {reply}")
    return reply


def balance(client):
    reply = run(client, "BALANCE", "OK|")
    return Decimal(reply.split("|", 1)[1])


def main():
    secrets_file = ROOT / "secrets" / "users.json"
    credentials = json.loads(secrets_file.read_text(encoding="utf-8"))
    password = credentials["alice"]

    print("This demonstration uses TLS and the current Docker database.")
    print("A transfer of 0.01 from alice to bob will change stored balances.")
    answer = input("Run the transfer demonstration? [y/N]: ").strip().lower()
    if answer not in ("y", "yes"):
        print("Cancelled. No bank commands were sent.")
        return

    client = BankClient()
    try:
        print("> LOGIN alice ********", flush=True)
        login_reply = client.cmd("LOGIN alice " + password)
        print(login_reply, flush=True)
        if login_reply != "OK|Logged in":
            raise RuntimeError("Login failed; check credentials or rate limit.")

        before = balance(client)
        request_id = secrets.token_hex(16)
        transfer = f"TRANSFER 3 0.01 {request_id} defense"
        first = run(client, transfer, "OK|Transfer completed|tx=")
        replay = run(client, transfer, "OK|Already processed|tx=")
        if first.split("tx=", 1)[1] != replay.split("tx=", 1)[1]:
            raise RuntimeError("Replay returned a different transaction ID.")

        after = balance(client)
        if after != before - Decimal("0.01"):
            raise RuntimeError("Unexpected balance after the transfer and replay.")
        print("Replay protection confirmed: alice was charged only once.")

        run(client, "HISTORY", "OK|")
        run(client, "HISTORY 3", "ERR|Access denied")
        run(client, "ADMIN USERS", "ERR|Access denied")
        run(client, f"TRANSFER 3 -100 {secrets.token_hex(16)} defense", "ERR|Invalid request")
        run(client, "QUIT", "BYE")
        print("Defense demonstration finished successfully.")
    finally:
        client.close()


if __name__ == "__main__":
    main()
