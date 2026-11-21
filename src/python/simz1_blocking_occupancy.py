"""Native FIFO stop audit. Does not infer centimetric positions from queue events."""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import xml.etree.ElementTree as ET
from simz1_run import checked_path, load_manifest, xml_elements, sha256


def single_lane_queues(network_path, lanes_path):
    """Caller verifies both artifacts; absence is read from the full inventory.

    Only one physical/model lane is eligible. A lone QLinkImpl queue on a
    multi-lane link may offer independent model slots and is not global FIFO.
    """
    from simz1_lane_validation import read_lanes
    assigned=read_lanes(lanes_path)
    return {row.get('id') for row in xml_elements(network_path,'link','network')
            if float(row.get('permlanes','nan'))==1 and row.get('id') not in assigned}


class BlockingStopAudit:
    def __init__(self, blocking_facilities, *, single_queue_links=(), facility_links=None):
        self.facilities=set(blocking_facilities)
        # QLanesNetworkFactory delegates links without a lane assignment to
        # QLinkImpl. Its sole queue emits link boundaries, not LaneEnter/Leave.
        # Callers must derive this set from the complete verified lane inventory;
        # missing lane events alone never establish a single queue.
        self.single_queue_links=frozenset(single_queue_links)
        self.facility_links=dict(facility_links or {})
        self.locations={}
        self.stops={}
        # The audit relates actors only inside the exact native (link, lane)
        # queue. Index that same relation instead of scanning every actor or
        # every stopped bus for an unrelated lane event.
        self._locations_by_lane=defaultdict(dict)
        self._stops_by_lane=defaultdict(dict)
        self._stop_order={}
        self._next_stop_order=0
        self.intervals=0
        self.unlocated=0
        self.reconstructed_intervals=0
        self.followers=set()
        self.violations=[]

    def _forget_location(self, vehicle):
        previous=self.locations.pop(vehicle,None)
        if previous is not None:
            lane,_=previous
            bucket=self._locations_by_lane[lane]
            del bucket[vehicle]
            if not bucket:del self._locations_by_lane[lane]

    def _forget_stop(self, vehicle):
        previous=self.stops.pop(vehicle,None)
        if previous is not None:
            del self._stop_order[vehicle]
            lane,_,_=previous
            bucket=self._stops_by_lane[lane]
            del bucket[vehicle]
            if not bucket:del self._stops_by_lane[lane]

    def consume(self, e):
        kind=e.get('type'); vehicle=e.get('vehicle') or e.get('vehicleId'); t=float(e['time'])
        key=(e.get('link'),e.get('lane'))
        if e.get('link') in self.single_queue_links:
            if kind in ('entered lane','left lane'):
                raise ValueError('Lane event contradicts verified single-queue topology')
            # None denotes the verified sole native queue, not an invented
            # native lane identifier. Preserve event times and strict FIFO test.
            if kind in ('entered link','vehicle enters traffic'):
                kind='entered lane';key=(e['link'],None)
            elif kind=='left link':
                kind='left lane';key=(e['link'],None)
        if kind=='entered lane':
            self._forget_location(vehicle)
            self.locations[vehicle]=(key,t)
            self._locations_by_lane[key][vehicle]=t
            for bus,(entered,start) in self._stops_by_lane.get(key,{}).items():
                if vehicle!=bus and t>=entered:self.followers.add((bus,start,vehicle))
        elif kind=='VehicleArrivesAtFacility' and e.get('facility') in self.facilities:
            self.intervals+=1
            location=self.locations.get(vehicle)
            expected_link=self.facility_links.get(e.get('facility'))
            if location and expected_link is not None and location[0][0]!=expected_link:
                location=None
            if not location:self.unlocated+=1;return
            lane,entered=location
            if lane[1] is None and lane[0] in self.single_queue_links:self.reconstructed_intervals+=1
            # Repeated arrivals replace the old stop in the reference audit.
            # Keep the two indexes consistent with that same overwrite.
            order=self._stop_order.get(vehicle)
            self._forget_stop(vehicle)
            if order is None:
                self._next_stop_order+=1;order=self._next_stop_order
            self._stop_order[vehicle]=order
            self.stops[vehicle]=(lane,entered,t)
            self._stops_by_lane[lane][vehicle]=(entered,t)
            for follower,entry in self._locations_by_lane.get(lane,{}).items():
                if follower!=vehicle and entry>=entered:self.followers.add((vehicle,t,follower))
        elif kind=='VehicleDepartsAtFacility':self._forget_stop(vehicle)
        elif kind=='left lane':
            location=self.locations.get(vehicle)
            local_stops=self._stops_by_lane.get(key,{})
            # Preserve the reference audit's violation order even if a bus
            # overwrote an existing stop after moving to another native lane.
            for bus in sorted(local_stops,key=self._stop_order.__getitem__):
                entered,start=local_stops[bus]
                if vehicle!=bus and location and location[0]==key and location[1]>entered:
                    self.violations.append(dict(bus=bus,follower=vehicle,time=t,stop_start=start,link=key[0],lane=key[1]))
            if location and location[0]==key:self._forget_location(vehicle)
        elif kind=='vehicle leaves traffic':self._forget_location(vehicle)

    def result(self):
        return dict(schema='simz1-native-blocking-stop-audit-v1',blocking_stop_intervals=self.intervals,
            unlocated_intervals=self.unlocated,following_vehicle_exposures=len(self.followers),
            native_lane_located_intervals=self.intervals-self.unlocated-self.reconstructed_intervals,
            reconstructed_single_queue_intervals=self.reconstructed_intervals,
            illegal_follower_exits=len(self.violations),violations=self.violations,
            continuous_physical_spacing_observed=False,
            scope='FIFO exits during native blocking facility dwell; verified single queues use link boundaries; equal-entry-time order is not inferred')


def audit_run(run):
    run=Path(run).resolve();manifest=load_manifest(run)
    if manifest['status']!='completed' or manifest['validation']['status']!='valid':
        raise ValueError('Occupancy audit requires completed/valid native run')
    schedule=run/'inputs/transit-weekday/transitSchedule.xml'
    # The manifest already fingerprints the schedule; recheck every recorded input.
    for record in manifest['inputs'].values():checked_path(run,record)
    facility_links={row.get('id'):row.get('linkRefId') for row in ET.parse(schedule).findall('./transitStops/stopFacility') if row.get('isBlocking')=='true'}
    loaded=manifest.get('effective_lane_configuration_validation',{}).get('loaded_artifacts',{})
    single=(single_lane_queues(checked_path(run,loaded['network']),checked_path(run,loaded['lanes']))
            if loaded.get('network') and loaded.get('lanes') else ())
    events=run/'output/output_events.xml.gz';audit=BlockingStopAudit(facility_links,
        single_queue_links=single,facility_links=facility_links)
    for row in xml_elements(events,'event','events'):audit.consume(row.attrib)
    return dict(run_id=manifest['run_id'],events_sha256=sha256(events),schedule_sha256=sha256(schedule),**audit.result())


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run-dir',required=True,type=Path);p.add_argument('--output',required=True,type=Path)
    args=p.parse_args();result=audit_run(args.run_dir)
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2));raise SystemExit(bool(result['illegal_follower_exits']))
