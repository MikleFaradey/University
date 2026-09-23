import json
import logging
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST = "127.0.0.1"
PORT = int(os.getenv("GAME_PORT", "8000"))

USERS = {
    "user1": {"name": "Алексей", "game": "Dota 2", "level": 42, "score": 15320, "playtime_hours": 210},
    "user2": {"name": "Мария", "game": "Valorant", "level": 30, "score": 9870, "playtime_hours": 95},
    "user3": {"name": "Игорь", "game": "CS2", "level": 55, "score": 21000, "playtime_hours": 340}
}

logging.basicConfig(level=logging.DEBUG, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S", handlers=[logging.FileHandler("server.log", mode="w", encoding="utf-8")])
log = logging.getLogger("server")

class Handler(BaseHTTPRequestHandler):
    def send_json(self, code, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        try:
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            log.info("<<< %s %s", code, HTTPStatus(code).phrase)
            log.info("    %s", body.decode("utf-8"))
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            log.warning("Клиент отключился до получения ответа")
        finally:
            log.info("-" * 60)

    def parts(self):
        return [part for part in self.path.split("?", 1)[0].split("/") if part]

    def do_GET(self):
        log.info(">>> GET %s", self.path)
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
                raise RuntimeError("Демонстрационная внутренняя ошибка")
            else:
                self.send_json(404, {"error": "Маршрут не найден"})
        except Exception as error:
            log.error("Внутренняя ошибка: %s", error)
            self.send_json(500, {"error": "Внутренняя ошибка сервера"})

    def do_POST(self):
        log.info(">>> POST %s", self.path)
        try:
            parts = self.parts()
            if len(parts) != 3 or parts[0] != "users" or parts[2] != "score":
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
                self.send_json(400, {"error": "Тело запроса пустое"})
                return
            try:
                raw = self.rfile.read(length)
            except (ConnectionError, OSError):
                log.warning("Клиент разорвал соединение при передаче тела")
                log.info("-" * 60)
                return
            if len(raw) != length:
                log.warning("Обрыв соединения: получено %s из %s байт", len(raw), length)
                log.info("-" * 60)
                return
            try:
                data = json.loads(raw.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                log.debug("    body: %s", raw.decode("utf-8", errors="replace"))
                self.send_json(400, {"error": "Невалидный JSON"})
                return
            log.debug("    body: %s", data)
            if not isinstance(data, dict) or "score" not in data:
                self.send_json(400, {"error": "Отсутствует поле score"})
                return
            score = data["score"]
            if isinstance(score, bool) or not isinstance(score, (int, float)):
                self.send_json(400, {"error": "Поле score должно быть числом"})
                return
            USERS[user_id]["score"] += score
            self.send_json(200, USERS[user_id])
        except Exception as error:
            log.error("Внутренняя ошибка: %s", error)
            self.send_json(500, {"error": "Внутренняя ошибка сервера"})

    def method_not_allowed(self):
        log.info(">>> %s %s", self.command, self.path)
        self.send_json(405, {"error": "Метод не поддерживается"})

    do_DELETE = method_not_allowed
    do_PUT = method_not_allowed
    do_PATCH = method_not_allowed

    def log_message(self, format, *args):
        pass

server = ThreadingHTTPServer((HOST, PORT), Handler)
log.info("=" * 60)
log.info("Запуск сервера: %s:%s", HOST, PORT)
log.info("=" * 60)
print("Server:", "http://" + HOST + ":" + str(PORT))
try:
    server.serve_forever()
except KeyboardInterrupt:
    pass
finally:
    server.server_close()
    log.info("Сервер завершил работу")
