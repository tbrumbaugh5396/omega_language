"""Truck route planning: haversine distances, nearest-neighbor + 2-opt."""
import math


def haversine_km(a, b) -> float:
    lat1, lng1, lat2, lng2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    dlat, dlng = lat2 - lat1, lng2 - lng1
    h = (math.sin(dlat / 2) ** 2 +
         math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2)
    return 6371.0 * 2 * math.asin(math.sqrt(h))


def plan(points: list[dict]) -> tuple[list[dict], float]:
    """Order stops to minimize drive distance. points: [{id, lat, lng, ...}].
    The first point is the depot/start and stays first."""
    if len(points) <= 2:
        return _with_legs(points)
    order = _nearest_neighbor(points)
    order = _two_opt(order)
    return _with_legs(order)


def _nearest_neighbor(points):
    remaining = points[1:]
    order = [points[0]]
    while remaining:
        cur = order[-1]
        nxt = min(remaining, key=lambda p: haversine_km(
            (cur["lat"], cur["lng"]), (p["lat"], p["lng"])))
        remaining.remove(nxt)
        order.append(nxt)
    return order


def _two_opt(order, max_rounds: int = 8):
    def d(i, j):
        return haversine_km((order[i]["lat"], order[i]["lng"]),
                            (order[j]["lat"], order[j]["lng"]))
    n = len(order)
    for _ in range(max_rounds):
        improved = False
        for i in range(1, n - 2):
            for j in range(i + 1, n - 1):
                if d(i - 1, i) + d(j, j + 1) > d(i - 1, j) + d(i, j + 1) + 1e-9:
                    order[i:j + 1] = reversed(order[i:j + 1])
                    improved = True
        if not improved:
            break
    return order


def add_times(stops: list[dict], avg_kmh: float, service_min: float):
    """Annotate ordered stops with drive minutes and a running ETA; returns
    total minutes (drive + service at every stop after the depot)."""
    eta = 0.0
    for i, s in enumerate(stops):
        drive = (s.get("leg_km", 0) / avg_kmh) * 60 if avg_kmh else 0
        eta += drive
        if i:
            eta += service_min
        s["drive_min"] = round(drive)
        s["eta_min"] = round(eta)
    return round(eta, 1)


def _with_legs(order):
    total = 0.0
    out = []
    for i, p in enumerate(order):
        leg = 0.0
        if i:
            leg = haversine_km((order[i - 1]["lat"], order[i - 1]["lng"]),
                               (p["lat"], p["lng"]))
        total += leg
        q = dict(p)
        q["leg_km"] = round(leg, 1)
        out.append(q)
    return out, round(total, 1)
