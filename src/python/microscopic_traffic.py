"""Deterministic visual reconstruction, not a replacement for MATSim/QSim.

XML replay preserves event times. Microscopic playback preserves route order and
earliest event times, but queues may delay admission, arrival and activities.
Distances, speeds, capacities and time are in m, m/s, vehicles/hour and seconds.
"""
from collections import defaultdict, deque
from collections.abc import Mapping
from bisect import bisect_left, insort
from dataclasses import dataclass, replace
from functools import lru_cache
import gzip
import hashlib
import heapq
import math
import random
import time as wall_time
import warnings
import xml.etree.ElementTree as ET

SPEED_COLORS = ("#FFFFFF", "#FF6600", "#00BFFF", "#8A2BE2", "#FF0000", "#FFFF00")
STOP_SPEED = 1e-6  # Numerical zero, m/s; creeping vehicles remain orange.
GAP = 8.0  # Vehicle length plus standstill clearance, front-to-front.
ACCELERATION = 2.0
BRAKING = 3.0
PARKING_SECONDS = 3.0
DAY_SECONDS = 86400.0
DAY_PLAYBACK_SPEED = 120.0


def day_time(elapsed_seconds, speed=DAY_PLAYBACK_SPEED):
    """Wall-clock mapping, independent of the number of rendered frames."""
    if not math.isfinite(elapsed_seconds) or elapsed_seconds < 0 or not math.isfinite(speed) or speed <= 0:
        raise ValueError("Tiempo y escala inválidos")
    return min(DAY_SECONDS, elapsed_seconds * speed)


def daily_operations(routes):
    """Keep OD, route and departure; recompute movement rather than hold XML exits.

    Explicit activity durations remain constraints. This is a synthetic daily
    scenario, not a modification of observed events or a speed calibration.
    """
    return {agent: [replace(op, start=ops[0].start,
                           end=ops[0].start + (op.end - op.start if op.kind == "parking" else 0),
                           source="synthetic-day") for op in ops]
            for agent, ops in routes.items()}


class DayFrameCache:
    """Compact display samples at the selected playback scale; physics still integrates at <=0.5 s.

    Prepare before starting the real-time clock. Slow GUI refreshes skip display
    frames without slowing the day. Interpolate only within the same link/lane.
    """
    def __init__(self, frames, duration=DAY_SECONDS, spacing=4.0, progress=None):
        import numpy as np
        self.duration, self.spacing = duration, spacing
        if (not math.isfinite(spacing) or not math.isfinite(duration) or spacing <= 0
                or duration < 0 or abs(duration / spacing - round(duration / spacing)) > 1e-8):
            raise ValueError("Duración o muestreo inválido")
        self.frames, self.agents, self.links, self.states, self.sources = [], [], [], [], []
        maps = [{}, {}, {}, {}]
        tables = [self.agents, self.links, self.states, self.sources]

        def code(value, column):
            if value not in maps[column]:
                maps[column][value] = len(tables[column])
                tables[column].append(value)
            return maps[column][value]

        next_time, report_hour = 0.0, -1
        for time, frame in frames:
            if time > duration + 1e-8:
                break
            if time + 1e-8 < next_time:
                continue
            if abs(time - next_time) > 1e-8:
                raise ValueError("Los cuadros no estan alineados al muestreo de la cache")
            rows = [(code(agent, 0), code(s.link, 1), code(s.state, 2), code(s.source, 3),
                     s.lane, s.distance, s.speed, s.elapsed_time, s.travelled_distance, s.min_speed, s.max_speed)
                    for agent, s in frame.items()]
            self.frames.append(np.asarray(rows, dtype=np.float64).reshape(-1, 11))
            next_time += spacing
            if int(time // 3600) > report_hour:
                report_hour = int(time // 3600)
                if progress:
                    progress(time)
        expected = round(duration / spacing) + 1
        if len(self.frames) != expected:
            raise ValueError("La caché requiere cuadros desde 0 hasta el final, alineados al muestreo")

    def _decode(self, index):
        return {self.agents[int(r[0])]: Sample(self.links[int(r[1])], int(r[4]), r[5], r[6],
                    self.states[int(r[2])], self.sources[int(r[3])], r[7], r[8], r[9], r[10])
                for r in self.frames[index]}

    def at(self, time):
        time = max(0, min(self.duration, time))
        index = min(int(time / self.spacing), len(self.frames) - 1)
        left = self._decode(index)
        alpha = time / self.spacing - index
        if alpha <= 1e-8 or index + 1 == len(self.frames):
            return left
        right = self._decode(index + 1)
        original = dict(left)
        for agent, sample in list(left.items()):
            nxt = right.get(agent)
            if (nxt and nxt.link == sample.link and nxt.lane == sample.lane
                    and nxt.distance >= sample.distance and nxt.state == sample.state
                    and sample.state not in ("parking", "queued")):
                left[agent] = replace(sample,
                    distance=sample.distance + alpha * (nxt.distance - sample.distance),
                    speed=sample.speed + alpha * (nxt.speed - sample.speed),
                    elapsed_time=sample.elapsed_time + alpha * (nxt.elapsed_time - sample.elapsed_time),
                    travelled_distance=sample.travelled_distance + alpha * (nxt.travelled_distance - sample.travelled_distance),
                    min_speed=min(sample.min_speed, sample.speed + alpha * (nxt.speed - sample.speed)),
                    max_speed=max(sample.max_speed, sample.speed + alpha * (nxt.speed - sample.speed)))
        # During a leader's state/link transition its displayed position is held.
        # Hold that lane's interpolation too, preserving headways and telemetry.
        held_lanes = {(s.link, s.lane) for agent, s in original.items()
                      if agent not in right or right[agent].link != s.link
                      or right[agent].lane != s.lane or right[agent].state != s.state}
        for agent, sample in original.items():
            if (sample.link, sample.lane) in held_lanes:
                left[agent] = sample
        return left


class FocalContinuousCache:
    """Lazy physical timeline; retains history for backward seeking, never wraps IDs."""
    def __init__(self, engine):
        self.engine = engine
        self.stream = engine.frames(start_time=0)
        self.history = []

    def at(self, time):
        index = int(max(0, time) / self.engine.dt)
        alpha = max(0, time) / self.engine.dt - index
        last = index + (1 if alpha > 1e-8 else 0)
        while len(self.history) <= last:
            _, frame = next(self.stream)
            self.history.append(frame)
        left = self.history[index]
        if last == index:
            return left
        result = dict(left)
        for agent, sample in left.items():
            nxt = self.history[last].get(agent)
            if nxt and (sample.link,sample.lane,sample.state)==(nxt.link,nxt.lane,nxt.state):
                speed = sample.speed + alpha*(nxt.speed-sample.speed)
                result[agent] = replace(sample,
                    distance=sample.distance+alpha*(nxt.distance-sample.distance),speed=speed,
                    elapsed_time=sample.elapsed_time+alpha*(nxt.elapsed_time-sample.elapsed_time),
                    travelled_distance=sample.travelled_distance+alpha*(nxt.travelled_distance-sample.travelled_distance),
                    min_speed=min(sample.min_speed,speed),max_speed=max(sample.max_speed,speed))
        return result


class PlaybackClock:
    """Absolute simulation time; rates multiply the selected simulated seconds per wall second."""
    def __init__(self, base_speed=DAY_PLAYBACK_SPEED, now=None):
        self.now = now or wall_time.perf_counter
        self.base_speed, self.rate, self.time = base_speed, 1.0, 0.0
        self.anchor = None

    def tick(self):
        now = self.now()
        if self.anchor is not None:
            self.time = max(0.0, self.time + (now - self.anchor) * self.base_speed * self.rate)
        self.anchor = now
        return self.time

    def set_scale(self, scale):
        if not math.isfinite(scale) or scale <= 0:
            raise ValueError('La escala debe ser positiva y finita')
        self.tick()  # Settle elapsed real time at the OLD scale before changing it.
        self.base_speed = scale

    def set_rate(self, rate):
        if not math.isfinite(rate):
            raise ValueError("Velocidad de reproduccion invalida")
        self.tick()
        self.rate = rate

    def seek(self, seconds):
        if not math.isfinite(seconds) or seconds < 0:
            raise ValueError("Tiempo de busqueda invalido")
        self.time, self.anchor = seconds, self.now()
        return self.time

    def seek_day(self, seconds):
        if not 0 <= seconds <= DAY_SECONDS - 1:
            raise ValueError("Hora fuera de 00:00:00-23:59:59")
        return self.seek(math.floor(self.time / DAY_SECONDS) * DAY_SECONDS + seconds)


class PeriodicFrameCache:
    """Repeat a physically joined day, with bounded storage and stable trip IDs.

    Consecutive cohorts share the same engine/queues. A quiet seam is required
    after warmup AND one period later; it is not assumed to occur at midnight.
    If the scenario never drains, refuse a false periodic approximation.
    """
    def __init__(self, engine, period=DAY_SECONDS, spacing=4.0, progress=None):
        self.period = period
        if period <= 0 or abs(period / spacing - round(period / spacing)) > 1e-8:
            raise ValueError("Periodo incompatible con el muestreo")
        stream = engine.frames(start_time=0, end_time=3 * period,
                               repeat_period=period, cycles=3)
        self.origin = None

        def joined_frames():
            last_hour = -1
            for time, frame in stream:
                if getattr(engine, 'gridlock_time', None) is not None:
                    raise RuntimeError("La red no se vacia: bloqueo permanente certificado "
                                       f"a t={engine.gridlock_time:.1f} s; no se descartan agentes para cerrar el ciclo")
                if progress and int(time // 3600) != last_hour:
                    last_hour = int(time // 3600)
                    progress(time)
                if self.origin is None:
                    if time >= period and engine.quiet and not frame and abs(time / spacing - round(time / spacing)) < 1e-8:
                        self.origin = time
                    elif time >= 2 * period:
                        raise RuntimeError("La red no se vacia: no se puede cerrar un ciclo continuo sin perder colas")
                    else:
                        continue
                elapsed = time - self.origin
                if elapsed >= period:
                    if not engine.quiet or frame:
                        raise RuntimeError("El estado final no coincide con el inicio del ciclo")
                    yield period, frame
                    return
                yield elapsed, frame
        try:
            self.cache = DayFrameCache(joined_frames(), duration=period, spacing=spacing)
        finally:
            stream.close()

    def at(self, time):
        if not math.isfinite(time) or time < 0:
            raise ValueError("Tiempo absoluto invalido")
        shift = math.floor((time - self.origin) / self.period)
        phase = time - self.origin - shift * self.period
        frame = self.cache.at(phase)
        return {f"D{int(agent.split('::', 1)[0]) + shift + 1}:{agent.split('::', 1)[1]}": sample
                for agent, sample in frame.items()}


def speed_color(speed, frame_index=0):
    """Map instantaneous m/s to km/h bands, including fractional speeds.

    0 white, (0,30] orange, (30,60] cyan, (60,100] purple, >100 red.
    At >=150 km/h alternate red/yellow on successive simulation frames.
    """
    if not math.isfinite(speed) or speed < 0:
        raise ValueError("La velocidad debe ser finita y no negativa")
    if speed == 0:
        return SPEED_COLORS[0]
    if speed <= 30 / 3.6:
        return SPEED_COLORS[1]
    if speed <= 60 / 3.6:
        return SPEED_COLORS[2]
    if speed <= 100 / 3.6:
        return SPEED_COLORS[3]
    if speed >= 150 / 3.6:
        return SPEED_COLORS[4 + int(frame_index) % 2]
    return SPEED_COLORS[4]


def stable_seed(value):
    return int.from_bytes(hashlib.sha256(str(value).encode()).digest()[:8], "big")


@dataclass(frozen=True)
class Profile:
    speed_factor: float
    stop_probability: float
    bypass_factor: float = 1.0
    night_factor: float = 1.75
    kind: str = "legacy"
    individual_factor: float = 1.0


def random_focal_profile():
    """One uniform OS-random draw per execution, never per frame or agent ID."""
    rng = random.SystemRandom()
    kind = rng.choice(("normal", "tortuga", "liebre"))
    factor = rng.gauss(1.0, .05)
    while not .8 <= factor <= 1.2:
        factor = rng.gauss(1.0, .05)
    return Profile(1.5 if kind == "liebre" else 1.0, 0, kind=kind, individual_factor=factor)


@lru_cache(maxsize=10000)
def agent_profile(agent):
    rng = random.Random(stable_seed(agent))
    group = rng.random()
    factor = .7 if group < .25 else (1.0 if group > .8 else .88)
    stops = .4 if rng.random() < .35 else 0.0
    # Reproducible visual scenarios: 4% aggressive, 1% exceptional profiles.
    aggressive = random.Random(stable_seed(f"{agent}:aggressive")).random()
    bypass_factor = 2.15 if aggressive < .01 else (1.65 if aggressive < .05 else 1.0)
    return Profile(factor, stops, bypass_factor,
                   1.5 + .5 * random.Random(stable_seed(f"{agent}:night")).random())


def desired_speed(profile, road, aggressive=True, time=None):
    """Synthetic temporal speed hypotheses apply only to explicitly tagged roads."""
    if profile.kind == "tortuga":
        return 3.0 * profile.individual_factor
    if profile.kind in ("normal", "liebre"):
        return road["freespeed"] * profile.speed_factor * profile.individual_factor
    if time is not None and aggressive and road.get("extreme_night", False):
        hour = time % DAY_SECONDS / 3600
        blend = 1.0 if hour < 4 else max(0.0, (4.5 - hour) / .5)
        factor = profile.speed_factor + blend * (profile.night_factor - profile.speed_factor)
        return road["freespeed"] * factor
    if time is not None and aggressive and road.get("night_freespeed"):
        hour = (time % 86400) / 3600
        # Smooth transition avoids imposing an instantaneous morning speed drop.
        blend = 1.0 if hour < 4 else (max(0.0, (4.5 - hour) / .5) if hour < 4.5 else 0.0)
        return (road["freespeed"] + blend * (road["night_freespeed"] - road["freespeed"])) * profile.speed_factor
    if aggressive and road.get("is_bypass", False) and profile.bypass_factor > 1:
        return road["freespeed"] * profile.bypass_factor
    return road["freespeed"] * profile.speed_factor


def following_acceleration(speed, target, leader_speed=None, front_distance=None, profile=None):
    """Reactive longitudinal controller: speed matching plus time-gap feedback.

    Equilibrium is leader speed with GAP + 1.2 * speed front-to-front distance.
    A separate displacement clamp guarantees the minimum gap if comfortable
    deceleration is insufficient. This is not a calibrated intersection model.
    """
    kind = profile.kind if profile else 'legacy'
    accel, brake, reaction, headway = {
        'normal': (2.0,4.0,.9,1.5),
        'tortuga': (.8,3.0,1.4,2.0),
        'liebre': (3.0,5.0,.6,1.0),
    }.get(kind,(ACCELERATION,BRAKING,.8,1.2))
    acceleration = (target - speed) / reaction
    if leader_speed is not None:
        gap_error = front_distance - GAP - headway * speed
        acceleration = min(acceleration, .7 * (leader_speed - speed) + .4 * gap_error)
    comfortable = max(-brake, min(accel, acceleration))
    if kind != 'legacy' and leader_speed is not None and speed > leader_speed:
        clearance = max(.01, front_distance-GAP)
        required = max(0, speed*speed-leader_speed*leader_speed)/(2*clearance)
        if required > brake:
            return min(comfortable, -min(12.0, required))
    return comfortable


def sample_color(sample, frame_index=0):
    return speed_color(sample.speed, frame_index)


@dataclass(frozen=True)
class Operation:
    link: str
    start: float
    end: float
    first: float = 0.0
    last: float = 1.0
    kind: str = "drive"
    source: str = "XML"


def read_operations(path, links):
    """Stream XML, pairing each entry/exit and parking start/end explicitly."""
    routes = defaultdict(list)
    drivers, active, parking, arrivals = {}, {}, {}, {}
    rejected = 0
    opener = gzip.open if str(path).endswith(".gz") else open
    with opener(path, "rb") as stream:
        context = ET.iterparse(stream, events=("start", "end"))
        _, root = next(context)
        for phase, elem in context:
            if phase != "end" or elem.tag != "event":
                continue
            a = elem.attrib
            kind, link = a.get("type"), a.get("link")
            person = a.get("person")
            vehicle = a.get("vehicle") or person
            time = float(a["time"])
            if kind == "vehicle enters traffic" and vehicle:
                drivers[vehicle] = person or vehicle
            if kind in ("entered link", "vehicle enters traffic") and vehicle:
                if vehicle in active:
                    rejected += 1
                active[vehicle] = (drivers.get(vehicle, person or vehicle), link,
                                   time, float(a.get("relativePosition", 0)))
            elif kind in ("left link", "vehicle leaves traffic") and vehicle:
                entry = active.pop(vehicle, None)
                if entry:
                    agent, entered_link, start, fraction = entry
                    end_fraction = float(a.get("relativePosition", 1))
                    if (entered_link == link and link in links and time >= start
                            and 0 <= fraction <= end_fraction <= 1):
                        routes[agent].append(Operation(link, start, time, fraction, end_fraction))
                        arrivals[agent] = (link, end_fraction)
                    else:
                        rejected += 1
                if kind == "vehicle leaves traffic":
                    drivers.pop(vehicle, None)
            elif kind == "actstart" and a.get("actType") == "parking" and person:
                fraction = arrivals.get(person, (None, 1))[1] if arrivals.get(person, (None,))[0] == link else 1.0
                # An activity coordinate, when supplied, is projected onto its link.
                if link in links and "x" in a and "y" in a:
                    p, q = links[link]["from"], links[link]["to"]
                    dx, dy = q[0] - p[0], q[1] - p[1]
                    norm = dx * dx + dy * dy
                    if norm:
                        fraction = max(0, min(1, ((float(a["x"]) - p[0]) * dx +
                                                 (float(a["y"]) - p[1]) * dy) / norm))
                parking[person] = (link, time, fraction)
            elif kind == "actend" and a.get("actType") == "parking" and person:
                entry = parking.pop(person, None)
                if entry:
                    parked_link, start, fraction = entry
                    if link == parked_link and link in links and time >= start:
                        routes[person].append(Operation(link, start, time, fraction, fraction, "parking"))
                    else:
                        rejected += 1
            elem.clear()
            root.clear()
    rejected += len(active) + len(parking)
    if rejected:
        warnings.warn(f"Se omitieron {rejected} tramos/actividades incompletos o inválidos.")
    # Stable sort preserves XML ordering for instantaneous trips and activities.
    return {agent: sorted(ops, key=lambda op: op.start) for agent, ops in routes.items()}


def lane_for(agent, link):
    return stable_seed(agent) % max(1, int(link.get("lanes", 1)))


def position(link, distance, lane):
    fraction = distance / link["length"]
    p, q = link["from"], link["to"]
    dx, dy = q[0] - p[0], q[1] - p[1]
    norm = math.hypot(dx, dy)
    # All lanes lie to the right of travel. Opposite directions stay separate.
    offset = ((lane - (link.get("lanes", 1) - 1) / 2) * link["lane_width"]
              if "lane_width" in link else 1.75 + 3.5 * lane)
    offset += link.get('lateral_offset', 0)
    return (p[0] + dx * fraction + (dy / norm * offset if norm else 0),
            p[1] + dy * fraction - (dx / norm * offset if norm else 0))


def vehicle_hitbox(road, distance, lane, length=4.5, width=1.8):
    """Oriented rectangle in metres; position() is the vehicle centre."""
    x, y = position(road, distance, lane)
    dx, dy = (road['to'][i] - road['from'][i] for i in (0, 1))
    norm = math.hypot(dx, dy)
    if norm <= 0 or length <= 0 or width <= 0:
        raise ValueError('Invalid vehicle/road geometry')
    ux, uy = dx/norm, dy/norm
    return tuple((x + a*length/2*ux - b*width/2*uy,
                  y + a*length/2*uy + b*width/2*ux)
                 for a,b in ((-1,-1),(1,-1),(1,1),(-1,1)))


def polygons_overlap(a, b):
    """Separating axes for convex polygons; touching counts as collision."""
    for polygon in (a, b):
        for p, q in zip(polygon, polygon[1:] + polygon[:1]):
            axis = (p[1]-q[1], q[0]-p[0])
            pa = [x*axis[0]+y*axis[1] for x,y in a]
            pb = [x*axis[0]+y*axis[1] for x,y in b]
            if max(pa) < min(pb) - 1e-9 or max(pb) < min(pa) - 1e-9:
                return False
    return True


def validate_focal_clearance(routes, links, obstacles):
    """Conservative swept bounds cover travel, lane changes and junction rotation.

    Obstacles are explicit axis-aligned boxes [xmin,ymin,xmax,ymax] in metres.
    Reject an unsafe route before admission, rather than teleporting through it.
    Bounds may reject a physically possible route; they never claim unknown objects.
    """
    boxes = []
    for box in obstacles:
        if len(box) != 4 or not all(math.isfinite(v) for v in box) or box[0] >= box[2] or box[1] >= box[3]:
            raise ValueError('Obstacle must be [xmin,ymin,xmax,ymax], finite and nonempty')
        x,y,u,v = box
        boxes.append(((x,y),(u,y),(u,v),(x,v)))
    radius = math.hypot(4.5, 1.8)/2
    for operations in routes.values():
        previous = []
        for op in operations:
            road = links[op.link]
            if road.get('lane_width', 3.5) < 1.8:
                raise ValueError('Lane narrower than vehicle')
            starts = [position(road, op.first*road['length'], lane) for lane in range(road['lanes'])]
            ends = [position(road, op.last*road['length'], lane) for lane in range(road['lanes'])]
            points = previous + starts + ends
            xmin = min(p[0] for p in points)-radius
            xmax = max(p[0] for p in points)+radius
            ymin = min(p[1] for p in points)-radius
            ymax = max(p[1] for p in points)+radius
            swept = ((xmin,ymin),(xmax,ymin),(xmax,ymax),(xmin,ymax))
            if any(polygons_overlap(swept, box) for box in boxes):
                raise ValueError(f'Focal swept hitbox intersects obstacle near {op.link}')
            previous = ends


def intersection_clear(vehicle, active, links, horizon=3.0, time=None):
    """Check receiving lane, lateral junction occupancy and priority arrival window.

    Conservative node conflict zone, not a calibrated intersection trajectory model.
    Account for acceleration: a slow priority vehicle can reach the node soon too.
    """
    road = links[vehicle.op.link]
    node = road.get('to_id')
    nxt = vehicle.ops[vehicle.index+1] if vehicle.index+1 < len(vehicle.ops) else None
    connected = [r for r in links.values() if node is not None and node in (r.get('from_id'), r.get('to_id'))]
    radius = max([GAP] + [r['lanes']*r.get('lane_width',3.5)/2 for r in connected])
    # Time for a stopped minor-road car to clear the entire junction, plus margin.
    crossing_accel = {'tortuga':.8,'normal':2.0,'liebre':3.0}.get(vehicle.profile.kind,ACCELERATION)
    clearance_time = math.sqrt(2*(2*radius + vehicle.length)/crossing_accel) + 1
    horizon = max(horizon, clearance_time)
    for other in active.values():
        if other is vehicle or not other.visible:
            continue
        incoming = links[other.op.link]
        if nxt and other.op.link == nxt.link:
            lane = min(vehicle.lane, incoming['lanes']-1)
            if other.lane == lane and other.distance - nxt.first*incoming['length'] < GAP:
                return False
        if incoming.get('from_id') == node and other.distance < radius + other.length/2:
            return False
        remaining = max(0, incoming['length']-other.distance)
        if incoming.get('to_id') == node and remaining < radius + other.length/2:
            return False
        if incoming.get('to_id') == node and incoming.get('right_of_way', False):
            plan = incoming.get('signal_plan')
            if plan and time is not None and not other.signal_committed:
                color = plan.states(time)[0 if incoming['signal_group']=='avenue' else 1]
                if color != 'green' and other.distance <= incoming['length']-incoming.get('stop_setback',3.25)+1e-8:
                    continue  # A stopped priority approach cannot override its red.
            approach_accel = {'tortuga':.8,'normal':2.0,'liebre':3.0}.get(other.profile.kind,ACCELERATION)
            if remaining <= other.speed*horizon + .5*approach_accel*horizon*horizon + radius:
                return False
    return True


def exit_speed(op, nxt, links, profile, aggressive=True, time=None):
    """Look ahead to the next road's speed, instead of stopping at every node."""
    if nxt is None or nxt.kind != "drive" or op.last < 1 or nxt.first > 0:
        return 0.0
    road, following = links[op.link], links[nxt.link]
    if (road.get("to_id") is None or road["to_id"] != following.get("from_id")
            or op.link == nxt.link):
        return 0.0
    target = desired_speed(profile, following, aggressive, time)
    # Sharp turns still require an approach speed reduction. Gentle curves and
    # straight bypass segments keep their free-flow speed.
    dx, dy = (road["to"][i] - road["from"][i] for i in (0, 1))
    nx, ny = (following["to"][i] - following["from"][i] for i in (0, 1))
    norm = math.hypot(dx, dy) * math.hypot(nx, ny)
    if norm and (dx * nx + dy * ny) / norm < .5:
        target = min(target, 8.33 * profile.speed_factor)
    return target


@dataclass(frozen=True)
class Sample:
    link: str
    lane: int
    distance: float
    speed: float
    state: str
    source: str = "XML"
    elapsed_time: float = 0.0
    travelled_distance: float = 0.0
    min_speed: float = 0.0
    max_speed: float = 0.0

    @property
    def elapsed_clock(self):
        seconds = max(0, int(self.elapsed_time))
        return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"

    @property
    def mean_speed(self):
        """Distance/time, including parking and queueing; all values in SI units."""
        return self.travelled_distance / self.elapsed_time if self.elapsed_time > 0 else 0.0


def replay_frames(routes, links, dt=.2):
    """Exact XML intervals; intra-link position is inferred, never measured."""
    if not routes:
        return
    indexes = dict.fromkeys(routes, 0)
    travelled = dict.fromkeys(routes, 0.0)
    minimum = dict.fromkeys(routes, math.inf)
    maximum = dict.fromkeys(routes, 0.0)
    start = min(ops[0].start for ops in routes.values())
    end = max(ops[-1].end for ops in routes.values())
    for tick in range(math.ceil((end - start) / dt) + 1):
        time = round(start + tick * dt, 9)
        frame = {}
        for agent, ops in routes.items():
            i = indexes[agent]
            while i < len(ops) and ops[i].end <= time:
                past = ops[i]
                travelled[agent] += links[past.link]["length"] * (past.last - past.first)
                if past.kind == "parking" and past.end > past.start:
                    minimum[agent] = 0.0
                i += 1
            indexes[agent] = i
            if i == len(ops) or time < ops[i].start:
                continue
            op = ops[i]
            alpha = (time - op.start) / (op.end - op.start)
            length = links[op.link]["length"]
            speed = length * (op.last - op.first) / (op.end - op.start)
            minimum[agent] = min(minimum[agent], speed)
            maximum[agent] = max(maximum[agent], speed)
            frame[agent] = Sample(op.link, lane_for(agent, links[op.link]),
                                  length * (op.first + alpha * (op.last - op.first)),
                                  speed, op.kind, op.source, time - ops[0].start,
                                  travelled[agent] + length * alpha * (op.last - op.first), minimum[agent], maximum[agent])
        yield time, frame


@dataclass
class Vehicle:
    agent: str
    ops: list
    profile: Profile
    seed_agent: str = ""
    index: int = 0
    visible: bool = False
    lane: int = 0
    distance: float = 0.0
    speed: float = 0.0
    hold_until: float = -math.inf
    stop_at: float | None = None
    stop_done: bool = False
    spawn_time: float | None = None
    travelled_distance: float = 0.0
    min_speed: float = math.inf
    max_speed: float = 0.0
    length: float = 4.5
    width: float = 1.8
    last_lane_change: float = -math.inf
    yield_until: float | None = None
    yield_released: bool = False
    entered_links: int = 0
    signal_committed: bool = False

    @property
    def op(self):
        return self.ops[self.index]


class LaneIndex:
    """Snapshot index for sequential lane decisions; updated on every reservation."""
    def __init__(self, occupied):
        self.rows = {key: sorted((v.distance, v.agent, v) for v in queue)
                     for key, queue in occupied.items()}

    def neighbors(self, vehicle, lane):
        rows = self.rows.get((vehicle.op.link, lane), ())
        index = bisect_left(rows, (vehicle.distance,))
        ahead = index
        while ahead < len(rows) and rows[ahead][2] is vehicle:
            ahead += 1
        behind = index - 1
        return (rows[ahead][2] if ahead < len(rows) else None,
                rows[behind][2] if behind >= 0 else None)

    def move(self, vehicle, old_lane, new_lane):
        row = (vehicle.distance, vehicle.agent, vehicle)
        rows = self.rows[vehicle.op.link, old_lane]
        rows.pop(bisect_left(rows, (vehicle.distance, vehicle.agent)))
        insort(self.rows.setdefault((vehicle.op.link, new_lane), []), row)


def lane_change_candidate(vehicle, road, occupied, time, target, lane_index=None):
    """Discrete adjacent-lane decision: incentive + front/rear braking gaps.

    Commit one vehicle at a time against updated occupancy, preventing two
    simultaneous claims on the same gap. No changes near a junction or while
    parking. This is a scenario model, not calibrated MOBIL parameters.
    """
    if (not road.get("lane_changing", False) or time - vehicle.last_lane_change < 5
            or vehicle.op.kind != "drive" or time < vehicle.hold_until
            or vehicle.distance < 12 or road["length"] - vehicle.distance < 20):
        return None

    def neighbors(lane):
        if lane_index is not None:
            return lane_index.neighbors(vehicle, lane)
        others = [w for w in occupied.get((vehicle.op.link, lane), ()) if w is not vehicle]
        front = min((w for w in others if w.distance >= vehicle.distance),
                    key=lambda w: w.distance, default=None)
        rear = max((w for w in others if w.distance < vehicle.distance),
                   key=lambda w: w.distance, default=None)
        return front, rear

    def attainable(front):
        if front is None:
            return target
        return min(target, max(0, front.speed +
                   (front.distance - vehicle.distance - GAP - 1.2 * vehicle.speed) / 3))

    front, _ = neighbors(vehicle.lane)
    baseline = attainable(front)
    best, gain = None, {'normal':1.5,'tortuga':2.0,'liebre':.8}.get(vehicle.profile.kind,1.5)
    for lane in (vehicle.lane - 1, vehicle.lane + 1):
        if not 0 <= lane < road["lanes"]:
            continue
        ahead, behind = neighbors(lane)
        front_gap = GAP + .8 * vehicle.speed
        rear_gap = GAP
        if ahead:
            front_gap += max(0, vehicle.speed**2 - ahead.speed**2) / (2 * BRAKING)
        if behind:
            rear_gap += 1.2 * behind.speed + max(0, behind.speed**2 - vehicle.speed**2) / (2 * BRAKING)
        if ((ahead and ahead.distance - vehicle.distance < front_gap)
                or (behind and vehicle.distance - behind.distance < rear_gap)):
            continue
        benefit = attainable(ahead) - baseline
        if benefit > gain:
            best, gain = lane, benefit
    return best

class FrozenQueueFrame(Mapping):
    """Immutable, lazy samples of a proven absorbing queue; clock still advances."""
    def __init__(self, frame, elapsed):
        self.frame, self.elapsed = frame, elapsed

    def __len__(self):
        return len(self.frame)

    def __iter__(self):
        return iter(self.frame)

    def __getitem__(self, agent):
        sample = self.frame[agent]
        return replace(sample, elapsed_time=sample.elapsed_time+self.elapsed)


def absorbing_gridlock(active, occupied, links, last_exit, time, max_active, daily, aggressive):
    """Sufficient (not necessary) proof of permanent standstill in this model.

    Full admission cap prevents external perturbation. Every interior vehicle
    is at the exact stopped-following clamp; every endpoint is blocked by a
    receiving vehicle. All releases/cooldowns have expired. Test lane incentives
    at maximum possible daily target (the gain is monotone in this target when
    all speeds are zero). No future clock change can enable any transition.
    """
    if not active or len(active) < max_active:
        return False
    index = LaneIndex(occupied)
    for v in active.values():
        road, op = links[v.op.link], v.op
        if (v.speed != 0 or op.kind not in ('drive','parking') or op.end > time or v.hold_until > time
                or time-v.last_lane_change < 5):
            return False
        if time-last_exit.get((op.link,v.lane), -math.inf) < 3600*road['lanes']/road['capacity']:
            return False
        targets = (0, 4.5*3600, time) if daily else (None,)
        target = max(desired_speed(v.profile, road, aggressive, t) for t in targets)
        if lane_change_candidate(v,road,occupied,time,target,index) is not None:
            return False
        if op.kind == 'drive' and op.last*road['length']-v.distance > 1e-8:
            ahead, _ = index.neighbors(v, v.lane)
            if ahead is not None:
                if ahead.distance-v.distance > GAP+1e-8:
                    return False
            else:
                # Spillback can stop the head *before* its endpoint: the
                # receiving lane's first car is its virtual longitudinal leader.
                if v.index+1 == len(v.ops):
                    return False
                nxt = v.ops[v.index+1]
                receiver = links[nxt.link]
                if (nxt.kind != 'drive' or nxt.link == op.link or road.get('to_id') is None
                        or road['to_id'] != receiver.get('from_id')):
                    return False
                lane = min(v.lane,receiver['lanes']-1) if 'lane_width' in receiver else lane_for(v.seed_agent,receiver)
                receiving = occupied.get((nxt.link,lane), ())
                if not receiving:
                    return False
                clearance = max(0, op.last*road['length']-v.distance
                                + min(w.distance for w in receiving)-nxt.first*receiver['length']-GAP)
                if clearance+GAP > GAP:
                    return False
        else:
            if v.index+1 == len(v.ops):
                return False
            nxt = v.ops[v.index+1]
            if nxt.kind != 'drive' or nxt.start > time:
                return False
            receiver = links[nxt.link]
            lane = min(v.lane,receiver['lanes']-1) if 'lane_width' in receiver else lane_for(v.seed_agent,receiver)
            distance = nxt.first*receiver['length']
            if not any(w is not v and abs(w.distance-distance) < GAP-1e-8
                       for w in occupied.get((nxt.link,lane), ())):
                return False
    return True


class MicroscopicPlayback:
    """Fixed-step FIFO lane model with receiving-space checks and spillback.

    This is a visual model: no calibrated intersection priority or collision
    geometry across crossing/opposing lanes. Safety is longitudinal per lane.
    Vehicle demand is queued off-map if its XML spawn position is occupied.
    """
    def __init__(self, routes, links, dt=.2, synthetic_stops=True, max_delay=7200,
                 aggressive_profiles=True, daily=False, focal=False, obstacles=(), persistent=False):
        if not math.isfinite(dt) or dt <= 0 or dt > .5 or abs(3 / dt - round(3 / dt)) > 1e-8:
            raise ValueError("El paso debe dividir 3 s exactamente y ser <= 0.5 s.")
        self.routes, self.links, self.dt = routes, links, dt
        self.synthetic_stops, self.max_delay = synthetic_stops, max_delay
        self.aggressive_profiles = aggressive_profiles
        self.daily = daily
        if persistent and not focal:
            raise ValueError('Persistence requires the single focal agent')
        self.persistent = persistent
        self.obstacles = obstacles
        if persistent:
            routes = {a: [replace(op, start=0, end=0, first=0, last=1) for op in ops if op.kind == 'drive']
                      for a,ops in routes.items()}
            self.routes = routes
        if focal and len(routes) != 1:
            raise ValueError("Lab08 requires exactly one agent")
        if obstacles and not focal:
            raise ValueError('Obstacle clearance is currently supported only for the focal scenario')
        if focal:
            validate_focal_clearance(routes, links, obstacles)
        self.focal_profile = random_focal_profile() if focal else None
        if focal:
            self.synthetic_stops = False
        self.completed = 0
        self.parking_log = []
        self.max_active = min((r.get("max_active", math.inf) for r in links.values()), default=math.inf)
        if focal:
            self.max_active = 1
        self.peak_active = 0
        self.lane_change_log = []
        self.intersection_log = []
        self.lane_changing = any(r.get("lane_changing", False) for r in links.values())

    def frames(self, start_time=None, end_time=None, repeat_period=None, cycles=1, resume_state=None):
        if getattr(self, "focal_profile", None) and cycles != 1:
            raise ValueError("Lab08 runs one journey, without repeated cohorts")
        if not self.routes:
            return
        if cycles < 1 or (cycles > 1 and (repeat_period is None or repeat_period <= 0)):
            raise ValueError("Repeticion temporal invalida")
        # Pending demand references shared routes, not duplicated Vehicle/Operation
        # graphs for all cohorts. Materialize a vehicle only at its departure.
        pending = deque(sorted((ops[0].start + day * (repeat_period or 0),
                                f"{day}::{a}" if repeat_period else a, day, a)
                               for day in range(cycles) for a, ops in self.routes.items()))
        vehicle_count = len(pending)
        waiting, active = defaultdict(deque), {}
        occupied = defaultdict(list)
        last_exit = defaultdict(lambda: -math.inf)
        self.completed = 0
        self.parking_log = []
        self.peak_active = 0
        self.lane_change_log = []
        self.intersection_log = []
        start = pending[0][0] if start_time is None else start_time
        deadline = max(ops[-1].end for ops in self.routes.values()) + (cycles - 1) * (repeat_period or 0) + self.max_delay
        if self.persistent:
            deadline = math.inf
        quiet_gap = max(3600 * road["lanes"] / road["capacity"] for road in self.links.values())
        self.quiet = False
        self.gridlock_time = None
        frozen_frame = None

        def key(v):
            return v.op.link, v.lane

        def enter(v, index, time):
            op = v.ops[index]
            if time + 1e-8 < op.start:
                return False
            link = self.links[op.link]
            lane = lane_for(v.seed_agent, link)
            if v.visible and "lane_width" in link:
                lane = min(v.lane, link["lanes"] - 1)
            distance = op.first * link["length"]
            if not v.visible and "lane_width" in link:
                available = [i for i in range(link["lanes"])
                             if all(abs(w.distance - distance) >= GAP for w in occupied[op.link, i])]
                if not available:
                    return False
                lane = min(available, key=lambda i: (len(occupied[op.link, i]), (i - lane) % link["lanes"]))
            if any(w is not v and abs(w.distance - distance) < GAP - 1e-8
                   for w in occupied[op.link, lane]):
                return False
            if v.visible:
                occupied[key(v)].remove(v)
            v.index, v.lane, v.distance = index, lane, distance
            v.visible, v.stop_done = True, False
            v.hold_until, v.stop_at = -math.inf, None
            v.entered_links += 1
            v.yield_until, v.yield_released = None, False
            v.signal_committed = False
            v.speed = min(v.speed, desired_speed(v.profile, link, self.aggressive_profiles, time if self.daily else None))
            night_free = self.daily and link.get("extreme_night", False) and time % DAY_SECONDS < 4 * 3600
            if (self.focal_profile and op.kind == 'drive' and link['length'] >= 60
                    and link.get('attributes',{}).get('roadClass','local') in ('street','local')
                    and v.entered_links % 4 == 1 and op.first < .55 < op.last):
                v.stop_at = .55 * link['length']
            if self.synthetic_stops and not night_free and op.kind == "drive" and link.get("internal", False):
                rng = random.Random(stable_seed(f"{v.seed_agent}:{index}:stop"))
                if op.first < .55 < op.last and rng.random() < v.profile.stop_probability:
                    v.stop_at = .55 * link["length"]
            occupied[key(v)].append(v)
            if v.spawn_time is None:
                v.spawn_time = time
            if op.kind == "parking":
                v.speed = 0
                v.hold_until = time + op.end - op.start
                self.parking_log.append((v.agent, time, v.hold_until, op.source, op.link, v.distance))
            return True

        def sample(v, time, speed, state, source):
            if speed <= STOP_SPEED:
                speed = 0.0
                state = state if state in ("parking", "yielding", "signal") else "queued"
            v.min_speed = min(v.min_speed, speed)
            v.max_speed = max(v.max_speed, speed)
            return Sample(v.op.link, v.lane, v.distance, speed, state, source,
                          time - v.spawn_time, v.travelled_distance, v.min_speed, v.max_speed)

        tick = 0
        if resume_state is not None:
            # Trusted local benchmark checkpoint, taken immediately after yield.
            pending, waiting, active = (resume_state[k] for k in ('pending','waiting','active'))
            occupied = resume_state['occupied']
            last_exit = defaultdict(lambda: -math.inf, resume_state['last_exit'])
            start, tick, deadline, quiet_gap, vehicle_count, frozen_frame = (
                resume_state[k] for k in ('start','tick','deadline','quiet_gap','vehicle_count','frozen_frame'))
            for attribute, value in resume_state['engine_attrs'].items():
                setattr(self,attribute,value)
        while self.completed < vehicle_count or (end_time is not None and start + tick * self.dt <= end_time):
            time = round(start + tick * self.dt, 9)
            if end_time is not None and time > end_time + 1e-8:
                return
            if time > deadline and self.completed < vehicle_count:
                raise RuntimeError("La reproducción microscópica no se vació: posible bloqueo circular. "
                                   "Use --mode replay para consultar los tiempos XML.")
            if frozen_frame is not None:
                # Demand remains referenced in pending/waiting; a full, proven
                # absorbing state can never admit it. Never reset or drop agents.
                yield time, FrozenQueueFrame(frozen_frame, time-self.gridlock_time)
                tick += 1
                continue
            # Exit/transfer before admitting demand; a full receiving lane holds
            # its upstream vehicle in place, propagating queues across links.
            for v in list(active.values()):
                if not v.visible:
                    continue
                if self.persistent and v.index == len(v.ops)-1:
                    candidates = [k for k,r in self.links.items()
                                  if r.get('from_id') == self.links[v.op.link].get('to_id')
                                  and r.get('routing_eligible', True)]
                    random.SystemRandom().shuffle(candidates)
                    for candidate in candidates:
                        nxt = Operation(candidate, 0, 0)
                        try:
                            validate_focal_clearance({'focal': [v.op, nxt]}, self.links, self.obstacles)
                        except ValueError:
                            continue
                        v.ops = [v.op, nxt]
                        v.index = 0
                        break
                    else:
                        raise ValueError('No connected, obstacle-free continuation for focal agent')
                op, link = v.op, self.links[v.op.link]
                done = (time + 1e-8 >= v.hold_until if op.kind == "parking" else
                        v.distance >= op.last * link["length"] - 1e-8 and time + 1e-8 >= op.end)
                if not done:
                    if op.kind == "drive" and v.distance >= op.last * link["length"] - 1e-8:
                        v.speed = 0.0  # Waiting for the XML release time.
                    continue
                lane_key = key(v)
                headway = 3600 * link["lanes"] / link["capacity"]
                if op.kind == "drive" and time - last_exit[lane_key] < headway - 1e-8:
                    v.speed = 0.0
                    continue
                next_index = v.index + 1
                if next_index == len(v.ops):
                    occupied[lane_key].remove(v)
                    v.visible = False
                    v.index = next_index
                    self.completed += 1
                    active.pop(v.agent)
                else:
                    nxt = v.ops[next_index]
                    if nxt.kind == "parking" and nxt.link == op.link and time >= nxt.start:
                        # Retain the actual stopping position and lane; no jump to
                        # a link endpoint when entering an observed activity.
                        v.index = next_index
                        v.speed = 0
                        v.hold_until = time + nxt.end - nxt.start
                        self.parking_log.append((v.agent, time, v.hold_until, nxt.source, nxt.link, v.distance))
                    elif not enter(v, next_index, time):
                        v.speed = 0.0
                        continue
                last_exit[lane_key] = time

            while pending and pending[0][0] <= time + 1e-8:
                _, agent, day, seed = pending.popleft()
                offset = day * (repeat_period or 0)
                ops = self.routes[seed]
                if offset:
                    ops = [replace(op, start=op.start + offset, end=op.end + offset) for op in ops]
                v = Vehicle(agent, ops, getattr(self, "focal_profile", None) or agent_profile(seed), seed_agent=seed)
                road = self.links[v.op.link]
                entry = (v.op.link, v.op.first,
                         -1 if "lane_width" in road else lane_for(v.seed_agent, road))
                waiting[entry].append(v)
            # Admission only adds occupancy. If an entry has no space, no later
            # vehicle at that same position/lane can enter during this tick.
            # Merge queue heads in original departure/ID order, without scanning
            # thousands of identical blocked requests on every physics step.
            admissions = [(q[0].op.start, q[0].agent, entry) for entry, q in waiting.items()] if len(active) < self.max_active else []
            heapq.heapify(admissions)
            while admissions and len(active) < self.max_active:
                _, _, entry = heapq.heappop(admissions)
                q = waiting[entry]
                v = q[0]
                if enter(v, v.index, time):
                    active[v.agent] = v
                    q.popleft()
                    if q:
                        heapq.heappush(admissions, (q[0].op.start, q[0].agent, entry))
                    else:
                        del waiting[entry]
            occupied = defaultdict(list, {k: q for k, q in occupied.items() if q})
            # Decisions use pre-movement positions; successful reservations are
            # immediately visible to the next candidate (no simultaneous swaps).
            evaluate_changes = self.lane_changing and tick % max(1, round(1 / self.dt)) == 0
            lane_index = LaneIndex(occupied) if evaluate_changes else None
            for v in (sorted(active.values(), key=lambda w: (-w.distance, w.seed_agent)) if evaluate_changes else ()):
                road = self.links[v.op.link]
                if (road.get('stop_before_avenue', False) or road.get('signal_plan')) and road['length']-v.distance <= max(30, v.speed*3):
                    continue  # Commit to the receiving lane before checking its gap.
                target = desired_speed(v.profile, road, self.aggressive_profiles, time if self.daily else None)
                lane = lane_change_candidate(v, road, occupied, time, target, lane_index)
                if lane is not None:
                    old_lane = v.lane
                    lane_index.move(v, old_lane, lane)
                    occupied[key(v)].remove(v)
                    v.lane, v.last_lane_change = lane, time
                    occupied[key(v)].append(v)
                    self.lane_change_log.append((time, v.agent, v.op.link, old_lane, lane))
            self.peak_active = max(self.peak_active, len(active))

            # Save positions before advancing all lanes, so update order cannot
            # let a follower pass its leader within the same time step.
            frame = {}
            previous = {v.agent: (v.distance, v.speed) for q in occupied.values() for v in q}
            for lane_key, queue in occupied.items():
                queue.sort(key=lambda v: (-v.distance, v.op.start, v.agent))
                leader = None
                for v in queue:
                    link = self.links[v.op.link]
                    state = "parking" if v.op.kind == "parking" or time < v.hold_until - 1e-8 else (
                        "queued" if v.speed <= STOP_SPEED else "drive")
                    source = "synthetic" if v.op.kind != "parking" and state == "parking" else v.op.source
                    if state == "parking":
                        v.speed = 0
                        frame[v.agent] = sample(v, time, 0.0, state, source)
                        leader = frame[v.agent]
                        continue
                    remaining = v.op.last * link["length"] - v.distance
                    must_stop = link.get('stop_before_avenue', False) and v.op.last == 1
                    stop_line = max(0, link['length'] - link.get('stop_setback', 3.25))
                    signal = link.get('signal_plan')
                    signal_color = signal.states(time)[0 if link['signal_group']=='avenue' else 1] if signal else 'green'
                    signal_blocked = signal_color != 'green' and not v.signal_committed and v.op.last == 1
                    if signal_blocked and v.distance >= stop_line - 1e-8:
                        v.speed = 0
                        frame[v.agent] = sample(v, time, 0, 'signal', 'signal:'+signal_color)
                        leader = frame[v.agent]
                        continue
                    if must_stop and not v.yield_released and v.distance >= stop_line - 1e-8:
                        v.speed = 0.0
                        if v.yield_until is None:
                            v.yield_until = time + max(self.dt, link.get('stop_seconds', 1.0))
                            self.intersection_log.append((time, v.agent, v.op.link, 'stop'))
                        if time + 1e-8 >= v.yield_until and intersection_clear(v, active, self.links,time=time):
                            v.yield_released = True
                            self.intersection_log.append((time, v.agent, v.op.link, 'release'))
                        else:
                            frame[v.agent] = sample(v, time, 0, 'yielding', 'intersection')
                            leader = frame[v.agent]
                            continue
                    # A blocked endpoint or a bumper-to-bumper stopped follower
                    # has exactly zero feasible displacement this tick. Avoid
                    # evaluating speed/braking formulas for this common case.
                    if remaining <= 1e-8 or (leader is not None and leader.speed == 0
                                             and leader.distance - v.distance <= GAP + 1e-8):
                        v.speed = 0
                        frame[v.agent] = sample(v, time, 0.0, "queued", source)
                        leader = frame[v.agent]
                        continue
                    free_speed = desired_speed(v.profile, link, self.aggressive_profiles, time if self.daily else None)
                    target = free_speed
                    nxt = v.ops[v.index + 1] if v.index + 1 < len(v.ops) else None
                    boundary_speed = exit_speed(v.op, nxt, self.links, v.profile, self.aggressive_profiles, time if self.daily else None)
                    release = max(v.op.end, nxt.start if nxt else v.op.end,
                                  last_exit[lane_key] + 3600 * link["lanes"] / link["capacity"])
                    # A red release time is a real hold; an ordinary geometry
                    # node on a free road is not a mandatory stop.
                    if time + remaining / max(v.speed, target, .01) < release - 1e-8:
                        boundary_speed = 0.0
                    stop_distance = remaining
                    if signal_blocked:
                        stop_distance = min(stop_distance, max(0, stop_line-v.distance))
                        boundary_speed = 0.0
                    if must_stop and not v.yield_released:
                        stop_distance = min(stop_distance, max(0, stop_line-v.distance))
                        boundary_speed = 0.0
                    if v.stop_at is not None and not v.stop_done:
                        stop_distance = min(stop_distance, v.stop_at - v.distance)
                        boundary_speed = 0.0
                    target = min(target, math.sqrt(boundary_speed ** 2 + 2 * BRAKING * max(0, stop_distance)))
                    limit = remaining
                    leader_speed, front_distance = None, None
                    if leader:
                        clearance = max(0, leader.distance - v.distance - GAP)
                        leader_speed, front_distance = leader.speed, leader.distance - v.distance
                        target = min(target, math.sqrt(leader.speed ** 2 + 2 * BRAKING * clearance),
                                     free_speed)
                        limit = min(limit, clearance)
                    elif v.index + 1 < len(v.ops):
                        nxt = v.ops[v.index + 1]
                        next_link = self.links[nxt.link]
                        connected = (link.get("to_id") is not None and
                                     link.get("to_id") == next_link.get("from_id"))
                        if nxt.kind == "drive" and nxt.link != v.op.link and connected:
                            receiving_lane = (min(v.lane, next_link["lanes"] - 1)
                                              if "lane_width" in next_link else lane_for(v.seed_agent, next_link))
                            receiving = occupied.get((nxt.link, receiving_lane), ())
                            if receiving:
                                front = min((previous[w.agent] for w in receiving), key=lambda p: p[0])
                                clearance = max(0, remaining + front[0] -
                                                nxt.first * next_link["length"] - GAP)
                                leader_speed, front_distance = front[1], clearance + GAP
                                target = min(target, math.sqrt(front[1] ** 2 + 2 * BRAKING * clearance),
                                             free_speed)
                                limit = min(limit, clearance)
                    acceleration = following_acceleration(v.speed, target, leader_speed, front_distance, v.profile)
                    next_speed = max(0, min(v.speed + acceleration * self.dt, free_speed))
                    step = min(limit, stop_distance, next_speed * self.dt)
                    # Publish only after queue/parking/receiving-space constraints
                    # are applied. In a queue, the kinetic speed carried from the
                    # preceding link must not keep a motionless marker cyan/purple.
                    reported_speed = min(v.speed, free_speed)
                    if leader_speed is not None or remaining <= 1e-8:
                        reported_speed = min(reported_speed, max(0, step) / self.dt)
                    state = "following" if leader_speed is not None and 0 < reported_speed <= 30 / 3.6 else "drive"
                    frame[v.agent] = sample(v, time, reported_speed, state, source)
                    # Safety clamp has priority over comfortable deceleration.
                    v.distance += max(0, step)
                    if signal and signal_color == 'green' and v.distance > stop_line + 1e-8:
                        v.signal_committed = True
                    v.travelled_distance += max(0, step)
                    v.speed = max(0, step) / self.dt
                    if (boundary_speed > 0 and remaining > 1e-8 and
                            step >= remaining - 1e-8 and limit >= remaining):
                        # Keep kinetic speed when a discrete step is clipped at
                        # a link boundary. Fractional leftover distance is not
                        # a physical braking event; blocked transfers reset to 0.
                        v.speed = min(next_speed, boundary_speed)
                    if v.stop_at is not None and not v.stop_done and v.distance >= v.stop_at - 1e-8:
                        v.stop_done = True
                        v.speed = 0
                        v.hold_until = round(time + self.dt + PARKING_SECONDS, 9)
                        self.parking_log.append((v.agent, round(time + self.dt, 9), v.hold_until,
                                                 "synthetic", v.op.link, v.distance))
                    leader = frame[v.agent]
            self.quiet = not active and not waiting and time - max(last_exit.values(), default=-math.inf) >= quiet_gap
            if (tick % max(1,round(60/self.dt)) == 0
                    and all(s.speed == 0 and s.distance == active[a].distance for a,s in frame.items())
                    and absorbing_gridlock(
                    active,occupied,self.links,last_exit,time,self.max_active,self.daily,self.aggressive_profiles)):
                self.gridlock_time, frozen_frame = time, frame
            yield time, frame
            tick += 1
