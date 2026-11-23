import re
from common import Problem, serve
from frontend import Frontend


class Main(Frontend):
    def handle_request(self, path, data):
        if self.static(path, "courier"):
            return
        if self.command == "GET" and path == "/api/orders":
            return self.forward("orders", "/orders", data)
        if self.command == "POST" and re.fullmatch(r"/api/orders/\d+/advance", path):
            return self.forward("orders", path[4:], data)
        if (self.command, path) in {("GET", "/api/health"), ("POST", "/api/route")}:
            return self.forward("navigation", path[4:], data)
        raise Problem(404, "Ресурс не найден")


if __name__ == "__main__":
    serve(Main)
