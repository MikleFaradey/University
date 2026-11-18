import hashlib
import hmac
import json
import os
import time
from urllib.parse import parse_qsl

from common import Problem


def customer(headers):
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise Problem(500, "Для Mini App требуется BOT_TOKEN в .env")
    try:
        pairs = parse_qsl(headers.get("X-Telegram-Init", ""), keep_blank_values=True,
                          strict_parsing=True, max_num_fields=32)
        fields = dict(pairs)
        if len(fields) != len(pairs):
            raise ValueError()
        signature = fields.pop("hash")
        check = "\n".join(k + "=" + fields[k] for k in sorted(fields))
        secret = hmac.digest(b"WebAppData", token.encode(), "sha256")
        expected = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise ValueError()
        if not -60 <= time.time() - int(fields["auth_date"]) <= 86400:
            raise ValueError()
        user_id = json.loads(fields["user"])["id"]
        if type(user_id) is not int or user_id <= 0:
            raise ValueError()
        return f"tg-{user_id}"
    except (ValueError, TypeError, KeyError):
        pass
    raise Problem(401, "Откройте Mini App заново кнопкой в Telegram")
