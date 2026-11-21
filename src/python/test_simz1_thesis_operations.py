"""Small, no-QSim checks for operational thesis renderers."""
import copy
import json
import math
from pathlib import Path
import tempfile
import unittest

from simz1_thesis_operations import (aggregate_temporal, cohort_view, number,
    numeric_rows, operational_views, public_transport_view, render_operations, temporal_views)


class CapturePublisher:
    def __init__(self):
        self.figures = {}

    def save(self, fig, stem, rows, metadata):
        if stem in self.figures:
            raise ValueError('Duplicate figure')
        json.dumps(dict(rows=rows, metadata=metadata), allow_nan=False)
        self.figures[stem] = (fig, rows, metadata)


def fixture():
    return dict(identity=dict(N_configured=55789, iteration=3, run_id='fixture', horizon_seconds=86400),
        balanced_report=dict(schema_version='simz1-balanced-launch-report-v2',
            public_transport=dict(public_transport_vehicles_configured=2,
                public_transport_vehicle_ids_in_traffic=['b1', 'b2'], public_transport_departures_scheduled=7,
                observed_expedition_starts=5, trips=dict(completed_trips=4),
                event_counts={'boundary_cancelled_duty_after_closing':2})),
        balanced_hours=[dict(hour=h, scheduled_requests=3,departures=2,incorporations=1,real_arrivals=1,
                            active_non_public=1,active_public_vehicles=1,waiting_non_public=1) for h in range(24)],
        balanced_groups=[dict(family='carro',scheduled_hour=1,scheduled_requests=3,completed=1,active_at_cut=1,scheduled_not_departed=1),
                         dict(family='bus',scheduled_hour=1,scheduled_requests=7,completed=4)],
        operational_report=dict(native=dict(storage_stuck_removals=0)),
        operational_intervals=[dict(time=0, elapsed_sim_seconds=0, active_vehicles=0, forced_moves=0,
            wait_signal=0, wait_storage=0, wait_priority=0, wait_congestion=None,link_transitions=0,arrivals=0),
            dict(time=60, elapsed_sim_seconds=60, active_vehicles=2, forced_moves=3,
            wait_signal=60, wait_storage=120, wait_priority=30, wait_congestion=None,link_transitions=60,arrivals=1)],
        freight_rows=[dict(route_id='R',window_close_seconds=18000,deadline_seconds=21600,
                           classification='nominal',trip_outcome='completed',delay_seconds=0, vehicle_id='c1')])


class ThesisOperationTests(unittest.TestCase):
    def tearDown(self):
        import matplotlib.pyplot as plt
        plt.close('all')

    def test_weighted_occupancy_sum_counts_and_endpoint_gauges(self):
        rows = [dict(start_seconds=0,end_seconds=900,duration_seconds=900,planned_main=2,
                    active_vehicle_seconds_main=1800,active_mean_main=2,active_start_main=1,active_end_main=3),
                dict(start_seconds=900,end_seconds=3600,duration_seconds=2700,planned_main=4,
                    active_vehicle_seconds_main=10800,active_mean_main=4,active_start_main=3,active_end_main=1)]
        result = aggregate_temporal(rows)[0]
        self.assertEqual(result['planned_main'], 6)
        self.assertEqual(result['active_mean_main'], 3.5)
        self.assertEqual(result['active_end_main'], 1)
        self.assertEqual(result['active_start_main'], 1)
        self.assertTrue(result['full_bucket'])

    def test_missing_count_and_occupancy_remain_null(self):
        rows = [dict(start_seconds=0,end_seconds=900,planned_public=None),
                dict(start_seconds=900,end_seconds=1800,planned_public=2)]
        result = aggregate_temporal(rows)[0]
        self.assertIsNone(result['planned_public'])
        self.assertIsNone(result['active_mean_main'])
        self.assertFalse(result['full_bucket'])

    def test_gap_cannot_be_complete_hour(self):
        rows = [dict(start_seconds=0,end_seconds=900,planned_main=3),
                dict(start_seconds=1800,end_seconds=3600,planned_main=5)]
        result = aggregate_temporal(rows)[0]
        self.assertFalse(result['continuous_coverage'])
        self.assertIsNone(result['planned_main'])

    def test_cannot_split_counts_or_repeat_intervals(self):
        with self.assertRaises(ValueError):
            aggregate_temporal([dict(start_seconds=3500,end_seconds=3700,planned_main=2)])
        with self.assertRaises(ValueError):
            aggregate_temporal([dict(start_seconds=0,end_seconds=900),dict(start_seconds=0,end_seconds=900)])

    def test_nonfinite_rejected_and_empty_preserved(self):
        for v in ('NaN', float('inf'), '-inf'):
            with self.assertRaises(ValueError): number(v)
        with self.assertRaises(ValueError): numeric_rows([dict(active='nan')])
        self.assertIsNone(number(''))

    def test_hourly_fallback_is_explicit_not_fake_fifteen_minutes(self):
        bundle = fixture()
        rows, source, note = temporal_views(bundle)
        self.assertEqual(source, 'fixed_day_hourly')
        self.assertEqual(len(rows), 24)
        self.assertIn('No existe serie de 15', note)
        self.assertEqual(rows[0]['hour_end'], 1)
        bundle['balanced_report']['schema_version'] = 'unverified'
        self.assertEqual(temporal_views(bundle)[0], [])

    def test_native_15min_is_preserved_and_hourly_optional(self):
        bundle = dict(identity=fixture()['identity'],temporal_rows=[dict(start_seconds=i*900,end_seconds=(i+1)*900,planned_main=1) for i in range(4)])
        self.assertEqual(len(temporal_views(bundle)[0]), 4)
        bundle['temporal_resolution'] = 'hourly'
        rows, _, _ = temporal_views(bundle)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['planned_main'], 4)

    def test_wait_rate_has_real_interval_and_not_distinct_vehicles(self):
        views = operational_views(fixture())
        self.assertIsNone(views[0]['wait_storage_per_second'])
        self.assertEqual(views[1]['wait_storage_per_second'], 2)
        self.assertIsNone(views[1]['wait_congestion_per_second'])
        self.assertEqual(views[1]['forced_moves_cumulative'], 3)
        self.assertNotIn('queue_length', views[1])

    def test_duplicate_progress_and_missing_force_rejected_or_unknown(self):
        bundle = fixture(); bundle['operational_intervals'].append(bundle['operational_intervals'][0])
        with self.assertRaises(ValueError): operational_views(bundle)
        bundle = fixture(); bundle['operational_intervals'][0]['forced_moves']=None
        self.assertIsNone(operational_views(bundle)[1]['forced_moves_cumulative'])

    def test_flows_are_not_physical_fleet(self):
        views = public_transport_view(fixture())
        self.assertEqual([r['value'] for r in views], [2,2,7,5,4,2])
        self.assertEqual(views[0]['unit'], 'vehículos físicos')
        self.assertEqual(views[2]['unit'], 'expediciones')
        bundle=fixture();bundle['balanced_report']['public_transport']['event_counts']={}
        self.assertIsNone(public_transport_view(bundle)[-1]['value'])

    def test_cohort_no_started_request_and_empty_hours_not_completed_zero_minutes(self):
        rows, fields, denominator = cohort_view(fixture())
        self.assertEqual(denominator, 'scheduled_requests')
        self.assertEqual(rows[1]['completed'], 1)
        self.assertEqual(rows[1]['scheduled_not_departed'], 1)
        self.assertEqual(rows[1]['scheduled_requests'], 3)
        self.assertNotIn('completed', rows[0])
        self.assertNotIn('duration', rows[1])

    def test_figures_have_sample_data_units_and_all_outputs(self):
        bundle=fixture();before=copy.deepcopy(bundle);pub=CapturePublisher()
        names=render_operations(bundle,pub)['figures']
        self.assertEqual(bundle,before)
        expected={'demanda_salida_insercion','ocupacion_y_pendientes','llegadas_y_salidas','cohortes_y_censura',
                  'operational_timeline','operational_timeline_ampliado','transporte_publico_flota_expediciones','carga_clasificacion_ventanas'}
        self.assertEqual(set(names),expected)
        for _, rows, metadata in pub.figures.values():
            self.assertTrue(rows);self.assertTrue(metadata['units']);self.assertEqual(metadata['observations'],len(rows))
        percentages=pub.figures['cohortes_y_censura'][1]
        self.assertIsNone(percentages[0]['completion_percent'])
        self.assertAlmostEqual(percentages[1]['completion_percent'],100/3)
        hist=pub.figures['carga_clasificacion_ventanas'][2]['histogram']
        self.assertEqual(sum(r['count'] for r in hist),1)

    def test_png_svg_really_render(self):
        publisher=CapturePublisher();render_operations(fixture(),publisher)
        from PIL import Image
        with tempfile.TemporaryDirectory() as temp:
            for stem,(fig,rows,meta) in publisher.figures.items():
                target=Path(temp)/stem
                fig.savefig(target.with_suffix('.png'),dpi=120)
                fig.savefig(target.with_suffix('.svg'))
                with Image.open(target.with_suffix('.png')) as im:
                    self.assertGreaterEqual(im.width,1400)
                self.assertIn('<svg',target.with_suffix('.svg').read_text('utf8'))

    def test_absent_sources_produce_no_false_bars(self):
        result=render_operations({'identity':fixture()['identity']},CapturePublisher())
        self.assertEqual(result['figures'],[])
        self.assertEqual(len(result['pending']),2)


if __name__=='__main__':
    unittest.main()
