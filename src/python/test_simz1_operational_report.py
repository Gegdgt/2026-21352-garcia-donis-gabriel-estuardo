import json
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from simz1_native_validation import NativeDecisionAudit
from simz1_operational_report import progress_log, trip_metrics, hourly_metrics, compare_reports, plot_operations
from simz1_trip_table import write_events


class OperationalReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='simz1 operational ')
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)

    def progress(self, time, elapsed, iteration=0, **changes):
        values = dict(iteration=iteration, elapsedSimSeconds=elapsed, stepCount=int(time)+1,
                      processCpuNanos=10, wallNanos=20, linkTransitions=1, arrivals=0,
                      activeVehicles=2, rerouteCalculations=0, waitSignal=1, waitStorage=2,
                      waitPriority=3, forcedMoves=1, threadDeadlocks=0,
                      classification='progress_observed')
        values.update(changes)
        return dict(time=str(time), **{key:str(value) for key,value in values.items()})

    def log(self, records):
        path = self.directory/'single logfile.log'
        with path.open('w', encoding='utf-8') as stream:
            for event in records:
                fields = ', '.join(f'{key}={value}' for key,value in event.items() if key != 'time')
                stream.write(f"INFO SimZ1Diagnostics SIMZ1_PROGRESS simulatedTime={event['time']} {{{fields}}}\n")
        return path

    @staticmethod
    def expected(records):
        audit = NativeDecisionAudit()
        for record in records:
            audit.record_progress(ET.Element('event', record))
        return audit.summary()

    def test_progress_deltas_sum_while_active_is_a_snapshot_and_iteration_is_isolated(self):
        events = [self.progress(0, 0), self.progress(60, 60, forcedMoves=4, activeVehicles=7)]
        path = self.log(events + [self.progress(0, 0, iteration=1, forcedMoves=999)])
        records, provenance = progress_log(path, 0, self.expected(events))
        self.assertEqual(sum(record['forced_moves'] for record in records), 5)
        self.assertEqual(records[-1]['active_vehicles'], 7)
        self.assertEqual(len(records), 2)
        self.assertTrue(provenance['reconciled'])
        self.assertNotIn('wait_congestion', provenance['available_delta_fields'])
        self.assertIsNone(records[-1]['wait_congestion'])

    def test_double_log_missing_interval_and_corrupt_counts_fail(self):
        events = [self.progress(0, 0), self.progress(60, 60)]
        expected = self.expected(events)
        with self.assertRaisesRegex(ValueError, 'duplicado'):
            progress_log(self.log(events + events), 0, expected)
        with self.assertRaisesRegex(ValueError, 'Falta un intervalo'):
            progress_log(self.log([events[0], self.progress(120, 60)]), 0, expected)
        with self.assertRaisesRegex(ValueError, 'incompatible'):
            progress_log(self.log([events[0], self.progress(60, 60, forcedMoves=99)]), 0, expected)

    def test_hourly_exact_events_are_not_fabricated_from_progress_intervals(self):
        events = [self.progress(3540, 0, forcedMoves=0), self.progress(3600, 60, forcedMoves=6),
                  self.progress(3660, 60, forcedMoves=2)]
        intervals, _ = progress_log(self.log(events), 0, self.expected(events))
        temporal = dict(by_event_hour={'0': dict(departures=10, arrivals=3, abort_events=0),
                                       '1': dict(departures=5, arrivals=4, abort_events=0)},
                        by_departure_hour={'0':dict(departures=10, completed=7, censored=3)})
        hourly = hourly_metrics(temporal, intervals)
        self.assertEqual(hourly[0]['departures_at_event_hour'], 10)
        self.assertEqual(hourly[0]['arrivals_at_event_hour'], 3)
        self.assertEqual(hourly[0]['cohort_completed'], 7)
        self.assertEqual(hourly[1]['reported_delta_forced_moves'], 8)
        self.assertEqual(hourly[1]['intervals_crossing_hour_boundary'], 1)
        self.assertEqual(hourly[1]['active_snapshot_time'], 3660)
        self.assertNotIn('reported_delta_wait_congestion', hourly[1])

    def test_censoring_midnight_individual_times_and_mode_denominators(self):
        events = self.directory/'events.xml'
        events.write_text('''<events>
          <event type="departure" person="p" time="86390" legMode="car"/>
          <event type="arrival" person="p" time="86420" legMode="car"/>
          <event type="departure" person="q" time="86430" legMode="car"/>
          <event type="departure" person="r" time="86440" legMode="car"/>
          <event type="stuckAndAbort" person="r" time="86445" legMode="car"/>
          <event type="departure" person="w" time="86450" legMode="walk"/>
          <event type="arrival" person="w" time="86451" legMode="walk"/>
          <event type="stuckAndAbort" person="q" time="90001" legMode="car"/>
        </events>''')
        table = self.directory/'trips.csv.gz'
        write_events(events, table, 'selected', 0, {}, horizon=90000)
        stats = trip_metrics(table, 'selected', 0, 'car')
        self.assertEqual(stats['all_modes_departures'], 4)
        self.assertEqual(stats['departures'], 3)
        self.assertEqual(stats['completed'], 1)
        self.assertEqual(stats['aborted_before_horizon'], 1)
        self.assertEqual(stats['censored_at_horizon'], 1)
        self.assertEqual(stats['other_mode'], 1)
        self.assertAlmostEqual(stats['completion_rate'], 1/3)
        self.assertEqual(stats['durations_completed_only']['mean_seconds'], 30)
        self.assertEqual(stats['durations_completed_only']['p95_seconds'], 30)
        self.assertEqual(stats['durations_completed_only']['excluded'], 2)
        self.assertEqual(stats['by_departure_hour']['23']['completed'], 1)
        self.assertEqual(stats['by_departure_hour']['24']['departures'], 2)
        with self.assertRaisesRegex(ValueError, 'otra corrida'):
            trip_metrics(table, 'other', 0)

    def test_no_completions_have_no_zero_duration_and_new_queue_instrumentation_is_retained(self):
        events = self.directory/'events.xml'
        events.write_text('<events><event type="departure" person="p" time="10" legMode="car"/></events>')
        table = self.directory/'trips.csv.gz'
        write_events(events, table, 'selected', 0, {}, horizon=20)
        stats = trip_metrics(table, 'selected', 0)
        self.assertIsNone(stats['durations_completed_only']['mean_seconds'])
        self.assertIsNone(stats['durations_completed_only']['p95_seconds'])
        self.assertEqual(stats['censored_at_horizon'], 1)
        progress = [self.progress(0, 0, waitCongestion=3, turnRestrictions=0)]
        records, provenance = progress_log(self.log(progress), 0, self.expected(progress))
        self.assertEqual(records[0]['wait_congestion'], 3)
        self.assertIn('wait_congestion', provenance['available_delta_fields'])

    def test_comparison_keeps_different_denominators_and_does_not_claim_causality(self):
        def report(ident, population, completed, pending, active, forced):
            return dict(run_id=ident, run_dir=f'/runs/{ident}', planned=dict(planned_persons=population),
                horizon=dict(start_seconds=0, end_seconds=86400), observed_event_end_seconds=86401,
                trips=dict(all_modes_departures=population, completion_rate=completed/population,
                           durations_completed_only=dict(mean_seconds=30,p50_seconds=20,p95_seconds=80)),
                event_counts=dict(completed_legs=completed, aborted_before_horizon=0),
                pending=dict(censored_legs_at_cut=pending, active_vehicles_snapshot=active),
                native=dict(forced_storage_moves=forced,forced_per_1000_observed_departures=1000*forced/population),
                effective_settings={'zona1Priority.conflicts': 'geometric' if ident=='new' else 'conservative'},
                input_hashes=dict(network=ident))
        result = compare_reports(report('new',100,80,20,15,200), report('old',200,140,60,40,600))
        metrics = {row['metric']:row for row in result['metrics']}
        self.assertEqual(metrics['pending_legs_at_horizon']['historical'], 60)
        self.assertEqual(metrics['active_vehicles_snapshot']['historical'], 40)
        self.assertEqual(metrics['forced_per_1000_observed_departures']['current'], 2000)
        self.assertEqual(metrics['forced_per_1000_observed_departures']['historical'], 3000)
        self.assertAlmostEqual(metrics['forced_per_1000_observed_departures']['relative_reduction'], 1/3)
        self.assertIsNone(metrics['wait_storage_attempts']['historical'])
        self.assertIsNone(metrics['maximum_active_vehicles']['historical'])
        self.assertFalse(result['causal_effect_established'])
        self.assertFalse(result['same_planned_person_count'])
        self.assertFalse(result['matching_input_hashes']['network'])
        self.assertIn('zona1Priority.conflicts', result['effective_setting_differences'])
        json.dumps(result, allow_nan=False)

    def test_storage_attempts_and_maximum_snapshot_reduction_preserve_missing_congestion(self):
        from copy import deepcopy
        historical = dict(run_id='old', run_dir='/old', planned=dict(planned_persons=100),
            horizon=dict(start_seconds=0, end_seconds=86400), observed_event_end_seconds=86401,
            trips=dict(all_modes_departures=100, completion_rate=.7,
                       durations_completed_only=dict(mean_seconds=30,p50_seconds=20,p95_seconds=80)),
            event_counts=dict(completed_legs=70, aborted_before_horizon=0),
            pending=dict(censored_legs_at_cut=30, active_vehicles_snapshot=20, maximum_active_vehicles=50),
            native=dict(forced_storage_moves=10, forced_per_1000_observed_departures=100,
                        reason_attempts={'storage_wait':1000}), effective_settings={}, input_hashes={})
        current = deepcopy(historical)
        current['run_id'] = 'new'
        current['pending']['maximum_active_vehicles'] = 30
        current['native']['progress'] = dict(wait_storage=700, wait_congestion=0)
        metrics = {row['metric']:row for row in compare_reports(current,historical)['metrics']}
        self.assertEqual(metrics['wait_storage_attempts']['absolute_reduction'], 300)
        self.assertEqual(metrics['wait_storage_attempts']['relative_reduction'], .3)
        self.assertEqual(metrics['maximum_active_vehicles']['absolute_reduction'], 20)
        self.assertIsNone(metrics['wait_congestion_attempts']['historical'])
        self.assertEqual(metrics['wait_congestion_attempts']['current'], 0)
        self.assertIsNone(metrics['wait_congestion_attempts']['absolute_reduction'])

    def test_operational_plot_handles_zero_duration_first_sample_and_missing_historical_queue(self):
        events = [self.progress(0, 0), self.progress(60, 60)]
        intervals, _ = progress_log(self.log(events), 0, self.expected(events))
        hourly = hourly_metrics({}, intervals)
        report = dict(run_id='fixture-no-qsim', iteration=0,
                      event_counts=dict(completed_legs=1, pending_legs_at_horizon=2, aborted_before_horizon=0))
        plot_operations(report, intervals, hourly, self.directory)
        from PIL import Image
        with Image.open(self.directory/'operational_timeline.png') as rendered:
            self.assertGreater(rendered.width, 1000)
            self.assertGreater(rendered.height, 1000)


if __name__ == '__main__':
    unittest.main()
