"""Per-private-trip acceptance, independent of freight and transit routing.

An observed reroute is allowed inside the verified interior. Its selected
entry/exit chains remain ordered, and no other exterior link is accepted.
This is an acceptance audit, not a new native routing or movement mechanism.
"""
import json
import math
from pathlib import Path

from simz1_balanced_od import VARIANT, GAP_M, load_model, native_queue_ends


def implementation_signature():
    from simz1_balanced_od import digest
    folder = Path(__file__).resolve().parent
    names = ('generate_montecarlo_z1.py','simz1_balanced_od.py','simz1_balanced_od_audit.py',
             'simz1_gateway_od.py','simz1_od_policy.py','simz1_agent_demand.py','simz1_agent_types.py',
             'simz1_demand_composition.py','simz1_freight_gateways.py','simz1_freight.py',
             'simz1_temporal.py','simz1_population.py','simz1_route_xml.py','simz1_run.py',
             'simz1_sequence_contract.py','simz1_osm_turn_audit.py','simz1_effective_access.py',
             'simz1_weekday_transit.py','simz1_stop_proxy.py','simz1_temporal_passage.py')
    from simz1_sequence_contract import CONTRACT
    return dict(version=VARIANT, source_sha256={name:digest(folder/name) for name in names},
                sequence_contract_sha256=digest(CONTRACT))


def check_config(values, *, allow_seed_override=False, iterations=1, origin_admission_policy='empty-slot-origin-v1'):
    if type(iterations) is not int or iterations not in (1,10):raise ValueError("Unsupported balanced iteration contract")
    if any(k.startswith('zona1SpatialRouting.') for k in values):
        raise ValueError('balanced-gateway-v1 forbids a global spatial whitelist; private OD is validated per trip')
    required = {'qsim.useLanes':'true', 'qsim.numberOfThreads':'1',
                'simz1Admission.storagePolicy':'strict-receiver-v1', 'simz1Admission.wholeVehicleReservation':'true',
                'controler.enableLinkToLinkRouting':'true', 'controler.firstIteration':'0', 'controler.lastIteration':str(iterations-1)}
    if not allow_seed_override:
        required['global.randomSeed'] = '20261023'
    for k, v in required.items():
        if values.get(k) != v:
            raise ValueError('Balanced OD requires unchanged physical/one-iteration contract: '+k+'='+v)
    from simz1_scale_contract import LEGACY_ORIGIN_POLICY, GAP_ORIGIN_POLICY
    if (origin_admission_policy not in (LEGACY_ORIGIN_POLICY, GAP_ORIGIN_POLICY) or
            values.get('simz1Admission.originPolicy', LEGACY_ORIGIN_POLICY) != origin_admission_policy):
        raise ValueError('Balanced OD origin admission policy differs from selected experiment')
    for k, v in {'qsim.removeStuckVehicles':'false','qsim.linkDynamics':'FIFO','qsim.trafficDynamics':'queue'}.items():
        if values.get(k, v) != v:
            raise ValueError('Balanced OD cannot change physical execution: '+k)


def require_native_success(manifest):
    """Preparation quotas cannot promote failed/missing native execution."""
    if (type(manifest.get('returncode')) is not int or manifest['returncode'] != 0 or
            manifest.get('returncode_origin') != 'natural_exit' or
            manifest.get('status') not in ('running','completed')):
        raise ValueError('Balanced OD results require successful native execution, not prepared quotas or a failed run')


def validate_scheduled_report(model, composition, spatial, records, audit, buses=None):
    """Rebuild scheduled statistics from validated plans, not reported totals."""
    from collections import Counter
    from simz1_balanced_od import demand_report
    from simz1_od_policy import CLASS_BY_TYPE
    origins = Counter(r['origin_link'] for r in records.values())
    entries = Counter(r['origin_gateway'] for r in records.values() if r['origin_gateway'])
    exits = Counter(r['destination_gateway'] for r in records.values() if r['destination_gateway'])
    types = Counter(r['od_type'] for r in records.values())
    hourly = Counter(f"{int(r['planned_departure']//3600):02}:00" for r in records.values())
    class_hours = Counter((r['od_type'],int(r['planned_departure']//3600)) for r in records.values())
    expected_spatial = dict(realized_counts={k:types[k] for k in CLASS_BY_TYPE},
        realized_class_counts={v:types[k] for k,v in CLASS_BY_TYPE.items()},
        scheduled_gateway_entries=dict(entries),scheduled_gateway_exits=dict(exits),
        departures_by_class_hour={v:{f'{h:02}:00':class_hours[k,h] for h in range(24)} for k,v in CLASS_BY_TYPE.items()})
    for key,value in expected_spatial.items():
        if spatial.get(key) != value:
            raise ValueError('Scheduled private OD metadata differs from plans: '+key)
    expected = demand_report(model,composition,spatial,origins,{f'{h:02}:00':hourly[f'{h:02}:00'] for h in range(24)},20261023,buses)
    for key,value in expected.items():
        if audit.get(key) != value:
            raise ValueError('Scheduled private OD report differs from plans: '+key)


def check_effective_network(model, network, lanes):
    """Transit may annotate its isolated inputs, never invalidate private proofs."""
    # Read the effective network directly; no alternate perimeter is inferred.
    from simz1_gateway_od import _xml
    from simz1_osm_turn_audit import load_lanes
    from simz1_visual_lanes import _path
    from pyproj import Transformer
    from collections import defaultdict
    geographic = Transformer.from_crs('EPSG:32615','EPSG:4326',always_xy=True)
    root = _xml(network)
    nodes = {n.get('id'):(float(n.get('x')),float(n.get('y'))) for n in root.findall('nodes/node')}
    links = {l.get('id'):l for l in root.findall('links/link')}
    moves = load_lanes(lanes)
    ends = native_queue_ends(network, lanes)
    current_outgoing, original_outgoing = defaultdict(set), defaultdict(set)
    for key,row in links.items():
        if 'car' in row.get('modes','').split(','):
            current_outgoing[row.get('from')].add(key)
    for key,row in model.links.items():
        if 'car' in row['modes']:
            original_outgoing[row['from_node']].add(key)
    for key in model.eligible_links:
        row, old = links.get(key), model.links[key]
        if row is None or 'car' not in row.get('modes','').split(','):
            raise ValueError('Effective network removed private route access: '+key)
        if (row.get('from') != old['from_node'] or row.get('to') != old['to_node'] or
                any(nodes[n] != tuple(model.nodes[n]) for n in (old['from_node'], old['to_node'])) or
                any(abs(float(row.get(xml))-old[field]) > 1e-8 for xml,field in
                    (('length','length'),('permlanes','lanes'),('capacity','capacity'),('freespeed','freespeed')))):
            raise ValueError('Effective geometry/capacity changed after private OD proof: '+key)
        current_car_turns = set(moves.get(key,current_outgoing[old['to_node']])) & current_outgoing[old['to_node']]
        original_car_turns = set(model.lane_movements.get(key,original_outgoing[old['to_node']])) & original_outgoing[old['to_node']]
        if current_car_turns != original_car_turns:
            raise ValueError('Effective lane movements changed after private OD proof: '+key)
        attributes = {a.get('name'):a.text for a in row.findall('attributes/attribute')}
        access = next((attributes['osm:'+k] for k in ('motorcar','motor_vehicle','vehicle','access') if 'osm:'+k in attributes),'yes')
        path, _, valid = _path(attributes, list(geographic.transform(*nodes[old['from_node']])),
                              list(geographic.transform(*nodes[old['to_node']])),
                              lambda x,y: geographic.transform(x,y,errcheck=True))
        if (access != old['car_access'] or not valid or len(path) != len(old['path']) or
                any(math.dist(a,b) > 1e-10 for a,b in zip(path,old['path'])) or
                any(k.startswith('osm:') and ':conditional' in k and
                    any(mode in k for mode in ('access','motorcar','motor_vehicle','vehicle')) for k in attributes)):
            raise ValueError('Effective access/path shape changed after private OD proof: '+key)
        if key in model.internal_links or key in model.entry_gateways or key in model.exit_gateways:
            if abs(ends[key]-model.queue_ends[key]) > 1e-8:
                raise ValueError('Native activity endpoint changed; access review must target effective lanes: '+key)


def validate_implementation_signature(saved_code, current_code, implementation_compatibility=None):
    """Default equality remains strict; recovery supplies separately pinned pairs."""
    if implementation_compatibility is None:
        if saved_code != current_code:
            raise ValueError('Private OD implementation changed since preparation; source fingerprints differ')
        return
    compatibility = implementation_compatibility
    names = {'simz1_balanced_od_audit.py', 'simz1_run.py', 'simz1_temporal_passage.py'}
    # An exact reviewed preparation-byte repair is a separate compatibility
    # version. The historical three-source recovery contract stays unchanged.
    if isinstance(compatibility, dict) and compatibility.get('schema') == 'fixed-day-preparation-identity-audit-v1':
        names.add('generate_montecarlo_z1.py')
    if (not isinstance(compatibility, dict) or set(compatibility) != {'schema', 'transitions'} or
            compatibility['schema'] not in ('fixed-day-step-time-format-v1', 'fixed-day-postprocessing-audit-v1',
                                           'fixed-day-preparation-identity-audit-v1') or
            not isinstance(compatibility['transitions'], dict) or set(compatibility['transitions']) != names or
            not isinstance(saved_code, dict) or not isinstance(current_code, dict) or
            not isinstance(saved_code.get('source_sha256'), dict) or
            not isinstance(current_code.get('source_sha256'), dict)):
        raise ValueError('Unsupported private OD implementation compatibility')
    updated = dict(saved_code['source_sha256'])
    for name, pair in compatibility['transitions'].items():
        if (not isinstance(pair, dict) or set(pair) != {'before', 'after'} or
                any(not isinstance(value, str) or len(value) != 64 or
                    any(c not in '0123456789abcdef' for c in value) for value in pair.values()) or
                pair['before'] == pair['after'] or updated.get(name) != pair['before'] or
                current_code['source_sha256'].get(name) != pair['after']):
            raise ValueError('Private OD compatibility source transition differs: '+name)
        updated[name] = pair['after']
    if dict(saved_code, source_sha256=updated) != current_code:
        raise ValueError('Private OD compatibility cannot change other implementation evidence')


def validate_manifest(directory, manifest, *, postprocessing=False, implementation_compatibility=None):
    from simz1_run import checked_path, parameters, xml_elements
    from simz1_od_policy import validate_osm_turns
    from simz1_freight import is_freight
    from simz1_temporal import trip_id
    from simz1_agent_types import load_catalog, sample_departures
    from simz1_demand_composition import split
    contract = manifest.get('balanced_od')
    if contract is None:
        if isinstance(manifest.get('spatial_demand'),dict) and manifest['spatial_demand'].get('mode') == VARIANT:
            raise ValueError('Missing balanced OD manifest contract')
        return None
    if contract.get('variant') != VARIANT or manifest.get('spatial_demand',{}).get('mode') != VARIANT:
        raise ValueError('Balanced OD manifest identity mismatch')
    saved_code = json.loads(checked_path(directory, contract['implementation']).read_text(encoding='utf-8'))
    if postprocessing:
        if implementation_compatibility is not None:
            raise ValueError('Implementation recovery compatibility is not a postprocessing bypass')
        require_native_success(manifest)
        if manifest.get('status')!='completed' or manifest.get('validation',{}).get('status')!='valid':
            raise ValueError('Postprocessing requires the original completed/valid native run')
        from simz1_sequence_contract import SHA256
        if saved_code.get('version')!=VARIANT or saved_code.get('sequence_contract_sha256')!=SHA256:
            raise ValueError('Unsupported native OD version for this postprocessor')
    else:
        validate_implementation_signature(saved_code, implementation_signature(), implementation_compatibility)
    config = parameters(checked_path(directory, manifest.get('effective_config', manifest['inputs']['config'])))
    selected=manifest.get('experiment')
    if selected:
        from simz1_scale_contract import experiment
        pinned=checked_path(directory,manifest['inputs']['input:experiment-specification.json'])
        rebuilt_selection=experiment(pinned,selected['scenario'])
        from simz1_scale_contract import RANDOM_SCHEMA, DIAGNOSTIC_SCHEMA, ORIGIN_SCHEMA, FREIGHT_SCHEMA, validate_manifest_selection, TRANSIT_SCHEMA
        strict_schemas = (RANDOM_SCHEMA, DIAGNOSTIC_SCHEMA, ORIGIN_SCHEMA, FREIGHT_SCHEMA, TRANSIT_SCHEMA)
        if selected.get('schema') in strict_schemas or rebuilt_selection.get('schema') in strict_schemas:
            validate_manifest_selection(manifest, rebuilt_selection)
        for key in ('total_non_public_vehicles','iterations','demand_seed','freight_completion_policy','observation_end_seconds'):
            if selected[key]!=rebuilt_selection[key]:raise ValueError('Experiment selection mismatch: '+key)
        if manifest['demand_composition']['total_non_public_vehicles']!=selected['total_non_public_vehicles']:
            raise ValueError('Experiment N changed')
        from simz1_run import seconds
        temporal=manifest.get('temporal_demand',{})
        if (seconds(config.get('qsim.endTime','nan'))!=selected.get('native_qsim_end_seconds',selected['observation_end_seconds']) or
                temporal.get('demand_window')!=dict(start_seconds=0,end_seconds=86400,end_exclusive=True) or
                temporal.get('observation_policy')!=selected.get('observation_policy',selected['freight_completion_policy'])):
            raise ValueError('Experiment demand/observation horizon mismatch')
        if selected.get('observation_policy') and (config.get('simz1Observation.policy')!=selected['observation_policy'] or
                seconds(config.get('qsim.timeStepSize','1'))!=1):raise ValueError('Native fixed-day boundary contract mismatch')
        if selected.get('observation_policy'):
            from simz1_day_observation import policy_document as day_policy
            saved=json.loads(checked_path(directory,manifest['inputs']['input:day-observation-policy.json']).read_bytes())
            if saved!=day_policy():raise ValueError('Pinned fixed-day policy differs')
    from simz1_scale_contract import origin_policy_for_selection, ORIGIN_SCHEMA, FREIGHT_SCHEMA, TRANSIT_SCHEMA
    check_config(config,iterations=selected['iterations'] if selected else 1,
                 origin_admission_policy=origin_policy_for_selection(selected))
    if selected and selected.get('schema') in (ORIGIN_SCHEMA,FREIGHT_SCHEMA, TRANSIT_SCHEMA):
        policy = selected['origin_admission_policy']
        record = manifest.get('origin_admission_policy', {})
        artifact = record.get('artifact', {})
        if (any(record.get(k) != v for k, v in policy.items()) or
                record.get('effective_policy') != policy['version'] or
                record.get('source') != 'explicit versioned experiment' or
                artifact != dict(path='inputs/origin-admission-policy.json', sha256=policy['policy_sha256'])):
            raise ValueError('Native origin admission policy provenance differs')
        checked_path(directory, artifact)
    catalog = load_catalog(checked_path(directory, manifest['agent_configuration']['catalog_artifact']))
    composition = split(manifest['demand_composition']['total_non_public_vehicles'],catalog)
    if (composition['family_weights'] != dict(carro=44,moto=55,pesado=1) or
            any(manifest['demand_composition'].get(k) != v for k,v in composition.items()) or
            manifest['counts']['public_transport_vehicles_configured'] != 269):
        raise ValueError('Balanced private/freight/public composition differs from its source catalog')
    source_network, source_lanes = (checked_path(directory, contract[k]) for k in ('source_network','source_lanes'))
    boundary = checked_path(directory, manifest['inputs']['zone_boundary'])
    osm = checked_path(directory, manifest['inputs']['od_source_osm'])
    access = checked_path(directory, contract['access_catalog'])
    if contract.get('effective_access_review'):
        from simz1_effective_access import review
        proof = json.loads(checked_path(directory, contract['effective_access_review']).read_text(encoding='utf-8'))
        model, rebuilt = review(source_network, source_lanes,
            checked_path(directory, manifest['inputs']['network']),
            directory/config['network.laneDefinitionsFile'], boundary, osm, access,
            (directory/config['transit.transitScheduleFile']).parent, config['global.coordinateSystem'])
        if any(proof.get(key) != value for key, value in rebuilt.items()):
            raise ValueError('Effective access review differs from the pinned source/service derivation')
        proof_network, proof_lanes = directory/config['network.inputNetworkFile'], directory/config['network.laneDefinitionsFile']
    else:
        model = load_model(source_network, boundary, source_lanes, osm, access, config['global.coordinateSystem'])
        proof_network, proof_lanes = source_network, source_lanes
    spatial = manifest['spatial_demand']
    import hashlib
    from simz1_od_policy import named_percentages, allocate, CLASS_BY_TYPE
    hypothesis = dict(spatial['hypothesis'])
    recorded_hash = hypothesis.pop('sha256')
    if (hypothesis.get('version') != VARIANT or hypothesis.get('empirical_calibration') is not False or
            recorded_hash != hashlib.sha256(json.dumps(hypothesis,sort_keys=True,separators=(',',':')).encode()).hexdigest()):
        raise ValueError('OD synthetic hypothesis/version/hash mismatch')
    from simz1_gateway_od import normalize_shares
    shares = normalize_shares(named_percentages(hypothesis['percentages']))
    _, quotas = allocate(composition['private_vehicles'],shares,20261023)
    if (manifest['demand_seed'] != 20261023 or manifest['matsim_seed'] != 20261023 or
            spatial['class_shares'] != {CLASS_BY_TYPE[k]:v for k,v in shares.items()} or
            spatial['target_class_counts'] != {CLASS_BY_TYPE[k]:v for k,v in quotas.items()}):
        raise ValueError('OD percentages/seed/quotas differ from declared hypothesis')
    for key, value in model.summary.items():
        if spatial.get(key) != value:
            raise ValueError('Balanced OD catalogue/source manifest mismatch: '+key)
    if validate_osm_turns(osm, proof_network, proof_lanes, allow_transit_bus_exits=bool(contract.get('effective_access_review'))) != spatial['restriction_preflight']:
        raise ValueError('Balanced OD turn audit changed')
    lanes = Path(config['network.laneDefinitionsFile'])
    if not lanes.is_absolute():
        lanes = directory/lanes
    # Every effective input is still covered by the existing manifest hashes.
    lane_record = next((r for r in manifest['inputs'].values() if (directory/r['path']).resolve() == lanes.resolve()), None)
    if lane_record is None:
        raise ValueError('Unfingerprinted effective private lanes')
    check_effective_network(model, checked_path(directory, manifest['inputs']['network']), checked_path(directory, lane_record))
    from collections import Counter
    from simz1_balanced_od import IncorporationBudget
    budget = IncorporationBudget(model,float(config.get('qsim.flowCapacityFactor','1')))
    records, profiles = {}, Counter()
    from simz1_temporal_passage import TemporalPassage
    model.temporal = TemporalPassage(checked_path(directory, manifest.get('effective_config', manifest['inputs']['config'])), directory)
    freight_ids = set()
    for person in xml_elements(checked_path(directory, manifest['inputs']['plans']), 'person', 'population'):
        if is_freight(person):
            if person.get('id') in freight_ids or person.get('id') in records:
                raise ValueError('Duplicate private/freight vehicle')
            freight_ids.add(person.get('id'))
            continue
        ident = person.get('id')
        raw = json.loads(person.findtext("attributes/attribute[@name='simz1SpatialOD']", 'null'))
        trips = json.loads(person.findtext("attributes/attribute[@name='simz1Trips']", 'null'))
        if ident in records or ident in freight_ids or not isinstance(raw,dict) or set(raw) != {trip_id(ident,1)} or not isinstance(trips,list) or len(trips) != 1:
            raise ValueError('Duplicate private vehicle or invalid OD ledger')
        kind = person.findtext("attributes/attribute[@name='simz1AgentType']")
        if kind not in catalog['profiles'] or catalog['profiles'][kind]['family'] not in ('carro','moto'):
            raise ValueError('OD classes apply only to private cars/motorcycles')
        record = model.validate_metadata(raw[trip_id(ident,1)], catalog['profiles'][kind]['maximum_speed_kmh']/3.6)
        profiles[kind] += 1
        expected_departure = sample_departures(kind,1,20261023,ident,catalog)[0]
        if (trips[0]['planned_departure'] != expected_departure or
                float(person.find('plan/activity').get('end_time')) != expected_departure):
            raise ValueError('Private OD rescheduled a catalog departure')
        if any(record[k] != trips[0][k] for k in ('origin_link','destination_link')):
            raise ValueError('Private trip endpoints differ from OD evidence')
        if (float(person.findtext("attributes/attribute[@name='simz1VehicleLengthM']", 'nan')) != record['body_length_m'] or
                catalog['profiles'][kind]['dimensions']['length_m'] != record['body_length_m']):
            raise ValueError('Gateway clearance body differs from the private catalog')
        from simz1_route_xml import validate_link_route
        activities = person.findall('plan/activity')
        if len(activities) != 2:
            raise ValueError('Private OD requires exactly two activities')
        validate_link_route(person.find('plan/leg/route'), record['route_link_ids'],
            origin=activities[0].get('link'), destination=activities[-1].get('link'), vehicle_id=ident)
        if not budget.accept(record,int(expected_departure//3600),catalog['profiles'][kind]['pcu']):
            raise ValueError('Prepared private demand exceeds reviewed access capacity')
        records[ident] = dict(record, planned_departure=trips[0]['planned_departure'])
    counts = Counter(r['od_class'] for r in records.values())
    if (len(freight_ids) != composition['freight_vehicles'] or
            any(profiles[k] != v for k,v in composition['private_profile_counts'].items())):
        raise ValueError('Private/freight quotas do not match actual actor types')
    if len(records) != manifest['demand_composition']['private_vehicles'] or any(counts[k] != v for k,v in spatial['target_class_counts'].items()):
        raise ValueError('Private class quotas changed')
    audit = json.loads(checked_path(directory, contract['audit']).read_text(encoding='utf-8'))
    validate_scheduled_report(model,composition,spatial,records,audit,dict(total=269,transmetro=176,tubus=93))
    actual_budget = budget.summary()
    saved_budget = spatial['gateway_capacity']
    for key in ('usage','incorporation_usage'):
        amount = 'scheduled_pcu'
        saved = [r for r in saved_budget[key] if r[amount]]
        if saved != actual_budget[key]:
            raise ValueError('Saved gateway capacity usage differs from prepared plans: '+key)
    return model, records


class PrivateODAudit:
    def __init__(self, model, records):
        self.model, self.records = model, records
        self.paths, self.active, self.front = {}, {}, {}
        self.domains = {}
        self.inserted, self.completed, self.left = set(), set(), set()
        self.aborted = set()
        self.exit_proofs = {}
        self.departed, self.initial_enter, self.pending_leave = set(), set(), {}
        self.link_entries = 0
        self.last_time = -math.inf
        self.finalized = False

    @staticmethod
    def number(e, key):
        value = float(e.get(key, 'nan'))
        if not math.isfinite(value):
            raise ValueError('Private gateway missing native physical evidence: '+key)
        return value

    def allowed(self, record):
        result = set(self.model.interior)
        for key, table in ((record['origin_gateway'], self.model.entry_gateways),
                           (record['destination_gateway'], self.model.exit_gateways)):
            if key:
                result.update(table[key]['link_ids'])
        return result

    def validate_observed_route(self, ident, path, *, complete=False):
        row = self.records[ident]
        if not path or path[0] != row['origin_link'] or any(k not in self.allowed(row) for k in path):
            raise ValueError('Private observed route escaped its selected gateways/interior')
        self.model.validate_route(path)
        if row['origin_gateway']:
            chain = self.model.entry_gateways[row['origin_gateway']]['link_ids']
            n = min(len(path), len(chain))
            if path[:n] != chain[:n]:
                raise ValueError('Private route skipped part of its verified entry chain')
        if row['destination_gateway']:
            chain = self.model.exit_gateways[row['destination_gateway']]['link_ids']
            # Until entering the crossing, a reroute may revisit the interior
            # observation. Once crossing, its entire suffix is compulsory.
            cut = row['exit_crossing_link']
            if cut in path:
                start = path.index(cut)-chain.index(cut)
                tail = path[start:] if start >= 0 else []
                if start < 0 or tail != chain[:len(tail)]:
                    raise ValueError('Private route skipped part of its verified exit chain')
        crossings = [k for k in path if self.model.classification[k] in ('entry_crossing','exit_crossing')]
        expected = [k for k in (row['entry_crossing_link'], row['exit_crossing_link']) if k]
        if crossings != expected[:len(crossings)] or len(crossings) > len(expected):
            raise ValueError('Private route used an undeclared/repeated perimeter crossing')
        if complete and (path[-1] != row['destination_link'] or crossings != expected or
                not set(path) & set(self.model.internal_links)):
            raise ValueError('Private trip did not complete its directed interior/gateway route')

    def _local_front(self, ident, endpoint):
        proof = self.front.get(ident); state = self.active.get(ident)
        if proof is None or state is None or proof['corridor'] != state['corridor']:
            raise ValueError('Private external endpoint lacks active native body evidence')
        domain = self.domains.get(endpoint)
        if domain and domain['corridor'] == proof['corridor']:
            return proof['front']-domain['offset']
        # Retained-origin terminal passage: translate using the actual traveled
        # link sequence. Never infer progress from free-flow time or a link event.
        anchor = state.get('exitFromLink') if state.get('passageKind') == 'boundary_exit' else state.get('receiptLink')
        path = self.paths.get(ident, [])
        if (not anchor or path.count(anchor) != 1 or path.count(endpoint) != 1 or
                anchor not in self.domains or self.domains[anchor]['corridor'] != proof['corridor']):
            raise ValueError('Private endpoint coordinate translation is unproved')
        positions, at = {}, 0.
        for key in path:
            positions[key] = at; at += self.model.links[key]['length']
        return proof['front']-self.domains[anchor]['offset']+positions[anchor]-positions[endpoint]

    def consume(self, event):
        if self.finalized:
            raise ValueError('Private OD audit already finalized')
        kind = event.get('type')
        if kind == 'simz1OccupancyDomain':
            self.domains[event['link']] = dict(corridor=event['corridor'], offset=self.number(event,'linkOffsetMeters'))
            return
        person, vehicle = event.get('person'), event.get('vehicle')
        if person and vehicle and person != vehicle and (person in self.records or vehicle in self.records):
            raise ValueError('Private OD person/vehicle identity mismatch')
        ident = person or vehicle
        if ident not in self.records:
            return  # Freight and public transport keep their existing audits.
        time = self.number(event,'time')
        if time < 0 or time < self.last_time:
            raise ValueError('Private OD events out of chronological order')
        self.last_time = time
        row = self.records[ident]
        if kind == 'departure':
            if ident in self.departed or ident in self.completed or ident in self.aborted or event.get('link') != row['origin_link']:
                raise ValueError('Duplicate/wrong private departure')
            if time+1e-8 < math.floor(row['planned_departure']):
                raise ValueError('Private departure precedes its catalog schedule')
            self.departed.add(ident)
        elif kind == 'simz1OccupancyReservation':
            action = event.get('action')
            if action in ('ENTER','TRANSFER'):
                if abs(self.number(event,'bodyLengthMeters')-row['body_length_m']) > 1e-8 or abs(self.number(event,'footprintMeters')-row['body_length_m']-GAP_M) > 1e-8:
                    raise ValueError('Private body/gap differs from gateway proof')
                self.active[ident] = dict(event); self.front.pop(ident,None)
            elif action == 'EXIT':
                self.active.pop(ident,None); self.front.pop(ident,None)
        elif kind == 'simz1OccupancyProgress':
            if ident not in self.active or event.get('corridor') != self.active[ident]['corridor']:
                raise ValueError('Private gateway progress has no matching reservation')
            self.front[ident] = dict(corridor=event['corridor'], front=self.number(event,'modeledFrontLowerBoundMeters'))
        elif kind == 'vehicle enters traffic':
            if ident not in self.departed or ident in self.inserted or ident in self.aborted or event.get('link') != row['origin_link']:
                raise ValueError('Duplicate/wrong private native insertion')
            self.paths[ident] = [event['link']]
            if row['origin_gateway']:
                gateway = self.model.entry_gateways[row['origin_gateway']]
                if self._local_front(ident,row['origin_link']) > gateway['crossing_distance_m']+1e-8:
                    raise ValueError('Native private insertion occurs after its real entry crossing')
            self.inserted.add(ident)
            self.initial_enter.add(ident)
        elif kind == 'left link':
            if (ident not in self.inserted or ident in self.left or ident in self.aborted or
                    ident in self.pending_leave or event.get('link') != self.paths[ident][-1]):
                raise ValueError('Private LinkLeave without matching active link')
            self.initial_enter.discard(ident)
            self.pending_leave[ident] = event['link']
        elif kind == 'entered link':
            if ident not in self.inserted or ident in self.left or ident in self.aborted:
                raise ValueError('Private link movement without active insertion')
            # MATSim may repeat the origin as LinkEnter after traffic insertion.
            # It is evidence of the same link, not a second traversal.
            if ident in self.initial_enter and event.get('link') == row['origin_link']:
                self.initial_enter.discard(ident)
                return
            if self.pending_leave.pop(ident,None) != self.paths[ident][-1]:
                raise ValueError('Private LinkEnter lacks its preceding LinkLeave')
            self.paths[ident].append(event['link'])
            self.validate_observed_route(ident,self.paths[ident])
            self.link_entries += 1
        elif kind == 'vehicle leaves traffic':
            self.validate_observed_route(ident,self.paths.get(ident,[]),complete=True)
            if event.get('link') != row['destination_link'] or ident in self.left:
                raise ValueError('Wrong/duplicate native private exit')
            if row['destination_gateway']:
                gateway = self.model.exit_gateways[row['destination_gateway']]
                relative = gateway['crossing_distance_m']-sum(self.model.links[k]['length'] for k in gateway['link_ids'][:-1])
                clearance = self._local_front(ident,row['destination_link'])-row['body_length_m']-GAP_M-relative
                if clearance < -1e-8:
                    raise ValueError('Private exterior arrival before whole-body + 0.10m perimeter clearance')
                self.exit_proofs[ident] = dict(rear_plus_gap_clearance_m=clearance, basis='native_modeled_front_lower_bound', time=self.number(event,'time'))
            self.left.add(ident)
            self.pending_leave.pop(ident,None)
        elif kind == 'arrival':
            if ident not in self.left or ident in self.completed or ident in self.aborted or event.get('link') != row['destination_link']:
                raise ValueError('Private arrival without matching native exit/clearance')
            self.completed.add(ident)
        elif kind in ('stuckAndAbort','vehicle aborts'):
            if ident in self.completed:
                raise ValueError('Private abort after a completed arrival')
            self.aborted.add(ident)
            self.pending_leave.pop(ident,None)

    def finish(self):
        """Called only after complete XML consumption; unfinished trips stay so."""
        if (self.active or self.pending_leave or self.left-self.completed or
                self.records and not self.departed and not self.aborted):
            raise ValueError('Incomplete private event evidence at native end: release/arrival/abort missing')
        self.finalized = True
        return self.summary()

    def summary(self):
        scheduled = set(self.records)
        return dict(variant=VARIANT, scheduled=len(scheduled), incorporated=len(self.inserted), completed=len(self.completed),
            observed_departures=len(self.departed), observed_link_transitions=self.link_entries,
            internal_destination_arrivals=sum(not self.records[k]['destination_gateway'] for k in self.completed),
            verified_exterior_arrivals=sum(bool(self.records[k]['destination_gateway']) for k in self.completed),
            evidence_status='closed_native_event_stream' if self.finalized else 'not_finalized',
            never_incorporated=len(scheduled-self.inserted),
            never_observed=len(scheduled-self.departed-self.aborted),
            waiting_to_incorporate=len(self.departed-self.inserted-self.aborted),
            circulating=len(self.inserted-self.left-self.aborted), not_arrived=len(scheduled-self.completed),
            aborted_or_horizon_censored=len(self.aborted-self.completed),
            native_exits_awaiting_arrival=len(self.left-self.completed),
            external_clearance_proofs=self.exit_proofs, door_to_door_seconds=None,
            clock_end_is_not_arrival=True, scope='observed_z1_and_declared_anchors_only')
