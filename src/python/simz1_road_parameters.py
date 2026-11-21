"""Explicit, auditable SimZ1 lane and hourly-capacity assumptions."""
import math
import re

IDEAL_CAPACITY = 2000.0  # veh/h/lane: requested scenario baseline, not a field measurement


def lane_count(tags, direction, directions):
    def integer(key, zero=False):
        if key not in tags:
            return None
        value = tags[key]
        if not re.fullmatch(r'\d+', value) or int(value) < (0 if zero else 1):
            raise ValueError(f'Invalid physical lane count {key}={value!r}; review OSM')
        return int(value)

    total = integer('lanes')
    shared = integer('lanes:both_ways', zero=True) or 0
    forward = integer('lanes:forward')
    backward = integer('lanes:backward')
    key = 'forward' if direction == 1 else 'backward'
    explicit = forward if direction == 1 else backward
    opposite = backward if direction == 1 else forward
    if len(directions) == 1:
        if shared or opposite is not None:
            raise ValueError('One-way road has conflicting opposite/shared lane tags')
        if total is not None and explicit is not None and total != explicit:
            raise ValueError('Directional lanes disagree with one-way total')
        return (explicit, 'osm:lanes:'+key) if explicit is not None else (
            (total, 'osm:lanes') if total is not None else (1, 'assumed:one_lane'))
    available = total - shared if total is not None else None
    if available is not None and available < 2:
        raise ValueError('Shared single-lane road needs an explicit alternating-flow model')
    if forward is not None and backward is not None:
        if available is not None and forward + backward != available:
            raise ValueError('Directional lane counts disagree with total minus shared lanes')
        return explicit, 'osm:lanes:'+key
    if explicit is not None:
        if available is not None and explicit >= available:
            raise ValueError('No lane left for the opposite direction')
        return explicit, 'osm:lanes:'+key
    if opposite is not None and available is not None:
        if opposite >= available:
            raise ValueError('No lane left after subtracting opposite lanes')
        return available - opposite, 'derived:total_minus_opposite_and_shared'
    if available is not None:
        if available % 2:
            raise ValueError('Odd bidirectional lane total requires directional lane tags')
        return available // 2, 'assumed:equal_direction_split'
    return 1, 'assumed:one_lane'


def road_parameters(tags, direction, directions, default_kmh, capacity_factor=1.0):
    if not math.isfinite(capacity_factor) or not 0 < capacity_factor <= 1:
        raise ValueError('capacity_factor must be finite and in (0, 1]')
    lanes, lane_source = lane_count(tags, direction, directions)
    key = 'maxspeed:' + ('forward' if direction == 1 else 'backward')
    if key not in tags:
        key = 'maxspeed'
    raw = tags.get(key, '')
    match = re.fullmatch(r'\s*(\d+(?:\.\d+)?)\s*(mph|km/h|kph)?\s*', raw)
    if match and float(match[1]) > 0:
        kmh = float(match[1]) * (1.609344 if match[2] == 'mph' else 1)
        speed_source = 'osm:' + key
    else:
        kmh = default_kmh
        speed_source = 'assumed:highway_default'
    if not math.isfinite(kmh) or kmh <= 0:
        raise ValueError('Speed must be positive and finite')
    metadata = {'physical:lanesSource': lane_source,
                'physical:speedSource': speed_source,
                'physical:modeledMaxSpeedKmh': kmh,
                'physical:idealCapacityPerLane': IDEAL_CAPACITY,
                'physical:capacityFactor': capacity_factor,
                'physical:capacityModel': 'ideal_per_lane_times_lanes_times_factor'}
    if raw and speed_source.startswith('assumed:'):
        metadata['physical:speedReview'] = 'unsupported OSM maxspeed: ' + raw
    if any(k.startswith('maxspeed') and ':conditional' in k for k in tags):
        metadata['physical:speedReview'] = 'conditional maxspeed not modeled; review required'
    return dict(permlanes=lanes, freespeed=kmh/3.6,
                capacity=IDEAL_CAPACITY*lanes*capacity_factor, physical=metadata)
