"""Four synthetic OD classes. No municipal proportions or exterior travel times."""
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
import random
import xml.etree.ElementTree as ET

CLASSES = ('INTERNAL_INTERNAL', 'INTERNAL_EXTERNAL', 'EXTERNAL_INTERNAL', 'EXTERNAL_EXTERNAL_THROUGH')
LEGACY = ('internal-internal', 'internal-external', 'external-internal', 'external-external')
CLASS_BY_TYPE = dict(zip(LEGACY, CLASSES))
TYPE_BY_CLASS = dict(zip(CLASSES, LEGACY))
CONTRACT = 'simz1-four-od-v2'


def percentage_document(raw):
    """Canonical decimal strings preserve an exactly-100 input and its hash."""
    from decimal import Decimal, InvalidOperation
    from fractions import Fraction
    document = json.loads(raw, parse_float=str) if isinstance(raw, str) else raw
    if not isinstance(document, dict) or set(document) != set(CLASSES):
        raise ValueError('OD percentages require the four explicit class names')
    if any(type(v) not in (int, float, str) or isinstance(v, bool) for v in document.values()):
        raise ValueError('OD percentages must be finite decimal numbers')
    try:
        values = {k: Fraction(Decimal(str(v))) for k, v in document.items()}
    except (ValueError, OverflowError, InvalidOperation) as exc:
        raise ValueError('OD percentages must be finite decimal numbers') from exc
    if any(v < 0 for v in values.values()) or sum(values.values()) != 100:
        raise ValueError('OD percentages must sum exactly to 100; no automatic redistribution')
    return {k: str(Decimal(str(document[k]))) for k in CLASSES}


def named_percentages(raw):
    """Explicit experimental percentages, never silently normalize a bad total."""
    from fractions import Fraction
    return {TYPE_BY_CLASS[k]: float(Fraction(v)/100) for k,v in percentage_document(raw).items()}


def named_mix(raw):
    """Named classes avoid silently changing the historical EE,EI,IE,II CLI order."""
    from simz1_gateway_od import normalize_shares
    document = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(document, dict) or set(document) != set(CLASSES):
        raise ValueError('--od-mix requiere las cuatro clases OD explicitas')
    return normalize_shares({TYPE_BY_CLASS[k]: v for k, v in document.items()})


def allocate(count, shares, seed):
    if type(count) is not int or count < 0:
        raise ValueError('Cantidad OD invalida')
    from simz1_gateway_od import normalize_shares
    normalized = normalize_shares(shares)
    quotas = {kind: count * normalized[kind] for kind in LEGACY}
    counts = {kind: math.floor(quotas[kind]) for kind in LEGACY}
    remainder = count - sum(counts.values())
    order = sorted(LEGACY, key=lambda k: (-(quotas[k] - counts[k]), LEGACY.index(k)))
    for kind in order[:remainder]:
        counts[kind] += 1
    result = [kind for kind in LEGACY for _ in range(counts[kind])]
    random.Random(f'{CONTRACT}:allocation:{seed}').shuffle(result)
    assert len(result) == count
    return result, counts


def hourly_profiles(path, temporal):
    """All input profiles are explicit synthetic assumptions, unless separately calibrated."""
    from simz1_temporal import temporal_spec
    if path is None:
        return {kind: list(temporal['hourly_probabilities']) for kind in LEGACY}, None
    raw = Path(path).read_bytes()
    document = json.loads(raw)
    if (not isinstance(document, dict) or set(document) != {'source', 'profiles'} or
            document['source'] != 'synthetic' or not isinstance(document['profiles'], dict) or
            set(document['profiles']) != set(CLASSES)):
        raise ValueError('--od-hourly-profiles requiere source=synthetic y profiles con las cuatro clases')
    profiles = {TYPE_BY_CLASS[k]: temporal_spec(weights=v)['hourly_probabilities']
                for k, v in document['profiles'].items()}
    return profiles, dict(source='explicit-synthetic-per-od-class',
                         sha256=hashlib.sha256(raw).hexdigest(), document=document)


class ClassDepartureSampler:
    def __init__(self, seed, profiles, catalog=None):
        self.rng = random.Random(f'{CONTRACT}:departures:{seed}')
        self.slots = {}
        types = catalog['profiles'] if catalog is not None else {None: None}
        from simz1_agent_types import active_types
        active = set(active_types(catalog)) if catalog is not None else {None}
        for od_type, probabilities in profiles.items():
            for kind, spec in types.items():
                if kind not in active:
                    continue
                intervals = spec['departure_intervals'] if spec else [dict(start_seconds=0, end_seconds=86400, weight=1)]
                slots, total = [], 0.
                for h, probability in enumerate(probabilities):
                    for interval in intervals:
                        low, high = max(h*3600, interval['start_seconds']), min((h+1)*3600, interval['end_seconds'])
                        if high > low and probability > 0 and interval['weight'] > 0:
                            # Product of explicit OD intensity and agent schedule
                            # density, then renormalized over their intersection.
                            total += probability * (high-low)/3600 * interval['weight']
                            slots.append((low, high, total))
                self.slots[od_type, kind] = slots

    def sample(self, od_type, kind=None):
        slots = self.slots[od_type, kind]
        if not slots:
            raise ValueError(f'Horarios OD/categoria sin interseccion: {od_type}/{kind}')
        draw = self.rng.random() * slots[-1][2]
        low, high, _ = next(slot for slot in slots if draw < slot[2])
        return min(math.nextafter(float(high), low), low + (high-low)*self.rng.random())


class GatewayBudget:
    """Conservative PCU/hour *scheduled* gateway load; QSim still models queues.

    Exits have no known arrival hour before simulation. Their departure-cohort
    budgets are not a prediction or guarantee of actual hourly outflow.
    Shared crossing links share a budget; using the smallest crossing capacity
    is conservative when more than one crossing provides the same gateway.
    """
    def __init__(self, model, factor=1.):
        if not math.isfinite(factor) or not 0 < factor <= 1:
            raise ValueError('gateway-od requiere flowCapacityFactor en (0,1]')
        self.model, self.factor = model, factor
        self.used = defaultdict(float)

    def resources(self, record):
        result = set()
        for side, table in (('origin', self.model.entry_gateways), ('destination', self.model.exit_gateways)):
            link = record[side + '_gateway']
            if link is not None:
                result.add(link)
                result.update(table[link]['evidence_crossing_links'])
                # Balanced boundary chains can share intermediate exterior links.
                # Those links must not receive independent budgets per gateway.
                result.update(table[link].get('link_ids', []))
        return sorted(result)

    def limit(self, link):
        return self.model.links[link].get('capacity', math.inf) * self.factor

    def accept(self, record, hour, pcu=1.):
        if not math.isfinite(pcu) or pcu <= 0:
            raise ValueError('PCU de categoria invalido')
        links = self.resources(record)
        if any(self.used[hour, link] + pcu > self.limit(link) + 1e-9 for link in links):
            return False
        for link in links:
            self.used[hour, link] += pcu
        return True

    def summary(self):
        return dict(unit='PCU', flow_capacity_factor=self.factor,
                    policy='bounded_scheduled_departure_cohorts; actual_exit_hour_unknown; QSim_queues_preserved',
                    usage=[dict(hour=h, link_id=link, scheduled_pcu=value, capacity_pcu=self.limit(link))
                           for (h, link), value in sorted(self.used.items()) if value])


def validate_osm_turns(osm_path, network_path, lanes_path, *, allow_transit_bus_exits=False):
    """Fail closed unless lanes or the exact shared sequence contract enforce OSM.

    Reads the approved audit's source relations; does not invent legal turns or
    flatten via-way sequences into pair prohibitions. The malformed-source
    treatment is hash-bound and does not establish a general turn permission.
    """
    from simz1_gateway_od import _xml
    from simz1_osm_turn_audit import load_lanes, source_way_id
    osm = _xml(osm_path)
    network = _xml(network_path)
    from simz1_sequence_contract import load_contract, relation_identity, malformed_disposition
    contract = load_contract()
    reviewed = {r['relation_id']: r for r in contract['restrictions']}
    unrepresented = {r['relation_id']: r for r in contract['unrepresented_relations']}
    ways = {w.get('id') for w in osm.findall('way')}
    all_links = {l.get('id'): l for l in network.findall('links/link')}
    links = {key: l for key, l in all_links.items() if 'car' in l.get('modes', 'car').split(',')}
    if any(all(link in links for link in sequence) for sequence in reviewed['17478998']['sequences']):
        import hashlib
        expected = next(meta['sha256'] for meta in contract['sources'].values() if meta['role']=='isolated_source_osm')
        if hashlib.sha256(Path(osm_path).read_bytes()).hexdigest() != expected:
            raise ValueError('OSM source evidence hash mismatch: supplied map for 17478998/17884471 contract')
    if any(source_way_id(l) not in ways for l in links.values()):
        raise ValueError('Procedencia OSM incompleta: cada enlace car requiere origid del mapa suministrado')
    by_way, outgoing = defaultdict(list), defaultdict(list)
    for ident, link in links.items():
        by_way[source_way_id(link)].append(ident)
        outgoing[link.get('from')].append(ident)
    lanes = load_lanes(lanes_path) if lanes_path else {}
    for start, targets in lanes.items():
        if start not in links or any(
                target not in all_links or links[start].get('to') != all_links[target].get('from') or
                (target not in links and not (allow_transit_bus_exits and
                    'bus' in links[start].get('modes', '').split(',') and
                    'bus' in all_links[target].get('modes', '').split(','))) for target in targets):
            raise ValueError('Movimiento de carril desconectado o sin permiso car en preflight OSM')
    successors = {a: set(outgoing[l.get('to')]) & set(lanes.get(a, outgoing[l.get('to')]))
                  for a, l in links.items()}
    rows, errors, pair_prohibitions = [], [], []
    for relation in osm.findall('relation'):
        tags = {t.get('k'): t.get('v') for t in relation.findall('tag')}
        if tags.get('type') != 'restriction':
            continue
        members = defaultdict(list)
        for member in relation.findall('member'):
            members[member.get('role'), member.get('type')].append(member.get('ref'))
        starts, ends = members['from', 'way'], members['to', 'way']
        vias, via_nodes = members['via', 'way'], members['via', 'node']
        row = dict(relation_id=relation.get('id'), restriction=tags.get('restriction'),
                   via_ways=vias, status='not_represented_in_car_network')
        if relation.get('id') == '17884471':
            treatment = malformed_disposition(relation, contract)
            row.update(status=treatment['status'], warning=treatment['warning'],
                       executable_maneuver_identified=False, unrestricted_access_verified=False)
            rows.append(row)
            continue
        if relation.get('id') in reviewed and relation_identity(relation) != reviewed[relation.get('id')]['relation']:
            raise ValueError('OSM relation differs from pinned sequence contract: ' + relation.get('id'))
        complete = len(starts) == 1 and len(ends) == 1 and (bool(vias) != bool(via_nodes)) and len(via_nodes) <= 1
        if not complete:
            # Preserve the existing out-of-network classification only for exact
            # reviewed content whose EVERY named link/node is absent from the
            # effective car graph. Bus-only source extensions are not car access.
            # This is not the 17884471 treatment or an invented turn permission.
            known = unrepresented.get(relation.get('id'))
            network_nodes = {link.get(end) for link in links.values() for end in ('from', 'to')}
            if (known and relation_identity(relation) == known['relation']
                    and not any(by_way[w] for w in starts + ends + vias)
                    and not any(n in network_nodes for n in via_nodes)):
                rows.append(row)
                continue
            row['status'] = 'unsupported_requires_review'
            errors.append(row); rows.append(row)
            continue
        # Absent source members cannot become a maneuver in the current graph.
        if any(not by_way[w] for w in starts + ends + vias):
            rows.append(row)
            continue
        if (len(starts) != 1 or len(ends) != 1 or (bool(vias) == bool(via_nodes)) or
                len(via_nodes) > 1 or not tags.get('restriction', '').startswith('no_') or
                any(k.startswith('restriction:') or k == 'except' for k in tags)):
            row['status'] = 'unsupported_requires_review'
            errors.append(row); rows.append(row)
            continue
        admitted = []
        if via_nodes:
            via = via_nodes[0]
            mapped = []
            for start in sorted(by_way[starts[0]]):
                if links[start].get('to') != via:
                    continue
                for end in sorted(by_way[ends[0]]):
                    if links[end].get('from') == via:
                        mapped.append([start, end])
                        if end in successors[start]:
                            admitted.append([start, end])
            rule = reviewed.get(relation.get('id'))
            if rule is not None:
                # This mapping uses the source relation and directed network,
                # never the lane exclusions that it is intended to justify.
                if mapped != rule['sequences'] or any(len(seq) != 2 for seq in mapped):
                    raise ValueError(relation.get('id') + ' directed mapping differs from sequence contract')
                if 'car' in rule['modes'] and 'car' not in rule['exceptions']:
                    pair_prohibitions.extend(dict(relation_id=rule['relation_id'], from_link=a, to_link=b)
                                             for a, b in mapped)
        else:
            # Follow contiguous directed links of each ordered via way. Never
            # join crossings geometrically or substitute a from->to shortcut.
            def visit(path, stage):
                last = path[-1]
                for target in sorted(successors[last]):
                    way = source_way_id(links[target])
                    if stage == len(vias) - 1 and way == ends[0]:
                        admitted.append(path + [target])
                    elif target not in path and way == vias[stage]:
                        visit(path + [target], stage)
                    elif stage + 1 < len(vias) and way == vias[stage + 1]:
                        visit(path + [target], stage + 1)
            for start in sorted(by_way[starts[0]]):
                for target in sorted(successors[start]):
                    if source_way_id(links[target]) == vias[0]:
                        visit([start, target], 0)
        row['admitted_prohibited_sequences'] = admitted
        row['status'] = 'unimported_prohibition' if admitted else 'no_admitted_prohibited_sequence'
        if relation.get('id') == '17478998':
            from simz1_osm_turn_audit import verify_sequence_mapping
            mapped = verify_sequence_mapping(osm, links.values(), reviewed['17478998'])
            row.update(status='enforced_by_shared_sequence_contract',
                       contract_version=contract['version'], sequences=mapped)
            admitted = []  # Only this verified sequence is delegated to the DFA.
        if admitted:
            errors.append(row)
        rows.append(row)
    if errors:
        ids = ', '.join(r['relation_id'] for r in errors)
        raise ValueError(f'Restricciones OSM pendientes ({len(errors)}): {ids}. '
                         'Se requiere una nueva version de red/restricciones; no se publica demanda ni se modifica la historica')
    return dict(source='OSM restriction relations; effective directed car/lane graph',
                relations=rows, count=len(rows), checked=True,
                pair_prohibitions=sorted(pair_prohibitions, key=lambda row: (row['relation_id'], row['from_link'], row['to_link'])),
                sequence_contract_version=contract['version'],
                limitation='No extrapolation of missing OSM data; via-way restrictions are not flattened')
