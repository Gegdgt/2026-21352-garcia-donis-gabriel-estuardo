"""Queue-index equivalence to the original audit, including negative FIFO cases."""
from collections import Counter
import random
import unittest
from simz1_blocking_occupancy import BlockingStopAudit


class ReferenceStopAudit(BlockingStopAudit):
    """Frozen straightforward exhaustive relation, independent of new indexes."""
    def consume(self,e):
        kind=e.get('type');vehicle=e.get('vehicle') or e.get('vehicleId');t=float(e['time'])
        key=(e.get('link'),e.get('lane'))
        if kind=='entered lane':
            self.locations[vehicle]=(key,t)
            for bus,(lane,entered,start) in self.stops.items():
                if key==lane and vehicle!=bus and t>=entered:self.followers.add((bus,start,vehicle))
        elif kind=='VehicleArrivesAtFacility' and e.get('facility') in self.facilities:
            self.intervals+=1
            location=self.locations.get(vehicle)
            if not location:self.unlocated+=1;return
            lane,entered=location
            self.stops[vehicle]=(lane,entered,t)
            for follower,(other,entry) in self.locations.items():
                if other==lane and follower!=vehicle and entry>=entered:self.followers.add((vehicle,t,follower))
        elif kind=='VehicleDepartsAtFacility':self.stops.pop(vehicle,None)
        elif kind=='left lane':
            location=self.locations.get(vehicle)
            for bus,(lane,entered,start) in self.stops.items():
                if vehicle!=bus and lane==key and location and location[0]==key and location[1]>entered:
                    self.violations.append(dict(bus=bus,follower=vehicle,time=t,stop_start=start,link=key[0],lane=key[1]))
            if location and location[0]==key:self.locations.pop(vehicle,None)
        elif kind=='vehicle leaves traffic':self.locations.pop(vehicle,None)


def event(kind,time,vehicle='bus',lane='q',link='r',facility='s'):
    return dict(type=kind,time=time,vehicle=vehicle,link=link,lane=lane,facility=facility)


class NoGlobalIteration(dict):
    def items(self):raise AssertionError('Global actor scan in local native queue audit')
    def values(self):raise AssertionError('Global actor scan in local native queue audit')
    def __iter__(self):raise AssertionError('Global actor scan in local native queue audit')


class IndexedBlockingOccupancyTests(unittest.TestCase):
    def equivalent(self,rows):
        actual,reference=BlockingStopAudit({'s'}),ReferenceStopAudit({'s'})
        for i,row in enumerate(rows):
            actual.consume(row);reference.consume(row)
            self.assertEqual(actual.result(),reference.result(),f'after event {i}: {row}')
            self.assertEqual(actual.locations,reference.locations)
            self.assertEqual(actual.stops,reference.stops)
            self.assertEqual(actual.followers,reference.followers)
            indexed_locations={v:(lane,t) for lane,items in actual._locations_by_lane.items() for v,t in items.items()}
            indexed_stops={v:(lane,*times) for lane,items in actual._stops_by_lane.items() for v,times in items.items()}
            self.assertEqual(actual.locations,indexed_locations)
            self.assertEqual(actual.stops,indexed_stops)
        return actual

    def test_violation_only_during_blocking_dwell_and_equal_time_order_unknown(self):
        for exit_time,violations in ((9,1),(11,0)):
            rows=[event('entered lane',0),event('entered lane',1,'follower'),
                  event('entered lane',0,'equal'),event('VehicleArrivesAtFacility',5),
                  event('left lane',6,'equal'),event('VehicleDepartsAtFacility',10),
                  event('left lane',exit_time,'follower')]
            audit=self.equivalent(sorted(rows,key=lambda e:e['time']))
            self.assertEqual(audit.result()['illegal_follower_exits'],violations)
            self.assertEqual(audit.result()['following_vehicle_exposures'],2)

    def test_two_stops_keep_reference_violation_order_after_overwrite_and_lane_move(self):
        rows=[event('entered lane',0,'first','parallel'),event('entered lane',1,'second'),
              event('VehicleArrivesAtFacility',2,'first'),event('VehicleArrivesAtFacility',3,'second'),
              event('entered lane',4,'first'),event('VehicleArrivesAtFacility',5,'first'),
              event('entered lane',6,'follower'),event('left lane',7,'follower')]
        audit=self.equivalent(rows)
        self.assertEqual([v['bus'] for v in audit.violations],['first','second'])

    def test_randomized_reference_equivalence_including_unlocated_and_duplicate_events(self):
        for seed in range(6):
            rng=random.Random(seed)
            kinds=['entered lane','left lane','vehicle leaves traffic','VehicleArrivesAtFacility',
                   'VehicleDepartsAtFacility','simz1NativeDecision']
            rows=[event(rng.choice(kinds),i//3,'v'+str(rng.randrange(18)),
                        'q'+str(rng.randrange(4)),link='r'+str(rng.randrange(3)),
                        facility=rng.choice(['s','nonblocking'])) for i in range(600)]
            self.equivalent(rows)

    def test_native_queue_access_never_iterates_global_vehicle_or_stop_collections(self):
        audit=BlockingStopAudit({'s'})
        for i in range(1000):audit.consume(event('entered lane',0,'v'+str(i),'q'+str(i)))
        for i in range(100):audit.consume(event('VehicleArrivesAtFacility',1,'v'+str(i)))
        audit.locations=NoGlobalIteration(audit.locations);audit.stops=NoGlobalIteration(audit.stops)
        audit.consume(event('VehicleArrivesAtFacility',2,'v1'))
        audit.consume(event('entered lane',3,'new','q1'))
        audit.consume(event('left lane',4,'new','q1'))
        self.assertEqual(audit.result()['illegal_follower_exits'],1)
        audit.consume(event('VehicleDepartsAtFacility',5,'v1'))
        audit.consume(event('vehicle leaves traffic',6,'v1'))

    def test_irrelevant_event_time_validation_is_preserved(self):
        for cls in (BlockingStopAudit,ReferenceStopAudit):
            with self.assertRaises(ValueError):cls({'s'}).consume(event('simz1NativeDecision','invalid'))


if __name__=='__main__':unittest.main()
