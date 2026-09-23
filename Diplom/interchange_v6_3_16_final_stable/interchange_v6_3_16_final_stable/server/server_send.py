import argparse
from pathlib import Path

import db


def main():
    p = argparse.ArgumentParser(
        description="Queue a file or folder for sending from the server"
    )
    p.add_argument("--db", default="lan_exchange.db")
    p.add_argument("--to", required=True, dest="recipient")
    p.add_argument("--path", required=True)
    args = p.parse_args()

    db.configure_db(args.db)
    db.init_db()

    source = Path(args.path).expanduser().resolve()
    if not source.exists():
        raise SystemExit(f"Not found: {source}")
    if not db.get_user(args.recipient):
        raise SystemExit(
            f"Unknown user: {args.recipient}"
        )

    item_type = "folder" if source.is_dir() else "file"
    tid = db.add_transfer(
        "server", args.recipient, source.name,
        item_type, str(source),
        stored_archive=False,
        delete_after=False
    )
    mid = db.add_message(
        "server", args.recipient,
        f"{source.name}: prepared by server",
        "file_status",
        {"transfer_id": tid, "status": "waiting"}
    )

    print(f"Task #{tid} created for {args.recipient}.")
    print(f"History event #{mid} stored.")


if __name__ == "__main__":
    main()
