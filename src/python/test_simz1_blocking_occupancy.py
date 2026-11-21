import unittest
from simz1_blocking_occupancy import BlockingStopAudit

class BlockingOccupancyTests(unittest.TestCase):
    def test_blocks_followers_and_detects_real_queue_overtake(self):
        for follower_exit,expected in [(19,1),(21,0)]:
            audit=BlockingStopAudit({'s'})
            rows=[dict(time=0,type='entered lane',vehicle='bus',link='r',lane='q'),
                  dict(time=1,type='entered lane',vehicle='car',link='r',lane='q'),
                  dict(time=10,type='VehicleArrivesAtFacility',vehicle='bus',facility='s'),
                  dict(time=20,type='VehicleDepartsAtFacility',vehicle='bus',facility='s'),
                  dict(time=follower_exit,type='left lane',vehicle='car',link='r',lane='q')]
            for row in sorted(rows,key=lambda e:e['time']):audit.consume(row)
            self.assertEqual(audit.result()['illegal_follower_exits'],expected)
            self.assertEqual(audit.result()['following_vehicle_exposures'],1)

    def test_other_lanes_earlier_vehicles_and_nonblocking_stops_are_not_false_positives(self):
        audit=BlockingStopAudit({'s'})
        for row in [dict(time=0,type='entered lane',vehicle='ahead',link='r',lane='q'),
                    dict(time=1,type='entered lane',vehicle='bus',link='r',lane='q'),
                    dict(time=2,type='entered lane',vehicle='other',link='r',lane='parallel'),
                    dict(time=10,type='VehicleArrivesAtFacility',vehicle='bus',facility='s'),
                    dict(time=11,type='left lane',vehicle='ahead',link='r',lane='q'),
                    dict(time=11,type='left lane',vehicle='other',link='r',lane='parallel')]:audit.consume(row)
        self.assertEqual(audit.result()['illegal_follower_exits'],0)

    def test_missing_lane_evidence_is_reported(self):
        audit=BlockingStopAudit({'s'});audit.consume(dict(time=10,type='VehicleArrivesAtFacility',vehicle='bus',facility='s'))
        self.assertEqual(audit.result()['unlocated_intervals'],1)

if __name__=='__main__':unittest.main()
