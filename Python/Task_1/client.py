import http.client
import json
import socket

HOST = "127.0.0.1"
PORT = 8000

def request(method, path, body=None):
    connection = http.client.HTTPConnection(HOST, PORT, timeout=5)
    headers = {"Content-Type": "application/json"} if body is not None else {}
    try:
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        return response.status, response.reason, response.read().decode("utf-8")
    finally:
        connection.close()

def show(status, reason, body):
    print(status, reason)
    try:
        print(json.dumps(json.loads(body), ensure_ascii=False, indent=2))
    except json.JSONDecodeError:
        print(body)

def send(method, path, body=None):
    status, reason, response = request(method, path, body)
    show(status, reason, response)
    return status, reason, response

def run_tests():
    tests = [
        ("GET", "/users/user99", None),
        ("GET", "/foo", None),
        ("POST", "/users/user1/score", '{"score": 100'),
        ("POST", "/users/user1/score", '{"score": "abc"}'),
        ("DELETE", "/users", None),
        ("GET", "/error", None)
    ]

    log = []
    for method, path, body in tests:
        status, reason, response = request(method, path, body)
        line = method + " " + path + (" " + body if body else "")
        log.append(line)
        log.append(str(status) + " " + reason)
        log.append(response)
        log.append("")

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((HOST, PORT))
    sock.sendall(b'POST /users/user1/score HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Length: 100\r\n\r\n{"score":')
    sock.close()

    log.append("Если прерывается соединение во время выполнения POST")
    log.append("Клиент закрывает соединение перед отправкой полного тела запроса")
    log.append("")

    status, reason, response = request("GET", "/users")
    log.append("Проверка работы сервера после разрыва соединения с клиентом")
    log.append("GET /users")
    log.append(str(status) + " " + reason)
    log.append(response)

    with open("test_results.txt", "w", encoding="utf-8") as file:
        file.write("\n".join(log))

    print("Tests completed. Results: test.txt")

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
            if len(parts) < 2:
                print("Format: METHOD /path [JSON]")
                continue

            method = parts[0].upper()
            path = parts[1]
            body = parts[2] if len(parts) == 3 else None

            if not path.startswith("/"):
                print("Path must start with /")
                continue

            send(method, path, body)

        except ConnectionRefusedError:
            print("Server is not running")
        except socket.timeout:
            print("Server timeout")
        except (KeyboardInterrupt, EOFError):
            break
        except Exception as error:
            print("Error:", error)

interactive()
