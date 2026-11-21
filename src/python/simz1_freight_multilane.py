"""Source-backed directional lane eligibility for compact freight.

OSM tags are evidence in the saved source, not a field survey. Missing tags
never turn the importer's one-lane default into a measured physical lane count.
No inferred lane, direction, width or traffic permission is written to the map.
"""
import re

POLICY = 'verified-multilane-through-v3'
TAGGING_SOURCES = [
    'https://wiki.openstreetmap.org/wiki/Key:lanes',
    'https://wiki.openstreetmap.org/wiki/Key:lanes:bus',
    'https://wiki.openstreetmap.org/wiki/Key:*:lanes',
]


def directional_lane_evidence(ctx, ident):
    """Fail closed unless OSM explicitly establishes >1 usable lane this way.

    A bidirectional total is never divided by two. Direction-specific counts
    or a count on an explicit one-way carriageway are required. Lane-reserved
    counts subtract from that total; conditional/ambiguous variants are rejected.
    The native effective count must accommodate the source-backed count.
    """
    link = ctx['links'][ident]
    way = ctx['ways'].get(link.get('way'), {})
    tags = way.get('tags', {})
    direction = link.get('direction')
    result = dict(link_id=ident, osm_way_id=link.get('way'), direction=direction,
                  native_permlanes=link['lanes'], osm_tags=dict(tags),
                  source_url='https://www.openstreetmap.org/way/'+str(link.get('way')),
                  directional_lanes=None, reserved_lanes=None, usable_directional_lanes=None,
                  status='unverified', field_survey_verified=False)

    def reject(reason, status='unverified'):
        result.update(status=status, reason=reason)
        return result

    def count(key):
        raw = tags.get(key)
        return int(raw) if raw is not None and re.fullmatch(r'[0-9]+', raw) else None

    oneway = tags.get('oneway', 'yes' if tags.get('junction') == 'roundabout' else 'no').lower()
    one_direction = ('forward' if oneway in ('yes', '1', 'true') else
                     'backward' if oneway == '-1' else None)
    if direction not in ('forward', 'backward') or oneway not in ('yes', '1', 'true', '-1', 'no', '0', 'false', ''):
        return reject('unverified directional OSM mapping')
    if one_direction is not None and direction != one_direction:
        return reject('wrong OSM direction', 'prohibited')
    for key in tags:
        if 'lanes' in key and 'conditional' in key:
            return reject('unreviewed conditional lane allocation '+key)
        if key.startswith('busway') and tags[key] not in ('no', 'separate'):
            return reject('unreviewed busway allocation '+key)
    directional_key = 'lanes:'+direction
    if directional_key in tags:
        lanes, basis = count(directional_key), directional_key
    elif one_direction is not None and 'lanes' in tags:
        lanes, basis = count('lanes'), 'lanes + explicit oneway'
    else:
        return reject('missing explicit directional lane count; native permlanes is not physical evidence')
    if lanes is None or lanes <= 0:
        return reject('unsupported directional lane count '+str(tags.get(directional_key, tags.get('lanes'))))
    if 'lanes' in tags:
        total = count('lanes')
        if total is None or total < lanes:
            return reject('inconsistent total and directional lane counts')
        if one_direction is not None and total != lanes:
            return reject('inconsistent one-way total and directional lane counts')
        if one_direction is None and all(k in tags for k in ('lanes:forward', 'lanes:backward')):
            parts = [count(k) for k in ('lanes:forward', 'lanes:backward')]
            center = count('lanes:both_ways') if 'lanes:both_ways' in tags else 0
            if any(v is None for v in parts) or center is None or sum(parts)+center != total:
                return reject('inconsistent bidirectional lane allocation')
    result.update(directional_lanes=lanes, lane_count_basis=basis)
    # Lane access vectors need an explicit reviewed alignment with motorised
    # counts (OSM vectors may include bicycle lanes). Never ignore these tags.
    vectors = [k for k in tags if ':lanes' in k and k.split(':')[0] in
               ('access', 'vehicle', 'motor_vehicle', 'motorcar', 'hgv', 'goods', 'psv', 'bus', 'taxi', 'bicycle')]
    if vectors:
        return reject('unreviewed per-lane access allocation '+','.join(sorted(vectors)))
    reserved = 0
    # Several reserved modes can overlap; without explicit alignment do not
    # double count or assume the less restrictive interpretation.
    modes = []
    for mode in ('bus', 'psv', 'taxi', 'hov', 'bicycle'):
        key = 'lanes:'+mode+':'+direction
        generic = 'lanes:'+mode
        opposite = 'lanes:'+mode+':'+('backward' if direction == 'forward' else 'forward')
        relevant = [k for k in tags if k.startswith(generic) and k != opposite]
        if not relevant:
            continue
        if key not in tags:
            if generic in tags and one_direction is not None:
                key = generic
            elif generic in tags:
                return reject('unverified directional reserved-lane allocation '+generic)
            else:
                return reject('unsupported reserved-lane allocation '+','.join(relevant))
        value = count(key)
        if value is None or value > lanes:
            return reject('invalid reserved-lane count '+key)
        modes.append(mode)
        reserved += value
    if len(modes) > 1:
        return reject('unreviewed overlap between reserved-lane modes '+','.join(modes))
    usable = lanes-reserved
    result.update(reserved_lanes=reserved, usable_directional_lanes=usable)
    if usable <= 1:
        return reject('at most one explicitly usable directional lane', 'prohibited')
    if reserved:
        return reject('reserved lanes require a verified native slot-permission mapping')
    if link['lanes'] < usable:
        return reject('effective MATSim lanes below verified usable directional lanes', 'incompatible')
    if link['lanes'] > usable:
        return reject('extra effective MATSim lanes lack a verified freight slot-permission mapping', 'incompatible')
    if link['lanes'] != int(link['lanes']):
        return reject('fractional effective MATSim lanes', 'incompatible')
    result.update(status='verified_multilane', reason=None,
                  verification_basis='explicit_saved_OSM_directional_motorised_lanes_and_native_graph')
    return result
