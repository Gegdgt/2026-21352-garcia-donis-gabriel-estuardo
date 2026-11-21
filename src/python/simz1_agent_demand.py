"""Opt-in typed demand; legacy generators retain their original RNG and XML.

The six-category blueprint is not a runnable population. Unsupported passenger
services and heavy-vehicle access are never replaced with ordinary car trips.
"""
from collections import Counter
import json
from pathlib import Path
import xml.etree.ElementTree as ET

from simz1_agent_types import (load_catalog, allocate_types, sample_departures,
                             require_executable, catalog_manifest, active_types, type_probabilities)
from simz1_road_catalog import SCHEMA as ROAD_SCHEMA
from simz1_temporal import ContinuousDepartureSampler, COHORT_WINDOWS

SCHEMA = 'simz1-six-v1'


def generation_catalog(path, *, mode, temporal_profile, hourly_weights, drain_seconds):
    if path is None:
        return None
    if mode != 'montecarlo':
        raise ValueError('--agent-catalog solo se admite en montecarlo; historical/debug conservan sus perfiles')
    if temporal_profile is not None or hourly_weights is not None or drain_seconds not in (None, 0):
        raise ValueError('--agent-catalog define horarios por tipo dentro de 24 h; no combinar opciones temporales globales')
    catalog = load_catalog(path)
    # Check declared shares, not just rounded counts: tiny N cannot bypass an
    # unsupported service by happening to round its target to zero persons.
    require_executable(active_types(catalog), catalog)
    return catalog


def validate_road_access(network, catalog):
    """Reject mode-specific access the current common car router cannot enforce.

    This is a conservative preflight, NOT a new motorcycle network or evidence
    that OSM captures every legal restriction. Existing car turns/signals remain.
    """
    if not any(name in ('Motociclista', 'MotocicletaLenta', 'MotocicletaRapida') for name in active_types(catalog)):
        return
    root = ET.parse(network).getroot()
    for element in list(root.findall('nodes/node')) + list(root.findall('links/link')):
        tags = {a.get('name', '').removeprefix('osm:'): a.text or ''
                for a in element.findall('attributes/attribute')}
        for key, value in tags.items():
            if key == 'motorcycle' and value not in ('yes', 'permissive', 'designated'):
                raise ValueError(f'Acceso motorcycle requiere ruteo especifico: {element.get("id")} {key}={value}')
            if 'motorcycle' in key and key != 'motorcycle':
                raise ValueError(f'Restriccion motorcycle no soportada: {element.get("id")} {key}')


def person_attributes(person, kind, catalog):
    spec = catalog['profiles'][kind]
    attributes = person.find('attributes')
    if attributes is None:
        attributes = ET.SubElement(person, 'attributes')
    values = {'drivingProfile': spec.get('driving_profile', kind), 'simz1AgentSchema': catalog['schema_version'],
              'simz1AgentType': kind, 'effectiveVehicleType': spec['vehicle_type'],
              'simz1MaximumVelocityMps': str(spec['maximum_speed_kmh'] / 3.6)}
    if catalog['schema_version'] == ROAD_SCHEMA:
        values.update(simz1VehicleFamily=spec['family'], simz1RoutingPolicy=spec['routing_preference'],
                      simz1VehicleLengthM=str(spec['dimensions']['length_m']),
                      simz1VehicleWidthM=str(spec['dimensions']['width_m']), simz1VehiclePCU=str(spec['pcu']),
                      simz1ScenarioVersion=catalog['scenario_version'])
    for name, value in values.items():
        found = attributes.find(f"attribute[@name='{name}']")
        if found is None:
            found = ET.SubElement(attributes, 'attribute', name=name, **{'class': 'java.lang.String'})
        found.text = value


def assignment_record(ident, kind, departures, catalog, *, prepared_only=False, temporal_policy=None, cohort=None):
    spec = catalog['profiles'][kind]
    return dict(person_id=ident, agent_schema=catalog['schema_version'], agent_type=kind,
                population_role=spec['population_role'],
                vehicle_id=None if prepared_only or spec['population_role'] == 'passenger' else ident,
                target_vehicle_type=spec['vehicle_type'],
                effective_vehicle_type=None if prepared_only else spec['vehicle_type'],
                pcu=spec['pcu'], maximum_speed_kmh=spec['maximum_speed_kmh'],
                planned_departures=departures,
                status='allocation_only' if prepared_only else 'assigned_input_not_simulated',
                **(dict(population_cohort=cohort, temporal_policy_sha256=temporal_policy['policy_sha256'],
                        study_start_seconds=temporal_policy['windows']['study']['start_seconds']) if temporal_policy else {}),
                **(dict(family=spec['family'], driving_profile=spec['driving_profile'], label=spec['label'],
                        routing_policy=spec['routing_preference'], dimensions=spec['dimensions'],
                        acceleration=spec['acceleration']) if catalog['schema_version'] == ROAD_SCHEMA else {}))


def typed_people(people, report, catalog, count, seed, trips, temporal, ledger_path, *, preserve_departures=False,
                 temporal_policy=None, cohort='main', kinds_override=None, append_ledger=False, preserve_catalog_departures=False):
    """Keep the existing spatial sampler; replace only explicit v2 type/time data."""
    kinds = allocate_types(count, seed, catalog) if kinds_override is None else kinds_override
    if len(kinds) != count:
        raise ValueError('Explicit cohort allocation does not match requested count')
    if temporal_policy and (preserve_departures or trips != 1 or cohort not in COHORT_WINDOWS):
        raise ValueError('Continuous weekday policy requires one trip and an explicit supported cohort')
    histogram, counts = Counter(), Counter()
    with Path(ledger_path).open('a' if append_ledger else 'x', encoding='utf-8', newline='\n') as output:
        seen = 0
        for index, person in enumerate(people):
            if index >= count:
                raise ValueError('El generador produjo mas personas que las solicitadas')
            kind, ident = kinds[index], person.get('id')
            departures = (ContinuousDepartureSampler(temporal_policy,kind,ident,cohort).sample(trips) if temporal_policy else
                          [float(a.get('end_time')) for a in person.findall('plan/activity')[:-1]] if preserve_departures else
                          sample_departures(kind, trips, seed, ident, catalog))
            if preserve_catalog_departures and (not preserve_departures or temporal_policy is not None or
                    departures != sample_departures(kind, trips, seed, ident, catalog)):
                raise ValueError('Balanced OD changed a catalog-scheduled departure')
            if preserve_departures and any(not any(slot['start_seconds'] <= t < slot['end_seconds'] and slot['weight'] > 0
                                                  for slot in catalog['profiles'][kind]['departure_intervals']) for t in departures):
                raise ValueError('Horario OD fuera de ventanas de categoria')
            person_attributes(person, kind, catalog)
            if temporal_policy:
                for name,value in dict(simz1PopulationCohort=cohort,
                        simz1StudyStartSeconds=temporal_policy['windows']['study']['start_seconds'],
                        simz1PlannedDepartureSeconds=departures[0],
                        simz1TemporalPolicySha256=temporal_policy['policy_sha256']).items():
                    ET.SubElement(person.find('attributes'),'attribute',name=name,
                                  **{'class':'java.lang.String'}).text=str(value)
            activities = person.findall('plan/activity')
            if len(activities) != trips + 1:
                raise ValueError('Cantidad de actividades incompatible con el catalogo')
            ledger_attr = person.find("attributes/attribute[@name='simz1Trips']")
            ledger = json.loads(ledger_attr.text)
            for i, departure in enumerate(departures):
                activities[i].set('end_time', str(departure))
                ledger[i]['planned_departure'] = departure
                histogram[f'{int(departure // 3600):02}:00'] += 1
            ledger_attr.text = json.dumps(ledger, separators=(',', ':'))
            output.write(json.dumps(assignment_record(ident, kind, departures, catalog,
                                    temporal_policy=temporal_policy,cohort=cohort),
                                    ensure_ascii=False, sort_keys=True, allow_nan=False) + '\n')
            counts[kind] += 1
            seen += 1
            yield person
        if seen != count:
            raise ValueError('El generador produjo menos personas que las solicitadas')
    if temporal_policy:
        temporal.update(catalog_temporal_override='Explicit continuous policy replaces catalog departure windows and hourly weights',
                        catalog_temporal_previous=catalog.get('temporal_demand'),
                        type_schedules_source='temporal_policy.intensity plus optional profile_multipliers')
    else:
        temporal.update(profile='by-od-and-agent-type' if preserve_departures else 'by-agent-type', hourly_weights=None, hourly_probabilities=None,
                    weight_source='synthetic-OD-times-intersect-agent-windows' if preserve_departures else 'explicit-synthetic-agent-catalog',
                    type_schedules={name: spec['departure_intervals'] for name, spec in catalog['profiles'].items()})
        if preserve_catalog_departures:
            temporal.update(profile='by-agent-type', weight_source='explicit-synthetic-agent-catalog',
                            od_departures='identical_per_person_to_balanced_network_catalog')
    for obsolete in ('peak_windows', 'peak_mu_seconds', 'sigma_seconds', 'morning_share', 'agents_by_peak'):
        report.pop(obsolete, None)
    report.update(driving_profiles=dict(counts),
                  driving_profile_probabilities=type_probabilities(catalog),
                  allocation_method=catalog['allocation']['rounding'] + '_canonical_ties_then_seeded_shuffle',
                  agent_configuration=catalog_manifest(catalog),
                  agent_type_counts={name: counts[name] for name in catalog['profiles']},
                  departures_by_hour={f'{h:02}:00': histogram[f'{h:02}:00'] for h in range(
                      (temporal_policy['windows']['simulation']['end_seconds']+3599)//3600 if temporal_policy else 24)},
                  hourly_sampling_check=None, temporal_profile=temporal,
                  rng_compatibility=catalog['schema_version'] + (': preserves four-OD allocation/times/capacity budgets' if preserve_departures else ': independent exact allocation and per-person temporal RNG'))
    if catalog['schema_version'] == ROAD_SCHEMA:
        families, profiles, probabilities = Counter(), Counter(), Counter()
        for name, probability in type_probabilities(catalog).items():
            spec = catalog['profiles'][name]
            families[spec['family']] += counts[name]
            profiles[spec['driving_profile']] += counts[name]
            probabilities[spec['driving_profile']] += probability
        report.update(vehicle_family_counts=dict(families), driving_profiles=dict(profiles),
                      driving_profile_probabilities=dict(probabilities), vehicle_type_probabilities=type_probabilities(catalog))


def verify_type_ledger(plans_path, ledger_path, catalog, *, temporal_policy=None):
    """Check exported identity and scheduled times against the actual written XML."""
    with Path(plans_path).open('rb') as plans, Path(ledger_path).open(encoding='utf-8') as records:
        context = ET.iterparse(plans, events=('start', 'end'))
        _, root = next(context)
        counts = Counter()
        for event, person in context:
            if event != 'end' or person.tag != 'person':
                continue
            record = json.loads(next(records, 'null'))
            attrs = {a.get('name'): a.text for a in person.findall('attributes/attribute')}
            kind = attrs.get('simz1AgentType')
            if kind not in catalog['profiles'] or attrs.get('simz1AgentSchema') != catalog['schema_version']:
                raise ValueError('Tipo/schema ausente en planes v2')
            departures = [float(a.get('end_time')) for a in person.findall('plan/activity')[:-1]]
            cohort = attrs.get('simz1PopulationCohort')
            if temporal_policy:
                if (cohort not in COHORT_WINDOWS or attrs.get('simz1TemporalPolicySha256') != temporal_policy['policy_sha256'] or
                        float(attrs.get('simz1StudyStartSeconds','nan')) != temporal_policy['windows']['study']['start_seconds'] or
                        len(departures) != 1 or float(attrs.get('simz1PlannedDepartureSeconds','nan')) != departures[0]):
                    raise ValueError('Temporal cohort identity differs from effective policy')
            elif cohort is not None:
                raise ValueError('Temporal cohort requires its explicit policy')
            expected = assignment_record(person.get('id'), kind, departures, catalog,
                                         temporal_policy=temporal_policy,cohort=cohort)
            if record != expected or attrs.get('drivingProfile') != catalog['profiles'][kind].get('driving_profile', kind) or attrs.get('effectiveVehicleType') != expected['effective_vehicle_type']:
                raise ValueError('Manifiesto de tipos no coincide con las personas/vehiculos')
            if catalog['schema_version'] == ROAD_SCHEMA:
                expected_person = ET.Element('person')
                person_attributes(expected_person, kind, catalog)
                for a in expected_person.findall('attributes/attribute'):
                    if attrs.get(a.get('name')) != a.text:
                        raise ValueError('Familia/perfil/parametros de persona difieren del catalogo')
            if float(attrs.get('simz1MaximumVelocityMps', 'nan')) != catalog['profiles'][kind]['maximum_speed_kmh'] / 3.6:
                raise ValueError('Techo de velocidad de persona no coincide con el catalogo')
            for departure in departures:
                if temporal_policy:
                    window=temporal_policy['windows'][COHORT_WINDOWS[cohort]]
                    if not window['start_seconds'] <= departure < window['end_seconds']:
                        raise ValueError('Departure outside its absolute cohort window')
                elif not any(slot['start_seconds'] <= departure < slot['end_seconds'] and slot['weight'] > 0
                           for slot in catalog['profiles'][kind]['departure_intervals']):
                    raise ValueError('Salida fuera del horario del tipo')
            counts[kind] += 1
            person.clear(); root.clear()
        if next(records, None) is not None:
            raise ValueError('Manifiesto de tipos contiene personas adicionales')
        return {name: counts[name] for name in catalog['profiles']}
