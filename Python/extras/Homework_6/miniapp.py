from auth import customer
from common import Problem, serve
from frontend import Frontend


class MiniApp(Frontend):
    def handle_request(self, path, data):
        if self.static(path, "client"):
            return
        if path == "/api/orders":
            return self.forward("orders", "/orders", data, owner=customer(self.headers))
        raise Problem(404, "Ресурс не найден")


if __name__ == "__main__":
    serve(MiniApp)
