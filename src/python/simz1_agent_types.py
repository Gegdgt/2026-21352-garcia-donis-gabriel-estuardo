"""Opt-in six-category proposal, independent of SimZ1 historical profiles.

The allocation unit is a person, not a trip or a vehicle. Transit passengers
never acquire a road vehicle through this module. Sampling creates planned
departure times only; it does not implement QSim link-entry restrictions.
"""
from bisect import bisect_right
import copy
import hashlib
from itertools import accumulate
import json
import math
from pathlib import Path
import random
import xml.etree.ElementTree as ET
import simz1_road_catalog as road

SCHEMA_VERSION = 'simz1-six-v1'
CANONICAL_TYPES = ('Normal', 'Motociclista', 'Liebre', 'Tortuga',
                   'TransportePublico', 'TransportePesado')
DEFAULT_CATALOG = Path(__file__).resolve().parents[1] / 'scenarios/zona1/agent-types-v2.json'
ROAD_DEFAULT_CATALOG = DEFAULT_CATALOG.with_name('agent-types-road-v1.json')
ROAD_PARAMETERS = {'Normal': (1.0, 50.0), 'Motociclista': (.25, 60.0),
                   'Liebre': (1.0, 90.0), 'Tortuga': (1.0, 25.0)}


def _integer(value, name, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError(f'{name} must be an integer >= {minimum}')
    return value


def _positive(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ValueError(f'{name} must be finite and positive')


def validate_catalog(catalog):
    """Reject ambiguous units, incomplete types and unsafe numeric values.

    Missing heavy/transit execution inputs are permitted in the *proposal*;
    require_executable() is the separate fail-closed execution gate.
    """
    if isinstance(catalog, dict) and catalog.get('schema_version') == road.SCHEMA:
        return road.validate(catalog)
    if not isinstance(catalog, dict) or catalog.get('schema_version') != SCHEMA_VERSION:
        raise ValueError(f'Expected catalog schema_version={SCHEMA_VERSION}')
    if catalog.get('denominator') != 'persons':
        raise ValueError('Catalog denominator must be persons')
    if catalog.get('canonical_order') != list(CANONICAL_TYPES):
        raise ValueError('Canonical types/order must preserve the six established identifiers')
    if catalog.get('horizon_seconds') != 86400 or type(catalog['horizon_seconds']) is not int:
        raise ValueError('The proposed demand horizon must be 86400 seconds')
    allocation = catalog.get('allocation', {})
    if allocation.get('rounding') != 'largest_remainder' or allocation.get('tie_break') != 'canonical_order':
        raise ValueError('Allocation must use largest_remainder and canonical_order tie breaking')
    profiles = catalog.get('profiles')
    if not isinstance(profiles, dict) or set(profiles) != set(CANONICAL_TYPES):
        raise ValueError('Catalog must contain exactly the six canonical types')
    total = 0
    for name in CANONICAL_TYPES:
        spec = profiles[name]
        if not isinstance(spec, dict):
            raise ValueError(f'{name}: expected profile object')
        total += _integer(spec.get('share_percent'), f'{name}.share_percent')
        passenger = name == 'TransportePublico'
        expected = ('passenger', 'pt', None) if passenger else ('driver', 'car', name)
        if (spec.get('population_role'), spec.get('mode'), spec.get('vehicle_type')) != expected:
            raise ValueError(f'{name}: person role, mode and vehicle type are inconsistent')
        if passenger:
            if spec.get('pcu') is not None or spec.get('maximum_speed_kmh') is not None:
                raise ValueError('Public transport passengers must not receive vehicle PCU/speed')
        else:
            _positive(spec.get('pcu'), f'{name}.pcu')
            speed = spec.get('maximum_speed_kmh')
            if speed is not None or name != 'TransportePesado':
                _positive(speed, f'{name}.maximum_speed_kmh')
            if name in ROAD_PARAMETERS and (spec['pcu'], speed) != ROAD_PARAMETERS[name]:
                raise ValueError(f'{name}: PCU/speed must match the versioned QSim profile {ROAD_PARAMETERS[name]}')
            if name == 'TransportePesado' and not 3 <= spec['pcu'] <= 4:
                raise ValueError('TransportePesado PCU must be in the proposed range 3..4')
        expected_routing = ('fixed-route-transit-service-required' if passenger else
                            'authorized-routes-required' if name == 'TransportePesado' else
                            'fastest-time' if name == 'Liebre' else 'configured-route-policy')
        if spec.get('routing_preference') != expected_routing:
            raise ValueError(f'{name}: unsupported routing preference')
        intervals = spec.get('departure_intervals')
        if not isinstance(intervals, list) or not intervals:
            raise ValueError(f'{name}: departure_intervals must not be empty')
        previous_end = 0
        for interval in intervals:
            if not isinstance(interval, dict) or set(interval) != {'start_seconds', 'end_seconds', 'weight'}:
                raise ValueError(f'{name}: invalid departure interval fields')
            start = _integer(interval['start_seconds'], f'{name}.start_seconds')
            end = _integer(interval['end_seconds'], f'{name}.end_seconds', 1)
            if start < previous_end or end <= start or end > catalog['horizon_seconds']:
                raise ValueError(f'{name}: departure intervals must be ordered, disjoint and inside the horizon')
            _positive(interval['weight'], f'{name}.weight')
            if not math.isfinite((end-start)*interval['weight']):
                raise ValueError(f'{name}: weighted interval duration must be finite')
            previous_end = end
        try:
            weighted_duration = math.fsum((i['end_seconds']-i['start_seconds'])*i['weight'] for i in intervals)
        except OverflowError:
            raise ValueError(f'{name}: total weighted duration must be finite') from None
        if not math.isfinite(weighted_duration):
            raise ValueError(f'{name}: total weighted duration must be finite')
        if name in ('Normal', 'Motociclista', 'Liebre', 'Tortuga'):
            if intervals[0]['start_seconds'] != 0 or intervals[-1]['end_seconds'] != catalog['horizon_seconds'] or any(a['end_seconds'] != b['start_seconds'] for a, b in zip(intervals, intervals[1:])):
                raise ValueError(f'{name}: activity must cover the full day; weights express emphasis')
        access = spec.get('access')
        if not isinstance(access, dict) or access.get('requires_authorized_links') is not (name == 'TransportePesado'):
            raise ValueError(f'{name}: invalid access policy')
        links = access.get('authorized_link_ids')
        if not isinstance(links, list) or any(not isinstance(link, str) or not link.strip() for link in links) or len(links) != len(set(links)):
            raise ValueError(f'{name}: authorized_link_ids must be unique nonempty strings')
        if name != 'TransportePesado' and links:
            raise ValueError(f'{name}: an access allowlist is unsupported for this profile')
        if access.get('municipal_status') not in ('not_claimed', 'unverified_assumption', 'verified_source'):
            raise ValueError(f'{name}: unknown municipal verification status')
        if access['municipal_status'] == 'verified_source' and not access.get('source'):
            raise ValueError(f'{name}: verified municipal restrictions require a source')
    if total != 100:
        raise ValueError(f'Person shares must sum to 100 percent, got {total}')
    service = catalog.get('transit_service')
    if not isinstance(service, dict) or service.get('vehicle_type') != 'TransitBus':
        raise ValueError('TransitBus must be separate from passenger profiles')
    _positive(service.get('pcu'), 'transit_service.pcu')
    if not 2.5 <= service['pcu'] <= 3.0:
        raise ValueError('TransitBus PCU must be in the proposed range 2.5..3.0')
    if service.get('maximum_speed_kmh') is not None:
        _positive(service['maximum_speed_kmh'], 'transit_service.maximum_speed_kmh')
    start = _integer(service.get('operation_start_seconds'), 'transit_service.operation_start_seconds')
    end = _integer(service.get('operation_end_seconds'), 'transit_service.operation_end_seconds', 1)
    if end <= start or end > catalog['horizon_seconds']:
        raise ValueError('Transit service operation must be inside the demand horizon')
    for interval in profiles['TransportePublico']['departure_intervals']:
        if interval['start_seconds'] < start or interval['end_seconds'] > end:
            raise ValueError('Transit passenger departures must be inside proposed service hours')
    return catalog


def load_catalog(path=None):
    return validate_catalog(json.loads(Path(path or DEFAULT_CATALOG).read_text(encoding='utf-8')))


def profile_spec(agent_type, catalog):
    try:
        return catalog['profiles'][agent_type]
    except (KeyError, TypeError):
        raise ValueError(f'Unknown canonical agent type: {agent_type}') from None


def allocation_counts(count, catalog):
    """Largest remainders computed with exact integer arithmetic."""
    _integer(count, 'count')
    validate_catalog(catalog)
    if catalog['schema_version'] == road.SCHEMA:
        return road.counts(count, catalog)
    quotients = [divmod(count * catalog['profiles'][name]['share_percent'], 100)
                 for name in CANONICAL_TYPES]
    counts = [q for q, _ in quotients]
    ranking = sorted(range(len(CANONICAL_TYPES)), key=lambda i: (-quotients[i][1], i))
    for i in ranking[:count-sum(counts)]:
        counts[i] += 1
    return dict(zip(CANONICAL_TYPES, counts))


def allocate_types(count, seed, catalog):
    """Return exactly count person categories, reproducibly shuffled by seed."""
    if type(seed) is not int:
        raise ValueError('seed must be an integer')
    counts = allocation_counts(count, catalog)
    allocated = [name for name in catalog['canonical_order'] for _ in range(counts[name])]
    stream = road.SCHEMA if catalog['schema_version'] == road.SCHEMA else 'SimZ1-six-allocation-v1'
    random.Random(f'{stream}:{seed}').shuffle(allocated)
    return allocated


def sample_departures(agent_type, count, seed, person_id, catalog):
    """Sorted planned times in [0, horizon), using a per-person RNG stream.

    Weight is density per second, so a longer interval has proportionally more
    probability. No departure is placed exactly at an exclusive ending time.
    """
    _integer(count, 'count')
    if type(seed) is not int or not isinstance(person_id, str) or not person_id:
        raise ValueError('An integer seed and nonempty string person_id are required')
    validate_catalog(catalog)
    intervals = profile_spec(agent_type, catalog)['departure_intervals']
    # Optional versioned temporal weights preserve morning/evening demand peaks.
    # Omission preserves existing catalog RNG/output exactly.
    temporal = catalog.get('temporal_demand')
    if temporal is not None:
        intervals = [dict(start_seconds=max(slot['start_seconds'], h*3600),
                          end_seconds=min(slot['end_seconds'], (h+1)*3600),
                          weight=slot['weight']*weight)
                     for slot in intervals for h, weight in enumerate(temporal['hourly_weights'])
                     if weight > 0 and max(slot['start_seconds'], h*3600) < min(slot['end_seconds'], (h+1)*3600)]
        if not intervals:
            raise ValueError(f'{agent_type}: no positive departure window after hourly intersection')
    cumulative = list(accumulate((i['end_seconds']-i['start_seconds'])*i['weight'] for i in intervals))
    # JSON encoding prevents delimiters in a person ID from colliding with the seed/type.
    stream = road.SCHEMA + ':departures' if catalog['schema_version'] == road.SCHEMA else 'SimZ1-six-departures-v1'
    rng = random.Random(json.dumps([stream, seed, agent_type, person_id]))
    values = set()
    while len(values) < count:
        interval = intervals[min(len(intervals)-1, bisect_right(cumulative, rng.random()*cumulative[-1]))]
        start, end = interval['start_seconds'], interval['end_seconds']
        value = min(math.nextafter(float(end), float(start)), start+rng.random()*(end-start))
        values.add(value)
    return sorted(values)


def allows_link(agent_type, link_id, allowed_modes, catalog):
    """Static access prerequisite only, not route or lane validation.

    Existing direction, turn, signal and lane constraints must still be applied
    by the network/router. A heavy allowlist never grants access to a link that
    does not allow the road mode. An empty heavy allowlist fails closed.
    """
    spec = profile_spec(agent_type, catalog)
    if spec['population_role'] != 'driver' or spec['mode'] not in allowed_modes:
        return False
    return not spec['access']['requires_authorized_links'] or link_id in spec['access']['authorized_link_ids']


def execution_blockers(agent_types, catalog):
    """Report prepared categories that must not silently become car OD trips.

    Transit and heavy execution remain gated even if data paths are filled in:
    an adapter must first validate fixed schedules and enforce route/time access.
    """
    validate_catalog(catalog)
    if catalog['schema_version'] == road.SCHEMA:
        return road.blockers(agent_types, catalog)
    names = set(agent_types)
    unknown = names-set(CANONICAL_TYPES)
    if unknown:
        raise ValueError(f'Unknown canonical agent types: {sorted(unknown)}')
    blockers = []
    if 'TransportePublico' in names:
        service = catalog['transit_service']
        missing = [key for key in ('schedule_file', 'vehicles_file', 'route_source', 'stop_source', 'maximum_speed_kmh') if not service.get(key)]
        if missing:
            blockers.append('TransportePublico: missing verified service inputs: '+', '.join(missing))
        blockers.append('TransportePublico: validated TransitSchedule/passenger assignment and finite vehicle duties adapter is not implemented')
    if 'TransportePesado' in names:
        spec = profile_spec('TransportePesado', catalog)
        if spec['maximum_speed_kmh'] is None:
            blockers.append('TransportePesado: maximum_speed_kmh requires an explicit value')
        if not spec['access']['authorized_link_ids']:
            blockers.append('TransportePesado: authorized_link_ids requires a supported route allowlist')
        blockers.append('TransportePesado: route access and actual traversal time-window enforcement/validation is not implemented; departure windows alone are insufficient')
    return blockers


def require_executable(agent_types, catalog):
    blockers = execution_blockers(agent_types, catalog)
    if blockers:
        label = 'Road-profile proposal' if catalog['schema_version'] == road.SCHEMA else 'Six-category proposal'
        raise ValueError(label + ' is not executable: '+'; '.join(blockers))


def road_vehicle_types(catalog):
    """MATSim-ready road vehicle parameters for categories ready to generate.

    No dimensions or acceleration model are inferred from PCU. Missing vehicle
    speeds and transit service data are never substituted with invented defaults.
    """
    validate_catalog(catalog)
    if catalog['schema_version'] == road.SCHEMA:
        return {name: dict(pcu=spec['pcu'], maximum_speed_kmh=spec['maximum_speed_kmh'],
                           maximum_speed_m_s=spec['maximum_speed_kmh']/3.6,
                           dimensions=copy.deepcopy(spec['dimensions']))
                for name, spec in catalog['profiles'].items()}
    return {name: dict(pcu=spec['pcu'], maximum_speed_kmh=spec['maximum_speed_kmh'],
                       maximum_speed_m_s=spec['maximum_speed_kmh']/3.6)
            for name, spec in catalog['profiles'].items()
            if spec['population_role'] == 'driver' and spec['maximum_speed_kmh'] is not None
            and name != 'TransportePesado'}


def catalog_manifest(catalog):
    """Self-contained snapshot and canonical JSON hash for provenance."""
    validate_catalog(catalog)
    payload = json.dumps(catalog, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    return dict(schema_version=catalog['schema_version'], denominator='persons',
                sha256=hashlib.sha256(payload.encode('utf-8')).hexdigest(),
                catalog=copy.deepcopy(catalog),
                execution_blockers=execution_blockers(active_types(catalog), catalog),
                unavailable_capabilities=execution_blockers(catalog['canonical_order'], catalog),
                **(dict(scenario_version=catalog['scenario_version'], normalized_weights=road.normalized_weights(catalog))
                   if catalog['schema_version'] == road.SCHEMA else {}))


def type_probabilities(catalog):
    return ({k: float(v) for k, v in road.probabilities(catalog).items()}
            if catalog['schema_version'] == road.SCHEMA else
            {k: v['share_percent']/100 for k, v in catalog['profiles'].items()})


def active_types(catalog):
    if catalog['schema_version'] == road.SCHEMA:
        return [k for k, v in road.probabilities(catalog).items() if v > 0]
    return [k for k, v in type_probabilities(catalog).items() if v > 0]


def vehicle_types_xml(catalog):
    """MATSim vehicleDefinitions v2 XML; a type definition alone grants no activation.

    Historical six-v1 dimensions remain unchanged. Road-v1 uses its explicit
    assumed dimensions, independent of PCU and any visualization margins.
    PCU is serialized as the v2 schema's ``pce`` attribute.
    """
    namespace = 'http://www.matsim.org/files/dtd'
    xsi = 'http://www.w3.org/2001/XMLSchema-instance'
    ET.register_namespace('', namespace)
    ET.register_namespace('xsi', xsi)
    root = ET.Element(f'{{{namespace}}}vehicleDefinitions', {
        f'{{{xsi}}}schemaLocation': namespace+' '+namespace+'/vehicleDefinitions_v2.0.xsd'})
    for name, values in road_vehicle_types(catalog).items():
        vehicle = ET.SubElement(root, f'{{{namespace}}}vehicleType', id=name)
        attributes = ET.SubElement(vehicle, f'{{{namespace}}}attributes')
        spec = catalog['profiles'][name]
        metadata = {'simz1AgentSchema': catalog['schema_version'],
                    'simz1DimensionsSource': 'Common QSim defaults; not measured physical geometry; no filtering'}
        dimensions = dict(length_m=4.5, width_m=1.8)
        if catalog['schema_version'] == road.SCHEMA:
            dimensions = spec['dimensions']
            metadata.update(simz1DimensionsSource=dimensions['source'], simz1DimensionsAssumed='true',
                            simz1VehicleFamily=spec['family'], drivingProfile=spec['driving_profile'],
                            simz1RoutingPolicy=spec['routing_preference'], simz1Label=spec['label'],
                            simz1ScenarioVersion=catalog['scenario_version'],
                            accelerationModel='not_integrated_by_QSim')
        for key, value in metadata.items():
            ET.SubElement(attributes, f'{{{namespace}}}attribute', name=key,
                          **{'class': 'java.lang.String'}).text = value
        ET.SubElement(vehicle, f'{{{namespace}}}capacity', seats='0', standingRoomInPersons='0')
        ET.SubElement(vehicle, f'{{{namespace}}}length', meter=str(dimensions['length_m']))
        ET.SubElement(vehicle, f'{{{namespace}}}width', meter=str(dimensions['width_m']))
        ET.SubElement(vehicle, f'{{{namespace}}}maximumVelocity', meterPerSecond=str(values['maximum_speed_m_s']))
        ET.SubElement(vehicle, f'{{{namespace}}}costInformation')
        ET.SubElement(vehicle, f'{{{namespace}}}passengerCarEquivalents', pce=str(values['pcu']))
        ET.SubElement(vehicle, f'{{{namespace}}}networkMode', networkMode='car')
        ET.SubElement(vehicle, f'{{{namespace}}}flowEfficiencyFactor', factor='1.0')
    return root
