#!/usr/bin/env python3
import argparse
from pathlib import Path

from qt_compat import QApplication, QDialog
from server_config import (
    default_config_path,
    is_server_config_complete,
    load_server_config,
)
from server_setup import ServerSetupDialog, dialog_exec


def parse_args():
    parser = argparse.ArgumentParser(
        description="Configure Interchange Server"
    )
    parser.add_argument("--config", default=None)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Open settings even when the configuration is complete"
    )
    return parser.parse_args()


def main():
    args = parse_args()
    config_path = Path(
        args.config or default_config_path()
    ).expanduser()

    values = load_server_config(config_path)

    if (
        not args.force
        and config_path.exists()
        and is_server_config_complete(values)
    ):
        return 0

    app = QApplication([])
    app.setApplicationName("Interchange Server Setup")

    dialog = ServerSetupDialog(
        config_path,
        values,
        first_run=not config_path.exists(),
        parent=None
    )

    if dialog_exec(dialog) != QDialog.Accepted:
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
