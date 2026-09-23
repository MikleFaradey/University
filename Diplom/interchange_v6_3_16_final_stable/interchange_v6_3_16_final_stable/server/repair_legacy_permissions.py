#!/usr/bin/env python3
import argparse
import configparser
import os
from pathlib import Path


def parse_args():
    parser = argparse.ArgumentParser(
        description="Repair Interchange legacy file ownership"
    )
    parser.add_argument("--config", required=True)
    return parser.parse_args()


def expand_for_user(value, user_home):
    text = str(value or "").strip()
    if not text:
        return None
    if text == "~":
        text = user_home
    elif text.startswith("~/"):
        text = os.path.join(user_home, text[2:])
    return Path(text).resolve()


def is_inside(path, root):
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def chown_tree(path, uid, gid):
    if not path.exists():
        return
    paths = [path]
    if path.is_dir():
        paths.extend(path.rglob("*"))


    for item in reversed(paths):
        try:
            if item.is_symlink():
                os.lchown(str(item), uid, gid)
            else:
                os.chown(str(item), uid, gid)
        except FileNotFoundError:
            pass


def main():
    args = parse_args()

    user_home = os.environ.get("INTERCHANGE_USER_HOME")
    uid_raw = os.environ.get("INTERCHANGE_USER_UID")
    gid_raw = os.environ.get("INTERCHANGE_USER_GID")

    if not user_home or uid_raw is None or gid_raw is None:
        raise RuntimeError("Missing original user identity")

    uid = int(uid_raw)
    gid = int(gid_raw)
    home = Path(user_home).resolve()
    config_path = Path(args.config).resolve()

    parser = configparser.ConfigParser()
    parser.read(str(config_path), encoding="utf-8")
    section = parser["server"] if parser.has_section("server") else {}

    candidates = [
        config_path.parent,
        expand_for_user(
            section.get(
                "db_file",
                str(home / ".interchange" / "lan_exchange.db")
            ),
            str(home)
        ),
        expand_for_user(
            section.get(
                "spool_dir",
                str(home / ".interchange" / "server_spool")
            ),
            str(home)
        ),
        expand_for_user(
            section.get(
                "pcap_dir",
                str(home / ".interchange" / "pcap")
            ),
            str(home)
        ),
        expand_for_user(
            section.get(
                "destination_dir",
                str(home / "InterchangeServerReceived")
            ),
            str(home)
        ),
    ]

    repaired = []
    skipped = []

    for path in candidates:
        if path is None:
            continue


        target = path.parent if path.suffix == ".db" else path

        if not is_inside(target, home):
            skipped.append(str(target))
            continue

        chown_tree(target, uid, gid)
        repaired.append(str(target))

    if repaired:
        print("Legacy ownership checked/repaired:")
        for value in sorted(set(repaired)):
            print("  " + value)

    if skipped:
        print("Skipped paths outside user HOME:")
        for value in sorted(set(skipped)):
            print("  " + value)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
