import os
from datetime import datetime


def safe_unlink(path):
    """Path.unlink(missing_ok=True), but compatible with old Python."""
    try:
        path.unlink()
    except OSError:


        if path.exists():
            raise


def parse_sqlite_datetime(value):
    """Parse SQLite CURRENT_TIMESTAMP values without datetime.fromisoformat()."""
    if not value:
        return None

    formats = (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S.%f",
    )
    for fmt in formats:
        try:
            return datetime.strptime(value, fmt)
        except (TypeError, ValueError):
            pass
    return None
