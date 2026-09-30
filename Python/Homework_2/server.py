from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import logging
from pydantic import BaseModel, Field, StrictInt, ValidationError

HOST = "127.0.0.1"
PORT = 57223


class UserStats(BaseModel):
    name: str = Field(..., description="Имя игрока")
    game: str = Field(..., description="Название игры")
    level: int = Field(..., ge=0, description="Уровень игрока")
    score: int = Field(..., ge=0, description="Количество очков")
    playtime_hours: int = Field(..., ge=0, description="Время в игре (часы)")


class ScoreUpdate(BaseModel):
    score: StrictInt = Field(..., ge=0)


USERS_DATA: dict[str, UserStats] = {
    "user1": UserStats(name="Алексей", game="Dota 2", level=42, score=15320, playtime_hours=210),
    "user2": UserStats(name="Мария", game="Valorant", level=30, score=9870, playtime_hours=95),
    "user3": UserStats(name="Игорь", game="CS2", level=55, score=21000, playtime_hours=340),
}


logging.basicConfig(
    filename="server.log",
    filemode="w",
    encoding="utf-8",
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("server")


def line():
    logger.info("-" * 60)


class RequestHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def send_json(self, status, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            logger.warning("Клиент разорвал соединение до получения ответа")
            return

        logger.info("<<< %s %s", status, self.responses.get(status, ("",))[0])
        logger.info("    %s", body.decode("utf-8"))
        line()

    def read_json_body(self):
        content_length = int(self.headers.get("Content-Length", "0") or 0)
        if content_length <= 0:
            raise ValueError("Тело запроса пустое")

        body = self.rfile.read(content_length)
        if len(body) != content_length:
            raise ConnectionAbortedError(
                f"Обрыв соединения: получено {len(body)} из {content_length} байт"
            )

        try:
            text = body.decode("utf-8")
            logger.debug("    body: %s", text)
            return json.loads(text)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("Невалидный JSON") from exc

    def do_GET(self):
        logger.info(">>> GET %s", self.path)
        try:
            if self.path == "/error":
                raise RuntimeError("Демонстрационная внутренняя ошибка")

            if self.path == "/users":
                result = {user_id: user.model_dump() for user_id, user in USERS_DATA.items()}
                self.send_json(200, result)
                return

            parts = self.path.strip("/").split("/")
            if len(parts) == 2 and parts[0] == "users":
                user = USERS_DATA.get(parts[1])
                if user is None:
                    self.send_json(404, {"error": "Пользователь не найден"})
                else:
                    self.send_json(200, user.model_dump())
                return

            if len(parts) == 3 and parts[0] == "users" and parts[2] == "score":
                self.send_json(405, {"error": "Метод не поддерживается"})
                return

            self.send_json(404, {"error": "Маршрут не найден"})

        except Exception as exc:
            logger.error("Внутренняя ошибка: %s", exc)
            self.send_json(500, {"error": "Внутренняя ошибка сервера"})

    def do_POST(self):
        logger.info(">>> POST %s", self.path)
        parts = self.path.strip("/").split("/")

        if self.path == "/users" or (len(parts) == 2 and parts[0] == "users"):
            self.send_json(405, {"error": "Метод не поддерживается"})
            return

        if not (len(parts) == 3 and parts[0] == "users" and parts[2] == "score"):
            self.send_json(404, {"error": "Маршрут не найден"})
            return

        user_id = parts[1]
        if user_id not in USERS_DATA:
            self.send_json(404, {"error": "Пользователь не найден"})
            return

        try:
            data = self.read_json_body()
            try:
                update = ScoreUpdate.model_validate(data)
            except ValidationError as exc:
                raise ValueError("Поле score должно быть неотрицательным целым числом") from exc

            user = USERS_DATA[user_id]
            USERS_DATA[user_id] = UserStats(
                **{
                    **user.model_dump(),
                    "score": user.score + update.score,
                }
            )
            self.send_json(200, USERS_DATA[user_id].model_dump())

        except ConnectionAbortedError as exc:
            logger.warning("%s", exc)
            line()
        except ValueError as exc:
            self.send_json(400, {"error": str(exc)})
        except Exception as exc:
            logger.error("Внутренняя ошибка: %s", exc)
            self.send_json(500, {"error": "Внутренняя ошибка сервера"})

    def do_DELETE(self):
        logger.info(">>> DELETE %s", self.path)
        self.send_json(405, {"error": "Метод не поддерживается"})

    def do_PUT(self):
        logger.info(">>> PUT %s", self.path)
        self.send_json(405, {"error": "Метод не поддерживается"})

    def do_PATCH(self):
        logger.info(">>> PATCH %s", self.path)
        self.send_json(405, {"error": "Метод не поддерживается"})


if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("Запуск сервера: %s:%s", HOST, PORT)
    logger.info("=" * 60)
    print(f"Сервер запущен: http://{HOST}:{PORT}")

    server = HTTPServer((HOST, PORT), RequestHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        logger.info("Сервер завершил работу")
