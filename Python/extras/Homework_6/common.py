import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit


class Problem(Exception):
    def __init__(self, status, message):
        self.status = status
        super().__init__(message)


class Handler(BaseHTTPRequestHandler):
    def send(self, status, body, mime="application/json"):
        if mime == "application/json":
            body = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", mime + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def dispatch(self):
        try:
            data = {}
            if self.command == "POST":
                if self.headers.get_content_type() != "application/json":
                    raise Problem(415, "Требуется JSON")
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 16384:
                    raise Problem(400, "Некорректный размер запроса")
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    raise ValueError()
            self.handle_request(urlsplit(self.path).path, data)
        except Problem as e:
            self.send(e.status, {"error": str(e)})
        except (ValueError, TypeError, KeyError):
            self.send(400, {"error": "Проверьте данные запроса"})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            self.log_error("Ошибка обработки запроса")
            self.send(500, {"error": "Ошибка сервиса"})

    do_GET = dispatch
    do_POST = dispatch


def serve(handler):
    ThreadingHTTPServer(("0.0.0.0", int(os.getenv("PORT", 8000))), handler).serve_forever()
