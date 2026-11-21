"""Recover uninstrumented QLinkImpl queues only from verified topology."""
import unittest
import tempfile
import gzip
import json
from pathlib import Path
from simz1_blocking_occupancy import BlockingStopAudit, single_lane_queues, audit_run
from simz1_run import artifact


def event(kind, time, vehicle='bus', link='r', **extra):
    return dict(type=kind, time=time, vehicle=vehicle, link=link, **extra)


class SingleQueueBlockingOccupancyTests(unittest.TestCase):
    def audit(self, links=('r',)):
        return BlockingStopAudit({'s'}, single_queue_links=links, facility_links={'s': 'r'})

    def test_reconstructs_single_queue_and_detects_illegal_follower_exit(self):
        for exit_time, expected in ((9, 1), (11, 0)):
            audit = self.audit()
            rows = [event('entered link', 1), event('entered link', 2, 'car'),
                    event('VehicleArrivesAtFacility', 5, facility='s'),
                    event('VehicleDepartsAtFacility', 10, facility='s'),
                    event('left link', exit_time, 'car')]
            for row in sorted(rows, key=lambda e: e['time']): audit.consume(row)
            result = audit.result()
            self.assertEqual(result['unlocated_intervals'], 0)
            self.assertEqual(result['reconstructed_single_queue_intervals'], 1)
            self.assertEqual(result['illegal_follower_exits'], expected)

    def test_no_topology_or_multiqueue_link_does_not_infer_a_lane(self):
        for audit in (BlockingStopAudit({'s'}), self.audit(('other',))):
            for row in [event('entered link', 1), event('VehicleArrivesAtFacility', 5, facility='s')]:
                audit.consume(row)
            self.assertEqual(audit.result()['unlocated_intervals'], 1)

    def test_equal_time_and_other_link_are_not_fifo_violations(self):
        audit = self.audit(('r', 'other'))
        for row in [event('entered link', 1), event('entered link', 1, 'equal'),
                    event('entered link', 2, 'elsewhere', 'other'),
                    event('VehicleArrivesAtFacility', 5, facility='s'),
                    event('left link', 6, 'equal'), event('left link', 6, 'elsewhere', 'other')]:
            audit.consume(row)
        self.assertEqual(audit.result()['illegal_follower_exits'], 0)

    def test_traffic_insertion_can_seed_only_verified_single_queue(self):
        audit = self.audit()
        for row in [event('vehicle enters traffic', 1), event('entered link', 2, 'car'),
                    event('VehicleArrivesAtFacility', 5, facility='s'), event('left link', 6, 'car')]:
            audit.consume(row)
        self.assertEqual(audit.result()['illegal_follower_exits'], 1)

    def test_left_link_or_traffic_exit_removes_reconstructed_membership(self):
        for kind in ('left link', 'vehicle leaves traffic'):
            audit = self.audit()
            for row in [event('entered link', 1), event(kind, 2),
                        event('VehicleArrivesAtFacility', 5, facility='s')]: audit.consume(row)
            self.assertEqual(audit.result()['unlocated_intervals'], 1)

    def test_facility_on_different_link_is_not_recovered(self):
        audit = self.audit(('r', 'other'))
        for row in [event('entered link', 1, link='other'),
                    event('VehicleArrivesAtFacility', 5, facility='s')]: audit.consume(row)
        self.assertEqual(audit.result()['unlocated_intervals'], 1)

    def test_native_lane_index_is_preserved_on_link_entry(self):
        audit = self.audit()
        for row in [event('entered lane', 1, link='assigned', lane='q'),
                    event('entered link', 1, link='assigned')]: audit.consume(row)
        self.assertEqual(audit.locations['bus'], (('assigned', 'q'), 1))

    def test_native_lane_event_rejects_contradictory_single_queue_claim(self):
        with self.assertRaisesRegex(ValueError, 'contradicts'):
            self.audit().consume(event('entered lane', 1, lane='q'))

    def test_inventory_excludes_assigned_and_multilane_links(self):
        with tempfile.TemporaryDirectory() as folder:
            network=Path(folder)/'network.xml';lanes=Path(folder)/'lanes.xml'
            network.write_text('<network><links><link id="single" permlanes="1"/>'
                '<link id="multi" permlanes="2"/><link id="assigned" permlanes="1"/>'
                '<link id="unknown"/></links></network>')
            lanes.write_text('<laneDefinitions><lanesToLinkAssignment linkIdRef="assigned">'
                '<lane id="q"><startsAt meterFromLinkEnd="10"/><representedLanes number="1"/>'
                '<capacity vehiclesPerHour="600"/><leadsTo><toLink refId="single"/></leadsTo>'
                '</lane></lanesToLinkAssignment></laneDefinitions>')
            self.assertEqual(single_lane_queues(network,lanes),{'single'})
            with self.assertRaisesRegex(ValueError,'no se puede leer'):
                single_lane_queues(network,Path(folder)/'absent.xml')

    def test_run_audit_rejects_changed_or_missing_fingerprinted_topology(self):
        for mutation in ('changed','missing'):
            with tempfile.TemporaryDirectory() as folder:
                run=Path(folder).resolve();(run/'inputs/transit-weekday').mkdir(parents=True)
                schedule=run/'inputs/transit-weekday/transitSchedule.xml'
                schedule.write_text('<transitSchedule><transitStops><stopFacility id="s" '
                    'linkRefId="r" isBlocking="true"/></transitStops></transitSchedule>')
                network=run/'network.xml';network.write_text('<network><links><link id="r" permlanes="1"/></links></network>')
                lanes=run/'lanes.xml';lanes.write_text('<laneDefinitions/>')
                manifest=dict(schema_version=1,folder=str(run),run_id='fixture',status='completed',
                    validation=dict(status='valid'),inputs=dict(schedule=artifact(run,schedule)),
                    effective_lane_configuration_validation=dict(loaded_artifacts=dict(
                        network=artifact(run,network),lanes=artifact(run,lanes))))
                (run/'run-manifest.json').write_text(json.dumps(manifest))
                if mutation=='changed':lanes.write_text('<laneDefinitions><!--mutation--></laneDefinitions>')
                else:lanes.unlink()
                with self.assertRaisesRegex(ValueError,'Hash no coincide|Archivo ausente'):
                    audit_run(run)

    def test_old_run_without_lane_inventory_keeps_unlocated_warning(self):
        with tempfile.TemporaryDirectory() as folder:
            run=Path(folder).resolve();(run/'inputs/transit-weekday').mkdir(parents=True);(run/'output').mkdir()
            schedule=run/'inputs/transit-weekday/transitSchedule.xml'
            schedule.write_text('<transitSchedule><transitStops><stopFacility id="s" '
                'linkRefId="r" isBlocking="true"/></transitStops></transitSchedule>')
            manifest=dict(schema_version=1,folder=str(run),run_id='fixture',status='completed',
                validation=dict(status='valid'),inputs=dict(schedule=artifact(run,schedule)))
            (run/'run-manifest.json').write_text(json.dumps(manifest))
            with gzip.open(run/'output/output_events.xml.gz','wt') as stream:
                stream.write('<events><event type="entered link" vehicle="bus" link="r" time="1"/>'
                    '<event type="VehicleArrivesAtFacility" vehicle="bus" facility="s" time="5"/></events>')
            self.assertEqual(audit_run(run)['unlocated_intervals'],1)


if __name__ == '__main__': unittest.main()
