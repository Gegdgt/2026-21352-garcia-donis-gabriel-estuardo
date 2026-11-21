"""Demanda SimZ1 aislada: debug fijo, referencia historical o poblacion montecarlo."""
import argparse
import copy
import hashlib
from bisect import bisect
from collections import Counter, defaultdict
from itertools import accumulate
import json
import math
from pathlib import Path
import random
import shutil
import unicodedata
from statistics import NormalDist
import xml.etree.ElementTree as ET

from generate_demand_z1 import principal_links, debug_population, END
from prepare_simz1 import SCENARIO, write_xml
from simz1_run import create_manifest, parameters, config_changes, atomic_json, MANIFEST, sha256
from simz1_run_directory import check_new_directory, create_run_directory
from simz1_population import (MODES, DEFAULT_MIN, DEFAULT_MAX, population_spec, draw_population,
                              positive_integer, write_population, verify_population,
                              resolve_demand_seed, duplicate_population_check)
from simz1_config_validation import ConfigurationError, validate_configuration
from simz1_lane_validation import audit_configuration
from simz1_temporal import (temporal_spec, DepartureSampler, hourly_fit, trip_id, nonnegative_integer,
                            load_temporal_policy, policy_spec, context_allocations, intensity_integral,
                            POLICY_SCENARIO_VERSION)
from simz1_signal_offsets import offset_policy
from simz1_gateway_od import load_gateway_model, normalize_shares
from simz1_agent_demand import generation_catalog, validate_road_access, typed_people, verify_type_ledger
from simz1_agent_types import vehicle_types_xml, allocation_counts
from simz1_od_policy import (CLASS_BY_TYPE, CONTRACT, named_mix, allocate, hourly_profiles,
                             ClassDepartureSampler, GatewayBudget, validate_osm_turns)
from simz1_balanced_od import VARIANT as BALANCED_OD, ORIGIN_POLICY as ACCESS_ORIGINS

PROJECT = SCENARIO.parents[1]
MIN_AGENTS = DEFAULT_MIN
MAX_AGENTS = DEFAULT_MAX
PEAK_WINDOWS = ((21600,30600),(61200,70200))
SIM_START, SIM_END = 19800,86400
CORRIDOR_SHARE = 0.7


def pin_experiment_specification(source, destination, selection):
    """Pin exact bytes and verify the same identity rebuilt by the native auditor.

    DryRun uses this preparation boundary with a temporary destination.  No
    population or manifest is needed to check the transport and reconstruction.
    """
    import os
    import tempfile
    from simz1_scale_contract import experiment, verify_selection_identity
    expected=selection.get('specification_sha256')
    raw=Path(source).read_bytes()
    if (not isinstance(expected,str) or len(expected)!=64 or
            any(c not in '0123456789abcdef' for c in expected) or
            hashlib.sha256(raw).hexdigest()!=expected):
        raise ValueError('Experiment specification bytes changed after selection')
    destination=Path(destination)
    destination.parent.mkdir(parents=True,exist_ok=True)
    fd,temporary=tempfile.mkstemp(prefix=destination.name+'.',suffix='.tmp',dir=destination.parent)
    try:
        with os.fdopen(fd,'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        if sha256(Path(temporary))!=expected:
            raise ValueError('Experiment specification temporary copy changed')
        rebuilt=experiment(Path(temporary),selection['scenario'])
        verify_selection_identity(selection,rebuilt)
        os.replace(temporary,destination)
        if sha256(destination)!=expected:
            raise ValueError('Experiment specification published copy changed')
    finally:
        if os.path.exists(temporary):os.unlink(temporary)
    return destination


def normal_truncada(rng, mu, sigma, low, high):
    normal = NormalDist(mu, sigma)
    a, b = normal.cdf(low), normal.cdf(high)
    p = a + (b-a)*rng.random()
    return normal.inv_cdf(max(math.nextafter(0.,1.), min(math.nextafter(1.,0.),p)))


def synthetic_people(network, seed, spec, corridor_policy, temporal=None, origin_policy="legacy-corridors", destination_policy="legacy-gaussian-v1"):
    """The snapshot sampler, with explicit size/corridor policy and streaming XML."""
    if corridor_policy not in ('redistribute', 'fail'):
        raise ValueError('Indique --corridor-policy redistribute o fail')
    if origin_policy not in ('legacy-corridors', 'uniform-nodes-v1'):
        raise ValueError('Politica de origen desconocida')
    if destination_policy not in ("legacy-gaussian-v1", "lane-length-destinations-v1"):
        raise ValueError("Unknown destination policy")
    temporal = temporal or temporal_spec()
    core, eligible, _, _ = principal_links(network)
    root = ET.parse(network).getroot()
    coords = {n.get('id'): (float(n.get('x')),float(n.get('y'))) for n in root.findall('nodes/node') if n.get('id') in core}
    incoming, outgoing = defaultdict(list), defaultdict(list)
    allowed=set(eligible)
    corridors={name:[] for name in ('Bulevar Asuncion','Calle Marti','Avenida Elena')}
    for link in root.findall('links/link'):
        if link.get('id') in allowed:
            outgoing[link.get('from')].append(link.get('id'))
            incoming[link.get('to')].append(link.get('id'))
            raw=link.findtext("attributes/attribute[@name='osm:name']",default='')
            name=unicodedata.normalize('NFKD',raw).encode('ascii','ignore').decode().lower()
            for label,words in [('Bulevar Asuncion',('asuncion',)),('Calle Marti',('calle','marti')),('Avenida Elena',('avenida','elena'))]:
                if all(word in name for word in words): corridors[label].append(link.get('id'))
    available = [name for name, ids in corridors.items() if ids]
    missing = [name for name, ids in corridors.items() if not ids]
    if origin_policy == 'legacy-corridors' and missing and corridor_policy == 'fail':
        raise ValueError(f'Corredores ausentes en el SCC car: {missing}. Politica fail; no se genero demanda.')
    if origin_policy == 'legacy-corridors' and not available:
        raise ValueError('No hay corredores disponibles; no se puede redistribuir la cuota del 70%')
    if origin_policy == 'legacy-corridors' and missing:
        print(f'Corredores ausentes: {missing}. Politica explicita redistribute: '
              f'el 70% probabilistico se reparte entre {available}; son pesos sinteticos, no aforos.', flush=True)
    nodes=sorted(core)
    for mapping in (incoming,outgoing):
        for links in mapping.values(): links.sort()
    xs,ys=zip(*coords.values());xmin,xmax,ymin,ymax=min(xs),max(xs),min(ys),max(ys)
    # Entradas geometricas del perimetro, no conexiones externas inventadas.
    entries=[n for n in nodes if min((coords[n][0]-xmin)/(xmax-xmin or 1.),(xmax-coords[n][0])/(xmax-xmin or 1.),
                                    (coords[n][1]-ymin)/(ymax-ymin or 1.),(ymax-coords[n][1])/(ymax-ymin or 1.)) <= .1]
    if len(entries)<2: raise ValueError('Perimetro insuficiente para seleccionar entradas')
    rng=random.Random(seed)
    profile_rng=random.Random(f'SimZ1-driving-profile:{seed}')
    chain_rng=random.Random(f'SimZ1-trip-destinations-v1:{seed}')
    sampler = DepartureSampler(seed, temporal['hourly_probabilities']) if temporal['profile']=='full-day' else None
    profile_counts=Counter()
    count=draw_population(spec, rng)
    centers=rng.sample(nodes,min(3, len(nodes)))
    radii=[rng.uniform(180,450) for _ in centers]
    strengths=[rng.uniform(.5,2) for _ in centers]
    weights=[.15+sum(w*math.exp(-math.dist(coords[n],coords[c])**2/(2*r*r))
                    for c,r,w in zip(centers,radii,strengths)) for n in nodes]
    destination_link_weights=({l.get("id"):float(l.get("length"))*float(l.get("permlanes")) for l in root.findall("links/link") if l.get("id") in allowed}
                             if destination_policy == "lane-length-destinations-v1" else {})
    if destination_policy == "lane-length-destinations-v1":
        weights=[sum(destination_link_weights[l] for l in incoming[n]) for n in nodes]
    cumulative=list(accumulate(weights))
    origin_cumulative=list(accumulate(rng.uniform(.5,1.5) for _ in entries))
    means=[normal_truncada(rng,(low+high)/2,10*60,(low+high)/2-15*60,(low+high)/2+15*60)
           for low,high in PEAK_WINDOWS]
    sigmas=[rng.uniform(25,35)*60 for _ in PEAK_WINDOWS]
    morning_share=rng.uniform(.45,.55)
    link_nodes={l.get('id'):l.get('from') for l in root.findall('links/link')}
    origin_counts=Counter()
    first_origin_links=Counter()
    origin_rng=random.Random(f'SimZ1-uniform-origin-nodes-v1:{seed}')
    eligible_origin_nodes=[n for n in nodes if outgoing[n]]
    if not eligible_origin_nodes:
        raise ValueError('No hay nodos con enlaces car de salida alcanzables')
    physical_origins=Counter()
    corridor_sets={name:set(ids) for name,ids in corridors.items()}
    peak_counts=Counter()
    histogram=Counter()
    report = {}
    def people():
        for index in range(count):
            origin=entries[bisect(origin_cumulative,rng.random()*origin_cumulative[-1])]
            destination=nodes[bisect(cumulative,rng.random()*cumulative[-1])]
            while destination==origin:
                destination=nodes[bisect(cumulative,rng.random()*cumulative[-1])]
            corridor='perimeter'
            if origin_policy == 'uniform-nodes-v1':
                origin=origin_rng.choice(eligible_origin_nodes)
                origin_link=origin_rng.choice(outgoing[origin])
                corridor='uniform-network-nodes'
                while destination==origin:
                    destination=nodes[bisect(cumulative,rng.random()*cumulative[-1])]
            elif available and rng.random()<CORRIDOR_SHARE:
                corridor=rng.choice(available)
                origin_link=rng.choice(sorted(corridors[corridor]))
                origin=link_nodes[origin_link]
                while destination==origin:
                    destination=nodes[bisect(cumulative,rng.random()*cumulative[-1])]
            else:
                origin_link=rng.choice(outgoing[origin])
            origin_counts[corridor]+=1
            first_origin_links[origin_link]+=1
            for name, ids in corridor_sets.items():
                if origin_link in ids:
                    physical_origins[name]+=1
            dest_options=[l for l in incoming[destination] if l!=origin_link]
            if not dest_options:
                # A two-node directed cycle has no distinct destination NODE
                # satisfying this condition, but does have distinct OD LINKS.
                # Handle it explicitly instead of an unbounded rejection loop.
                if not any(n != origin and any(l != origin_link for l in incoming[n]) for n in nodes):
                    destination=origin
                    dest_options=[l for l in incoming[destination] if l!=origin_link]
                    if not dest_options:
                        raise ValueError('No hay enlaces OD distintos alcanzables dentro del SCC car')
                # This can only occur for a direct neighbouring destination; resample a valid destination.
                while not dest_options:
                    destination=nodes[bisect(cumulative,rng.random()*cumulative[-1])]
                    dest_options=[l for l in incoming[destination] if l!=origin_link] if destination!=origin else []
            destination_link=(rng.choices(dest_options,weights=[destination_link_weights[l] for l in dest_options])[0]
                              if destination_policy=="lane-length-destinations-v1" else rng.choice(dest_options))
            peak=0 if rng.random()<morning_share else 1
            departure=int(normal_truncada(rng,means[peak],sigmas[peak],*PEAK_WINDOWS[peak]))
            if sampler is None:
                peak_counts[str(peak)]+=1
            departures = sampler.sample(temporal['trips_per_person']) if sampler else [departure]
            for time in departures:
                histogram[f'{int(time//3600):02}:00']+=1
            person=ET.Element('person',id=f'z1_{index+1:05}')
            draw=profile_rng.random()
            profile='Liebre' if draw < .15 else 'Tortuga' if draw < .40 else 'Normal'
            profile_counts[profile]+=1
            attributes=ET.SubElement(person,'attributes')
            ET.SubElement(attributes,'attribute',name='drivingProfile',
                          **{'class':'java.lang.String'}).text=profile
            plan=ET.SubElement(person,'plan',selected='yes')
            ox,oy=coords[origin];dx,dy=coords[destination]
            ET.SubElement(plan,'activity',type='home',link=origin_link,x=str(ox),y=str(oy),end_time=str(departures[0]))
            ledger=[]
            for trip_index, departure in enumerate(departures, 1):
                if trip_index > 1:
                    # Continue where the same person/vehicle actually ended; never teleport
                    # back to a corridor to manufacture a second independent origin.
                    origin_link = destination_link
                    while True:
                        destination = nodes[bisect(cumulative,chain_rng.random()*cumulative[-1])]
                        dest_options = [link for link in incoming[destination] if link != origin_link]
                        if dest_options:
                            break
                    destination_link = (chain_rng.choices(dest_options,weights=[destination_link_weights[l] for l in dest_options])[0]
                                        if destination_policy=="lane-length-destinations-v1" else chain_rng.choice(dest_options))
                    dx,dy=coords[destination]
                ledger.append(dict(id=trip_id(person.get('id'),trip_index), index=trip_index,
                                   planned_departure=departure, origin_link=origin_link, destination_link=destination_link))
                leg=ET.SubElement(plan,'leg',mode='car')
                attributes=ET.SubElement(leg,'attributes')
                ET.SubElement(attributes,'attribute',name='simz1TripId',
                              **{'class':'java.lang.String'}).text=trip_id(person.get('id'),trip_index)
                activity=ET.SubElement(plan,'activity',type='work' if trip_index%2 else 'home',
                                      link=destination_link,x=str(dx),y=str(dy))
                if trip_index < len(departures):
                    activity.set('end_time',str(departures[trip_index]))
            # MATSim PlanRouter replaces legs. Person attributes persist through
            # that operation and carry the canonical ordered trip identities.
            ET.SubElement(person.find('attributes'),'attribute',name='simz1Trips',
                          **{'class':'java.lang.String'}).text=json.dumps(ledger,separators=(',',':'))
            yield person
        report.update(demand_seed=seed,agents=count,driving_profiles=dict(profile_counts),
            driving_profile_probabilities={'Liebre':.15,'Tortuga':.25,'Normal':.60},
            agent_range=[spec['minimum'],spec['maximum']],core_nodes=len(core),eligible_links=len(eligible),entry_nodes=len(entries),
            time_window=list(temporal['simulation_window'].values()),peak_windows=PEAK_WINDOWS,peak_mu_seconds=means,agents_by_peak=dict(peak_counts),
            origin_policy=origin_policy, destination_policy=destination_policy,
            corridor_share=CORRIDOR_SHARE if origin_policy=='legacy-corridors' else 0.,
            corridor_links=corridors,origins_by_source=dict(origin_counts),
            first_origins_by_link=dict(sorted(first_origin_links.items())),
            max_first_origin_link_fraction=(max(first_origin_links.values(),default=0)/count if count else None),
            missing_corridors=[name for name,ids in corridors.items() if not ids],
            sigma_seconds=sigmas,morning_share=morning_share,departures_by_hour=dict(sorted(histogram.items())),
            attraction_centers=([dict(node=c,utm=coords[c],radius_m=r,weight=w) for c,r,w in zip(centers,radii,strengths)] if destination_policy=="legacy-gaussian-v1" else []),
            assumptions=['Synthetic mixture, not observed PMT demand',
                         'Temporal weights are synthetic assumptions, not measured demand; see temporal_profile',
                         ('70% origins on identified named corridors, otherwise geometric perimeter; assumed uncalibrated weights'
                          if origin_policy=='legacy-corridors' else
                          'Synthetic uniform eligible SCC car origin nodes then outgoing link; internal network demand, not measured external gateways'),
                         'Missing named corridors are reported, never assigned invented coordinates',
                         'Coordinates are actual network nodes in EPSG:32615; network geometry unchanged',
                         'Population generation alone does not establish QSim stability'])
        report.update(mode=spec['mode'], population_selection=spec,
                      corridor_policy=corridor_policy,
                      corridor_probabilities={name: (CORRIDOR_SHARE/len(available) if origin_policy=='legacy-corridors' and name in available else 0.) for name in corridors},
                      origin_source_fractions={name: number/count for name, number in origin_counts.items()},
                      physical_origins_by_corridor=dict(physical_origins),
                      concentrated_corridor=available[0] if origin_policy=='legacy-corridors' and len(available) == 1 else None,
                      rng_compatibility=('snapshot-v1: range draws count first; fixed skips count draw; vehicle bindings consume no RNG'
                          if origin_policy=='legacy-corridors' else 'uniform-nodes-v1: independent origin stream; new spatial scenario'),
                      historical_reference='synthetic size reference, not a replay of archived trips' if spec['mode']=='historical' else None)
        report.update(temporal_profile=temporal, persons=count, trips=count*temporal['trips_per_person'],
                      corridor_origin_scope='First trip of each person; subsequent trips continue at previous destination',
                      departures_by_hour={f'{h:02}:00':histogram[f'{h:02}:00'] for h in range(24)},
                      hourly_sampling_check=hourly_fit([histogram[f'{h:02}:00'] for h in range(24)], temporal['hourly_probabilities']))
    return people(), report, eligible


def continuous_cohort_people(people, report, catalog, count, seed, temporal, ledger_path,
                            network, corridor_policy, origin_policy, policy):
    """Append independently generated physical context; leave principal OD/type RNG intact."""
    counts = allocation_counts(count,catalog)
    contexts = context_allocations(counts,policy,catalog['canonical_order'])
    study=policy['windows']['study']
    probabilities_by_type={}
    for kind,number in counts.items():
        if number:
            total=intensity_integral(policy,study['start_seconds'],study['end_seconds'],kind)
            probabilities_by_type[kind]=[intensity_integral(policy,study['start_seconds']+h*3600,
                study['start_seconds']+(h+1)*3600,kind)/total for h in range(24)]
    probabilities=[math.fsum(counts[k]*values[h] for k,values in probabilities_by_type.items())/count for h in range(24)]
    temporal.update(hourly_weights=probabilities,hourly_probabilities=probabilities,
        hourly_weights_kind='Normalized main-cohort mixture probability mass per equal3600-second interval',
        per_type_hourly_probabilities=probabilities_by_type)
    local_histogram = Counter()
    for person in typed_people(people,report,catalog,count,seed,1,temporal,ledger_path,temporal_policy=policy):
        departure=float(person.find('plan/activity').get('end_time'))
        local_histogram[int((departure-policy['windows']['study']['start_seconds'])//3600)] += 1
        yield person
    main_type_counts=dict(report['agent_type_counts'])
    total_types=Counter(main_type_counts)
    total_histogram=Counter(report['departures_by_hour'])
    cohort_histograms={'main':dict(report['departures_by_hour'])}
    for cohort,prefix in (('warmup_context','ctx_pre_'),('post_context','ctx_post_')):
        context=contexts[cohort]
        if context['persons'] == 0:
            cohort_histograms[cohort]={}
            continue
        # Neither context generation nor temporal_seed consumes the principal
        # spatial/allocation stream. Context persons are real MATSim plans.
        context_seed=int.from_bytes(hashlib.sha256(f'SimZ1-context-spatial-v1:{seed}:{cohort}'.encode()).digest()[:8],'big')
        context_spec=dict(mode='montecarlo',kind='fixed',minimum=context['persons'],maximum=context['persons'])
        generated,context_report,_=synthetic_people(network,context_seed,context_spec,corridor_policy,
            copy.deepcopy(temporal),origin_policy=origin_policy)
        def rename(stream, name_prefix):
            for index,person in enumerate(stream,1):
                ident=name_prefix+f'{index:05}'
                person.set('id',ident)
                ledger_attr=person.find("attributes/attribute[@name='simz1Trips']")
                ledger=json.loads(ledger_attr.text)
                for number,(leg,entry) in enumerate(zip(person.findall('plan/leg'),ledger),1):
                    entry['id']=trip_id(ident,number)
                    leg.find("attributes/attribute[@name='simz1TripId']").text=entry['id']
                ledger_attr.text=json.dumps(ledger,separators=(',',':'))
                yield person
        kinds=[name for name in catalog['canonical_order'] for _ in range(context['type_counts'][name])]
        random.Random(f'SimZ1-context-types-v1:{seed}:{cohort}').shuffle(kinds)
        yield from typed_people(rename(generated,prefix),context_report,catalog,context['persons'],context_seed,
            1,copy.deepcopy(temporal),ledger_path,temporal_policy=policy,cohort=cohort,
            kinds_override=kinds,append_ledger=True)
        total_types.update(context_report['agent_type_counts'])
        total_histogram.update(context_report['departures_by_hour'])
        cohort_histograms[cohort]=context_report['departures_by_hour']
    context_total=sum(value['persons'] for value in contexts.values())
    report.update(agents=count+context_total,persons=count+context_total,trips=count+context_total,
        principal_cohort_persons=count,context_persons=context_total,
        context_persons_warmup=contexts['warmup_context']['persons'],context_persons_post=contexts['post_context']['persons'],
        principal_agent_type_counts=main_type_counts,agent_type_counts=dict(total_types),
        population_cohorts=dict(main=dict(persons=count,id_prefix='z1_'),**contexts),
        departures_by_cohort_hour=cohort_histograms,departures_by_hour=dict(total_histogram),
        principal_departures_by_hour_local={f'{h:02}:00':local_histogram[h] for h in range(24)},
        rng_compatibility='Principal spatial/allocation RNG unchanged; separate policy temporal seed and auxiliary spatial/type streams',
        temporal_policy=policy)
    family_counts,profile_counts=Counter(),Counter()
    for kind,number in total_types.items():
        family_counts[catalog['profiles'][kind].get('family','carro')]+=number
        profile_counts[catalog['profiles'][kind].get('driving_profile',kind)]+=number
    report.update(vehicle_family_counts=dict(family_counts),driving_profiles=dict(profile_counts))


def gateway_people(model, seed, spec, shares, temporal, *, class_profiles=None, catalog=None, flow_factor=1., legacy_pcus=None,
                   balanced_composition=None, balanced_percentages=None):
    """One trip per person; real exterior anchors require the opt-in verified contract."""
    if temporal['profile'] != 'full-day' or temporal['trips_per_person'] != 1:
        raise ValueError('gateway-od requiere full-day y --trips-per-person 1')
    if (temporal['simulation_window'] != dict(start_seconds=0, end_seconds=86400) and
            not (temporal.get('observation_policy')=='freight-close-plus3600-v1' and
                 temporal['simulation_window']==dict(start_seconds=0,end_seconds=108000) and
                 temporal['demand_window']==dict(start_seconds=0,end_seconds=86400,end_exclusive=True))):
        raise ValueError('Las cuatro clases OD requieren horizonte 00:00-24:00, sin drenaje adicional')
    model.validate_shares(shares)
    count = draw_population(spec, random.Random(seed))
    rng = random.Random(f'{CONTRACT}:spatial:{seed}')
    profile_rng = random.Random(f'SimZ1-driving-profile:{seed}')
    class_profiles = class_profiles or hourly_profiles(None, temporal)[0]
    sampler = ClassDepartureSampler(seed, class_profiles, catalog)
    assignments, target_counts = allocate(count, shares, seed)
    agent_types = None
    if catalog is not None:
        from simz1_agent_types import allocate_types
        agent_types = allocate_types(count, seed, catalog)
    balanced = balanced_composition is not None
    if balanced:
        from simz1_balanced_od import IncorporationBudget
        from simz1_od_policy import percentage_document, named_percentages
        hypothesis_percentages = percentage_document(balanced_percentages)
        if normalize_shares(named_percentages(hypothesis_percentages)) != normalize_shares(shares):
            raise ValueError('Balanced OD percentages and sampling shares disagree')
        if catalog is None:
            raise ValueError('Balanced gateway OD requires the private catalog')
        budget = IncorporationBudget(model, flow_factor)
    else:
        budget = GatewayBudget(model, flow_factor)
    legacy_pcus = legacy_pcus or dict.fromkeys(('Liebre', 'Tortuga', 'Normal'), 1.)
    if set(legacy_pcus) != {'Liebre', 'Tortuga', 'Normal'} or any(not math.isfinite(v) or v <= 0 for v in legacy_pcus.values()):
        raise ValueError('PCU de perfiles historicos ausente/invalido')
    kinds = list(shares)
    counts, profiles, histogram, class_histograms = Counter(), Counter(), Counter(), defaultdict(Counter)
    spatial = dict(model.summary, mode='gateway-od', shares=dict(shares), seed=seed,
                   scope='observed_z1_only', door_to_door_seconds=None,
                   metadata_source='synthetic_gateway_od', allowed_links=sorted(model.eligible_links),
                   od_contract=CONTRACT, class_shares={CLASS_BY_TYPE[k]: v for k, v in shares.items()},
                   target_class_counts={CLASS_BY_TYPE[k]: v for k, v in target_counts.items()},
                   allocation='largest_remainder_canonical_ties_then_seeded_shuffle',
                   through_policy='every_allowed_path_visits_at_least_one_non_gateway_interior_link; distinct_gateway_nodes',
                   gateway_selection='uniform_feasible_links_then_capacity_rejection; no_named_corridor_bias',
                   max_pair_attempts=1024,
                   hourly_probabilities_by_class={CLASS_BY_TYPE[k]: v for k, v in class_profiles.items()},
                   time_semantics='planned_departure_is_scheduled_system_entry; actual_entry/exit_from_native_events; exterior_duration_unknown')
    report = dict(spatial_demand=spatial)
    origin_counts, gateway_entries, gateway_exits = Counter(), Counter(), Counter()
    if balanced:
        spatial.update(mode=BALANCED_OD, schema_version=2, od_contract=BALANCED_OD,
            metadata_source='simz1-private-gateway-trip-v1',
            scope='observed_z1_and_declared_anchors_only', origin_policy=ACCESS_ORIGINS,
            gateway_selection='reviewed_useful_lane_meters_then_connected_lane_length_destinations; bounded_capacity_rejection',
            through_policy='selected_real_entry_and_exit_crossings_plus_interior; observed_route_validated_per_private_trip',
            hourly_probabilities_by_class=None, hourly_profile_source='unchanged_balanced_catalog_per_person_samples',
            hypothesis=dict(version=BALANCED_OD, empirical_calibration=False, percentages=hypothesis_percentages))
        spatial['hypothesis']['sha256'] = hashlib.sha256(json.dumps(spatial['hypothesis'],sort_keys=True,separators=(',',':')).encode()).hexdigest()

    def people():
        for index in range(count):
            od_type = assignments[index]
            agent_type = agent_types[index] if agent_types is not None else None
            ident = f'z1_{index+1:05}'
            if balanced:
                from simz1_agent_types import sample_departures
                departure = sample_departures(agent_type, 1, seed, ident, catalog)[0]
            else:
                departure = sampler.sample(od_type, agent_type)
            draw = profile_rng.random()
            profile = 'Liebre' if draw < .15 else 'Tortuga' if draw < .40 else 'Normal'
            pcu = catalog['profiles'][agent_type]['pcu'] if catalog is not None else legacy_pcus[profile]
            for attempt in range(1024):
                selected = (model.sample(rng, od_type, catalog['profiles'][agent_type]['dimensions']['length_m'])
                            if balanced else model.sample(rng, od_type))
                if budget.accept(selected, int(departure//3600), pcu):
                    break
            else:
                if balanced:
                    from simz1_balanced_od import CapacityIncompatibility
                    raise CapacityIncompatibility(dict(variant=BALANCED_OD, status='rejected_not_prepared',
                        requested_non_public=balanced_composition['total_non_public_vehicles'],
                        private_vehicles=count, accepted_before_failure=index, failed_person=ident,
                        od_class=CLASS_BY_TYPE[od_type], hour=int(departure//3600), planned_departure=departure,
                        seed=seed, capacity=budget.summary(),
                        limitation='Bounded pair sampling failure; not a proof of global network saturation. No demand rescheduled or dropped.'))
                raise ValueError(f'Capacidad perimetral insuficiente o sin par disponible tras 1024 intentos: {od_type}, hora {int(departure//3600)}. '
                                 'No se cambian N, clase ni hora y no se publica manifiesto preparado')
            selected['od_class'] = CLASS_BY_TYPE[od_type]
            if balanced and getattr(model, 'temporal', None) is not None:
                profile_spec = catalog['profiles'][agent_type]
                speed = profile_spec['maximum_speed_kmh']/3.6
                old_route = selected['route_link_ids']
                new_route = model.temporal_route(selected['origin_link'], selected['destination_link'], selected['body_length_m'], speed)
                if old_route != new_route:
                    changes = report.setdefault('temporal_route_repairs', dict(policy='periodic-native-body-passage-v1', routes={}, persons=[]))
                    def save_route(path):
                        digest = hashlib.sha256(' '.join(path).encode()).hexdigest(); changes['routes'][digest] = path; return digest
                    changes['persons'].append(dict(person=ident, old_sha256=save_route(old_route), new_sha256=save_route(new_route),
                        reason='proved_impossible_to_compatible', body_m=selected['body_length_m'], maximum_speed_mps=speed,
                        departure=departure, od_class=selected['od_class'], origin=selected['origin_link'], destination=selected['destination_link']))
                selected['route_link_ids'] = new_route
            metadata = {key: value for key, value in selected.items() if key not in ('origin_xy', 'destination_xy')}
            origin, destination = selected['origin_link'], selected['destination_link']
            if balanced:
                model.validate_metadata(metadata, catalog['profiles'][agent_type]['maximum_speed_kmh']/3.6 if getattr(model, 'temporal', None) is not None else None)
                origin_counts[origin] += 1
                if selected['origin_gateway']:
                    gateway_entries[selected['origin_gateway']] += 1
                if selected['destination_gateway']:
                    gateway_exits[selected['destination_gateway']] += 1
            ident = f'z1_{index+1:05}'
            canonical_trip = trip_id(ident, 1)
            counts[od_type] += 1; profiles[profile] += 1; histogram[f'{int(departure//3600):02}:00'] += 1
            class_histograms[od_type][f'{int(departure//3600):02}:00'] += 1
            person = ET.Element('person', id=ident)
            attributes = ET.SubElement(person, 'attributes')
            for name, value in (
                    ('drivingProfile', profile),
                    ('simz1Trips', json.dumps([dict(id=canonical_trip, index=1, planned_departure=departure,
                                                  origin_link=origin, destination_link=destination)], separators=(',', ':'))),
                    ('simz1SpatialOD', json.dumps({canonical_trip: metadata}, separators=(',', ':'), allow_nan=False))):
                ET.SubElement(attributes, 'attribute', name=name, **{'class': 'java.lang.String'}).text = value
            plan = ET.SubElement(person, 'plan', selected='yes')
            ox, oy = selected['origin_xy']; dx, dy = selected['destination_xy']
            ET.SubElement(plan, 'activity', type='home', link=origin, x=str(ox), y=str(oy), end_time=str(departure))
            leg = ET.SubElement(plan, 'leg', mode='car')
            leg_attributes = ET.SubElement(leg, 'attributes')
            ET.SubElement(leg_attributes, 'attribute', name='simz1TripId', **{'class': 'java.lang.String'}).text = canonical_trip
            if balanced:
                route = selected['route_link_ids']
                model.validate_route(route)  # Full route, including both gateway joins.
                # PopulationReader 15 uses the text to set BOTH endpoints.
                ET.SubElement(leg, 'route', type='links', start_link=origin, end_link=destination, vehicleRefId=ident).text = ' '.join(route)
            ET.SubElement(plan, 'activity', type='work', link=destination, x=str(dx), y=str(dy))
            yield person
        spatial['realized_counts'] = {kind: counts[kind] for kind in kinds}
        spatial['realized_class_counts'] = {CLASS_BY_TYPE[k]: counts[k] for k in kinds}
        spatial['departures_by_class_hour'] = {CLASS_BY_TYPE[k]: {f'{h:02}:00': class_histograms[k][f'{h:02}:00'] for h in range(24)} for k in kinds}
        spatial['gateway_capacity'] = budget.summary()
        if balanced:
            spatial.update(scheduled_gateway_entries=dict(gateway_entries), scheduled_gateway_exits=dict(gateway_exits))
            from simz1_balanced_od import demand_report
            report['balanced_od_audit'] = demand_report(model, balanced_composition, spatial, origin_counts,
                {f'{h:02}:00':histogram[f'{h:02}:00'] for h in range(24)}, seed)
        report.update(demand_seed=seed, agents=count, persons=count, trips=count,
                      mode=spec['mode'], population_selection=spec, agent_range=[spec['minimum'], spec['maximum']],
                      driving_profiles=dict(profiles), driving_profile_probabilities={'Liebre': .15, 'Tortuga': .25, 'Normal': .60},
                      eligible_links=len(model.eligible_links), corridor_policy='not_applicable',
                      rng_compatibility=CONTRACT + ': independent allocation/spatial/profile/temporal streams',
                      temporal_profile=temporal, time_window=list(temporal['simulation_window'].values()),
                      departures_by_hour={f'{hour:02}:00': histogram[f'{hour:02}:00'] for hour in range(24)},
                      hourly_sampling_check=None,
                      assumptions=['Synthetic gateway OD proportions and exterior labels, not observed demand.',
                                   'Only the observed Zona 1 segment is simulated; door-to-door time is unavailable.',
                                   'Existing directed links and configured turns constrain every sampled OD.',
                                   'No external links, population outside the boundary or external travel times are fabricated.'])
    return people(), report, model.eligible_links


def spatial_options(od_mode, zone_boundary, od_shares, *, mode, trips_per_person, temporal_profile, corridor_policy):
    """Reject incompatible options before reading inputs or creating a run directory."""
    if od_mode not in ('network', 'gateway-od', 'through-traffic', BALANCED_OD):
        raise ValueError('--od-mode debe ser network, gateway-od o through-traffic')
    if od_mode == 'network':
        if zone_boundary is not None or od_shares is not None:
            raise ValueError('--zone-boundary/--od-shares requieren --od-mode gateway-od')
        return None
    if mode == 'debug':
        raise ValueError('debug no admite --od-mode gateway-od')
    if trips_per_person != 1:
        raise ValueError('gateway-od requiere --trips-per-person 1; no se inventan cadenas exteriores')
    if temporal_profile not in (None, 'full-day'):
        raise ValueError('gateway-od requiere --temporal-profile full-day')
    if corridor_policy is not None:
        raise ValueError('gateway-od no admite --corridor-policy; use --od-shares')
    if zone_boundary is None:
        raise ValueError('Falta configurar --zone-boundary con el GeoJSON verificado de Zona 1; '
                         'gateway-od es opcional y --od-mode network conserva el escenario actual sin poligono')
    if not Path(zone_boundary).is_file():
        raise ValueError(f'Falta configurar --zone-boundary: no existe o no es un archivo: {zone_boundary}; '
                         'no se sustituye por el bbox OSM ni por el perimetro vial')
    return normalize_shares(od_shares)


def apply_origin_admission_selection(config, selection):
    """Apply only the explicit experiment opt-in to an isolated XML tree."""
    from simz1_scale_contract import origin_policy_for_selection, LEGACY_ORIGIN_POLICY, ORIGIN_SCHEMA, FREIGHT_SCHEMA, TRANSIT_SCHEMA
    expected = origin_policy_for_selection(selection)
    modules = config.findall("module[@name='simz1Admission']")
    if len(modules) > 1:
        raise ValueError('Duplicate simz1Admission module')
    module = modules[0] if modules else None
    existing = [] if module is None else module.findall("param[@name='originPolicy']")
    if len(existing) > 1:
        raise ValueError('Duplicate simz1Admission.originPolicy')
    before = existing[0].get('value') if existing else LEGACY_ORIGIN_POLICY
    if before not in (LEGACY_ORIGIN_POLICY, expected):
        raise ValueError('Source origin admission policy conflicts with selected experiment')
    if selection and selection.get('schema') in (ORIGIN_SCHEMA,FREIGHT_SCHEMA, TRANSIT_SCHEMA):
        if module is None:
            module = ET.SubElement(config, 'module', name='simz1Admission')
        parameter = existing[0] if existing else ET.SubElement(module, 'param', name='originPolicy')
        parameter.set('value', expected)
    return expected


def generar(config_path, run_dir, seed=None, *, mode='montecarlo', agents=None, min_agents=None, max_agents=None,
            corridor_policy=None, matsim_seed=None, use_lanes=None, within_day_routing=None, routing_share=None,
            reroute_budget=None, signals=None, incidents=None, qsim_threads=None, storage_policy=None, whole_vehicle_reservation=None,
            temporal_profile=None, hourly_weights=None, trips_per_person=1, drain_seconds=None,
            temporal_policy=None, temporal_seed=None,
            signal_offset_policy='preserve', signal_offset_seed=None, short_link_signal_coordination='none',
            unsignalized_priority=None, priority_stop_seconds=None, priority_classification=None, priority_conflicts=None,
            priority_max_yield_seconds=None, od_mode='network', zone_boundary=None, od_shares=None, massive=False,
            agent_catalog=None, od_mix=None, od_hourly_profiles=None, od_osm=None, origin_policy='legacy-corridors',
            destination_policy='legacy-gaussian-v1',
            transit_service=None, transit_service_date=None, accept_transit_route_assumptions=False,
            freight_service=None, freight_service_date=None, freight_vehicles=None, no_freight_transport=False,
            od_access_catalog=None, experiment_spec=None, experiment_scenario=None):
    balanced_od = od_mode == BALANCED_OD
    experiment_selection=None
    if experiment_spec is not None:
        from simz1_scale_contract import experiment, require_scale, require_base_inputs
        experiment_selection=experiment(experiment_spec,experiment_scenario)
        require_base_inputs(experiment_selection, source_config=config_path, agent_catalog=agent_catalog,
                            transit_service=transit_service, freight_service=freight_service,
                            zone_boundary=zone_boundary, od_access_catalog=od_access_catalog)
        if experiment_selection.get('base_inputs'):
            from simz1_od_policy import percentage_document
            expected_mix = percentage_document((SCENARIO/'od/balanced-gateway-v1/mix.json').read_text(encoding='utf-8-sig'))
            if percentage_document(od_mix) != expected_mix:
                raise ValueError('Experiment OD weights differ from the versioned base')
            if transit_service_date != experiment_selection['service_date'] or freight_service_date != experiment_selection['service_date']:
                raise ValueError('Experiment service dates differ')
        n=experiment_selection['total_non_public_vehicles']
        requested=(agents,agents) if agents is not None else (min_agents,max_agents)
        selected_drain=experiment_selection['observation_end_seconds']-86400
        if not balanced_od or requested!=(n,n) or drain_seconds not in (None,selected_drain):
            raise ValueError('Experiment requires exact selected N, balanced OD and its versioned observation horizon')
        require_scale(n,seed,experiment_selection['iterations'],experiment_spec,experiment_scenario)
        drain_seconds=selected_drain
    elif experiment_scenario is not None:raise ValueError('Experiment scenario requires its versioned specification')
    if balanced_od:
        from simz1_balanced_od import input_options
        # Fail closed before config IO, service generation or directory creation.
        checked_shares = input_options(zone_boundary, od_access_catalog, od_mix)
        if (origin_policy != ACCESS_ORIGINS or destination_policy != 'lane-length-destinations-v1' or
                agent_catalog is None or temporal_policy is not None or od_hourly_profiles is not None or
                seed != 20261023 or matsim_seed not in (None, 20261023) or transit_service is None or
                short_link_signal_coordination != 'none' or signal_offset_policy != 'preserve'):
            raise ValueError('balanced-gateway-v1 requires seed=20261023, lane-length-access-v1, balanced destinations/catalog, '
                             'existing transit service and unchanged single-day catalog times/signals; continuous calendar is not compatible')
        matsim_seed = 20261023
    elif od_access_catalog is not None or origin_policy == ACCESS_ORIGINS:
        raise ValueError('--od-access-catalog/lane-length-access-v1 require balanced-gateway-v1')
    if origin_policy not in ('legacy-corridors', 'uniform-nodes-v1', ACCESS_ORIGINS):
        raise ValueError('Politica de origen desconocida')
    if origin_policy == 'uniform-nodes-v1' and (od_mode != 'network' or mode != 'montecarlo'):
        raise ValueError('--origin-policy uniform-nodes-v1 requiere montecarlo y od-mode network')
    if od_mix is not None:
        if od_shares is not None:
            raise ValueError('Use --od-mix o --od-shares, no ambos')
        od_shares = checked_shares if balanced_od else named_mix(od_mix)
    if od_mode == 'network' and (od_hourly_profiles is not None or od_osm is not None):
        raise ValueError('--od-hourly-profiles/--od-osm requieren gateway-od')
    shares = spatial_options(od_mode, zone_boundary, od_shares, mode=mode, trips_per_person=trips_per_person,
                             temporal_profile=temporal_profile, corridor_policy=corridor_policy)
    policy = load_temporal_policy(temporal_policy,temporal_seed) if temporal_policy is not None else None
    if policy is not None:
        if (mode != 'montecarlo' or od_mode != 'network' or agent_catalog is None or trips_per_person != 1 or
                temporal_profile is not None or hourly_weights is not None or drain_seconds is not None):
            raise ValueError('Continuous temporal policy requires montecarlo/network/agent-catalog/one trip; do not combine legacy temporal flags')
        if transit_service_date is not None and transit_service_date != policy['study_date']:
            raise ValueError('Transit study date must equal the temporal policy study date')
        if transit_service is not None:
            transit_service_date=policy['study_date']
    elif temporal_seed is not None:
        raise ValueError('--temporal-seed requires --temporal-policy')
    config_path = Path(config_path).resolve()
    from simz1_local_signal_variant import inspect_config as inspect_signal_variant, POLICY as SIGNAL_VARIANT_POLICY
    signal_variant = inspect_signal_variant(config_path)
    if signal_variant and (short_link_signal_coordination != 'none' or signal_offset_policy != 'preserve'):
        raise ValueError('LOCAL_SIGNAL_VARIANT: preserve the reviewed local offsets; additional coordination needs a separate review')
    if transit_service is not None:
        from simz1_weekday_transit import preflight as transit_preflight
        transit_check = transit_preflight(config_path, transit_service, transit_service_date, accept_transit_route_assumptions,
                          **({'temporal_policy':policy} if policy else {}))
        if balanced_od and transit_check['fleet_by_system'] != {'transmetro':176, 'tubus':93}:
            raise ValueError('Balanced gateway experiment requires the unchanged 176 Transmetro + 93 TuBus service')
    elif transit_service_date is not None or accept_transit_route_assumptions:
        raise ValueError('Transit date/assumption acceptance requires --transit-service')
    automatic_directory = run_dir is None
    if not automatic_directory:
        run_dir = check_new_directory(run_dir)
    seed, seed_selection = resolve_demand_seed(seed)
    catalog = generation_catalog(agent_catalog, mode=mode, temporal_profile=temporal_profile,
                                 hourly_weights=hourly_weights, drain_seconds=0 if experiment_selection else drain_seconds)
    if destination_policy != (catalog or {}).get("destination_policy", "legacy-gaussian-v1"):
        raise ValueError("Destination policy must match the explicit versioned catalog")
    if destination_policy != "legacy-gaussian-v1" and (mode != "montecarlo" or od_mode not in ("network", BALANCED_OD) or temporal_policy is not None):
        raise ValueError("Balanced destinations require one-day network Monte Carlo")
    from simz1_demand_composition import contract as composition_contract, split, freight_options
    composition_policy = composition_contract(catalog) if catalog is not None else None
    if balanced_od and (composition_policy is None or composition_policy['family_weights'] != dict(carro=44,moto=55,pesado=1)):
        raise ValueError('balanced-gateway-v1 requires the exact 44/55/1 non-public composition catalog')
    if balanced_od:
        from simz1_agent_types import load_catalog
        if catalog != load_catalog(SCENARIO/'agent-types-balanced-v1.json'):
            raise ValueError('balanced-gateway-v1 preserves the existing balanced catalog, dimensions and departure profiles')
    composition = None
    if composition_policy and massive and agents is None and min_agents is None and max_agents is None:
        min_agents, max_agents = composition_policy['default_range']
    spec = population_spec(mode, agents, min_agents, max_agents, massive=massive,
                           allow_empty=composition_policy is not None)
    if composition_policy is not None:
        if mode != 'montecarlo' or od_mode not in ('network', BALANCED_OD) or trips_per_person != 1 or policy is not None:
            raise ValueError('Non-public composition requires montecarlo/network/one trip and the existing single-day freight calendar; no continuous multi-day policy')
        if spec['maximum'] > 250000:
            raise ValueError('Non-public N must be within 0..250000')
        composition = split(draw_population(spec, random.Random(seed)), catalog)
        composition.update(requested_selection=dict(spec), demand_seed=seed,
                           selection_rng='One draw from Random(seed); private spatial generator receives a fixed quota')
        freight_service, freight_service_date, freight_vehicles, no_freight_transport = freight_options(
            composition, freight_service, freight_service_date, freight_vehicles, no_freight_transport)
        private = composition['private_vehicles']
        spec = dict(mode=mode, kind='fixed', minimum=private, maximum=private)
    if no_freight_transport and (freight_service or freight_service_date or freight_vehicles is not None):
        raise ValueError('--no-freight-transport conflicts with freight service options')
    if freight_service is not None:
        from simz1_freight import preflight as freight_preflight
        if od_mode not in ('network', BALANCED_OD) or mode != 'montecarlo' or agent_catalog is None:
            raise ValueError('Freight weekday-v1 requires the montecarlo/network/private-catalog flow')
        freight_check = freight_preflight(config_path, freight_service, freight_service_date, freight_vehicles, policy)
        if balanced_od and (freight_check.get('service_version') != 'weekday-compact-v3' or
                freight_check['native_dimensions_m'] != dict(length_m=8, width_m=2.3)):
            raise ValueError('Balanced gateway requires unchanged weekday-compact-v3 freight')
    elif freight_service_date is not None or freight_vehicles is not None:
        raise ValueError('Freight date/count requires --freight-service')
    temporal = policy_spec(policy) if policy else temporal_spec(temporal_profile, hourly_weights, trips_per_person, drain_seconds, mode)
    if experiment_selection:
        temporal['observation_policy']=experiment_selection.get('observation_policy',experiment_selection['freight_completion_policy'])
        if not signal_variant or signal_variant['policy']!=experiment_selection['signal_variant']:
            raise ValueError('Experiment requires the preserved L18 local signal variant')
    class_profiles, class_profile_source = hourly_profiles(od_hourly_profiles, temporal) if shares is not None else (None, None)
    if policy and set(policy['profile_multipliers'])-set(catalog['profiles']):
        raise ValueError('Temporal multiplier references unknown catalog profile')
    if reroute_budget is not None and (type(reroute_budget) is not int or reroute_budget <= 0):
        raise ValueError('--reroute-budget debe ser un entero positivo')
    if qsim_threads is not None and (type(qsim_threads) is not int or qsim_threads <= 0):
        raise ValueError('--qsim-threads debe ser un entero positivo')
    if storage_policy not in (None, 'strict-receiver-v1', 'matsim15-native'):
        raise ValueError('--storage-policy desconocida')
    if mode != 'debug' and shares is None and corridor_policy not in ('redistribute', 'fail'):
        raise ValueError('Indique --corridor-policy redistribute o fail; no se redistribuye silenciosamente')
    if mode == 'debug' and corridor_policy is not None:
        raise ValueError('El OD fijo debug no usa --corridor-policy')
    try:
        config = ET.parse(config_path).getroot()
    except ET.ParseError as exc:
        raise ConfigurationError(f'Configuracion invalida: XML de configuracion mal formado: {exc}') from exc
    original_parameters = parameters(config_path)
    if balanced_od:
        if any(k.startswith('zona1SpatialRouting.') for k in original_parameters):
            raise ValueError('balanced-gateway-v1 requires a source without a global spatial whitelist')
        protected = ((signals, 'signalsystems.useSignalsystems'),
                     (unsignalized_priority, 'zona1Priority.enabled'),
                     (priority_stop_seconds, 'zona1Priority.stopSeconds'),
                     (priority_max_yield_seconds, 'zona1Priority.maxYieldSeconds'),
                     (priority_classification, 'zona1Priority.classification'),
                     (priority_conflicts, 'zona1Priority.conflicts'))
        if any(value is not None and str(value).lower() != original_parameters.get(key, '').lower()
               for value, key in protected):
            raise ValueError('Balanced OD preserves source signals and priority; no physical overrides')
    if policy:
        strategies=[node.get('value') for node in config.findall("module[@name='strategy']/parameterset/param[@name='strategyName']")]
        if any(name not in ('ChangeExpBeta','SelectExpBeta','KeepLastSelected','BestScore','ReRoute') for name in strategies):
            raise ValueError('Fixed temporal policy rejects strategies that may mutate departure/activity times: '+str(strategies))
    if catalog is not None and original_parameters.get('zona1WithinDayRouting.routingPolicy', 'fastest-time') != 'fastest-time':
        raise ValueError('--agent-catalog requiere routingPolicy=fastest-time; no cambia el scoring historico')
    if catalog is not None and catalog['schema_version'] == 'simz1-road-profiles-v1':
        if (original_parameters.get('qsim.linkDynamics', 'FIFO') != 'FIFO' or
                original_parameters.get('qsim.trafficDynamics', 'queue') != 'queue'):
            raise ValueError('Perfiles road-v1 requieren queue/FIFO; no se activa filtrado de motos')
    if shares is None and config.find("module[@name='zona1SpatialRouting']") is not None:
        raise ValueError('--od-mode network no admite un modulo zona1SpatialRouting preexistente; use una configuracion de red sin whitelist')
    if shares is not None and original_parameters.get('controler.enableLinkToLinkRouting') != 'true':
        raise ValueError('gateway-od requiere controler.enableLinkToLinkRouting=true para respetar el dominio permitido; no se activa automaticamente')
    offset_seed = seed if signal_offset_policy == 'hash' and signal_offset_seed is None else signal_offset_seed
    if short_link_signal_coordination not in ('none', 'derive', 'derive-activity-v2'):
        raise ValueError('Coordinacion de senales cortas: none, derive o derive-activity-v2')
    if signal_offset_policy not in ('preserve','zero','hash') or (signal_offset_seed is not None and signal_offset_policy != 'hash'):
        raise ValueError('Opciones de offsets incompatibles; la semilla requiere politica hash')
    def option(module, name, explicit, default):
        parent = config.find(f"module[@name='{module}']")
        if parent is None:
            parent = ET.SubElement(config, 'module', name=module)
        element = parent.find(f"param[@name='{name}']")
        if element is None:
            element = ET.SubElement(parent, 'param', name=name, value=str(default))
        if explicit is not None:
            element.set('value', str(explicit).lower() if isinstance(explicit, bool) else str(explicit))
        return element
    lanes = option('qsim', 'useLanes', use_lanes, 'false').get('value')
    if lanes not in ('true', 'false'):
        raise ValueError('qsim.useLanes debe ser true o false')
    option('zona1WithinDayRouting', 'enabled', within_day_routing, 'true')
    option('zona1WithinDayRouting', 'agentShare', routing_share, '0.5')
    option('signalsystems', 'useSignalsystems', signals, 'false')
    option('zona1Diagnostics', 'incidentsEnabled', incidents, 'true')
    option('qsim', 'numberOfThreads', qsim_threads, '1')
    option('zona1Priority', 'enabled', unsignalized_priority, 'true')
    option('zona1Priority', 'stopSeconds', priority_stop_seconds, '5')
    option('zona1Priority', 'maxYieldSeconds', priority_max_yield_seconds, '30')
    option('zona1Priority', 'classification', priority_classification, 'osm-hierarchy')
    option('zona1Priority', 'conflicts', priority_conflicts, 'geometric')
    # New isolated runs opt into receiver-safe admission. An explicit policy
    # remains recorded, including a deliberately requested legacy comparison.
    option('simz1Admission', 'storagePolicy', storage_policy, 'strict-receiver-v1')
    # Preserve the historical API default. The new workflow explicitly opts
    # into metric corridor storage, requiring one QSim thread and native audit.
    option('simz1Admission', 'wholeVehicleReservation', whole_vehicle_reservation, 'false')
    selected_origin_admission = apply_origin_admission_selection(config, experiment_selection)
    # Expose the actual MATSim 15 defaults; retain every explicit source value.
    option('qsim', 'removeStuckVehicles', None, 'false')
    option('qsim', 'stuckTime', None, '10')
    link_times = config.find("module[@name='travelTimeCalculator']/param[@name='calculateLinkToLinkTravelTimes']")
    if link_times is not None and link_times.get('value') == 'true':
        # MATSim 15's native signal module previously supplied this implicitly;
        # the same supported setting is needed when signals are disabled.
        # Derive it only when absent. Explicit incompatible true is rejected.
        option('travelTimeCalculator', 'separateModes', None, 'false')
    # An omitted budget keeps the source setting (or the Java default if absent).
    # In particular, a budget does not enable an explicitly disabled router.
    if reroute_budget is not None:
        option('zona1WithinDayRouting', 'maxReroutesPerStep', reroute_budget, reroute_budget)
    if routing_share is not None and not 0 <= routing_share <= 1:
        raise ValueError('--routing-share debe estar entre 0 y 1')
    if matsim_seed is not None:
        option('global', 'randomSeed', matsim_seed, matsim_seed)
    if balanced_od:
        from simz1_balanced_od_audit import check_config
        option('controler', 'firstIteration', 0, 0)
        requested_iterations=experiment_selection['iterations'] if experiment_selection else 1
        option('controler', 'lastIteration', requested_iterations-1, requested_iterations-1)
        if experiment_selection:
            # Every requested iteration has native evidence and its own audit.
            option('controler','writeEventsInterval',1,1)
            option('controler','writePlansInterval',1,1)
        check_config({m.get('name')+'.'+p.get('name'):p.get('value')
                      for m in config.findall('module') for p in m.findall('param')},iterations=requested_iterations,
                     origin_admission_policy=selected_origin_admission)
    preflight = validate_configuration(config)
    control_input = config.find("module[@name='signalsystems']/param[@name='signalcontrol']")
    offset_report = None
    if control_input is not None and control_input.get('value') not in (None,'','null'):
        offset_report = offset_policy(config_path.parent/control_input.get('value'), signal_offset_policy, offset_seed)
    elif signal_offset_policy != 'preserve':
        raise ValueError('Politica de offsets explicita sin signalControl.xml')
    # Validate the source before creating any run directory. Disabling lanes
    # explicitly authorizes removal of signal lane references in the isolated copy.
    lane_audit = audit_configuration(config, base_dir=config_path.parent,
                                    allow_signal_lane_stripping=lanes == 'false', osm_path=od_osm)
    source_lane_audit = lane_audit
    def param(module, name):
        result = config.find(f"module[@name='{module}']/param[@name='{name}']")
        if result is None: raise ValueError(f'Falta {module}.{name}')
        return result
    def clock_value(value):
        return f'{value//3600:02}:{value%3600//60:02}:{value%60:02}'
    param('qsim','startTime').set('value','07:59:00' if mode=='debug' else clock_value(temporal['simulation_window']['start_seconds']))
    param('qsim','endTime').set('value','15:00:00' if mode=='debug' else clock_value(temporal['simulation_window']['end_seconds']))
    if experiment_selection and experiment_selection.get('observation_policy')=='fixed-day-24h-v1':
        param('qsim','endTime').set('value',clock_value(experiment_selection['native_qsim_end_seconds']))
        option('qsim','timeStepSize','1','1')
        option('simz1Observation','policy','fixed-day-24h-v1','fixed-day-24h-v1')
    param('travelTimeCalculator','maxTime').set('value',str(END if mode=='debug' else temporal['simulation_window']['end_seconds']))
    if temporal is not None:
        option('qsim','simStarttimeInterpretation','onlyUseStarttime','onlyUseStarttime')
        option('qsim','simEndtimeInterpretation','onlyUseEndtime','onlyUseEndtime')
    network = (config_path.parent / param('network','inputNetworkFile').get('value')).resolve()
    if catalog is not None:
        validate_road_access(network, catalog)
    spatial_model = None
    source_lane_param = config.find("module[@name='network']/param[@name='laneDefinitionsFile']")
    source_lane_path = ((config_path.parent/source_lane_param.get('value')).resolve()
                        if source_lane_param is not None and source_lane_param.get('value') not in (None, '', 'null') else None)
    spatial_source_hashes = {p: sha256(p) for p in (network, source_lane_path) if p is not None}
    # Resolve base inputs before moving the configuration to the run directory.
    vehicle_input=config.find("module[@name='vehicles']/param[@name='vehiclesFile']")
    if vehicle_input is not None:
        vehicle_path=(config_path.parent/vehicle_input.get('value')).resolve()
        if not vehicle_path.is_file(): raise FileNotFoundError(vehicle_path)
        if catalog is None and any(a.get('name') == 'simz1AgentSchema'
                                   for a in ET.parse(vehicle_path).getroot().iter()
                                   if a.tag.rsplit('}', 1)[-1] == 'attribute'):
            raise ValueError('Tipos v2 requieren --agent-catalog explicito; no se reinterpretan como perfiles historicos')
        vehicle_input.set('value',str(vehicle_path))
    param('network','inputNetworkFile').set('value',str(network))
    param('facilities','inputFacilitiesFile').set('value',str((config_path.parent/param('facilities','inputFacilitiesFile').get('value')).resolve()))
    param('plans','inputPlansFile').set('value','plans.xml')
    # Signal input paths remain relative to the source config, not the new run directory.
    for name in ('signalsystems','signalgroups','signalcontrol','ambertimes','intergreentimes','conflictingDirections'):
        element=config.find(f"module[@name='signalsystems']/param[@name='{name}']")
        if element is not None and element.get('value') and element.get('value') != 'null':
            source=(config_path.parent/element.get('value')).resolve()
            if not source.is_file(): raise FileNotFoundError(source)
            element.set('value',str(source))
    # Reserve only after preflight. mkdir(exist_ok=False) is authoritative even
    # when another process starts concurrently; UUIDs never consume demand RNG.
    run_dir = create_run_directory(run_dir, parent=SCENARIO/mode)
    print(f'Carpeta nueva ({"automatica" if automatic_directory else "explicita"}): {run_dir}', flush=True)
    param('controler','outputDirectory').set('value',str(run_dir/'output'))
    inputs = run_dir/'inputs'
    inputs.mkdir()
    if signal_variant:
        shutil.copyfile(SIGNAL_VARIANT_POLICY, inputs/'local-signal-variant.json')
    if policy:
        (inputs/'temporal-policy.json').write_text(json.dumps(policy['configuration'],indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    # Carry the verified source policy through transit's derived network/lanes.
    # The effective XML is checked semantically; the OSM evidence is immutable.
    turn_policy_source = None
    if source_lane_audit.get('turn_policy'):
        evidence = source_lane_audit['turn_policy']['source_osm']
        turn_policy_source = inputs/'osm-turn-policy-source.osm'
        shutil.copyfile(evidence['path'], turn_policy_source)
        if sha256(turn_policy_source) != evidence['sha256']:
            raise ValueError('El OSM de la politica de giros cambio durante preparacion')
    # Copy every configured XML input; the run never depends on mutable source files.
    sources = [('network', 'inputNetworkFile'), ('network', 'laneDefinitionsFile'),
               ('facilities', 'inputFacilitiesFile'), ('vehicles', 'vehiclesFile')]
    sources += [('signalsystems', n) for n in ('signalsystems', 'signalgroups', 'signalcontrol',
                'ambertimes', 'intergreentimes', 'conflictingDirections')]
    if lanes == 'true' and config.find("module[@name='network']/param[@name='laneDefinitionsFile']") is None:
        raise ValueError('Carriles activados sin network.laneDefinitionsFile')
    source_snapshots = {}
    for module, name in sources:
        element = config.find(f"module[@name='{module}']/param[@name='{name}']")
        if element is None or element.get('value') in (None, '', 'null'):
            continue
        source = (config_path.parent/element.get('value')).resolve()
        destination = inputs/f'{module}-{name}{"".join(source.suffixes)}'
        shutil.copyfile(source, destination)
        source_snapshots[module, name] = destination.name
        if source in spatial_source_hashes and sha256(destination) != spatial_source_hashes[source]:
            raise ValueError('Red/carriles cambiaron durante copia; corrida no preparada')
        element.set('value', str(destination))
    if offset_report is not None:
        offset_report = offset_policy(control_input.get('value'), signal_offset_policy, offset_seed, write=True)
    # A lane-aware signal XML would otherwise address missing QSim lanes.
    signal_input = config.find("module[@name='signalsystems']/param[@name='signalsystems']")
    if lanes == 'false' and signal_input is not None and signal_input.get('value') not in (None, '', 'null'):
        signals = ET.parse(signal_input.get('value'))
        for signal in signals.getroot().iter():
            if signal.tag.rsplit('}',1)[-1] == 'signal' and signal.get('linkIdRef') is not None:
                for child in list(signal):
                    if child.tag.rsplit('}',1)[-1] == 'lane': signal.remove(child)
        signal_file = Path(signal_input.get('value'))
        signals.write(signal_file, encoding='utf-8', xml_declaration=True)
        signal_input.set('value',str(signal_file))
    effective_access_evidence = None
    early_transit = None
    if balanced_od:
        from simz1_effective_access import prepare as prepare_effective_access
        effective_access_model, effective_access_evidence, early_transit, lane_audit = prepare_effective_access(
            config, config_path.parent, inputs/'transit-weekday', composition['private_vehicles'],
            transit_service, transit_service_date, accept_transit_route_assumptions,
            zone_boundary, od_osm, od_access_catalog)
        network = Path(param('network', 'inputNetworkFile').get('value'))
        effective_access_evidence['source_scenario'] = dict(path=str(config_path), sha256=sha256(config_path))
        atomic_json(inputs/'effective-access-review.json', effective_access_evidence)
    spatial_model = None
    boundary_source = None
    if shares is not None:
        if od_osm is None or not Path(od_osm).is_file():
            raise ValueError('gateway-od requiere --od-osm con el mapa OSM auditado para verificar giros antes de publicar')
        boundary_source = Path(zone_boundary).resolve()
        boundary_source_sha256 = sha256(boundary_source)
        lane_input = config.find("module[@name='network']/param[@name='laneDefinitionsFile']")
        lane_path = ((config_path.parent/lane_input.get('value')).resolve()
                     if lane_input is not None and lane_input.get('value') not in (None, '', 'null') else None)
        crs = param('global', 'coordinateSystem').get('value')
        spatial_source_hashes = {p: sha256(p) for p in (Path(od_osm).resolve(), network, lane_path) if p is not None}
        restriction_audit = validate_osm_turns(od_osm, network, lane_path, allow_transit_bus_exits=balanced_od)
        if balanced_od:
            spatial_model = effective_access_model
            spatial_source_hashes[Path(od_access_catalog).resolve()] = sha256(od_access_catalog)
        else:
            spatial_model = load_gateway_model(network, boundary_source, lanes_path=lane_path, crs=crs)
        spatial_model.validate_shares(shares)
        flow = float(option('qsim', 'flowCapacityFactor', None, '1.0').get('value'))
        legacy_pcus = None
        if catalog is None:
            from simz1_gateway_od import _xml
            template = _xml(config_path.parent/param('vehicles', 'vehiclesFile').get('value'))
            legacy_pcus = {}
            for kind in ('Liebre', 'Tortuga', 'Normal'):
                element = template.find(f"vehicleType[@id='{kind}']/passengerCarEquivalents")
                if element is None:
                    raise ValueError(f'Falta PCU verificable para {kind}')
                legacy_pcus[kind] = float(element.get('pce'))
        people, report, eligible = gateway_people(spatial_model, seed, spec, shares, temporal,
                                                 class_profiles=class_profiles, catalog=catalog, flow_factor=flow, legacy_pcus=legacy_pcus,
                                                 balanced_composition=composition if balanced_od else None,
                                                 balanced_percentages=od_mix if balanced_od else None)
        if not balanced_od:
            spatial_model.summary['od_contract'] = CONTRACT
        report['spatial_demand']['restriction_preflight'] = restriction_audit
        if not balanced_od:
            report['spatial_demand']['hourly_profile_source'] = class_profile_source or temporal['weight_source']
        od_osm = Path(od_osm).resolve()
        osm_source_sha256 = sha256(od_osm)
        if any(sha256(p) != expected for p, expected in spatial_source_hashes.items()):
            raise ValueError('Red/carriles/OSM cambiaron durante preflight; corrida no preparada')
        report['spatial_demand']['requested_mode'] = od_mode
        if not balanced_od:
            option('zona1SpatialRouting', 'mode', 'gateway-od', 'gateway-od')
            option('zona1SpatialRouting', 'allowedLinks', ' '.join(sorted(eligible)), '')
    elif mode == 'debug':
        signal_input = config.find("module[@name='signalsystems']/param[@name='signalsystems']")
        signals_path = (config_path.parent/signal_input.get('value')).resolve() if signal_input is not None else None
        debug, report = debug_population(network, signals_path=signals_path)
        people = iter(debug.findall('person'))
        _, eligible, _, _ = principal_links(network)
        report.update(demand_seed=seed, population_selection=spec, corridor_policy='not_applicable')
    else:
        people, report, eligible = synthetic_people(network, seed, spec, corridor_policy, temporal, origin_policy=origin_policy, destination_policy=destination_policy)
    boundary_artifact = None
    if boundary_source is not None:
        if balanced_od:
            shutil.copyfile(od_access_catalog, inputs/'od-access-catalog.json')
            if sha256(inputs/'od-access-catalog.json') != spatial_model.summary['access_sha256']:
                raise ValueError('Access catalogue changed during preflight')
        if od_hourly_profiles is not None:
            profile_destination = inputs/'od-hourly-profiles.json'
            shutil.copyfile(od_hourly_profiles, profile_destination)
            if sha256(profile_destination) != class_profile_source['sha256']:
                raise ValueError('El perfil horario OD cambio durante preflight; corrida no preparada')
        osm_destination = inputs/'od-source.osm'
        shutil.copyfile(od_osm, osm_destination)
        if sha256(osm_destination) != osm_source_sha256:
            raise ValueError('El OSM cambio durante preflight; corrida no preparada')
        boundary_destination = inputs/'zone-boundary.geojson'
        shutil.copyfile(boundary_source, boundary_destination)
        if (sha256(boundary_destination) != boundary_source_sha256 or
                json.loads(boundary_destination.read_text(encoding='utf-8')) != spatial_model.boundary_document):
            raise ValueError('El limite de zona cambio durante el preflight; corrida no preparada')
        boundary_artifact = dict(path='inputs/zone-boundary.geojson', sha256=boundary_source_sha256)
        report['spatial_demand']['boundary_artifact'] = boundary_artifact
    if early_transit is not None:
        report['weekday_transit'] = early_transit
    if vehicle_input is None:
        raise ValueError('Falta vehicles.vehiclesFile con los tipos de perfiles')
    if catalog is not None:
        # Replace only this new run's private type template. The master and all
        # archived XML retain Tortuga=20 and their original profile interpretation.
        ET.ElementTree(vehicle_types_xml(catalog)).write(vehicle_input.get('value'), encoding='utf-8', xml_declaration=True)
        (inputs/'agent-catalog.json').write_text(json.dumps(catalog, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
        requested = draw_population(spec, random.Random(seed))
        if policy:
            people=continuous_cohort_people(people,report,catalog,requested,seed,temporal,inputs/'agent-types.jsonl',
                network,corridor_policy,origin_policy,policy)
        else:
            people = typed_people(people, report, catalog, requested, seed, trips_per_person,
                                  temporal, inputs/'agent-types.jsonl', preserve_departures=spatial_model is not None,
                                  preserve_catalog_departures=balanced_od)
    generated_vehicles = inputs/'vehicles.xml'
    from simz1_balanced_od import CapacityIncompatibility
    try:
        write_population(run_dir/'plans.xml', generated_vehicles, people, Path(vehicle_input.get('value')),
                         'SimZ1 fixed signal debug' if mode=='debug' else 'SimZ1 synthetic demand; not calibrated observations')
    except CapacityIncompatibility as exc:
        atomic_json(inputs/'od-preflight-failure.json', exc.diagnostic)
        raise
    vehicle_input.set('value',str(generated_vehicles))
    if transit_service is not None and early_transit is None:
        from simz1_weekday_transit import attach as attach_transit
        report['weekday_transit'] = attach_transit(config, inputs/'transit-weekday', report['agents'],
            transit_service, transit_service_date, accept_transit_route_assumptions,
            **({'temporal_policy':policy} if policy else {}))
        network = Path(config.find("module[@name='network']/param[@name='inputNetworkFile']").get('value'))
    write_xml(run_dir/'config-simz1.xml',config,'config_v2.dtd')
    lane_audit = audit_configuration(run_dir/'config-simz1.xml', osm_path=turn_policy_source)
    lane_audit['selection_source'] = 'explicit CLI' if use_lanes is not None else 'source configuration'
    # Verify the actual written XML and all person/vehicle references before publishing a prepared manifest.
    actual = verify_population(run_dir/'plans.xml', generated_vehicles, report['agents'], eligible,
                               expected_trips_per_person=trips_per_person, require_trip_ids=temporal is not None,
                               spatial_model=spatial_model,temporal_policy=policy)
    if temporal is not None and actual['departures_by_hour'] != report['departures_by_hour']:
        raise ValueError('El histograma horario no coincide con las salidas del XML')
    if catalog is not None:
        checked_types = verify_type_ledger(run_dir/'plans.xml', inputs/'agent-types.jsonl', catalog,temporal_policy=policy)
        if checked_types != report['agent_type_counts']:
            raise ValueError('Los conteos por tipo no coinciden con el XML')
    if spatial_model is not None and actual['spatial_od_counts'] != report['spatial_demand']['realized_counts']:
        raise ValueError('Los conteos OD no coinciden con los metadatos del XML')
    if spatial_model is not None and {CLASS_BY_TYPE[k]: v for k, v in actual['spatial_od_counts'].items()} != report['spatial_demand']['target_class_counts']:
        raise ValueError('Los conteos OD no preservan las cuotas exactas solicitadas')
    freight = None
    if freight_service is not None:
        from simz1_freight import attach as attach_freight
        freight = attach_freight(run_dir, config_path, freight_service, freight_service_date, freight_vehicles,
            completion_policy=experiment_selection['freight_completion_policy'] if experiment_selection else None)
        if composition is not None:
            freight.update(independent_of_private_demand=False, generated_separately_from_private=True,
                           included_in_non_public_total=True, quantity_basis='derived_from_non_public_composition')
        report['freight_transport'] = freight
    if experiment_selection:
        from simz1_freight_completion import policy_document
        pin_experiment_specification(experiment_spec,inputs/'experiment-specification.json',experiment_selection)
        if experiment_selection.get('origin_admission_policy'):
            from simz1_scale_contract import PROJECT as policy_root, ORIGIN_POLICY, origin_policy_identity
            policy_identity = origin_policy_identity()
            if policy_identity != experiment_selection['origin_admission_policy']:
                raise ValueError('Origin admission policy changed during preparation')
            shutil.copyfile(policy_root/ORIGIN_POLICY, inputs/'origin-admission-policy.json')
            if sha256(inputs/'origin-admission-policy.json') != policy_identity['policy_sha256']:
                raise ValueError('Pinned origin admission policy differs')
        timing_document=policy_document(experiment_selection['freight_completion_policy'])
        if experiment_selection.get('freight_timing_policy'):
            timing_identity=experiment_selection['freight_timing_policy']
            timing_source=PROJECT/timing_identity['policy_path']
            if (sha256(timing_source)!=timing_identity['policy_sha256'] or
                    json.loads(timing_source.read_bytes())!=timing_document):
                raise ValueError('Freight timing policy changed during preparation')
            shutil.copyfile(timing_source,inputs/'freight-completion-policy.json')
        else:
            atomic_json(inputs/'freight-completion-policy.json',timing_document)
        if experiment_selection.get('observation_policy')=='fixed-day-24h-v1':
            from simz1_day_observation import policy_document as day_policy
            atomic_json(inputs/'day-observation-policy.json',day_policy())
    if composition is not None:
        report['demand_composition'] = composition
        atomic_json(inputs/'demand-composition.json', composition)
    if balanced_od:
        from simz1_balanced_od_audit import check_config, check_effective_network
        effective_options = parameters(run_dir/'config-simz1.xml')
        check_config(effective_options,iterations=experiment_selection['iterations'] if experiment_selection else 1,
                     origin_admission_policy=selected_origin_admission)
        check_effective_network(spatial_model, Path(effective_options['network.inputNetworkFile']),
                                Path(effective_options['network.laneDefinitionsFile']))
        audit = report['balanced_od_audit']
        audit['buses_additional'] = dict(total=269, transmetro=176, tubus=93)
        audit['catalog_sha256'] = sha256(inputs/'agent-catalog.json')
        audit['od_hypothesis'] = report['spatial_demand']['hypothesis']
        audit['preserved_services'] = dict(freight=report.get('freight_transport'), transit=report.get('weekday_transit'))
        from simz1_run import xml_elements, seconds
        from simz1_freight import is_freight
        freight_hours, transit_hours = Counter(), Counter()
        for person in xml_elements(run_dir/'plans.xml', 'person', 'population'):
            if is_freight(person):
                for trip in json.loads(person.findtext("attributes/attribute[@name='simz1Trips']")):
                    freight_hours[f"{int(trip['planned_departure']//3600):02}:00"] += 1
        from simz1_gateway_od import _xml
        schedule_path = Path(effective_options['transit.transitScheduleFile'])
        if not schedule_path.is_absolute():
            schedule_path = run_dir/schedule_path
        for departure in _xml(schedule_path).findall('.//departures/departure'):
            transit_hours[f"{int(seconds(departure.get('departureTime'))//3600):02}:00"] += 1
        audit['scheduled_departures_by_hour'] = {
            f'{hour:02}:00': dict(private=audit['private_departures_by_hour'][f'{hour:02}:00'],
                                freight=freight_hours[f'{hour:02}:00'],
                                transit_expeditions=transit_hours[f'{hour:02}:00']) for hour in range(24)}
        audit['transit_hourly_unit'] = 'scheduled expeditions, not additional vehicles; fixed fleet=269'
        from simz1_balanced_od_audit import implementation_signature
        atomic_json(inputs/'od-implementation.json', implementation_signature())
        atomic_json(inputs/'balanced-od-audit.json', audit)
    coordination = dict(enabled=False, policy='none')
    if short_link_signal_coordination in ('derive', 'derive-activity-v2'):
        if not preflight['whole_vehicle_reservation']:
            raise ValueError('La coordinacion de enlaces cortos requiere reserva del vehiculo completo')
        from simz1_signal_coordination import coordinate
        effective_config = ET.parse(run_dir/'config-simz1.xml').getroot()
        control = effective_config.find("module[@name='signalsystems']/param[@name='signalcontrol']")
        if control is not None:
            control = Path(control.get('value'))
            if not control.is_absolute(): control = run_dir/control
            shutil.copyfile(control, inputs/'signal-control-before-coordination.xml')
        coordination = coordinate(effective_config, run_dir, write=True,
                                  activity_origins=short_link_signal_coordination == 'derive-activity-v2')
        atomic_json(inputs/'signal-coordination.json', coordination)
        coordination = dict(coordination, artifact=dict(path='inputs/signal-coordination.json',
                            sha256=sha256(inputs/'signal-coordination.json')))
        if freight and freight.get('service_version') in ('weekday-v2', 'weekday-compact-v3'):
            from simz1_freight import refresh_through_validation
            refresh_through_validation(run_dir)
    report['short_link_signal_coordination'] = coordination
    report.update(run_dir=str(run_dir), xml_verified_counts=actual, matsim_seed=param('global','randomSeed').get('value'),
                  network_sha256=sha256(network), plans_sha256=sha256(run_dir/'plans.xml'),
                  vehicles_sha256=sha256(generated_vehicles))
    duplicates = duplicate_population_check(run_dir, [SCENARIO/name for name in MODES]+[run_dir.parent],
                                           report['plans_sha256'])
    report.update(seed_selection=seed_selection, massive_authorized=massive, duplicate_population_check=duplicates)
    for previous in duplicates['matches']:
        print(f"AVISO: hash de plans.xml identico a {previous['run_id']} (semilla {previous['demand_seed']}); "
              'se conserva la poblacion, sin cambiar semilla ni volver a sortear N.', flush=True)
    if duplicates['unverifiable_manifests']:
        print('AVISO: comprobacion de poblaciones repetidas incompleta; consulte duplicate_population_check. '
              'No se afirma unicidad fuera de las carpetas verificadas.', flush=True)
    report['signal_offsets'] = offset_report
    report['signal_variant'] = signal_variant
    (run_dir/'montecarlo-report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    overrides = config_changes(original_parameters, parameters(run_dir/'config-simz1.xml'),
                               f'{mode} generation / explicit CLI options / isolated inputs')
    for change in overrides:
        if change['parameter'] == 'travelTimeCalculator.separateModes' and change['before'] is None:
            change['reason'] = ('Derived missing default: MATSim 15 link-to-link times require separateModes=false; '
                                'native signals used to supply it implicitly, including when comparing signals off')
    if lanes == 'false' and signal_input is not None:
        overrides.append(dict(parameter='signalsystems.lane_references', before='source XML',
                              after='removed', reason='qsim.useLanes=false'))
    manifest = create_manifest(run_dir, seed, overrides, publish=False,
                               allow_empty=composition is not None and composition['total_non_public_vehicles'] == 0)
    manifest['freight_transport'] = freight or dict(enabled=False, explicitly_disabled=no_freight_transport)
    if signal_variant:
        manifest['signal_variant'] = dict(signal_variant, artifact=dict(path='inputs/local-signal-variant.json',sha256=sha256(inputs/'local-signal-variant.json')))
        manifest['inputs']['local_signal_variant'] = manifest['signal_variant']['artifact']
        manifest['configuration_overrides'].append(dict(parameter='signalsystems.synthetic_local_offsets',
            before=signal_variant['original_offsets'],after=signal_variant['effective_offsets'],
            reason='Explicit l18-local-synthetic-offsets-v1 scenario assumption; not observed signal timing'))
    if freight:
        manifest['counts'].update(freight_vehicles_configured=freight['vehicles_configured'],
                                  freight_departures_scheduled=freight['departures_scheduled'])
    if composition is not None:
        manifest['demand_composition'] = composition
        manifest['counts'].update(non_public_vehicles_configured=composition['total_non_public_vehicles'],
            private_vehicles_configured=composition['private_vehicles'],
            freight_vehicles_configured=composition['freight_vehicles'],
            freight_departures_scheduled=composition['freight_vehicles'],
            all_vehicles_configured=composition['total_non_public_vehicles'] +
                manifest['counts']['public_transport_vehicles_configured'])
    manifest['directory_selection'] = dict(
        mode='automatic' if automatic_directory else 'explicit',
        strategy='uuid4+exclusive_mkdir' if automatic_directory else 'explicit+exclusive_mkdir')
    manifest['demand_mode'] = mode
    manifest['destination_policy'] = destination_policy
    if catalog is not None:
        manifest['agent_configuration'] = dict(report['agent_configuration'],
            realized_person_counts=report['agent_type_counts'], allocation_method=report['allocation_method'],
            catalog_artifact=dict(path='inputs/agent-catalog.json', sha256=sha256(inputs/'agent-catalog.json')),
            person_type_artifact=dict(path='inputs/agent-types.jsonl', sha256=sha256(inputs/'agent-types.jsonl')),
            effective_vehicle_types_source='inputs/vehicles.xml; output vehicles must be validated after QSim')
        if catalog['schema_version'] == 'simz1-road-profiles-v1':
            manifest['scenario_version'] = catalog['scenario_version']
    manifest['signal_offsets'] = offset_report
    manifest['short_link_signal_coordination'] = coordination
    if coordination.get('changes'):
        manifest['configuration_overrides'].append(dict(parameter='signalsystems.signalcontrol.short_body_passage_offsets',
            before={row['system_id']:row['before'] for row in coordination['changes']},
            after={row['system_id']:row['after'] for row in coordination['changes']},
            reason='Explicit synthetic short-link signal coordination; phase durations and native signal enforcement preserved'))
    if offset_report is not None and signal_offset_policy != 'preserve':
        manifest['configuration_overrides'].append(dict(parameter='signalsystems.signalcontrol.offsets',
            before={p['system_id']:p['before'] for p in offset_report['plans']},
            after={p['system_id']:p['after'] for p in offset_report['plans']},
            reason=f'Explicit synthetic {signal_offset_policy} policy; seed={offset_seed}'))
    manifest['configuration_validation'] = preflight
    manifest['admission_policy_selection'] = dict(
        policy=preflight['admission_policy'],
        source='--storage-policy' if storage_policy is not None else
               'source XML' if 'simz1Admission.storagePolicy' in original_parameters else 'future-run default',
        source_policy=original_parameters.get('simz1Admission.storagePolicy'))
    if experiment_selection and experiment_selection.get('origin_admission_policy'):
        manifest['origin_admission_policy'] = dict(experiment_selection['origin_admission_policy'],
            effective_policy=preflight['origin_admission_policy'],
            source='explicit versioned experiment',
            source_policy=original_parameters.get('simz1Admission.originPolicy', 'empty-slot-origin-v1'),
            artifact=dict(path='inputs/origin-admission-policy.json',
                          sha256=sha256(inputs/'origin-admission-policy.json')))
    manifest['lane_configuration_validation'] = lane_audit
    if turn_policy_source is not None:
        manifest['source_lane_configuration_validation'] = source_lane_audit
        manifest['inputs']['osm_turn_policy_source'] = dict(
            path=turn_policy_source.relative_to(run_dir).as_posix(), sha256=sha256(turn_policy_source))
    manifest['population_generation'] = dict(selection=spec, verified=actual, corridor_policy=report['corridor_policy'],
                                             rng_compatibility=report.get('rng_compatibility', 'fixed debug, seed ignored'),
                                             seed_selection=seed_selection, massive_authorized=massive,
                                             duplicate_population_check=duplicates)
    if spatial_model is not None:
        manifest['spatial_demand'] = report['spatial_demand']
        manifest['inputs']['zone_boundary'] = boundary_artifact
        manifest['inputs']['od_source_osm'] = dict(path='inputs/od-source.osm', sha256=osm_source_sha256)
        if balanced_od:
            manifest['scenario_base_version'] = manifest.get('scenario_version')
            manifest['scenario_version'] = BALANCED_OD
            manifest['origin_policy'] = ACCESS_ORIGINS
            manifest['balanced_od'] = dict(variant=BALANCED_OD, state='prepared_not_simulated',
                source_network=manifest['inputs']['input:'+source_snapshots['network','inputNetworkFile']],
                source_lanes=manifest['inputs']['input:'+source_snapshots['network','laneDefinitionsFile']],
                access_catalog=manifest['inputs']['input:od-access-catalog.json'],
                effective_access_review=manifest['inputs']['input:effective-access-review.json'],
                audit=manifest['inputs']['input:balanced-od-audit.json'],
                implementation=manifest['inputs']['input:od-implementation.json'])
    if temporal is not None:
        manifest['temporal_demand'] = temporal
        manifest['demand_window'] = temporal['demand_window']
        manifest['replay_window'] = dict(manifest['time_horizon'])
        manifest['generated_departures_by_hour'] = report['departures_by_hour']
        manifest['inputs']['demand_report'] = dict(path='montecarlo-report.json', sha256=sha256(run_dir/'montecarlo-report.json'))
    if policy:
        manifest['temporal_policy']=policy
        manifest['study_window']=dict(policy['windows']['study'])
        manifest['population_cohorts']=report['population_cohorts']
        manifest['scenario_version']=POLICY_SCENARIO_VERSION
        manifest['scenario_base_version']=catalog.get('scenario_version',catalog['schema_version'])
        manifest['inputs']['temporal_policy']=dict(path='inputs/temporal-policy.json',sha256=sha256(inputs/'temporal-policy.json'))
    if experiment_selection:
        manifest['experiment']=experiment_selection
        manifest['time_horizon']['end_seconds']=experiment_selection['observation_end_seconds']
        manifest['freight_completion_policy']=experiment_selection['freight_completion_policy']
        manifest['experiment']['initial_population_sha256']=sha256(run_dir/'plans.xml')
        manifest['experiment']['population_identity_basis']='initial plans bytes; iteration count does not enter demand RNG or population serialization'
    if balanced_od:
        from simz1_balanced_od_audit import validate_manifest as validate_balanced
        validate_balanced(run_dir, manifest)
    atomic_json(run_dir/MANIFEST, manifest)
    if composition is not None:
        print(f"N no publico={composition['total_non_public_vehicles']} | familias={composition['family_counts']} | buses adicionales={manifest['counts']['public_transport_vehicles_configured']}", flush=True)
    print(f"Demanda preparada: {manifest['run_id']} | semilla={seed} | {actual['persons']} personas, "
          f"{actual['trips']} viajes, {actual['vehicles']} vehiculos definidos en XML", flush=True)
    return dict(report, run_id=manifest['run_id'])


def add_generation_options(parser):
    parser.add_argument('--experiment-spec',type=Path)
    parser.add_argument('--experiment-scenario')
    parser.add_argument('--short-link-signal-coordination', choices=['none', 'derive', 'derive-activity-v2'], default='none',
                        help='Explicit synthetic offsets for short whole-body passages; only the new run snapshot changes')
    parser.add_argument('--freight-service', type=Path)
    parser.add_argument('--freight-service-date')
    parser.add_argument('--freight-vehicles', type=int)
    parser.add_argument('--no-freight-transport', action='store_true')
    parser.add_argument('--temporal-policy',type=Path,help='Versioned continuous weekday intensity and absolute observation windows')
    parser.add_argument('--temporal-seed',type=int,help='Independent temporal seed override recorded in the effective policy')
    parser.add_argument('--transit-service', type=Path, help='Explicit weekday fixed fleet policy; B is separate from N')
    parser.add_argument('--transit-service-date', help='Explicit Monday-Friday scenario date (YYYY-MM-DD)')
    parser.add_argument('--accept-transit-route-assumptions', action='store_true', help='Acknowledge the dated GIS/OSM mapping conflicts and exterior-time assumptions in service.json')
    parser.add_argument('--destination-policy', choices=['legacy-gaussian-v1','lane-length-destinations-v1'], default='legacy-gaussian-v1')
    parser.add_argument('--origin-policy', choices=['legacy-corridors','uniform-nodes-v1',ACCESS_ORIGINS], default='legacy-corridors',
                        help='Opt-in new synthetic network demand without the historical 70% named-corridor branch. Does not calibrate capacity or create external gateways.')
    parser.add_argument('--agent-catalog', type=Path,
                        help='Catalogo versionado opt-in; conserva legacy si se omite. agent-types-road-v1 separa motos y excluye PT de N; pesados requieren acceso implementado. prepare_simz1_agents.py solo asigna tipos')
    parser.add_argument('--od-mode', choices=['network', 'gateway-od', 'through-traffic', BALANCED_OD], default='network',
                        help='network conserva demanda existente; balanced-gateway-v1 exige perimetro/accesos verificados y mezcla explicita')
    parser.add_argument('--zone-boundary', type=Path,
                        help='GeoJSON RFC 7946 verificado de Zona 1; obligatorio en las variantes OD espaciales; '
                             'el bbox OSM y el perimetro vial no son limites administrativos')
    parser.add_argument('--od-shares', help='4 pesos sinteticos: exterior-exterior, exterior-interior, interior-exterior, interior-interior; predeterminado 1,0,0,0')
    parser.add_argument('--od-mix', help='JSON con las cuatro clases: balanced-gateway-v1 exige porcentajes que sumen exactamente 100; legacy admite pesos')
    parser.add_argument('--od-hourly-profiles', type=Path, help='JSON {source: synthetic, profiles: {CLASE: [24 pesos]}}; se intersecta con horarios de categorias')
    parser.add_argument('--od-osm', type=Path, help='OSM fuente auditado; obligatorio con gateway-od, rechaza restricciones aun no importadas')
    parser.add_argument('--od-access-catalog', type=Path, help='Verified versioned private access evidence; required only by balanced-gateway-v1')
    parser.add_argument('--unsignalized-priority', action=argparse.BooleanOptionalAction, default=None,
                        help='Parada y cesion nativas en cruces elegibles; conserva el XML si se omite')
    parser.add_argument('--priority-stop-seconds', type=float, help='Parada minima desde cabecera; predeterminado 5 s')
    parser.add_argument('--priority-max-yield-seconds', type=float,
                        help='Espera tras Alto antes de reservar un cruce seguro; predeterminado 30 s')
    parser.add_argument('--priority-classification', choices=['osm-hierarchy','osm-name-orientation','orientation','explicit'])
    parser.add_argument('--priority-conflicts', choices=['geometric','conservative','verified-node-table'],
                        help='geometric distingue movimientos disjuntos; geometria ambigua conserva el conflicto')
    parser.add_argument('--signal-offset-policy', choices=['preserve','zero','hash'], default='preserve',
                        help='Conserva XML por defecto; hash genera desfases sinteticos persistentes por sistema')
    parser.add_argument('--signal-offset-seed', type=int,
                        help='Semilla del hash estable; por defecto usa --seed; requiere politica hash')
    parser.add_argument('--temporal-profile', choices=['full-day','peaks'],
                        help='Predeterminado full-day; peaks reproduce el muestreo temporal anterior; debug conserva su horario')
    parser.add_argument('--hourly-weights', help='24 pesos sinteticos separados por comas, horas 00..23; se normalizan')
    parser.add_argument('--trips-per-person', type=positive_integer, default=1,
                        help='Viajes por persona; --agents siempre cuenta personas (predeterminado 1 viaje)')
    parser.add_argument('--drain-seconds', type=nonnegative_integer,
                        help='Vaciado experimental adicional despues de 86400; predeterminado 0 (jornada de 24 h)')
    parser.add_argument('--mode', choices=MODES, default='montecarlo')
    parser.add_argument('--massive', action='store_true',
                        help='Autoriza >=150000; rango por catalogo: nonpublic 180000..220000, legacy 150000..250000. '
                             'Sin este flag ni cantidad, montecarlo prepara 10 personas')
    parser.add_argument('--agents', type=nonnegative_integer, help='Cantidad fija; catalogo nonpublic incluye carga y permite cero; legacy cuenta particulares')
    parser.add_argument('--min-agents', type=nonnegative_integer, help='Limite inferior inclusivo; requiere --max-agents')
    parser.add_argument('--max-agents', type=nonnegative_integer, help='Limite superior inclusivo; requiere --min-agents')
    parser.add_argument('--corridor-policy', choices=['redistribute', 'fail'],
                        help='Obligatorio con --od-mode network en historical/montecarlo; incompatible con gateway-od')
    parser.add_argument('--matsim-seed', type=int)
    parser.add_argument('--use-lanes', action=argparse.BooleanOptionalAction, default=None,
                        help='Conserva la opcion del XML si se omite')
    parser.add_argument('--within-day-routing', action=argparse.BooleanOptionalAction, default=None,
                        help='Conserva el reruteo del XML si se omite')
    parser.add_argument('--signals', action=argparse.BooleanOptionalAction, default=None,
                        help='Conserva las senales nativas del XML si se omite; no exige carriles')
    parser.add_argument('--incidents', action=argparse.BooleanOptionalAction, default=None,
                        help='Conserva incidentes del XML si se omite (predeterminado true)')
    parser.add_argument('--qsim-threads', type=positive_integer,
                        help='Hilos de QSim; conserva el XML si se omite')
    parser.add_argument('--whole-vehicle-reservation', action=argparse.BooleanOptionalAction, default=None,
                        help='Reserva longitud+.10m en corredores sin cruce; requiere QSim de un hilo')
    parser.add_argument('--storage-policy', choices=['strict-receiver-v1', 'matsim15-native'],
                        help='Conserva politica explicita del XML; si falta usa strict-receiver-v1. '
                             'matsim15-native permite la comparacion historica con FORCE tras stuckTime')
    parser.add_argument('--routing-share', type=float)
    parser.add_argument('--reroute-budget', type=positive_integer,
                        help='Maximo determinista de calculos por paso; omitir conserva el XML o el valor Java predeterminado')


def generation_options(args):
    return {key: getattr(args, key) for key in
            ('mode', 'agents', 'min_agents', 'max_agents', 'corridor_policy', 'matsim_seed', 'use_lanes', 'within_day_routing', 'routing_share', 'reroute_budget', 'signals', 'incidents', 'qsim_threads', 'storage_policy', 'whole_vehicle_reservation',
             'temporal_profile', 'hourly_weights', 'trips_per_person', 'drain_seconds', 'temporal_policy', 'temporal_seed',
             'signal_offset_policy', 'signal_offset_seed', 'short_link_signal_coordination', 'unsignalized_priority', 'priority_stop_seconds',
             'priority_classification', 'priority_conflicts', 'priority_max_yield_seconds',
             'od_mode', 'zone_boundary', 'od_shares', 'massive', 'agent_catalog', 'od_mix', 'od_hourly_profiles', 'od_osm', 'od_access_catalog', 'origin_policy', 'destination_policy', 'transit_service', 'transit_service_date', 'accept_transit_route_assumptions',
             'freight_service', 'freight_service_date', 'freight_vehicles', 'no_freight_transport', 'experiment_spec', 'experiment_scenario')}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,default=SCENARIO/'config-simz1.xml')
    parser.add_argument('--seed',type=int,default=None)
    parser.add_argument('--run-dir',type=Path,
                        help='Carpeta nueva explicita (error si existe); si se omite crea una carpeta unica con UUID')
    parser.add_argument('--run-matsim',action='store_true',help='Ejecutar MATSim despues de generar; conserva las iteraciones del XML. Para limitarlas use ejecutar_simz1.py --iterations')
    add_generation_options(parser)
    args=parser.parse_args()
    if args.od_mode == BALANCED_OD and args.run_matsim:
        parser.error('balanced-gateway-v1 only prepares explicit inputs in this phase; automatic MATSim execution is not enabled')
    try:
        report=generar(args.config,args.run_dir,args.seed, **generation_options(args))
    except (OSError,ValueError,ET.ParseError) as exc:
        parser.exit(1,f'No se pudo generar: {exc}\n')
    print(json.dumps(report,indent=2))
    directory=Path(report['run_dir'])
    print(f'Configuracion lista: {directory / "config-simz1.xml"}')
    if args.run_matsim:
        from ejecutar_simz1 import ejecutar
        try:
            state = ejecutar(directory)
            if state['analysis']['status'] == 'analysis_failed':
                parser.exit(2, 'analysis_failed: MATSim conserva completed/valid; reintente generar_graficas_z1.py.\n')
        except (OSError, ValueError, RuntimeError) as exc:
            parser.exit(1, f'No se pudo ejecutar MATSim: {exc}\n')



if __name__=='__main__':main()
