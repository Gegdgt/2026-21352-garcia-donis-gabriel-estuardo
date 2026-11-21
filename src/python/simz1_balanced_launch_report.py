"""Read-only live observations and post-run hourly evidence for balanced OD.

Live output is provisional, never an approval. Final reports require the exact
completed/valid run, pinned complete events, and the existing OD/freight audits.
No generation, simulation, source edit, or manifest promotion is performed.
"""
import argparse
from collections import Counter
from contextlib import ExitStack
import csv
import gzip
import json
import math
from pathlib import Path
import sys
import time
import xml.etree.ElementTree as ET
import zlib

from simz1_run import checked_path, load_manifest, xml_elements, atomic_json, sha256, select_run
from simz1_balanced_od_audit import validate_manifest, PrivateODAudit, require_native_success
from simz1_balanced_od import VARIANT
from simz1_balanced_launch import manifest_identity

def postprocessor_signature():
    folder=Path(__file__).resolve().parent
    return {name:sha256(folder/name) for name in ('simz1_balanced_launch_report.py','simz1_balanced_od_audit.py',
        'simz1_freight.py','simz1_freight_completion.py','simz1_freight_gateways.py','simz1_day_observation.py',
        'simz1_result_quality.py','simz1_run.py')}

class Observation:
    def __init__(self, model, records, freight_ids=(), bus_ids=(), groups=None, scheduled=None):
        self.od = PrivateODAudit(model, records)
        self.private = set(records)
        self.freight = set(freight_ids)
        self.buses = set(bus_ids)
        self.road = set(records) | self.freight
        self.active, self.inserted, self.waiting = set(), set(), set()
        self.initial, self.drivers = {}, {}
        self.counts, self.minute_counts, self.hour_counts = Counter(), Counter(), Counter()
        self.minute, self.hour, self.now = 0, 0, 0.
        self.minutes, self.hours = [], []
        self.gateway_exits = Counter()
        self.groups=groups or {k:dict(family='private',profile='unknown') for k in records}
        self.scheduled=scheduled or {k:r['planned_departure'] for k,r in records.items()}
        self.departed,self.completed,self.aborted=set(),set(),set()
        self.departure_times,self.entry_times,self.arrival_times={},{},{}

    def add(self, key, n=1):
        self.counts[key] += n
        self.minute_counts[key] += n
        self.hour_counts[key] += n

    def snapshot(self,at=None):
        at=self.now if at is None else at
        future=sum(t>at for ident,t in self.scheduled.items() if ident not in self.departed and ident not in self.aborted)
        due_unobserved=len(set(self.scheduled)-self.departed-self.aborted)-future
        return dict(active=len(self.active), private_active=len(self.active & self.private),
            freight_active=len(self.active & self.freight), buses_active=len(self.active & self.buses),
            waiting_to_incorporate=len(self.waiting), incorporated_unique=len(self.inserted),
            private_never_incorporated=len(self.od.records)-len(self.od.inserted),
            future_scheduled_non_public=future,due_without_departure=due_unobserved,
            completed_non_public=len(self.completed),aborted_non_public=len(self.aborted))

    def row(self, bucket, counts, complete,at=None):
        base = dict.fromkeys(('entries','road_departures','arrivals','transitions','storage_wait_attempts',
                             'freight_arrivals','freight_turn_restriction_attempts','interior_arrivals'),0)
        base.update(counts)
        return dict(bucket=bucket, complete_interval=complete, **base, **self.snapshot(at))

    def consume(self, event):
        at = float(event['time'])
        if not math.isfinite(at) or at < self.now:
            raise ValueError('Non-monotone native events; no hourly evidence can be accepted')
        while at >= (self.minute+1)*60:
            self.minutes.append(self.row(self.minute, self.minute_counts, True,at=(self.minute+1)*60))
            self.minute += 1; self.minute_counts.clear()
        while at >= (self.hour+1)*3600:
            self.hours.append(self.row(self.hour, self.hour_counts, True,at=(self.hour+1)*3600))
            self.hour += 1; self.hour_counts.clear()
        self.now = at
        kind, vehicle, person = event.get('type'), event.get('vehicle'), event.get('person')
        if kind == 'TransitDriverStarts':
            self.drivers[event['driverId']] = event['vehicleId']
        ident = vehicle or self.drivers.get(person, person)
        # The existing audit is the only authority for private exterior clearance.
        self.od.consume(event)
        if kind == 'departure' and person in self.road:
            self.waiting.add(person); self.add('road_departures')
            self.departed.add(person);self.departure_times[person]=at
        elif kind == 'vehicle enters traffic':
            if vehicle in self.active:
                raise ValueError('Duplicate native traffic entry: '+str(vehicle))
            self.active.add(vehicle); self.inserted.add(vehicle); self.waiting.discard(vehicle)
            self.initial[vehicle] = event.get('link'); self.add('entries')
            if vehicle in self.road:self.entry_times[vehicle]=at
            if vehicle in self.buses:self.add('bus_expedition_entries')
        elif kind == 'entered link' and vehicle in self.active:
            if self.initial.pop(vehicle, None) != event.get('link'):
                self.add('transitions')
        elif kind == 'left link':
            self.initial.pop(vehicle, None)
        elif kind == 'vehicle leaves traffic':
            if vehicle not in self.active:
                raise ValueError('Native exit without entry: '+str(vehicle))
            self.active.remove(vehicle); self.initial.pop(vehicle, None)
        elif kind == 'arrival':
            if ident in self.road or ident in self.buses:
                self.add('arrivals')
                self.waiting.discard(ident)
            if ident in self.freight:
                self.add('freight_arrivals')
            if ident in self.buses:self.add('bus_expedition_arrivals')
            if ident in self.road:
                self.completed.add(ident);self.arrival_times[ident]=at
            if ident in self.od.completed:
                gateway = self.od.records[ident]['destination_gateway']
                if gateway:
                    self.gateway_exits[gateway] += 1
                    self.add('verified_exit:'+gateway)
                else:
                    self.add('interior_arrivals')
        elif kind in ('stuckAndAbort','vehicle aborts'):
            self.active.discard(ident); self.waiting.discard(ident); self.initial.pop(ident, None)
            if ident in self.road:self.aborted.add(ident)
        elif kind == 'simz1NativeDecision':
            if event.get('reason') == 'storage_wait':
                self.add('storage_wait_attempts')
            if ident in self.freight and event.get('reason') == 'turn_restriction':
                self.add('freight_turn_restriction_attempts')

    def view(self):
        return dict(simulated_seconds=self.now, simulated_hour=f'{int(self.now)//3600:02}:{int(self.now)%3600//60:02}',
            cumulative=dict(self.counts), **self.snapshot(),
            last_complete_minute=self.minutes[-1] if self.minutes else None,
            current_partial_minute=self.row(self.minute,self.minute_counts,False),
            last_complete_hour=self.hours[-1] if self.hours else None,
            current_partial_hour=self.row(self.hour,self.hour_counts,False),
            verified_exits_by_gateway=dict(self.gateway_exits))


def context(run, manifest):
    contract = validate_manifest(run, manifest,postprocessing=manifest.get('status')=='completed')
    if contract is None:
        raise ValueError('Se requiere balanced-gateway-v1; no se etiqueta network como OD balanceado')
    from simz1_freight import verified_contract
    cargo = verified_contract(run, manifest)
    bus_file = checked_path(run, manifest['inputs']['transit_vehicles'])
    buses = {v.get('id') for v in ET.parse(bus_file).getroot().findall('{*}vehicle')}
    groups={};scheduled={k:r['planned_departure'] for k,r in contract[1].items()}
    ledger=checked_path(run,manifest['agent_configuration']['person_type_artifact'])
    with ledger.open(encoding='utf-8') as stream:
        for line in stream:
            row=json.loads(line);groups[row['person_id']]=dict(family=row['family'],profile=row['driving_profile'],agent_type=row['agent_type'])
    for ident,row in cargo.items():
        groups[ident]=dict(family='freight',profile='freight',agent_type='TransportePesado');scheduled[ident]=row['departure_seconds']
    return Observation(*contract, freight_ids=cargo, bus_ids=buses,groups=groups,scheduled=scheduled), cargo


def write_csv(path, rows):
    fields = sorted({key for row in rows for key in row})
    with path.open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader(); writer.writerows(rows)


# SimZ1DayObservation's fixed-day-v1 census has one shared schema, but native
# bus templates omit the person-only profile/od keys. Keep all columns before
# streaming the first row; unknown future fields still fail DictWriter's check.
FIXED_DAY_CSV_FIELDS = tuple(sorted((
    'trip_id', 'vehicle_id', 'family', 'scheduled_departure', 'profile', 'od',
    'departure', 'traffic_entry', 'traffic_exit', 'arrival', 'abort_before_cleanup',
    'last_transition', 'last_link', 'cut_seconds', 'complete_duration_seconds',
    'observed_traffic_end_seconds', 'observed_traffic_end_basis', 'observed_traffic_seconds',
    'request_age_seconds', 'incorporation_delay_seconds', 'status', 'pending_class',
    'run_id', 'iteration', 'policy', 'cleanup_abort_events')))


def fixed_day_rows(run,manifest,iteration):
    """Reuse the independently validated native census; no second XML scan."""
    from simz1_day_observation import POLICY, classify
    result=manifest['results'][str(iteration)];day=result.get('day_observation') or {}
    if (day.get('policy')!=POLICY or day.get('coverage_end_seconds')!=86400 or
            day.get('technical_integrity')!='verified_precleanup_census'):
        raise ValueError('Missing verified fixed-day census')
    path=checked_path(run,day['census']);counts=Counter();pending=Counter();seen=set()
    with gzip.open(path,'rt',encoding='utf-8') as stream:
        for line in stream:
            row=json.loads(line);ident=row['trip_id']
            if (ident in seen or row['run_id']!=manifest['run_id'] or row['iteration']!=iteration or
                    row['policy']!=POLICY or row['cut_seconds']!=86400):
                raise ValueError('Census identity/cut mismatch')
            seen.add(ident);classified=classify(row)
            for key in ('status','pending_class','complete_duration_seconds','request_age_seconds','incorporation_delay_seconds',
                    'observed_traffic_seconds','observed_traffic_end_seconds','observed_traffic_end_basis'):
                if row.get(key)!=classified[key]:raise ValueError('Census classification differs: '+ident+'/'+key)
            counts[row['status']]+=1
            if row.get('pending_class'):pending[row['pending_class']]+=1
            yield row
    if len(seen)!=day['scheduled_trips'] or dict(counts)!=day['counts'] or dict(pending)!=day['pending_classifications']:
        raise ValueError('Census totals differ from native acceptance')


def fixed_day_tables(rows,configured_buses):
    """Small derived tables, using event timestamps and pre-cleanup membership.

    The final hour includes physical events exactly at T; other hours are
    half-open. Counts of transitions/WAIT cannot be reconstructed from a census.
    """
    hours=[dict(hour=h,scheduled_requests=0,departures=0,incorporations=0,real_arrivals=0,
        prior_aborts=0,active_non_public=0,waiting_non_public=0,active_bus_expeditions=0) for h in range(24)]
    bus_active=[set() for _ in range(24)];profiles={};counts=Counter();pending=Counter()
    groups={};duration_groups={};last_transition_by_group={};bus_ids=set()
    for row in rows:
        family=row['family'];profile=row.get('profile') or ('bus' if family=='bus' else 'freight' if family=='pesado' else 'unknown')
        group=profiles.setdefault((family,profile),Counter());group['scheduled_requests']+=1;group[row['status']]+=1
        group['incorporations']+=row['traffic_entry'] is not None;group['real_arrivals']+=row['arrival'] is not None
        counts[row['status']]+=1
        if row.get('pending_class'):group[row['pending_class']]+=1;pending[row['pending_class']]+=1
        od=row.get('od');od=json.loads(od) if isinstance(od,str) else od
        od_type=next(iter(od.values())).get('od_class','unknown') if od else 'service'
        key=(family,od_type,int(row['scheduled_departure']//3600));g=groups.setdefault(key,Counter())
        g['scheduled_requests']+=1;g[row['status']]+=1;g['incorporations']+=row['traffic_entry'] is not None;g['real_arrivals']+=row['arrival'] is not None
        if row.get('pending_class'):g[row['pending_class']]+=1
        durations=duration_groups.setdefault(key,{})
        for field in ('observed_traffic_seconds','request_age_seconds','incorporation_delay_seconds','complete_duration_seconds'):
            values=durations.setdefault(field,dict(observed_count=0,sum_seconds=None,max_seconds=None))
            if row.get(field) is not None:
                values['observed_count']+=1
                values['sum_seconds']=(values['sum_seconds'] or 0)+row[field]
                values['max_seconds']=row[field] if values['max_seconds'] is None else max(values['max_seconds'],row[field])
        if row.get('last_transition') is not None:last_transition_by_group[key]=max(last_transition_by_group.get(key,-math.inf),row['last_transition'])
        for field,target in (('scheduled_departure','scheduled_requests'),('departure','departures'),('traffic_entry','incorporations'),('arrival','real_arrivals'),('abort_before_cleanup','prior_aborts')):
            value=row.get(field)
            if value is not None:
                if not 0<=value<=86400:raise ValueError('Census timestamp outside fixed day: '+field)
                hours[min(23,int(value//3600))][target]+=1
        if family=='bus':bus_ids.add(row['vehicle_id'])
        for h in range(24):
            end=(h+1)*3600;entry=row['traffic_entry'];departure=row['departure'];exit_time=row['traffic_exit'];abort=row['abort_before_cleanup']
            if abort is not None and abort<=end:continue
            if entry is not None and entry<=end and (exit_time is None or exit_time>end):
                if family=='bus':bus_active[h].add(row['vehicle_id']);hours[h]['active_bus_expeditions']+=1
                else:hours[h]['active_non_public']+=1
            elif family!='bus' and departure is not None and departure<=end and (entry is None or entry>end):
                hours[h]['waiting_non_public']+=1
    if len(bus_ids)>configured_buses:raise ValueError('Census uses more public vehicles than configured')
    for h,row in enumerate(hours):
        row.update(active_public_vehicles=len(bus_active[h]),inactive_configured_public_vehicles=configured_buses-len(bus_active[h]))
    group_rows=[dict(family=f,od=o,scheduled_hour=h,last_transition_seconds=last_transition_by_group.get((f,o,h)),**dict(v)) for (f,o,h),v in sorted(groups.items())]
    return dict(hours=hours,counts=dict(counts),pending=dict(pending),groups=group_rows,
        durations=[dict(family=f,od=o,scheduled_hour=h,**{field+'_'+metric:value for field,summary in measures.items()
            for metric,value in summary.items()}) for (f,o,h),measures in sorted(duration_groups.items())],
        profiles=[dict(family=f,profile=p,**dict(c)) for (f,p),c in sorted(profiles.items())])


def report_fixed_day(run,manifest,iteration,manifest_hash,directory):
    """Official fixed-day products retain raw denominators and censoring."""
    result=manifest['results'][str(iteration)];day=result['day_observation']
    directory.mkdir(parents=True,exist_ok=True)
    def flatten(row):return {k:json.dumps(v,sort_keys=True) if isinstance(v,(list,dict)) else v for k,v in row.items()}
    with ExitStack() as stack:
        streams=[stack.enter_context((directory/name).open('w',encoding='utf-8',newline='')) for name in
            ('day-lifecycle.csv','nonpublic-lifecycle.csv','bus-expeditions.csv')]
        writers=[csv.DictWriter(s,fieldnames=FIXED_DAY_CSV_FIELDS) for s in streams]
        for writer in writers:writer.writeheader()
        def export_rows():
            for row in fixed_day_rows(run,manifest,iteration):
                flat=flatten(row);writers[0].writerow(flat);writers[2 if row['family']=='bus' else 1].writerow(flat)
                yield row
        tables=fixed_day_tables(export_rows(),manifest['counts']['public_transport_vehicles_configured'])
    declared=[{k:v for k,v in r.items() if k!='last_transition_seconds'} for r in tables['groups']]
    if declared!=day['groups']:raise ValueError('Derived family/OD/hour groups differ from accepted census')
    write_csv(directory/'hours-00-24.csv',tables['hours'])
    write_csv(directory/'day-groups.csv',tables['groups'])
    write_csv(directory/'day-duration-groups.csv',tables['durations'])
    write_csv(directory/'completeness-by-profile.csv',tables['profiles'])
    freight=result['freight_transport_events']
    write_csv(directory/'freight-completion.csv',[flatten(r) for r in freight.get('completion_records',[])])
    write_csv(directory/'freight-restrictions.csv',freight.get('violations',[]))
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    figure,axes=plt.subplots(2,1,figsize=(12,8),sharex=True)
    for key in ('scheduled_requests','incorporations','real_arrivals'):axes[0].plot(range(24),[r[key] for r in tables['hours']],label=key)
    for key in ('active_non_public','waiting_non_public','active_public_vehicles'):axes[1].plot(range(24),[r[key] for r in tables['hours']],label=key)
    axes[0].set_ylabel('Trips / hour');axes[1].set_ylabel('Vehicles at hour end');axes[1].set_xlabel('Simulated hour; final interval includes T=86400')
    for ax in axes:ax.grid(alpha=.2);ax.legend()
    quality_path=directory.parent/'graficas_perfiles/calidad_resultados.json'
    quality=json.loads(quality_path.read_text(encoding='utf-8')) if quality_path.is_file() else {}
    if quality and (quality.get('run_id')!=manifest['run_id'] or quality.get('iteration')!=iteration):
        raise ValueError('Screening belongs to another run/iteration')
    needs_review=(day.get('pending_classifications',{}).get('prolonged_traffic_review_required') or
        day.get('counts',{}).get('exited_without_arrival'))
    warning=quality.get('status') or ('review_required' if needs_review else 'screening_not_evaluated')
    figure.suptitle(f"{manifest['run_id']} / iteration {iteration} / fixed day / {warning}")
    figure.tight_layout();figure.savefig(directory/'demand-day.png',dpi=150);plt.close(figure)
    if sha256(run/'run-manifest.json')!=manifest_hash:raise ValueError('Manifest changed during census reporting')
    value=dict(schema_version='simz1-balanced-launch-report-v2',run_id=manifest['run_id'],iteration=iteration,
        status='verified_observations',postprocessor_version='balanced-report-fixed-day-v1',
        postprocessor_sources=postprocessor_signature(),report_source_sha256=sha256(Path(__file__)),
        manifest_sha256=manifest_hash,events=result['events'],census=day['census'],day_observation=day,
        observation_coverage_seconds=86400,day_and_followup_separate=True,followup_window=None,
        lifecycle_csv_schema=dict(version='simz1-fixed-day-lifecycle-csv-v1',fields=FIXED_DAY_CSV_FIELDS,
            optional_person_fields=['profile','od'],missing_values='empty_csv_field'),
        completion_by_profile=tables['profiles'],freight=freight,public_transport=result['public_transport_events'],
        raw_completion_rate=day['completion_rate'],scheduled_trips_denominator=day['scheduled_trips'],
        screening_warning=warning,od_identity=manifest_identity(manifest),
        screening_source=dict(path=quality_path.relative_to(run).as_posix(),sha256=sha256(quality_path)) if quality else None,
        files={name:sha256(directory/name) for name in ('day-lifecycle.csv','nonpublic-lifecycle.csv','bus-expeditions.csv',
            'hours-00-24.csv','day-groups.csv','day-duration-groups.csv','completeness-by-profile.csv','freight-completion.csv','freight-restrictions.csv','demand-day.png')},
        semantics=['Native pre-cleanup census reuses the validated artifact; XML events are not parsed again.',
            'Final interval includes real physical events exactly at T=86400; no event beyond the cut is accepted.',
            'Pending duration is an observed lower bound; arrival and complete duration remain null.',
            'Request age and incorporation delay are separate from time in traffic.',
            'Public vehicles and public expeditions are separate; inactive configured fleet is not inferred motion.',
            'WAIT attempts and transition totals are not inferred from a census.',
            'Raw completion denominator includes every scheduled trip, including old pending requests.'])
    atomic_json(directory/'report.json',value)
    print(json.dumps(dict(status=value['status'],run_id=manifest['run_id'],reports=str(directory)),ensure_ascii=False))


def report(run,iteration=0):
    run = Path(run).resolve(strict=True)
    manifest = load_manifest(run)
    if manifest.get('status') != 'completed' or manifest.get('validation',{}).get('status') != 'valid':
        raise ValueError('Reportes oficiales requieren completed/valid; para fallos use --watch o los logs')
    require_native_success(manifest)
    selection = select_run(run, iteration)  # Preserve all existing artifact/inventory checks.
    manifest = selection['manifest']
    manifest_hash = sha256(run/'run-manifest.json')
    if iteration not in manifest['iterations']['completed']:
        raise ValueError('Requested native iteration is absent')
    result = manifest['results'][str(iteration)]
    directory = run/f'analysis/it.{iteration}/balanced-launch'
    from simz1_day_observation import enabled as fixed_day
    quality_path=directory.parent/'graficas_perfiles/calidad_resultados.json'
    screening_source=dict(path=quality_path.relative_to(run).as_posix(),sha256=sha256(quality_path)) if quality_path.is_file() else None
    cached=directory/'report.json'
    if cached.is_file():
        value=json.loads(cached.read_text(encoding='utf-8'))
        if (value.get('run_id')==manifest['run_id'] and value.get('iteration')==iteration and
                value.get('manifest_sha256')==manifest_hash and value.get('events')==result['events'] and
                value.get('postprocessor_sources')==postprocessor_signature() and
                value.get('report_source_sha256')==sha256(Path(__file__)) and value.get('files') and
                (not fixed_day(manifest) or value.get('screening_source')==screening_source) and
                all(Path(name).name==name and (directory/name).is_file() and sha256(directory/name)==digest
                    for name,digest in value['files'].items())):
            print(json.dumps(dict(status='verified_existing_observations',run_id=manifest['run_id'],reports=str(directory))))
            return
    if fixed_day(manifest):return report_fixed_day(run,manifest,iteration,manifest_hash,directory)
    events = checked_path(run, result['events'])
    observation, freight_contract = context(run, manifest)
    from simz1_freight import FreightAudit
    cargo = FreightAudit(freight_contract)
    for element in xml_elements(events, 'event', 'events'):
        observation.consume(element.attrib)
        cargo.consume(element)
    actual = observation.od.finish()
    expected = dict(result['private_od_events'])
    source = expected.pop('source')
    if source != dict(run_id=manifest['run_id'],events=result['events']) or actual != expected:
        raise ValueError('Evidencia OD distinta de la aceptada en este manifiesto')
    freight = cargo.summary()
    if freight != result['freight_transport_events']:
        raise ValueError('Evidencia de carga distinta de la aceptada')
    # Detect a file edit during consumption, including a trailing truncated gzip.
    checked_path(run, result['events'])
    if sha256(run/'run-manifest.json') != manifest_hash:
        raise ValueError('El manifiesto cambio durante la lectura; no se publica el reporte')
    directory.mkdir(parents=True, exist_ok=True)
    minute_rows = observation.minutes+[observation.row(observation.minute,observation.minute_counts,False)]
    hour_rows = observation.hours+[observation.row(observation.hour,observation.hour_counts,False)]
    restricted_hours = Counter(int(v['observed_seconds']//3600) for v in freight['violations'])
    for row in hour_rows:
        row['freight_first_restricted_window_violations'] = restricted_hours[row['bucket']]
    write_csv(directory/'minutes.csv', minute_rows)
    write_csv(directory/'hours.csv', hour_rows)
    write_csv(directory/'hours-05-09.csv', [r for r in hour_rows if 5 <= r['bucket'] <= 9])
    write_csv(directory/'freight-restrictions.csv', freight['violations'])
    write_csv(directory/'hours-00-24.csv',[r for r in hour_rows if r['bucket']<24])
    write_csv(directory/'followup-24-30.csv',[r for r in hour_rows if 24<=r['bucket']<=30])
    vehicles=[]
    for ident,planned in sorted(observation.scheduled.items()):
        dep=observation.departure_times.get(ident);arrival=observation.arrival_times.get(ident)
        vehicles.append(dict(vehicle_id=ident,**observation.groups[ident],scheduled_departure=planned,
            actual_departure=dep,traffic_entry=observation.entry_times.get(ident),arrival=arrival,
            trip_seconds=arrival-dep if arrival is not None and dep is not None else None,
            status='completed' if ident in observation.completed else 'aborted_or_censored' if ident in observation.aborted else
                'active' if ident in observation.active else 'waiting_incorporation' if ident in observation.waiting else
                'future' if planned>observation.now else 'unobserved_due'))
    write_csv(directory/'nonpublic-lifecycle.csv',vehicles)
    completion=[]
    for family,profile in sorted({(r['family'],r['profile']) for r in vehicles}):
        rows=[r for r in vehicles if (r['family'],r['profile'])==(family,profile)]
        counts=Counter(r['status'] for r in rows)
        completion.append(dict(family=family,profile=profile,scheduled=len(rows),incorporated=sum(r['traffic_entry'] is not None for r in rows),**counts))
    write_csv(directory/'completeness-by-profile.csv',completion)
    timing=freight.get('completion_records',[])
    write_csv(directory/'freight-completion.csv',[{k:(json.dumps(v,sort_keys=True) if isinstance(v,(list,dict)) else v) for k,v in row.items()} for row in timing])
    route_windows=[]
    for route,close in sorted({(r['route_id'],r['window_close_seconds']) for r in timing}):
        rows=[r for r in timing if r['route_id']==route and r['window_close_seconds']==close]
        counts=Counter(r['classification'] for r in rows)
        route_windows.append(dict(route_id=route,window_close_seconds=close,deadline_seconds=close+3600,
            scheduled=len(rows),incorporated=sum(r['entry_seconds'] is not None for r in rows),
            completed=sum(r['trip_outcome']=='completed' for r in rows),aborted=sum(r['trip_outcome']=='aborted' for r in rows),
            **{k:counts[k] for k in ('nominal','tolerated','excess_tolerance','pending_not_evaluable','technical_physical_error')}))
    write_csv(directory/'freight-route-window.csv',route_windows)
    # Existing analysis directory and plotting dependency; no new viewer or run.
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plots=[]
    for filename,rows,label in [('demand-day.png',[r for r in hour_rows if r['bucket']<24],'Demand day 00-24'),
                                ('followup.png',[r for r in hour_rows if 24<=r['bucket']<=30],'Follow-up 24-30')]:
        fig,axes=plt.subplots(2,1,figsize=(12,8),sharex=True)
        for key in ('entries','arrivals'):axes[0].plot([r['bucket'] for r in rows],[r.get(key,0) for r in rows],label=key)
        for key in ('active','waiting_to_incorporate','future_scheduled_non_public'):axes[1].plot([r['bucket'] for r in rows],[r.get(key,0) for r in rows],label=key)
        axes[0].set_ylabel('Native expeditions / hour');axes[1].set_ylabel('Vehicles at interval end');axes[1].set_xlabel('Simulated hour')
        for ax in axes:ax.legend();ax.grid(alpha=.2)
        fig.suptitle(f"{manifest['run_id']} / iteration {iteration} / {label}")
        fig.tight_layout();fig.savefig(directory/filename,dpi=150);plt.close(fig);plots.append(filename)
    if timing:
        fig,ax=plt.subplots(figsize=(10,5));delays=[r['delay_seconds'] for r in timing if r['delay_seconds'] is not None]
        ax.hist(delays,bins=40);ax.axvline(3600,color='red',label='inclusive tolerance 3600 s');ax.legend()
        ax.set_xlabel('Completion delay after original window close (s)');ax.set_ylabel('Completed trucks')
        ax.set_title(f"{manifest['run_id']} / iteration {iteration}; pending excluded, reported separately")
        fig.tight_layout();fig.savefig(directory/'freight-delay.png',dpi=150);plt.close(fig);plots.append('freight-delay.png')
    value = dict(schema_version='simz1-balanced-launch-report-v1',
        run_id=manifest['run_id'], iteration=iteration, status='verified_observations',
        postprocessor_version='balanced-report-v2',freight_route_windows=route_windows,completion_by_profile=completion,
        postprocessor_sources=postprocessor_signature(),
        freight_applicability='applicable' if cargo.contract else 'not_applicable_no_freight',
        day_and_followup_separate=True,observation_coverage_seconds=observation.now,
        report_source_sha256=sha256(Path(__file__)),
        manifest_sha256=manifest_hash, events=result['events'],
        od_identity=manifest_identity(manifest), observed=observation.view(), private_od=actual,
        freight=freight, public_transport=result['public_transport_events'],
        scheduled_audit=manifest['balanced_od']['audit'],
        files={p.name:sha256(p) for p in directory.iterdir() if p.suffix in ('.csv','.png')},
        semantics=['Entries are native vehicle enters traffic, not scheduled departures.',
            'Transitions are LinkEnter transitions excluding the optional initial origin event.',
            'Storage waits are decision attempts, not seconds or unique vehicles.',
            'Active/waiting are snapshots at interval end; final bucket may be partial.',
            'Bus arrivals/entries count expeditions; distinct vehicles are separate.',
            'Exterior exits require existing private native body-clearance audit and arrival.',
            'No clock-end arrival, no door-to-door time; no global whitelist.'])
    atomic_json(directory/'report.json',value)
    print(json.dumps(dict(status=value['status'],run_id=manifest['run_id'],reports=str(directory)),ensure_ascii=False))


class GrowingEvents:
    """Incremental gzip reader; an unfinished native file never becomes valid."""
    def __init__(self, path):
        self.stream = path.open('rb')
        self.decoder = zlib.decompressobj(16+zlib.MAX_WBITS)
        self.parser = ET.XMLPullParser(events=('start','end'))
        self.root = None
        self.closed_xml = False

    def poll(self):
        for _ in range(64):  # Bound each UI update even when the writer outpaces us.
            chunk = self.stream.read(65536)
            if not chunk:
                return
            if self.decoder.eof:
                raise ValueError('Unexpected bytes after completed native gzip')
            self.parser.feed(self.decoder.decompress(chunk))
            if self.decoder.unused_data:
                raise ValueError('Unexpected trailing gzip data')
            for action, element in self.parser.read_events():
                if self.root is None and action == 'start':
                    if element.tag != 'events':
                        raise ValueError('Invalid events root')
                    self.root = element
                elif action == 'end' and element.tag == 'event':
                    yield dict(element.attrib)
                    element.clear(); self.root.clear()
                elif action == 'end' and element.tag == 'events':
                    self.closed_xml = True

    def close(self):
        self.stream.close()

    def integrity(self, writer_alive):
        if self.decoder.eof and self.closed_xml: return 'closed_gzip_xml'
        return 'provisional_eof' if writer_alive else 'truncated_incomplete'


def watch(run, interval,iteration=0):
    """Tail ONE explicit run. Does not write files or start native processes."""
    run = Path(run).resolve()
    reader = None
    observation = None
    cargo = None
    try:
        while True:
            path = run/'run-manifest.json'
            if not path.exists():
                print(json.dumps(dict(status='waiting_for_manifest',run=str(run))), flush=True)
                time.sleep(interval); continue
            manifest = load_manifest(run)
            from simz1_resource_monitor import observe_run
            process_observation = observe_run(run)
            if (manifest.get('spatial_demand') or {}).get('mode') != VARIANT:
                raise ValueError('El manifiesto no corresponde a balanced-gateway-v1')
            events = run/f'output/ITERS/it.{iteration}/{iteration}.events.xml.gz'
            if observation is None and events.is_file():
                observation, freight_contract = context(run,manifest)
                from simz1_freight import FreightAudit
                cargo = FreightAudit(freight_contract)
                reader = GrowingEvents(events)
            if reader is not None:
                for event in reader.poll():
                    observation.consume(event)
                    cargo.consume(ET.Element('event',event))
            timing=cargo.summary() if cargo and cargo.experimental else {}
            value = dict(status=manifest['status'], phase=manifest.get('phase'), run_id=manifest['run_id'],
                process_observation=process_observation,
                iteration=iteration,auditor_coverage_seconds=observation.now if observation else None,
                freight_completion_policy=manifest.get('freight_completion_policy'),
                evidence='LIVE_PROVISIONAL_NOT_VALIDATION', first_causal_error=manifest.get('first_causal_error'),
                error=manifest.get('error'), events=str(events),
                observed=observation.view() if observation else None,
                freight_observed=(dict(completed=len(cargo.finished), restricted_window_vehicles=len(cargo.violations),
                    native_active=len(cargo.traffic),waiting_to_incorporate=len(set(cargo.active)-cargo.seen),
                    completion_classifications=timing.get('completion_classifications'),
                    experimental_acceptance=timing.get('experimental_acceptance'),
                    trip_outcome=timing.get('trip_outcome')) if cargo else None),
                compressed_bytes_consumed=reader.stream.tell() if reader else 0,
                compressed_bytes_available=events.stat().st_size if events.is_file() else 0)
            stopped = process_observation['stream_final'] is True
            caught_up = reader is None or reader.stream.tell() >= events.stat().st_size
            value['stream_integrity'] = reader.integrity(not stopped) if reader and caught_up else 'not_at_eof'
            native_step = (manifest.get('last_completed_step') or {}).get('seconds')
            value['reader_lag_sim_seconds'] = max(0, native_step-observation.now) if native_step is not None and observation else None
            print(json.dumps(value,ensure_ascii=False),flush=True)
            if stopped:
                if caught_up: return value
                continue  # Drain the available prefix once; no waiting for a dead writer.
            time.sleep(interval)
    finally:
        if reader is not None:
            reader.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run-dir',type=Path,required=True)
    p.add_argument('--watch',action='store_true')
    p.add_argument('--interval',type=int,default=15)
    p.add_argument('--iteration',type=int,default=0)
    a = p.parse_args()
    try:
        from simz1_resource_monitor import EventReaderLease
        with EventReaderLease(a.run_dir,a.iteration):
            if a.watch:
                if not 1 <= a.interval <= 60:
                    raise ValueError('Intervalo de consulta: 1..60 segundos')
                watch(a.run_dir,a.interval,a.iteration)
            else:
                report(a.run_dir,a.iteration)
        return 0
    except KeyboardInterrupt:
        return 130
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, EOFError, ET.ParseError, zlib.error) as exc:
        print('Evidence unavailable: '+str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
