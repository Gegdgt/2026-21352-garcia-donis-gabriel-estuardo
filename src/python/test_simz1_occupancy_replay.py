"""The replay carries native reservations without rewriting time or link events."""
import copy
import unittest
from simz1_motion import MotionContext
from simz1_trajectories import extract


def event(time, kind, **values):
    return dict(time=str(time), type=kind, **values)


def reservation(time, action, link, corridor, ordinal=1, slot=0):
    return event(time, 'simz1OccupancyReservation', vehicle='v', action=action,
                 link=link, corridor=corridor, policy='corridor-length-v1',
                 modelSlot=str(slot), reservationOrdinal=str(ordinal),
                 bodyLengthMeters='12', footprintMeters='12.1',
                 source='synchronous_QSim_corridor_ledger')


class OccupancyReplayTests(unittest.TestCase):
    def fixture(self):
        links = {key: dict(length=100, freespeed=10, from_node=a, to_node=b,
                          **{'from': [start, 0], 'to': [start+.001, 0]})
                 for key, a, b, start in [('A', 'a', 'b', 0), ('B', 'b', 'c', .001)]}
        events = [event(0, 'departure', person='p', link='A', legMode='car'),
                  reservation(0, 'ENTER', 'A', 'corridor'),
                  event(0, 'vehicle enters traffic', person='p', vehicle='v', link='A', relativePosition='0'),
                  event(10, 'left link', vehicle='v', link='A'),
                  event(10, 'entered link', vehicle='v', link='B'),
                  reservation(10, 'TRANSFER', 'B', 'corridor'),
                  event(20, 'left link', vehicle='v', link='B'),
                  reservation(20, 'EXIT', 'B', 'corridor'),
                  event(20, 'vehicle leaves traffic', person='p', vehicle='v', link='B', relativePosition='1'),
                  event(20, 'arrival', person='p', link='B', legMode='car')]
        return links, events

    def rows(self, links, events):
        return extract(events, links, lambda vehicle: True, lambda speed: [255,0,0], None,
                       motion=MotionContext({'v':10}, {'p':'Normal'}, {'v':'p'}), horizon=20)

    def test_link_and_activity_order_both_carry_reservation(self):
        links, events = self.fixture()
        before = copy.deepcopy(events)
        rows = self.rows(links, events)
        self.assertEqual([row['timestamps'] for row in rows], [[0,10], [10,20]])
        self.assertEqual([row['Link_ID'] for row in rows], ['A','B'])
        self.assertEqual([row['Native_Occupancy']['link_id'] for row in rows], ['A','B'])
        self.assertEqual([row['Native_Occupancy']['ordinal'] for row in rows], [1,1])
        self.assertFalse(any(row['Native_Occupancy']['positions_observed'] for row in rows))
        self.assertEqual(events, before)

    def test_exit_before_new_enter_does_not_relabel_old_interval(self):
        links, events = self.fixture()
        events[4:6] = [reservation(10,'EXIT','A','corridor'),
                       event(10,'entered link',vehicle='v',link='B'),
                       reservation(10,'ENTER','B','new',2,1)]
        rows = self.rows(links, events)
        self.assertEqual([row['Native_Occupancy']['corridor_id'] for row in rows], ['corridor','new'])
        self.assertEqual([row['Native_Occupancy']['model_slot'] for row in rows], [0,1])

    def test_history_without_events_does_not_gain_inferred_reservation(self):
        links, events = self.fixture()
        rows = self.rows(links, [e for e in events if e['type'] != 'simz1OccupancyReservation'])
        self.assertTrue(rows)
        self.assertTrue(all('Native_Occupancy' not in row for row in rows))

    def test_later_internal_transfer_does_not_redate_original_assignment(self):
        links, events = self.fixture()
        events.insert(3, reservation(5,'TRANSFER','A','corridor'))
        rows = self.rows(links, events)
        self.assertEqual(rows[0]['Native_Occupancy']['event_time'],0)
        self.assertEqual(rows[1]['Native_Occupancy']['event_time'],10)

    def test_modeled_progress_keeps_its_native_time_and_provenance(self):
        links, events = self.fixture()
        events.insert(3, event(5,'simz1OccupancyProgress',vehicle='v',link='A',
            modeledFrontLowerBoundMeters='20',nativeFrontBoundMeters='30',leaderVehicle='leader',
            leaderFrontLowerBoundMeters='32.1',leaderFootprintMeters='12.1',reason='native_earliest_exit_reached',
            nativeEarliestLinkExitTime='4',triggerVehicle='v',
            source='native_queue_endpoint_and_leader_reservation_order'))
        rows=self.rows(links,events)
        progress=rows[0]['Native_Occupancy_Progress'][0]
        self.assertEqual(progress['time'],5)
        self.assertEqual(progress['front_lower_bound_m'],20)
        self.assertEqual(progress['leader_vehicle'],'leader')
        self.assertEqual(progress['native_earliest_link_exit_time'],4)
        self.assertEqual(progress['trigger_vehicle'],'v')
        self.assertFalse(progress['positions_observed'])
        self.assertNotIn('Native_Occupancy_Progress',rows[1])


if __name__ == '__main__':
    unittest.main()
