import http.client
import json
import logging
import os
import socket
import time

HOST = "127.0.0.1"
PORT = int(os.getenv("GAME_PORT", "8000"))

logging.basicConfig(level=logging.DEBUG, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S", handlers=[logging.FileHandler("client.log", mode="w", encoding="utf-8")])
log = logging.getLogger("client")
log.info("=" * 60)
log.info("Запуск клиента: %s", time.strftime("%Y-%m-%dT%H:%M:%S"))
log.info("=" * 60)

def request(method, path, body=None):
    log.info(">>> %s %s", method, path)
    if body is not None:
        try:
            log.debug("    body: %s", json.loads(body))
        except ValueError:
            log.debug("    body: %s", body)
    connection = http.client.HTTPConnection(HOST, PORT, timeout=5)
    try:
        headers = {"Content-Type": "application/json"} if body is not None else {}
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        result = response.read().decode("utf-8")
        log.info("<<< %s %s", response.status, response.reason)
        try:
            log.info("    %s", json.dumps(json.loads(result), ensure_ascii=False))
        except ValueError:
            log.info("    %s", result)
        return response.status, response.reason, result
    except (OSError, http.client.HTTPException) as error:
        log.error("Ошибка соединения: %s", error)
        raise
    finally:
        connection.close()
        log.info("-" * 60)

def send(method, path, body=None):
    status, reason, response = request(method, path, body)
    print(status, reason)
    print(json.dumps(json.loads(response), ensure_ascii=False, indent=2))

def run_tests():
    tests = [
        ("GET", "/users", None, 200),
        ("GET", "/users/user2", None, 200),
        ("POST", "/users/user1/score", '{"score": 500}', 200),
        ("GET", "/users/user99", None, 404),
        ("POST", "/users/user1/score", None, 400),
        ("POST", "/users/user1/score", '{"score": "abc"}', 400),
        ("POST", "/users/user1/score", '{"score": 100', 400),
        ("GET", "/foo", None, 404),
        ("DELETE", "/users", None, 405),
        ("GET", "/error", None, 500)
    ]
    results = []
    for method, path, body, expected in tests:
        status, reason, response = request(method, path, body)
        results.append((method + " " + path, expected, status))

    log.info(">>> POST /users/user1/score (обрыв соединения)")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.connect((HOST, PORT))
        sock.sendall(b'POST /users/user1/score HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Length: 100\r\n\r\n{"score":')
        log.debug("    body: {\"score\": (неполный JSON)")
    finally:
        sock.close()
    log.warning("Клиент разорвал соединение во время отправки запроса")
    log.info("-" * 60)
    time.sleep(0.2)

    status, reason, response = request("GET", "/users")
    results.append(("GET /users после обрыва и ошибки 500", 200, status))
    with open("test_results.txt", "w", encoding="utf-8") as file:
        file.write("Результаты тестирования\n\n")
        for name, expected, actual in results:
            file.write("%s: %s (ожидалось %s) %s\n" % (name, actual, expected, "OK" if actual == expected else "FAIL"))
        file.write("Обрыв соединения: клиент отправил неполный POST и закрыл сокет.\n")
        file.write("Устойчивость: %s\n" % ("OK" if status == 200 else "FAIL"))
    print("Tests completed. Results: test_results.txt")

def help():
    print("""GET /users
GET /users/user1
POST /users/user1/score {"score": 100}
GET /error
DELETE /users

test  - run tests
help  - commands
exit  - quit""")

def interactive():
    help()
    while True:
        try:
            line = input("\n> ").strip()
            if not line:
                continue
            if line.lower() in ("exit", "quit"):
                break
            if line.lower() == "help":
                help()
                continue
            if line.lower() == "test":
                run_tests()
                continue
            parts = line.split(maxsplit=2)
            if len(parts) < 2 or not parts[1].startswith("/"):
                print("Format: METHOD /path [JSON]")
                continue
            send(parts[0].upper(), parts[1], parts[2] if len(parts) == 3 else None)
        except ConnectionRefusedError:
            print("Server is not running")
        except socket.timeout:
            print("Server timeout")
        except (KeyboardInterrupt, EOFError):
            break
        except Exception as error:
            print("Error:", error)
    log.info("Клиент завершил работу")

interactive()
