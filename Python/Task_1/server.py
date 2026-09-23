import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST = "127.0.0.1"
PORT = 8000

USERS = {
    "user1": {"name": "Алексей", "game": "Dota 2", "level": 42, "score": 15320, "playtime_hours": 210},
    "user2": {"name": "Мария", "game": "Valorant", "level": 30, "score": 9870, "playtime_hours": 95},
    "user3": {"name": "Игорь", "game": "CS2", "level": 55, "score": 21000, "playtime_hours": 340}
}

class Handler(BaseHTTPRequestHandler):
    def send_json(self, code, data):
        body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        try:
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    def parts(self):
        return [part for part in self.path.split("?", 1)[0].split("/") if part]

    def do_GET(self):
        try:
            parts = self.parts()
            if parts == ["users"]:
                self.send_json(200, USERS)
            elif len(parts) == 2 and parts[0] == "users":
                if parts[1] in USERS:
                    self.send_json(200, USERS[parts[1]])
                else:
                    self.send_json(404, {"error": "Пользователь не найден"})
            elif parts == ["error"]:
                raise RuntimeError
            else:
                self.send_json(404, {"error": "Маршрут не найден"})
        except Exception:
            self.send_json(500, {"error": "Внутренняя ошибка сервера"})

    def do_POST(self):
        try:
            parts = self.parts()
            if not (len(parts) == 3 and parts[0] == "users" and parts[2] == "score"):
                self.send_json(404, {"error": "Маршрут не найден"})
                return

            user_id = parts[1]
            if user_id not in USERS:
                self.send_json(404, {"error": "Пользователь не найден"})
                return

            try:
                length = int(self.headers.get("Content-Length", 0))
            except ValueError:
                self.send_json(400, {"error": "Некорректный Content-Length"})
                return

            if length <= 0:
                self.send_json(400, {"error": "Отсутствует тело запроса"})
                return

            try:
                data = json.loads(self.rfile.read(length).decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                self.send_json(400, {"error": "Невалидный JSON"})
                return

            if not isinstance(data, dict) or "score" not in data:
                self.send_json(400, {"error": "Отсутствует поле score"})
                return

            score = data["score"]
            if isinstance(score, bool) or not isinstance(score, (int, float)):
                self.send_json(400, {"error": "Поле score должно быть числом"})
                return

            USERS[user_id]["score"] += score
            self.send_json(200, USERS[user_id])
        except Exception:
            self.send_json(500, {"error": "Внутренняя ошибка сервера"})

    def method_not_allowed(self):
        self.send_json(405, {"error": "Метод не поддерживается"})

    do_DELETE = method_not_allowed
    do_PUT = method_not_allowed
    do_PATCH = method_not_allowed

    def log_message(self, format, *args):
        pass

server = ThreadingHTTPServer((HOST, PORT), Handler)
print(f"Server: http://{HOST}:{PORT}")

try:
    server.serve_forever()
except KeyboardInterrupt:
    pass
finally:
    server.server_close()
