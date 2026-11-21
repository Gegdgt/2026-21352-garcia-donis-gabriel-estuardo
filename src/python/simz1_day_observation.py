"""Versioned fixed-day contract; classifications never change native movement."""
import json
import gzip
import math
from collections import Counter
from pathlib import Path

POLICY='fixed-day-24h-v1'
RESOURCE=Path(__file__).resolve().parents[1]/'src/main/resources/simz1/day-observation-v1.json'


def policy_document():
    doc=json.loads(RESOURCE.read_bytes())
    if (doc['version']!=POLICY or doc['observation_end_seconds']!=86400 or
        doc['native_qsim_end_seconds']!=86399 or doc['native_time_step_seconds']!=1 or
        doc['private_pending_traffic_threshold_seconds_exclusive']!=3600 or
        doc['freight_pending_duration_threshold_seconds'] is not None):
        raise ValueError('Changed fixed-day contract')
    return doc


def enabled(manifest):
    return (manifest.get('experiment') or {}).get('observation_policy')==POLICY


def classify(row, cut=86400, reached=True):
    """Null means unobserved. Request age and incorporation delay stay separate."""
    scheduled=row.get('scheduled_departure'); departure=row.get('departure')
    entry=row.get('traffic_entry'); arrival=row.get('arrival'); aborted=row.get('abort_before_cleanup')
    exited=row.get('traffic_exit')
    base=dict(row,cut_seconds=cut,complete_duration_seconds=None,observed_traffic_seconds=None,
        observed_traffic_end_seconds=None,observed_traffic_end_basis=None,
        request_age_seconds=None if scheduled is None else max(0,cut-scheduled),
        incorporation_delay_seconds=None if entry is None or departure is None else entry-departure,
        pending_class=None)
    if entry is not None and arrival is None:
        end,_,basis=min([(cut,2,'observation_cut')]+([] if exited is None else [(exited,0,'traffic_exit')])+
                        ([] if aborted is None else [(aborted,1,'abort_before_cleanup')]))
        if not math.isfinite(entry) or entry<0 or not math.isfinite(end) or end<entry:
            raise ValueError('Invalid observed traffic interval')
        base.update(observed_traffic_seconds=end-entry,observed_traffic_end_seconds=end,
                    observed_traffic_end_basis=basis)
    if arrival is not None:
        if arrival>cut:raise ValueError('Physical arrival after observation cut')
        base.update(status='completed',complete_duration_seconds=None if departure is None else arrival-departure)
    elif aborted is not None:base['status']='aborted_before_cut'
    elif not reached:base['status']='interrupted_before_horizon'
    elif exited is not None:
        base.update(status='exited_without_arrival',pending_class='arrival_not_observed_review_required')
    elif entry is not None:
        duration=cut-entry
        if duration<0:raise ValueError('Traffic entry after cut')
        base.update(status='active_at_cut',observed_traffic_seconds=duration)
        if row.get('family') in ('carro','moto'):
            base['pending_class']=('prolonged_traffic_review_required' if duration>3600 else
                'recent_at_horizon' if scheduled is not None and scheduled>=cut-3600 and
                departure is not None and departure>=cut-3600 else 'recent_entry_old_request')
        else:base['pending_class']='horizon_censored_no_private_duration_threshold'
    elif departure is not None:base.update(status='waiting_for_incorporation',pending_class='incorporation_wait')
    else:base['status']='scheduled_not_departed'
    return base


PHYSICAL={'departure','arrival','vehicle enters traffic','vehicle leaves traffic',
          'entered link','left link','entered lane','left lane','TransitDriverStarts'}
FIELDS=('departure','traffic_entry','traffic_exit','arrival','abort_before_cleanup','last_transition','last_link')


class DayAudit:
    """Cross-check the native pre-cleanup census during the existing event pass."""
    def __init__(self, path, run_id, iteration, expected, *, bus_ids=None):
        self.path=Path(path);self.native={};self.rows={};self.cut=None
        self.run_id=run_id;self.iteration=iteration
        self.bus_ids=set(bus_ids) if bus_ids is not None else {r['vehicle_id'] for r in expected.values() if r['family']=='bus'}
        self.drivers={};self.vehicles={};self.cleanup=Counter();self.frozen=None
        with gzip.open(path,'rt',encoding='utf-8') as stream:
            for line in stream:
                r=json.loads(line);key=r['trip_id']
                if key in self.native or key not in expected:raise ValueError('Unknown/duplicate day census trip')
                if (r['run_id']!=run_id or r['iteration']!=iteration or r['policy']!=POLICY or r['cut_seconds']!=86400):
                    raise ValueError('Census run/iteration/cut identity differs')
                for field,value in expected[key].items():
                    if r.get(field)!=value:raise ValueError('Census scheduled identity differs: '+key+'/'+field)
                for field in ('od','profile'):
                    if r.get(field)!=expected[key].get(field):
                        raise ValueError('Census input metadata differs: '+key+'/'+field)
                self.native[key]=r
                self.rows[key]=dict(expected[key],trip_id=key,**{k:None for k in FIELDS})
        if set(self.native)!=set(expected):raise ValueError('Day census omits scheduled trips')

    def consume(self, event):
        kind=event.get('type');t=float(event.get('time'))
        if kind in PHYSICAL and t>86400:raise ValueError('Physical event after fixed-day cut')
        if kind=='simz1DayCut':
            if (self.cut is not None or t!=86400 or float(event.get('lastCompletedStep','nan'))!=86400 or
                event.get('policy')!=POLICY or event.get('iteration')!=str(self.iteration) or
                event.get('run_id')!=self.run_id):
                raise ValueError('Missing/duplicate/incomplete native day boundary')
            self.cut=t;self.frozen={k:classify(r) for k,r in self.rows.items()};return
        if kind=='TransitDriverStarts':
            key='bus:'+':'.join(event[k] for k in ('transitLineId','transitRouteId','departureId'))
            if key not in self.rows:raise ValueError('Unscheduled bus at day census')
            self.drivers[event['driverId']]=key;self.vehicles[event['vehicleId']]=key
        person=event.get('person');vehicle=event.get('vehicle')
        key=self.drivers.get(person,person) if person is not None else self.vehicles.get(vehicle,vehicle)
        if key not in self.rows:return
        abort=kind in ('stuckAndAbort','vehicle aborts')
        if self.frozen is not None:
            if abort:self.cleanup[key]+=1
            elif kind in PHYSICAL:raise ValueError('Physical event during cleanup')
            return
        row=self.rows[key]
        field={'departure':'departure','vehicle enters traffic':'traffic_entry',
               'vehicle leaves traffic':'traffic_exit','arrival':'arrival'}.get(kind)
        if field:row[field]=t
        if abort:row['abort_before_cleanup']=t
        if kind in PHYSICAL:row.update(last_transition=t,last_link=event.get('link'))
        if vehicle:self.vehicles[vehicle]=key

    def finish(self):
        if self.frozen is None:raise ValueError('No native pre-cleanup day census marker')
        grouped={};counts=Counter();pending=Counter();unique_buses=set();active_buses=set()
        for key,row in self.frozen.items():
            actual=self.native[key]
            for field in (*FIELDS,'status','pending_class','request_age_seconds','incorporation_delay_seconds','complete_duration_seconds','observed_traffic_seconds','observed_traffic_end_seconds','observed_traffic_end_basis'):
                if row.get(field)!=actual.get(field):raise ValueError('Native census differs from events: '+key+'/'+field)
            if actual.get('cleanup_abort_events')!=self.cleanup[key]:raise ValueError('Cleanup abort count differs')
            row['cleanup_abort_events']=self.cleanup[key]
            counts[row['status']]+=1
            if row['pending_class']:pending[row['pending_class']]+=1
            if row['family']=='bus':
                unique_buses.add(row['vehicle_id'])
                if row['status']=='active_at_cut':active_buses.add(row['vehicle_id'])
            od=actual.get('od');od=json.loads(od) if isinstance(od,str) else od
            od_type=next(iter(od.values())).get('od_class','unknown') if od else 'service'
            group=(row['family'],od_type,int(row['scheduled_departure']//3600))
            g=grouped.setdefault(group,Counter());g['scheduled_requests']+=1;g[row['status']]+=1
            g['incorporations']+=row['traffic_entry'] is not None;g['real_arrivals']+=row['arrival'] is not None
            if row['pending_class']:g[row['pending_class']]+=1
        return dict(policy=POLICY,execution='native_day_completed',technical_integrity='verified_precleanup_census',
            coverage_end_seconds=86400,counts=dict(counts),pending_classifications=dict(pending),
            scheduled_trips=len(self.frozen),completion_rate=counts['completed']/len(self.frozen) if self.frozen else None,
            public_vehicles_configured=len(self.bus_ids),public_vehicles_with_scheduled_expeditions=len(unique_buses),
            active_public_vehicles_at_cut=len(active_buses),public_vehicles_not_in_traffic_at_cut=len(self.bus_ids-active_buses),
            parked_public_vehicles_at_cut=None,parked_status_basis='not inferred from absent traffic; includes waiting-for-incorporation separately',
            public_expeditions_scheduled=sum(r['family']=='bus' for r in self.frozen.values()),
            groups=[dict(family=f,od=o,scheduled_hour=h,**dict(v)) for (f,o,h),v in sorted(grouped.items())])
