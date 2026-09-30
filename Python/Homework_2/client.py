import http.client
import json
import logging
import socket
import sys
import time

HOST = "127.0.0.1"
PORT = 57223


logging.basicConfig(
    filename="client.log",
    filemode="w",
    encoding="utf-8",
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("client")


TEST_RESULTS = []


def line():
    logger.info("-" * 60)


def request(method, path, data=None, raw_body=None):
    logger.info(">>> %s %s", method, path)

    if raw_body is not None:
        body = raw_body
        logger.debug("    body: %s", body)
    elif data is not None:
        body = json.dumps(data, ensure_ascii=False)
        logger.debug("    body: %s", data)
    else:
        body = None

    headers = {}
    if method == "POST":
        headers["Content-Type"] = "application/json"
        if body is None:
            body = ""

    connection = http.client.HTTPConnection(HOST, PORT, timeout=5)
    try:
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        text = response.read().decode("utf-8")

        logger.info("<<< %s %s", response.status, response.reason)
        logger.info("    %s", text)
        line()

        print(f"{response.status} {response.reason}")
        print(text)
        return response.status, text
    except Exception as exc:
        logger.error("Ошибка запроса: %s", exc)
        line()
        print(f"Ошибка запроса: {exc}")
        return None, str(exc)
    finally:
        connection.close()


def remember(name, status, body):
    TEST_RESULTS.append((name, status, body))


def disconnect_test():
    logger.info(">>> POST /users/user1/score (обрыв соединения)")
    logger.debug('    body: {"score": (неполный JSON)')

    sock = socket.create_connection((HOST, PORT), timeout=5)
    request_head = (
        "POST /users/user1/score HTTP/1.1\r\n"
        f"Host: {HOST}:{PORT}\r\n"
        "Content-Type: application/json\r\n"
        "Content-Length: 100\r\n"
        "Connection: close\r\n"
        "\r\n"
    ).encode("utf-8")

    sock.sendall(request_head + b'{"score":')
    sock.close()
    logger.warning("Клиент разорвал соединение во время отправки запроса")
    line()
    print("Обрыв соединения отправлен")
    time.sleep(0.2)


def write_report():
    with open("test_results.txt", "w", encoding="utf-8") as file:
        file.write("Результаты тестирования плохих запросов\n")
        file.write("=" * 60 + "\n\n")
        for name, status, body in TEST_RESULTS:
            file.write(f"{name}\n")
            file.write(f"Код ответа: {status}\n")
            file.write(f"Ответ: {body}\n\n")
        file.write("После всех ошибок и обрыва соединения выполнен контрольный GET /users.\n")
        file.write("Если он вернул 200 OK, сервер продолжил работу и не завершился аварийно.\n")


def run_test():
    TEST_RESULTS.clear()
    logger.info("=" * 60)
    logger.info("Запуск автоматических тестов")
    logger.info("=" * 60)

    print("\n--- Корректные запросы ---")
    request("GET", "/users")
    request("GET", "/users/user2")
    request("POST", "/users/user1/score", {"score": 500})

    print("\n--- Проверки устойчивости ---")

    status, body = request("GET", "/users/user99")
    remember("1. Несуществующий пользователь", status, body)

    status, body = request("GET", "/foo")
    remember("2. Несуществующий маршрут", status, body)

    status, body = request("POST", "/users/user1/score")
    remember("3. POST без тела", status, body)

    status, body = request("POST", "/users/user1/score", raw_body='{"score": 100')
    remember("4. Невалидный JSON", status, body)

    status, body = request("POST", "/users/user1/score", {"score": "abc"})
    remember("5. Неверный тип поля score", status, body)

    status, body = request("DELETE", "/users")
    remember("6. Неподходящий HTTP-метод", status, body)

    status, body = request("GET", "/error")
    remember("7. Внутренняя ошибка сервера", status, body)

    disconnect_test()
    TEST_RESULTS.append(("8. Обрыв соединения посреди отправки", "соединение разорвано клиентом", "см. server.log"))

    print("\n--- Контроль после ошибок ---")
    status, body = request("GET", "/users")
    remember("Контрольный запрос после всех ошибок", status, body)

    write_report()
    print("\nРезультаты сохранены в test_results.txt")


def show_help():
    print("\nКоманды вводятся одной строкой:")
    print("GET /users")
    print("GET /users/user1")
    print('POST /users/user1/score {"score": 100}')
    print("GET /users/user99")
    print("DELETE /users")
    print("GET /foo")
    print("GET /error")
    print("help - показать примеры")
    print("exit - выйти\n")


def interactive():
    print("\n--- Интерактивный режим ---")
    print("Введите help для списка примеров, exit для выхода.")

    while True:
        command = input("> ").strip()
        if not command:
            continue

        if command.lower() == "exit":
            break

        if command.lower() == "help":
            show_help()
            continue

        parts = command.split(maxsplit=2)
        if len(parts) < 2:
            print("Формат: METHOD /path [JSON]")
            continue

        method = parts[0].upper()
        path = parts[1]

        if method == "POST" and len(parts) == 3:
            body = parts[2]
            try:
                data = json.loads(body)
                request(method, path, data=data)
            except json.JSONDecodeError:
                request(method, path, raw_body=body)
        else:
            request(method, path)

    logger.info("Клиент завершил работу")


if __name__ == "__main__":
    mode = sys.argv[1].lower() if len(sys.argv) > 1 else "full"

    if mode == "test":
        run_test()
    elif mode in ("interactive", "manual"):
        interactive()
    else:
        run_test()
        interactive()
