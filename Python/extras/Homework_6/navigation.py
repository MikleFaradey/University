import heapq
import json
import math
import os
import threading
import time
from collections import defaultdict
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from catalog import PLACES
from common import Handler, Problem, serve

CACHE = Path(os.getenv("STREET_CACHE", "/data/tverskoy-v1.json"))
QUERY = """[out:json][timeout:45];
way["highway"~"^(footway|steps|path|pedestrian|living_street|residential|service|unclassified)$"]
(55.755,37.596,55.770,37.621);(._;>;);out body qt;"""
network = None
status = "Загружаются пешеходные улицы района"


def distance(a, b):
    # Local equirectangular approximation for this small district, in metres.
    return 111195 * math.hypot(a[0] - b[0], (a[1] - b[1]) * math.cos(math.radians((a[0] + b[0]) / 2)))


class Streets:
    def __init__(self, elements):
        self.points = {e["id"]: (e["lat"], e["lon"]) for e in elements if e["type"] == "node"}
        blocked = {e["id"] for e in elements if e["type"] == "node" and
                   e.get("tags", {}).get("foot", e.get("tags", {}).get("access")) in ("no", "private")}
        self.edges = defaultdict(list)
        for way in elements:
            if way["type"] != "way":
                continue
            tags = way.get("tags", {})
            if tags.get("foot", tags.get("access")) in ("no", "private", "customers") or tags.get("area") == "yes":
                continue
            for a, b in zip(way["nodes"], way["nodes"][1:]):
                if a in blocked or b in blocked or a not in self.points or b not in self.points:
                    continue
                length = distance(self.points[a], self.points[b])
                if tags.get("oneway:foot") != "-1":
                    self.edges[a].append((b, length))
                if tags.get("oneway:foot") not in ("1", "yes", "true"):
                    self.edges[b].append((a, length))
        # Snap to the main walkable component, avoiding isolated courtyards.
        todo = set(self.edges)
        largest = set()
        while todo:
            stack = [todo.pop()]
            component = set(stack)
            while stack:
                for node, _ in self.edges[stack.pop()]:
                    if node in todo:
                        todo.remove(node)
                        component.add(node)
                        stack.append(node)
            if len(component) > len(largest):
                largest = component
        if not largest:
            raise ValueError("Пустая сеть улиц")
        self.stops = {}
        for name, coord in PLACES.items():
            nearest = min(largest, key=lambda i: distance(coord, self.points[i]))
            if distance(coord, self.points[nearest]) > 100:
                raise ValueError("Нет пешеходной точки рядом с " + name)
            self.stops[name] = nearest

    @lru_cache(maxsize=64)
    def route(self, start, end):
        src, dst = self.stops[start], self.stops[end]
        costs, previous, queue = {src: 0}, {}, [(0, src)]
        while queue:
            cost, node = heapq.heappop(queue)
            if node == dst:
                path = [node]
                while path[-1] != src:
                    path.append(previous[path[-1]])
                return {"points": [self.points[i] for i in reversed(path)], "meters": round(cost)}
            if cost != costs[node]:
                continue
            for other, length in self.edges[node]:
                total = cost + length
                if total < costs.get(other, math.inf):
                    costs[other] = total
                    previous[other] = node
                    heapq.heappush(queue, (total, other))
        raise Problem(422, "Между этими точками нет доступного пешего пути")


def prepare():
    global network, status
    if CACHE.exists():
        try:
            network = Streets(json.loads(CACHE.read_bytes())["elements"])
            return
        except (KeyError, ValueError, OSError) as err:
            print("Не удалось прочитать кэш:", err, flush=True)
    while network is None:
        try:
            request = Request("https://overpass-api.de/api/interpreter",
                              data=urlencode({"data": QUERY}).encode(),
                              headers={"User-Agent": "CourierDistrictDemo/1.0"})
            with urlopen(request, timeout=70) as response:
                raw = response.read()
            payload = json.loads(raw)
            if payload.get("remark"):
                raise ValueError(payload["remark"])
            streets = Streets(payload["elements"])
            CACHE.parent.mkdir(parents=True, exist_ok=True)
            temp = CACHE.with_suffix(".tmp")
            temp.write_bytes(raw)
            temp.replace(CACHE)
            network = streets
        except (ValueError, KeyError, OSError) as err:
            status = "Улицы района ещё не загружены. Повторная загрузка через минуту."
            print(status, err, flush=True)
            time.sleep(60)


class Navigation(Handler):
    def handle_request(self, path, data):
        if (self.command, path) not in (("GET", "/health"), ("POST", "/route")):
            raise Problem(404, "Ресурс не найден")
        if network is None:
            raise Problem(503, status)
        if path == "/health":
            return self.send(200, {"ok": True})
        if data.get("start") not in PLACES or data.get("end") not in PLACES:
            raise Problem(422, "Для адреса отсутствуют координаты")
        self.send(200, network.route(data["start"], data["end"]))


if __name__ == "__main__":
    threading.Thread(target=prepare, daemon=True).start()
    serve(Navigation)
