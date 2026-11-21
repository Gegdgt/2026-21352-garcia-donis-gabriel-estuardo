"""Population sizing and XML integrity for isolated SimZ1 demand generation."""
import argparse
import json
import math
import secrets
import stat
from collections import Counter
from pathlib import Path
import xml.etree.ElementTree as ET
from simz1_temporal import trip_id, COHORT_WINDOWS

MODES = ('debug', 'historical', 'montecarlo')
DEFAULT_MIN, DEFAULT_MAX = 150000, 250000
SAFE_DEFAULT_AGENTS = 10
MASSIVE_THRESHOLD = 150000
HISTORICAL_AGENTS = 10000


def positive_integer(value):
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        raise argparse.ArgumentTypeError('Se requiere un entero positivo')
    try:
        result = int(value)
    except (ValueError, TypeError):
        raise argparse.ArgumentTypeError('Se requiere un entero positivo') from None
    if result < 1:
        raise argparse.ArgumentTypeError('Se requiere un entero positivo')
    return result


def population_spec(mode='montecarlo', agents=None, min_agents=None, max_agents=None, *, massive=False, allow_empty=False):
    if mode not in MODES:
        raise ValueError(f'Modo desconocido: {mode}')
    if type(massive) is not bool:
        raise ValueError('--massive requiere un valor booleano')
    if massive and mode != 'montecarlo':
        raise ValueError('--massive solo corresponde al modo montecarlo')
    for name, value in (('agents', agents), ('min-agents', min_agents), ('max-agents', max_agents)):
        if value is not None and (type(value) is not int or value < (0 if allow_empty and mode == 'montecarlo' else 1)):
            label = 'no negativo' if allow_empty and mode == 'montecarlo' else 'positivo'
            raise ValueError(f'--{name} requiere un entero {label}')
    if agents is not None and (min_agents is not None or max_agents is not None):
        raise ValueError('--agents es excluyente con --min-agents/--max-agents')
    if (min_agents is None) != (max_agents is None):
        raise ValueError('Indique juntos --min-agents y --max-agents')
    if min_agents is not None and min_agents > max_agents:
        raise ValueError('--min-agents no puede superar --max-agents')
    if mode != 'montecarlo' and min_agents is not None:
        raise ValueError('El rango de poblacion solo corresponde al modo montecarlo')
    if mode == 'debug':
        if agents not in (None, 1):
            raise ValueError('El modo debug requiere exactamente 1 persona')
        return dict(mode=mode, kind='fixed', minimum=1, maximum=1)
    if mode == 'historical':
        if agents not in (None, HISTORICAL_AGENTS):
            raise ValueError('historical es la referencia sintetica de 10000; use montecarlo --agents N para otro tamano')
        return dict(mode=mode, kind='fixed', minimum=HISTORICAL_AGENTS, maximum=HISTORICAL_AGENTS)
    if not massive and (agents is not None and agents >= MASSIVE_THRESHOLD or
                        max_agents is not None and max_agents >= MASSIVE_THRESHOLD):
        raise ValueError(f'Cantidades de {MASSIVE_THRESHOLD} o mas requieren --massive explicito')
    if agents is not None:
        return dict(mode=mode, kind='fixed', minimum=agents, maximum=agents)
    if min_agents is not None:
        return dict(mode=mode, kind='range', minimum=min_agents, maximum=max_agents)
    if massive:
        return dict(mode=mode, kind='range', minimum=DEFAULT_MIN, maximum=DEFAULT_MAX)
    return dict(mode=mode, kind='fixed', minimum=SAFE_DEFAULT_AGENTS, maximum=SAFE_DEFAULT_AGENTS)


def draw_population(spec, rng):
    # Keep the historical count draw FIRST in this same RNG. Fixed sizes skip it,
    # preserving the pre-1A explicit --agents stream. Never reseed mid-generation.
    return rng.randint(spec['minimum'], spec['maximum']) if spec['kind'] == 'range' else spec['minimum']


def resolve_demand_seed(seed=None):
    """Resolve once per generation; an automatic seed does not establish uniqueness."""
    if seed is None:
        return secrets.randbits(53), dict(source='secrets.randbits(53)')
    if type(seed) is not int:
        raise ValueError('La semilla de demanda debe ser un entero explicito o None')
    return seed, dict(source='explicit')


def duplicate_population_check(directory, search_roots, plans_sha256):
    """Compare plan fingerprints only in immediate run folders of the declared scope.

    Other plans are read only when their recorded hash matches. A missing root is
    an empty scope; unreadable or malformed evidence makes the result incomplete.
    This is never a statement of global population uniqueness.
    """
    from simz1_run import MANIFEST, checked_path, load_manifest

    def valid_hash(value):
        return isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value)

    if not valid_hash(plans_sha256):
        raise ValueError('plans_sha256 debe ser un SHA-256 hexadecimal de 64 caracteres')
    directory = Path(directory).resolve()
    matches, unverifiable, visited = [], [], set()
    roots, scope = set(), set()
    for value in search_roots:
        root = Path(value)
        try:
            root = root.resolve()
        except (OSError, ValueError, RuntimeError) as error:
            scope.add(str(root))
            unverifiable.append(dict(path=str(root), reason=str(error)))
            continue
        roots.add(root); scope.add(str(root))
    checked = 0
    for root in sorted(roots, key=str):
        try:
            try:
                information = root.stat()
            except FileNotFoundError:
                continue
            if not stat.S_ISDIR(information.st_mode):
                raise ValueError('La raiz de busqueda no es una carpeta')
            # Unlike glob, explicit enumeration does not silently suppress access errors.
            children = sorted(root.iterdir(), key=str)
        except (OSError, ValueError, RuntimeError) as error:
            unverifiable.append(dict(path=str(root), reason=str(error)))
            continue
        for child in children:
            evidence_path = child
            try:
                if not stat.S_ISDIR(child.stat().st_mode):
                    continue
                folder = child.resolve()
                if folder == directory or folder in visited:
                    continue
                if not folder.is_relative_to(root):
                    raise ValueError('La carpeta resuelta queda fuera de la raiz declarada')
                manifest_path = child/MANIFEST
                evidence_path = manifest_path
                try:
                    manifest_information = manifest_path.stat()
                except FileNotFoundError:
                    continue
                visited.add(folder)
                checked += 1
                if not stat.S_ISREG(manifest_information.st_mode):
                    raise ValueError('El manifiesto no es un archivo regular')
                if not manifest_path.resolve().is_relative_to(folder):
                    raise ValueError('El manifiesto resuelto queda fuera de la carpeta de corrida')
                manifest = load_manifest(folder)
                record = manifest['inputs']['plans']
                if (not isinstance(record, dict) or not isinstance(record.get('path'), str) or not record['path'] or
                        not valid_hash(record.get('sha256'))):
                    raise ValueError('Referencia de planes incompleta o hash invalido')
                if record['sha256'] != plans_sha256:
                    continue
                run_id = manifest.get('run_id')
                if not isinstance(run_id, str) or not run_id.strip():
                    raise ValueError('run_id ausente o invalido para la coincidencia')
                checked_path(folder, record)
                matches.append(dict(run_id=run_id, demand_seed=manifest.get('demand_seed'),
                                    folder=str(folder), plans_sha256=plans_sha256))
            except (OSError, ValueError, TypeError, KeyError, AttributeError, RuntimeError) as error:
                unverifiable.append(dict(path=str(evidence_path), reason=str(error)))
    return dict(status='incomplete' if unverifiable else 'duplicates_found' if matches else 'none_found_in_scope',
                search_roots=sorted(scope), checked_manifests=checked,
                matches=matches, unverifiable_manifests=unverifiable)


def person_vehicle_type(person):
    schema = person.findtext("attributes/attribute[@name='simz1AgentSchema']")
    if schema == 'simz1-road-profiles-v1':
        kind = person.findtext("attributes/attribute[@name='effectiveVehicleType']")
        from simz1_road_catalog import IDENTITIES
        if kind not in IDENTITIES or person.findtext("attributes/attribute[@name='drivingProfile']") != IDENTITIES[kind][1]:
            raise ValueError('Tipo/perfil vial desconocido o incompatible')
        return kind
    if schema not in (None, 'simz1-six-v1'):
        raise ValueError(f'Schema de persona desconocido: {schema}')
    return person.findtext("attributes/attribute[@name='drivingProfile']", default='Normal')


def write_population(plans_path, vehicles_path, people, types_path, description):
    """Stream persons and their vehicles, keeping memory independent of XML size."""
    template = ET.parse(types_path).getroot()
    namespace = 'http://www.matsim.org/files/dtd'
    if template.tag != f'{{{namespace}}}vehicleDefinitions':
        raise ValueError('Se esperaba vehicleDefinitions de MATSim')
    ET.register_namespace('', namespace)
    ET.register_namespace('xsi', 'http://www.w3.org/2001/XMLSchema-instance')
    types = template.findall(f'{{{namespace}}}vehicleType')
    type_ids = {t.get('id') for t in types}
    if not {'Normal', 'Liebre', 'Tortuga'} <= type_ids:
        raise ValueError('Faltan tipos de vehiculo Normal/Liebre/Tortuga')
    vehicle_root = ET.Element(template.tag, template.attrib)
    vehicle_header = ET.tostring(vehicle_root, encoding='unicode', short_empty_elements=False).split('</vehicleDefinitions>')[0]
    population_root = ET.Element('population', desc=description)
    population_header = ET.tostring(population_root, encoding='unicode', short_empty_elements=False).split('</population>')[0]
    plans_path, vehicles_path = Path(plans_path), Path(vehicles_path)
    with plans_path.open('x', encoding='utf-8') as plans, vehicles_path.open('x', encoding='utf-8') as vehicles:
        plans.write('<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE population SYSTEM "http://www.matsim.org/files/dtd/population_v6.dtd">\n'+population_header+'\n')
        vehicles.write('<?xml version="1.0" encoding="utf-8"?>\n'+vehicle_header+'\n')
        for vehicle_type in types:
            vehicles.write(ET.tostring(vehicle_type, encoding='unicode'))
        for person in people:
            ident = person.get('id')
            attributes = person.find('attributes')
            if attributes is None:
                attributes = ET.Element('attributes')
                person.insert(0, attributes)
            profile = person_vehicle_type(person)
            if profile not in type_ids:
                raise ValueError(f'Tipo de vehiculo no definido: {profile}')
            # Same serialized binding that MATSim 15 DrivingProfiles writes at run time.
            ET.SubElement(attributes, 'attribute', name='vehicles',
                          **{'class': 'org.matsim.vehicles.PersonVehicles'}).text = json.dumps({'car': ident}, separators=(',', ':'))
            ET.indent(person, space='  ', level=1)
            plans.write('  '+ET.tostring(person, encoding='unicode')+'\n')
            vehicles.write('  '+ET.tostring(ET.Element('vehicle', id=ident, type=profile), encoding='unicode')+'\n')
        plans.write('</population>\n')
        vehicles.write('</vehicleDefinitions>\n')


def verify_population(plans_path, vehicles_path, expected, eligible_links, expected_trips_per_person=None, require_trip_ids=False,
                      *, spatial_model=None, temporal_policy=None):
    """Read generated XML back: requested N is never accepted as evidence of N."""
    # Own the handles explicitly: iterparse(path) can retain a Windows file lock
    # through a validation exception's traceback.
    with Path(plans_path).open('rb') as plans, Path(vehicles_path).open('rb') as vehicles:
        return _verify_population(plans, vehicles, expected, eligible_links, expected_trips_per_person, require_trip_ids,
                                  spatial_model=spatial_model,temporal_policy=temporal_policy)


def _verify_population(plans_path, vehicles_path, expected, eligible_links, expected_trips_per_person=None, require_trip_ids=False,
                       *, spatial_model=None, temporal_policy=None):
    vehicles, types, maximum_speeds = {}, set(), {}
    context = ET.iterparse(vehicles_path, events=('start', 'end'))
    _, root = next(context)
    if root.tag != '{http://www.matsim.org/files/dtd}vehicleDefinitions':
        raise ValueError('Se esperaba vehicleDefinitions de MATSim')
    for action, element in context:
        if action != 'end':
            continue
        tag = element.tag.rsplit('}', 1)[-1]
        if tag == 'vehicleType':
            ident = element.get('id')
            if not ident or ident in types:
                raise ValueError('Tipo de vehiculo ausente/duplicado')
            types.add(ident)
            velocity = element.find('{http://www.matsim.org/files/dtd}maximumVelocity')
            maximum_speeds[ident] = float(velocity.get('meterPerSecond')) if velocity is not None else None
            element.clear(); root.clear()
        elif tag == 'vehicle':
            ident, profile = element.get('id'), element.get('type')
            if not ident or ident in vehicles or profile not in types:
                raise ValueError('Vehiculo duplicado o tipo inexistente')
            vehicles[ident] = profile
            element.clear(); root.clear()
    ids, trips = set(), 0
    histogram = Counter()
    cohorts = Counter()
    context = ET.iterparse(plans_path, events=('start', 'end'))
    _, root = next(context)
    if root.tag != 'population':
        raise ValueError('Se esperaba population')
    allowed = set(eligible_links)
    spatial_counts = Counter()
    if spatial_model is not None and allowed != set(spatial_model.eligible_links):
        raise ValueError('Allowlist espacial incoherente con el modelo validado')
    for action, person in context:
        if action != 'end' or person.tag != 'person':
            continue
        ident = person.get('id')
        if not ident or ident in ids:
            raise ValueError('Persona duplicada o sin ID')
        ids.add(ident)
        cohort=person.findtext("attributes/attribute[@name='simz1PopulationCohort']")
        if temporal_policy:
            if cohort not in COHORT_WINDOWS:
                raise ValueError('Person lacks an explicit temporal cohort')
            cohorts[cohort]+=1
            departure_window=temporal_policy['windows'][COHORT_WINDOWS[cohort]]
        else:
            if cohort is not None:
                raise ValueError('Temporal cohort requires its effective policy for population validation')
            departure_window=dict(start_seconds=0,end_seconds=86400)
        binding = person.find("attributes/attribute[@name='vehicles']")
        if (binding is None or binding.get('class') != 'org.matsim.vehicles.PersonVehicles' or
                json.loads(binding.text) != {'car': ident}):
            raise ValueError(f'Referencia de vehiculo incoherente: {ident}')
        profile = person_vehicle_type(person)
        if vehicles.get(ident) != profile:
            raise ValueError(f'Vehiculo ausente o perfil incoherente: {ident}')
        plans = person.findall('plan')
        if len(plans) != 1 or plans[0].get('selected') != 'yes':
            raise ValueError(f'Plan seleccionado incoherente: {ident}')
        elements = list(plans[0])
        if (len(elements) < 3 or len(elements)%2 != 1 or
                any(e.tag != ('activity' if i%2 == 0 else 'leg') for i,e in enumerate(elements))):
            raise ValueError(f'Plan car invalido: {ident}')
        number = len(elements)//2
        ledger_text=person.findtext("attributes/attribute[@name='simz1Trips']")
        ledger=json.loads(ledger_text) if ledger_text is not None else None
        if (require_trip_ids or spatial_model is not None) and (not isinstance(ledger,list) or len(ledger)!=number):
            raise ValueError(f'Identidades de viaje persistentes ausentes: {ident}')
        if expected_trips_per_person is not None and number != expected_trips_per_person:
            raise ValueError(f'Cantidad de viajes incoherente: {ident}')
        spatial_attributes = person.findall("attributes/attribute[@name='simz1SpatialOD']")
        spatial = None
        if spatial_model is not None:
            if number != 1 or len(spatial_attributes) != 1 or spatial_attributes[0].get('class') != 'java.lang.String':
                raise ValueError(f'gateway-od requiere un viaje y metadatos persistentes: {ident}')
            try:
                spatial = json.loads(spatial_attributes[0].text)
            except (TypeError, ValueError):
                raise ValueError(f'Metadatos OD invalidos: {ident}') from None
            if not isinstance(spatial, dict) or set(spatial) != {trip_id(ident, 1)}:
                raise ValueError(f'Metadatos OD no corresponden al viaje: {ident}')
        elif spatial_attributes:
            raise ValueError(f'Los metadatos gateway-od requieren un modelo espacial validado: {ident}')
        previous = -1
        for i in range(number):
            origin, leg, destination = elements[2*i:2*i+3]
            if leg.get('mode') != 'car':
                raise ValueError(f'Plan car invalido: {ident}')
            if origin.get('link') == destination.get('link') or not {origin.get('link'), destination.get('link')} <= allowed:
                raise ValueError(f'OD fuera de enlaces car elegibles o no distinto: {ident}')
            if spatial is not None:
                metadata = spatial[trip_id(ident, i+1)]
                if getattr(spatial_model, 'temporal', None) is not None:
                    speed = maximum_speeds[profile]
                    if speed is None or not math.isfinite(speed) or speed <= 0:
                        raise ValueError(f'Temporal OD validation needs a finite serialized vehicle speed: {ident}')
                    spatial_model.validate_metadata(metadata, maximum_speed=speed)
                else:
                    spatial_model.validate_metadata(metadata)
                if metadata.get('metadata_source') == 'simz1-private-gateway-trip-v1':
                    from simz1_route_xml import validate_link_route
                    validate_link_route(leg.find('route'), metadata['route_link_ids'],
                        origin=origin.get('link'), destination=destination.get('link'), vehicle_id=ident)
                if metadata['origin_link'] != origin.get('link') or metadata['destination_link'] != destination.get('link'):
                    raise ValueError(f'OD espacial no coincide con los enlaces efectivos: {ident}')
                spatial_counts[metadata['od_type']] += 1
            value=origin.get('end_time','')
            try:
                parts=list(map(float,value.split(':')))
                departure=parts[0] if len(parts)==1 else sum(v*f for v,f in zip(parts,(3600,60,1)))
                if (len(parts) not in (1,3) or not math.isfinite(departure) or not previous < departure or
                        not departure_window['start_seconds'] <= departure < departure_window['end_seconds']):
                    raise ValueError()
            except ValueError:
                raise ValueError(f'Horario planificado invalido/no creciente: {ident}, viaje {i+1}') from None
            previous=departure
            histogram[f'{int(departure//3600):02}:00'] += 1
            value=leg.findtext("attributes/attribute[@name='simz1TripId']")
            if (require_trip_ids or spatial_model is not None or value is not None) and value != trip_id(ident,i+1):
                raise ValueError(f'ID de viaje incoherente: {ident}')
            if ledger is not None and (len(ledger)!=number or ledger[i] != dict(id=trip_id(ident,i+1),index=i+1,
                    planned_departure=departure,origin_link=origin.get('link'),destination_link=destination.get('link'))):
                raise ValueError(f'Identidad/horario/OD persistente incoherente: {ident}')
        trips += number
        person.clear(); root.clear()
    if len(ids) != expected or set(vehicles) != ids:
        raise ValueError(f'Conteo XML incoherente: solicitado={expected}, personas={len(ids)}, viajes={trips}, vehiculos={len(vehicles)}')
    result = dict(persons=len(ids), trips=trips, vehicles=len(vehicles), unique_person_ids=len(ids),
                  references_valid=True,
                  departures_by_hour={f'{h:02}:00':histogram[f'{h:02}:00'] for h in range(
                      (temporal_policy['windows']['simulation']['end_seconds']+3599)//3600 if temporal_policy else 24)})
    if temporal_policy:
        result.update(principal_cohort_persons=cohorts['main'],context_persons_warmup=cohorts['warmup_context'],
                      context_persons_post=cohorts['post_context'],context_persons=cohorts['warmup_context']+cohorts['post_context'])
    if spatial_model is None:
        result['directed_car_scc'] = True
    else:
        result.update(directed_car_turn_reachability=True, spatial_metadata_valid=True, allowlist_valid=True,
                      scope='observed_z1_only', spatial_od_counts={kind: spatial_counts[kind] for kind in
                          ('external-external', 'external-internal', 'internal-external', 'internal-internal')})
        if spatial_model.summary.get('mode') == 'balanced-gateway-v1':
            result.update(scope=spatial_model.summary['scope'],
                          routing_scope='per_private_trip; no_global_whitelist')
    return result
