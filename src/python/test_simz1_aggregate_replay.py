import copy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from simz1_aggregate_replay import AggregateReplay, VERSION, encode, pin, populate, validate_census_report


class AggregateFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.horizon = 100
        self.identity = dict(run_id='native-a', iteration=0,
                             run_manifest_sha256='a'*64, source_version='b'*64,
                             visual_policy='partial-native-v1')
        self.rows = [self.row('one', 'carro', 0, 1, 3, 10, 10),
                     self.row('two', 'moto', 2, 4, 5),
                     self.row('wait', 'carro', 6, 7),
                     self.row('future', 'carro', 90, None),
                     self.row('retired', 'pesado', 0, 1, 2, retired=8)]
        self.journeys = [('j1', self.trip(self.rows[0])), ('j2', self.trip(self.rows[1])),
                         ('j3', self.trip(self.rows[2])), ('j4', self.trip(self.rows[4]))]
        self.journeys[1][1]['Unrepresented_Traffic_Intervals'] = [dict(vehicle='two', link='B',
            start=6, end=100, presence_source='entered link', terminal_boundary='observation_end')]
        self.segments = [('j1', self.segment('A', 3, 6, 'vehicle enters traffic', 'left link')),
                         ('j1', self.segment('B', 6, 10, 'entered link', 'vehicle leaves traffic')),
                         ('j2', self.segment('A', 5, 6, 'vehicle enters traffic', 'left link')),
                         ('j4', self.segment('C', 2, 8, 'vehicle enters traffic', 'vehicle aborts'))]

    def tearDown(self):
        self.temp.cleanup()

    def row(self, name, family, scheduled, request, entry=None, arrival=None, exited=None, retired=None):
        return dict(trip_id=name, vehicle_id=name, family=family, cut_seconds=100,
                    scheduled_departure=scheduled, departure=request, traffic_entry=entry,
                    arrival=arrival, traffic_exit=exited, abort_before_cleanup=retired,
                    od=dict(origin_link='O'))

    def trip(self, row):
        return dict(Trip_ID=row['trip_id'], Person_ID=row['vehicle_id'], Departure=row['departure'],
                    Traffic_Entry=row['traffic_entry'], Arrival=row['arrival'],
                    Status='completed' if row['arrival'] is not None else 'censored',
                    OD=dict(origin_link='O'))

    def segment(self, link, start, end, first, last):
        return dict(Link_ID=link, timestamps=[start,end], Boundary_Provenance=dict(start=first,end=last))

    def build(self):
        database = self.root/'aggregate.sqlite'
        ident = {k:self.identity[k] for k in ('run_id','iteration','run_manifest_sha256','source_version')}
        with sqlite3.connect(database) as db:
            counts = populate(db, self.rows, self.journeys, self.segments, ident, self.horizon)
        manifest = dict(schema_version=1, version=VERSION, status='complete', identity=ident,
                        database=pin(database), sources=[], counts=counts,
                        replay_window=dict(start_seconds=0, end_seconds=self.horizon))
        (self.root/'aggregate-manifest.json').write_text(encode(manifest), encoding='utf-8')
        return AggregateReplay(self.root, self.identity)

    def test_temporal_request_is_not_entry_and_future_is_not_requested(self):
        replay = self.build()
        early = replay.snapshot(2)
        self.assertEqual(early['totals']['carro']['requested'], 1)
        self.assertEqual(early['totals']['carro']['entered'], 0)
        self.assertEqual(early['totals']['carro']['waiting_admission'], 1)
        at = replay.snapshot(7)
        self.assertEqual(at['totals']['carro']['scheduled_total'], 3)
        self.assertEqual(at['totals']['carro']['requested'], 2)
        self.assertEqual(at['totals']['carro']['waiting_admission'], 1)
        self.assertEqual(at['origins'][0]['hourly'][0]['requested'], 2)
        self.assertEqual(at['origins'][0]['hourly'][0]['waiting_admission_end'], 1)

    def test_native_transitions_retire_and_censored_tail_cut_inclusive(self):
        replay = self.build()
        self.assertEqual({x['link_id']:x['active_count'] for x in replay.snapshot(5)['links']}['A'], 2)
        at = replay.snapshot(10)
        links = {x['link_id']:x for x in at['links']}
        self.assertEqual(links['A']['active_count'], 0)
        self.assertEqual(links['B']['active_count'], 1)
        self.assertEqual(links['C']['active_count'], 0)
        self.assertEqual(links['C']['leave_count'], 0)  # retirement is not a LinkLeave
        self.assertEqual(links['A']['native_link_leave_count'], 2)
        self.assertEqual(links['B']['native_link_enter_count'], 2)
        end = replay.snapshot(100)
        self.assertEqual(end['coverage']['associated_active']['moto'], 1)
        self.assertEqual(end['coverage']['unassociated_active']['moto'], 0)
        self.assertEqual(end['totals']['pesado']['retired_before_arrival'], 1)

    def test_family_isolation_and_no_positions(self):
        snap = self.build().snapshot(7)
        links = {x['link_id']:x for x in snap['links']}
        self.assertEqual(links['B']['families'], dict(carro=1,moto=1,pesado=0,bus=0))
        self.assertTrue(snap['no_positions'])
        self.assertFalse(snap['coverage']['position_available'])
        self.assertNotIn('path', encode(snap))
        self.assertNotIn('latitude', encode(snap))
        self.assertEqual(snap['identity']['visual_policy'], 'partial-native-v1')

    def test_unknown_association_is_not_fabricated(self):
        self.segments = [p for p in self.segments if p[0] != 'j1']
        snap = self.build().snapshot(7)
        self.assertEqual(snap['coverage']['unassociated_active']['carro'], 1)
        self.assertFalse(snap['coverage']['complete_link_association'])

    def test_split_queue_hold_is_not_double_counted(self):
        self.segments[0:1] = [('j1',self.segment('A',3,4,'vehicle enters traffic','native_queue_exit_observed')),
                              ('j1',self.segment('A',4,6,'native_queue_exit_observed','left link'))]
        snap = self.build().snapshot(5)
        a = next(x for x in snap['links'] if x['link_id']=='A')
        self.assertEqual(a['entry_count'], 2)
        self.assertEqual(a['active_count'], 2)

    def test_identity_time_and_mutation_rejected(self):
        replay = self.build()
        for key in ('run_id','iteration','run_manifest_sha256','source_version'):
            bad = dict(self.identity); bad[key] = 'wrong'
            with self.assertRaises(ValueError): AggregateReplay(self.root,bad)
        for t in (-1,101,float('nan'),float('inf'),True):
            with self.assertRaises(ValueError): replay.snapshot(t)
        with (self.root/'aggregate.sqlite').open('ab') as f: f.write(b'x')
        with self.assertRaises(ValueError): replay.check_source_files()

    def test_duplicate_and_cross_link_overlap_rejected(self):
        self.rows.append(copy.deepcopy(self.rows[0]))
        with self.assertRaises(sqlite3.IntegrityError): self.build()

    def test_native_metadata_disagreement_rejected(self):
        self.journeys[0][1]['Traffic_Entry'] = 2
        with self.assertRaisesRegex(ValueError,'lifecycle mismatch'): self.build()

    def test_cross_link_overlap_rejected(self):
        self.segments.append(('j1',self.segment('X',4,5,'entered link','left link')))
        with self.assertRaisesRegex(ValueError,'Overlapping'): self.build()

    def test_same_physical_vehicle_overlapping_journeys_rejected(self):
        second = self.row('overlap', 'carro', 3, 4, 4, 8, 8)
        second['vehicle_id'] = 'one'
        self.rows.append(second)
        self.journeys.append(('j5',self.trip(second)))
        self.segments.append(('j5',self.segment('X',4,8,'vehicle enters traffic','vehicle leaves traffic')))
        with self.assertRaisesRegex(ValueError,'Physical vehicle'): self.build()

    def test_native_actor_census_and_replay_episode_identity(self):
        self.journeys[0][1]['Trip_ID'] = 'one:trip:0001'
        self.rows[0]['od'] = encode({'one:trip:0001':{'origin_link':'O'}})
        replay = self.build()
        self.assertEqual(replay.snapshot(10)['totals']['carro']['arrived'],1)

    def test_zero_duration_native_flows_and_bus_facility_splits(self):
        self.segments[0:1] = [
            ('j1',self.segment('Z',3,3,'vehicle enters traffic','left link')),
            ('j1',self.segment('A',3,4,'entered link','VehicleArrivesAtFacility')),
            ('j1',self.segment('A',4,5,'VehicleArrivesAtFacility','VehicleDepartsAtFacility')),
            ('j1',self.segment('A',5,6,'VehicleDepartsAtFacility','left link'))]
        snap = self.build().snapshot(7)
        links = {x['link_id']:x for x in snap['links']}
        self.assertEqual(links['Z']['active_count'],0)
        self.assertEqual(links['Z']['entry_count'],1)
        self.assertEqual(links['Z']['native_link_leave_count'],1)
        self.assertEqual(links['A']['native_link_enter_count'],1)
        self.assertEqual(links['A']['native_link_leave_count'],2)
        self.assertEqual(links['A']['active_count'],0)

    def test_zero_duration_flow_outside_lifetime_rejected(self):
        self.segments.append(('j1',self.segment('Z',11,11,'entered link','left link')))
        with self.assertRaisesRegex(ValueError,'outside traffic lifetime'): self.build()

    def test_retired_request_balance(self):
        self.rows[2]['abort_before_cleanup'] = 8
        snapshot = self.build().snapshot(9)
        car = snapshot['totals']['carro']
        self.assertEqual(car['retired_waiting'],1)
        self.assertEqual(car['requested'],car['waiting_admission']+car['entered']+car['retired_waiting'])

    def test_hour_boundary_and_inclusive_final_cut(self):
        self.horizon = 7200
        self.rows = [self.row('edge','carro',3599,3600,3601,7200,7200)]
        self.rows[0]['cut_seconds'] = 7200
        self.journeys = [('edge-key',self.trip(self.rows[0]))]
        self.segments = [('edge-key',self.segment('A',3601,7200,'vehicle enters traffic','vehicle leaves traffic'))]
        replay = self.build()
        hourly = replay.snapshot(3600)['origins'][0]['hourly']
        self.assertEqual(hourly[0]['requested'],0)
        self.assertEqual(hourly[0]['waiting_admission_end'],0)
        self.assertFalse(hourly[0]['end_inclusive'])
        self.assertEqual(hourly[1]['requested'],1)
        self.assertEqual(hourly[1]['waiting_admission_end'],1)
        self.assertEqual(replay.snapshot(7200)['origins'][0]['hourly'][1]['arrived'],1)

    def test_report_census_must_be_pinned_by_native_manifest(self):
        expected = self.identity
        census = dict(path='native.gz',sha256='c'*64)
        report = dict(run_id=expected['run_id'],iteration=0,manifest_sha256=expected['run_manifest_sha256'],census=census)
        native = dict(results={'0':{'day_observation':{'census':census}}})
        validate_census_report(report,native,expected)
        bad = copy.deepcopy(report); bad['census']['sha256']='d'*64
        with self.assertRaisesRegex(ValueError,'provenance'):validate_census_report(bad,native,expected)

    def test_source_mutation_and_absence_rejected(self):
        replay = self.build()
        source = self.root/'native.json'; source.write_text('{}',encoding='utf-8')
        replay.manifest['sources']=[pin(source)]
        replay.check_source_files()
        source.write_text('{"changed":true}',encoding='utf-8')
        with self.assertRaises(ValueError):replay.check_source_files()
        source.unlink()
        with self.assertRaises(FileNotFoundError):replay.check_source_files()


if __name__ == '__main__':
    unittest.main()
