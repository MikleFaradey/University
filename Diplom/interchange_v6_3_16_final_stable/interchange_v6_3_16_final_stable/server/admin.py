import argparse

import db
from server_config import default_config_path, load_server_config


def main():
    parser = argparse.ArgumentParser(
        description="Manage Interchange client authorization"
    )
    parser.add_argument("--db", default=None)
    parser.add_argument("--server-config", default=None)

    sub = parser.add_subparsers(dest="command")
    sub.add_parser("list-users")

    for name in ("approve", "reject", "block"):
        action = sub.add_parser(name)
        action.add_argument("user_id")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    if args.db is None:
        config_path = (
            args.server_config
            or default_config_path()
        )
        args.db = load_server_config(
            config_path
        )["db_file"]

    db.configure_db(args.db)
    db.init_db()

    if args.command == "list-users":
        for row in db.list_all_users():
            print(
                "%-24s %-24s ip=%-15s status=%s"
                % (
                    row["user_id"],
                    row["name"],
                    row["ip"] or "-",
                    row["auth_status"]
                )
            )
        return

    status_map = {
        "approve": "APPROVED",
        "reject": "REJECTED",
        "block": "BLOCKED"
    }

    db.set_user_auth_status(
        args.user_id,
        status_map[args.command]
    )
    print(
        "%s: %s"
        % (
            args.user_id,
            status_map[args.command]
        )
    )


if __name__ == "__main__":
    main()
