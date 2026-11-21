"""Synthetic visual routes with coverage-aware costs; never rewrite MATSim XML."""
from collections import Counter, defaultdict
from dataclasses import replace
import heapq
import math
import warnings

from microscopic_traffic import Operation, agent_profile, desired_speed, stable_seed


def road_zone(road):
    if road.get("is_bypass", False):
        return "bypass"
    if all(road.get(k, "").startswith("R_") for k in ("from_id", "to_id")):
        return "roundabout"
    p, q = road["from"], road["to"]
    if abs(p[0] - q[0]) > 1e-6 and abs(p[1] - q[1]) > 1e-6:
        return "diagonal"
    return "grid"


def routing_summary(routes, links):
    zones = Counter()
    visited = set()
    for ops in routes.values():
        for op in ops:
            if op.kind == "drive" and op.last > op.first:
                visited.add(op.link)
                zones[road_zone(links[op.link])] += links[op.link]["length"] * (op.last - op.first)
    return len(visited), {zone: round(meters / 1000, 1) for zone, meters in sorted(zones.items())}


def balanced_routes(routes, links, aggressive_profiles=True, batch_size=None, progress=None):
    """Preserve OD links/activity durations; add distributed intermediate waypoints.

    Dijkstra operates on directed links and forbids immediate U-turns. Route
    costs penalize bypass use and previously assigned traffic. Waypoints cycle
    across road classes and prefer the least used links within each class.
    New times use synthetic travel estimates, never presented as XML times.
    """
    outgoing = defaultdict(list)
    pools = defaultdict(list)
    for key, road in sorted(links.items()):
        if "from_id" not in road or "to_id" not in road:
            raise ValueError("El reparto de rutas requiere IDs de nodos en la red")
        outgoing[road["from_id"]].append(key)
        if road.get("routing_eligible", True):
            pools[road_zone(road)].append(key)
    neighbors = {
        key: [n for n in outgoing[road["to_id"]] if links[n]["to_id"] != road["from_id"]]
        for key, road in links.items()
    }
    used = Counter()
    categories = ("grid", "diagonal", "grid", "roundabout", "grid", "bypass", "grid", "diagonal")
    result, failures, trip_index = {}, 0, 0
    batch_size = (4096 if len(routes) > 10000 else 1) if batch_size is None else batch_size
    if batch_size < 1:
        raise ValueError("El lote de rutas debe ser positivo")
    # Lab07 exports effective free speeds: length / freespeed already includes
    # hotspot friction. Adding effectiveDelaySeconds again would double-charge it.
    base_cost = {key: road["length"] / road["freespeed"] * (2.5 if road_zone(road) == "bypass" else 1)
                 for key, road in links.items()}
    trees, frozen_cost = {}, {}
    epoch = -1

    def path(start, goal):
        nonlocal epoch, frozen_cost
        if batch_size > 1:
            current_epoch = trip_index // batch_size
            if epoch != current_epoch:
                trees.clear()
                frozen_cost = {key: value * (1 + used[key] / 15) for key, value in base_cost.items()}
                epoch = current_epoch
            if start in trees:
                parent, reachable = trees[start]
                if goal not in reachable:
                    return None
                answer = [goal]
                while answer[-1] != start:
                    answer.append(parent[answer[-1]])
                return answer[::-1]
        queue = [(0.0, start)]
        costs, parent = {start: 0.0}, {}
        while queue:
            cost, current = heapq.heappop(queue)
            if cost > costs[current]:
                continue
            if current == goal and batch_size == 1:
                answer = [current]
                while current != start:
                    current = parent[current]
                    answer.append(current)
                return answer[::-1]
            for nxt in neighbors[current]:
                candidate = cost + (frozen_cost[nxt] if batch_size > 1 else base_cost[nxt] * (1 + used[nxt] / 15))
                if candidate < costs.get(nxt, math.inf):
                    costs[nxt], parent[nxt] = candidate, current
                    heapq.heappush(queue, (candidate, nxt))
        if batch_size > 1:
            trees[start] = (parent, set(costs))
            if goal in costs:
                answer = [goal]
                while answer[-1] != start:
                    answer.append(parent[answer[-1]])
                return answer[::-1]
        return None

    for agent_number, (agent, ops) in enumerate(sorted(routes.items())):
        if progress and agent_number % 4096 == 0:
            progress(agent_number, len(routes))
        rebuilt, index, clock = [], 0, ops[0].start
        profile = agent_profile(agent)
        while index < len(ops):
            op = ops[index]
            if op.kind != "drive":
                start = max(clock, op.start)
                rebuilt.append(replace(op, start=start, end=start + op.end - op.start,
                                       source="synthetic-route"))
                clock = rebuilt[-1].end
                index += 1
                continue
            end = index + 1
            while end < len(ops) and ops[end].kind == "drive":
                end += 1
            trip = ops[index:end]
            sequence = [s.link for s in trip]
            if len(trip) > 1:
                category = categories[trip_index % len(categories)]
                candidates = pools.get(category, [key for key, road in links.items()
                                                  if road.get("routing_eligible", True)])
                ranked = sorted(candidates, key=lambda key: (used[key], stable_seed(f"{agent}:{trip_index}:{key}")))
                for waypoint in ranked[:16]:
                    before, after = path(trip[0].link, waypoint), path(waypoint, trip[-1].link)
                    if before is not None and after is not None:
                        sequence = before + after[1:]
                        break
                else:
                    failures += 1
                trip_index += 1
            clock = max(clock, trip[0].start)
            for i, key in enumerate(sequence):
                first = trip[0].first if i == 0 else 0.0
                last = trip[-1].last if i == len(sequence) - 1 else 1.0
                duration = max(0, last - first) * links[key]["length"] / desired_speed(profile, links[key], aggressive_profiles)
                rebuilt.append(Operation(key, clock, clock + duration, first, last, source="synthetic-route"))
                clock += duration
                used[key] += 1
            index = end
        result[agent] = rebuilt
    if failures:
        warnings.warn(f"{failures} viajes conservaron el recorrido original por falta de un desvío válido.")
    if progress:
        progress(len(routes), len(routes))
    return result
