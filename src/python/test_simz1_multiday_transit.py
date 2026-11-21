"""Bounded event regressions for a stable bus across civil-day duty cancellation."""
import copy
from types import SimpleNamespace
import unittest

from simz1_transit_events import TransitEventAudit
from simz1_transit_replay import TransitReplay


def contract():
    return dict(vehicle_modes={'b': 'bus'}, domain_scope='computational_network',
                domain_links={'a', 'z'}, source={'basis': 'synthetic regression'}, departures={
                    ('day0', 'r1', 'd1'): dict(vehicle='b', links=('a', 'z'), opens_seconds=0,
                                             closes_seconds=500, transfer_kind='exterior', transfer_seconds=30),
                    ('day0', 'r2', 'expired'): dict(vehicle='b', links=('a', 'z'), opens_seconds=0,
                                                  closes_seconds=500, transfer_kind='exterior', transfer_seconds=30),
                    ('day1', 'r3', 'future'): dict(vehicle='b', links=('a', 'z'), opens_seconds=86400,
                                                 closes_seconds=86500, civil_closes_seconds=90000,
                                                 transfer_kind='exterior', transfer_seconds=30)})


def boundary(action, time, ready, line='day0', dep='d1'):
    return dict(type='simz1TransitBoundary', vehicle='b', driver='driver', service=line,
                departure=dep, action=action, time=str(time), readyAt=str(ready))


def start(line, route, dep, time):
    return dict(type='TransitDriverStarts', driverId='driver', vehicleId='b', transitLineId=line,
                transitRouteId=route, departureId=dep, time=str(time))


class MultiDayTransitTests(unittest.TestCase):
    def test_cancel_expired_slot_keeps_future_day_and_no_fake_trip(self):
        motion = SimpleNamespace(transit_contract=contract(), profiles={'road'})
        replay = TransitReplay(motion)
        def consume(event):
            replay.consume(event, float(event['time']))
        def journey(line, route, dep, departure, arrival):
            consume(boundary('entry', departure, departure, line, dep))
            consume(start(line, route, dep, departure))
            trip = replay.departure('driver', departure, 'a', {})
            for kind, stamp, link, extra in [
                    ('vehicle enters traffic', departure, 'a', dict(person='driver', networkMode='car')),
                    ('left link', arrival-1, 'a', {}), ('entered link', arrival-1, 'z', {}),
                    ('vehicle leaves traffic', arrival, 'z', dict(person='driver'))]:
                consume(dict(type=kind, time=str(stamp), vehicle='b', link=link, **extra))
            replay.arrival('driver', arrival, 'z')
            consume(boundary('outside_start', arrival, arrival+30, line, dep))
            return trip
        first = journey('day0', 'r1', 'd1', 100, 550)
        self.assertEqual(first['Transit']['terminal_status'], 'between_services')
        consume(boundary('cancelled_duty_after_closing', 550, 580, dep='expired'))
        self.assertEqual(replay.remaining['b'], 1)
        self.assertNotIn('b', replay.audit.boundary_retired)
        self.assertEqual(len(replay.completed), 1)
        future = journey('day1', 'r3', 'future', 86400, 87000)
        consume(boundary('service_finished', 87000, 87000, 'day1', 'future'))
        self.assertEqual(replay.remaining['b'], 0)
        self.assertEqual(replay.ordinals['b'], 2)
        self.assertEqual(len(replay.completed), 2)
        self.assertEqual(future['Transit']['terminal_status'], 'service_finished')
        self.assertEqual(replay.audit.peak_active, 1)
        self.assertFalse(replay.audit.active)
        self.assertEqual(replay.audit.drivers, {'driver': 'b'})
        self.assertGreater(future['Transit']['service_end_time'], 86500)

    def test_cancelled_slot_cannot_restart_or_cancel_twice(self):
        audit = TransitEventAudit(contract(), {'road'})
        cancelled = boundary('cancelled_duty_after_closing', 550, 580, dep='expired')
        audit.consume(cancelled)
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            audit.consume(cancelled)
        # Move the synthetic window merely to isolate the cancellation guard.
        audit.contract['departures'][('day0', 'r2', 'expired')]['closes_seconds'] = 1000
        with self.assertRaisesRegex(ValueError, 'cancelled'):
            audit.consume(start('day0', 'r2', 'expired', 600))
        with self.assertRaisesRegex(ValueError, 'cancelled'):
            audit.consume(boundary('entry', 600, 600, dep='expired'))

    def test_started_slot_is_not_an_unstarted_cancellation(self):
        audit = TransitEventAudit(contract(), {'road'})
        audit.consume(start('day0', 'r1', 'd1', 100))
        with self.assertRaisesRegex(ValueError, 'Started duty'):
            audit.consume(boundary('cancelled_duty_after_closing', 550, 580))

    def test_legacy_closing_still_retires_whole_service(self):
        audit = TransitEventAudit(contract(), {'road'})
        audit.consume(boundary('cancelled_remaining_after_closing', 550, 580))
        with self.assertRaisesRegex(ValueError, 'retirement'):
            audit.consume(boundary('entry', 86400, 86400, 'day1', 'future'))

    def test_departure_cutoff_blocks_start_without_truncating_existing_service(self):
        audit = TransitEventAudit(contract(), {'road'})
        with self.assertRaisesRegex(ValueError, 'outside service hours'):
            audit.consume(boundary('entry', 86500, 86500, 'day1', 'future'))
        with self.assertRaisesRegex(ValueError, 'outside operating hours'):
            audit.consume(start('day1', 'r3', 'future', 86500))


if __name__ == '__main__':
    unittest.main()
