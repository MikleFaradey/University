import json
import os
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from catalog import ADDRESSES, SHOPS, BASE, PLACES
from common import Handler, Problem

WEB = Path(__file__).parent / "web"


class Frontend(Handler):
    def static(self, path, role):
        if self.command != "GET":
            return False
        if path == "/" or (role == "courier" and path == "/courier"):
            page = (WEB / "index.html").read_text(encoding="utf8")
            sdk = ""
            if role == "courier":
                sdk = ('<link rel="stylesheet" href="/leaflet.css">'
                       '<script defer src="/leaflet.js"></script>')
            if role == "client":
                sdk = '<script src="https://telegram.org/js/telegram-web-app.js"></script>'
            self.send(200, page.replace("{{role}}", role).replace("{{sdk}}", sdk).encode(), "text/html")
        elif path in ("/app.js", "/style.css", "/leaflet.js", "/leaflet.css", "/leaflet-license.txt"):
            mime = "text/javascript" if path.endswith(".js") else "text/css"
            self.send(200, (WEB / path[1:]).read_bytes(), "text/plain" if path.endswith(".txt") else mime)
        elif path == "/api/catalog":
            self.send(200, dict(shops=SHOPS, addresses=ADDRESSES, base=BASE, places=PLACES))
        else:
            return False
        return True

    def forward(self, service, path, data, owner=None):
        base = os.getenv("ORDERS_URL", "http://localhost:8001") if service == "orders" else os.getenv("NAV_URL", "http://localhost:8002")
        body = json.dumps(data).encode() if self.command == "POST" else None
        headers = {"Content-Type": "application/json"}
        if owner:
            headers["X-Owner"] = owner
        req = Request(base + path, data=body, headers=headers)
        try:
            with urlopen(req, timeout=1.5) as response:
                result = json.load(response)
        except HTTPError as err:
            raise Problem(err.code, json.load(err)["error"])
        except OSError:
            raise Problem(503, "Связь с сервисом прервана")
        self.send(200, result)
