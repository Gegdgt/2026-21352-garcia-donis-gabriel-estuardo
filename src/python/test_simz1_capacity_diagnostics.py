"""Small capacity/observation contracts; no MATSim, population generation or subprocesses."""
from copy import deepcopy
import contextlib
import gzip
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

import simz1_capacity_diagnostics as diagnostics
from simz1_capacity_events import CapacityEventAudit, audit_capacity_events
from simz1_operational_report import compare_reports


class CapacityComparisonTests(unittest.TestCase):
    @staticmethod
    def report(ident, horizon=86400, observed=86401, completed=80):
        return dict(run_id=ident, run_dir='/runs/'+ident, planned=dict(planned_persons=100),
                    horizon=dict(start_seconds=0, end_seconds=horizon), observed_event_end_seconds=observed,
                    trips=dict(all_modes_departures=100, completion_rate=completed/100,
                               durations_completed_only=dict(mean_seconds=30, p50_seconds=20, p95_seconds=80)),
                    event_counts=dict(completed_legs=completed, aborted_before_horizon=0),
                    pending=dict(censored_legs_at_cut=100-completed, active_vehicles_snapshot=10,
                                 maximum_active_vehicles=50),
                    native=dict(forced_storage_moves=4, forced_per_1000_observed_departures=40,
                                progress=dict(wait_storage=10, wait_congestion=5)),
                    effective_settings={}, input_hashes={'network': 'a'*64})

    def assert_no_differences(self, comparison):
        self.assertFalse(comparison['comparable_horizons'])
        for metric in comparison['metrics']:
            for field in ('delta', 'relative_change', 'absolute_reduction', 'relative_reduction'):
                self.assertIsNone(metric[field], (metric['metric'], field))

    def test_twenty_four_and_twenty_five_hours_keep_labeled_values_without_reductions(self):
        current = self.report('24h', completed=70)
        historical = self.report('25h', horizon=90000, observed=90001, completed=90)
        unchanged = deepcopy((current, historical))
        result = compare_reports(current, historical)
        self.assert_no_differences(result)
        self.assertEqual(result['current_horizon'], {'start_seconds': 0, 'end_seconds': 86400})
        self.assertEqual(result['historical_horizon'], {'start_seconds': 0, 'end_seconds': 90000})
        self.assertEqual(result['current_observed_event_end_seconds'], 86401)
        self.assertEqual(result['historical_observed_event_end_seconds'], 90001)
        completed = next(row for row in result['metrics'] if row['metric'] == 'completed_legs')
        self.assertEqual((completed['current'], completed['historical']), (70, 90))
        self.assertEqual((completed['current_configured_start_seconds'], completed['current_configured_end_seconds']), (0, 86400))
        self.assertEqual((completed['historical_configured_start_seconds'], completed['historical_configured_end_seconds']), (0, 90000))
        self.assertEqual((completed['current_observed_event_end_seconds'], completed['historical_observed_event_end_seconds']), (86401, 90001))
        self.assertEqual((current, historical), unchanged)
        json.dumps(result, allow_nan=False)

    def test_unknown_horizon_or_observed_end_never_implies_comparability(self):
        for missing in ('horizon', 'observed_event_end_seconds'):
            for side in ('current', 'historical'):
                pair = {'current': self.report('current'), 'historical': self.report('historical')}
                pair[side].pop(missing)
                with self.subTest(missing=missing, side=side):
                    result = compare_reports(pair['current'], pair['historical'])
                    self.assert_no_differences(result)
                    label = side+'_horizon' if missing == 'horizon' else side+'_observed_event_end_seconds'
                    self.assertIsNone(result[label])

    def test_identical_configured_horizons_still_require_the_same_observed_file_end(self):
        current = self.report('current', observed=86400, completed=70)
        historical = self.report('historical', observed=86401, completed=90)
        self.assert_no_differences(compare_reports(current, historical))
        historical['observed_event_end_seconds'] = 86400
        result = compare_reports(current, historical)
        self.assertTrue(result['comparable_horizons'])
        completed = next(row for row in result['metrics'] if row['metric'] == 'completed_legs')
        self.assertEqual(completed['delta'], -20)
        self.assertEqual(completed['absolute_reduction'], 20)
        self.assertFalse(result['causal_effect_established'])


class CapacityNetworkTests(unittest.TestCase):
    NETWORK = '''<network><nodes><node id="n0"/><node id="n1"/><node id="n2"/></nodes>
    <links capperiod="00:30:00">
      <link id="a" from="n0" to="n1" length="100" permlanes="2" capacity="900" modes="car"/>
      <link id="b" from="n1" to="n2" length="200" permlanes="1" capacity="450" modes="car"/>
    </links></network>'''

    def test_capperiod_and_flow_factor_convert_link_pcu_without_multiplying_lanes(self):
        with tempfile.TemporaryDirectory() as temporary:
            network = Path(temporary)/'network.xml'
            network.write_text(self.NETWORK, encoding='utf-8')
            original = network.read_bytes()
            result = diagnostics.read_network(network, flow_factor=.5)
            self.assertEqual(result['capacity_period_seconds'], 1800)
            self.assertEqual(result['links']['a']['lanes'], 2)
            self.assertEqual(result['links']['a']['capacity_pcu_per_hour'], 900)
            self.assertEqual(result['links']['b']['capacity_pcu_per_hour'], 450)
            self.assertEqual(network.read_bytes(), original)

    def test_network_capacity_requires_explicit_positive_period_and_finite_nonnegative_values(self):
        corruptions = [self.NETWORK.replace(' capperiod="00:30:00"', ''),
                       self.NETWORK.replace('00:30:00', '00:00:00'),
                       self.NETWORK.replace('capacity="900"', 'capacity="nan"'),
                       self.NETWORK.replace('capacity="900"', 'capacity="-1"'),
                       self.NETWORK.replace('permlanes="2"', 'permlanes="inf"'),
                       self.NETWORK.replace('from="n0"', 'from="unknown"')]
        with tempfile.TemporaryDirectory() as temporary:
            network = Path(temporary)/'network.xml'
            for xml in corruptions:
                network.write_text(xml, encoding='utf-8')
                with self.subTest(xml=xml), self.assertRaises(ValueError):
                    diagnostics.read_network(network)
            network.write_text(self.NETWORK, encoding='utf-8')
            for invalid in (-1, float('nan'), float('inf')):
                with self.subTest(flow_factor=invalid), self.assertRaises(ValueError):
                    diagnostics.read_network(network, invalid)

    def test_massive_alternatives_are_analytical_expectations_without_changing_inputs(self):
        probabilities = [1.]+[0.]*23
        links = {ident: dict(modes=['car'], capacity_pcu_per_hour=1000) for ident in ('a', 'b')}
        corridors = {'Elena': ['a', 'b']}
        originals = deepcopy((probabilities, links, corridors))
        for persons in (150000, 200000):
            scenarios = diagnostics.experimental_loads(persons, probabilities, corridors, links)
            self.assertEqual([row['corridor_share'] for row in scenarios], [.7, .5, .3])
            for row in scenarios:
                quota = persons*row['corridor_share']
                self.assertTrue(row['experimental'])
                self.assertEqual(row['trips_per_person'], 1)
                self.assertEqual(len(row['expected_departures_by_hour']), 24)
                self.assertEqual(sum(row['expected_departures_by_hour']), persons)
                self.assertEqual(row['expected_corridor_branch_origins'], quota)
                self.assertAlmostEqual(row['expected_perimeter_branch_origins']+quota, persons)
                self.assertEqual(row['corridors']['Elena']['expected_first_origins'], quota)
                for link in row['corridors']['Elena']['link_screening']:
                    self.assertEqual(link['capacity_pcu_per_hour'], 1000)
                    self.assertEqual(link['expected_hourly_first_origins'][0], quota/2)
                    self.assertEqual(link['peak_origin_load_per_nominal_capacity_at_one_pcu'], quota/2000)
                json.dumps(row, allow_nan=False)
        self.assertEqual((probabilities, links, corridors), originals)

    def test_analytical_alternatives_reject_invalid_weights_or_shared_unknown_links(self):
        links = {'a': dict(modes=['car'], capacity_pcu_per_hour=1000)}
        valid = [1.]+[0.]*23
        for weights in ([1.]*24, [1.]*23, [-1., 2.]+[0.]*22, [float('nan')]+[0.]*23):
            with self.subTest(weights=weights), self.assertRaises(ValueError):
                diagnostics.experimental_loads(10, weights, {'Elena': ['a']}, links)
        for corridors in ({'Elena': ['a'], 'Other': ['a']}, {'Elena': ['missing']}):
            with self.subTest(corridors=corridors), self.assertRaises(ValueError):
                diagnostics.experimental_loads(10, valid, corridors, links)
        for share in (-.1, 1.1, float('inf')):
            with self.subTest(share=share), self.assertRaises(ValueError):
                diagnostics.experimental_loads(10, valid, {'Elena': ['a']}, links, shares=[share])
        unavailable = diagnostics.experimental_loads(10, valid, {}, links)[0]
        self.assertFalse(unavailable['applicable'])
        self.assertIsNone(unavailable['expected_corridor_branch_origins'])

    def test_massive_event_reprocessing_is_rejected_before_opening_any_artifact(self):
        for persons in (1001, 100000):
            manifest = dict(iterations={'last': 0}, counts={'planned_persons': persons})
            with self.subTest(persons=persons), patch.object(diagnostics, 'load_manifest', return_value=manifest), \
                    patch.object(diagnostics, 'checked_path') as artifact, \
                    patch.object(diagnostics, 'read_network') as network, \
                    patch.object(diagnostics.ET, 'iterparse') as events:
                with self.assertRaisesRegex(ValueError, 'hasta 1000 personas'):
                    diagnostics.collect_diagnostics('fixture-not-opened', inspect_events=True)
                artifact.assert_not_called()
                network.assert_not_called()
                events.assert_not_called()


class CapacityEventsTests(unittest.TestCase):
    LINKS = {'a': ('n0', 'n1', {'car'}), 'b': ('n1', 'n2', {'car'}), 'bad': ('n8', 'n9', {'car'})}

    @staticmethod
    def event(kind, time, **attrs):
        return ET.Element('event', type=kind, time=str(time), **{key: str(value) for key, value in attrs.items()})

    def starting(self, time=0):
        return [self.event('departure', time, person='p', link='a', legMode='car'),
                self.event('vehicle enters traffic', time, person='p', vehicle='v', link='a', networkMode='car')]

    def test_link_occupancy_is_not_duplicated_by_initial_link_or_lane_events(self):
        events = self.starting()+[
            self.event('entered link', 0, vehicle='v', link='a'),
            self.event('entered lane', 1, vehicle='v', link='a', lane='a.1'),
            self.event('left lane', 2, vehicle='v', link='a', lane='a.1'),
            self.event('left link', 10, vehicle='v', link='a'),
            self.event('entered link', 10, vehicle='v', link='b'),
            self.event('vehicle leaves traffic', 20, person='p', vehicle='v', link='b'),
            self.event('arrival', 20, person='p', link='b', legMode='car')]
        original = [ET.tostring(event) for event in events]
        audit = CapacityEventAudit(self.LINKS, {'a': {'b'}})
        for event in events:
            audit.consume(event)
        result = audit.summary()
        self.assertEqual(result, audit.summary(), 'summary must not integrate occupancy twice')
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['counts']['lane_events_ignored'], 2)
        self.assertEqual(result['active_car_vehicles_at_horizon'], 0)
        for link in ('a', 'b'):
            self.assertEqual(result['link_metrics'][link]['max_occupancy_vehicles'], 1)
            self.assertEqual(result['link_metrics'][link]['vehicle_seconds'], 10)
            self.assertIsNone(result['link_metrics'][link]['saturation_ratio'])
        self.assertEqual(result['link_metrics']['a']['network_entries'], 1)
        self.assertEqual(result['link_metrics']['a']['exits_by_hour'][0], 1)
        self.assertEqual(result['link_metrics']['b']['entries_by_hour'][0], 1)
        self.assertEqual(result['trips']['completed_trips'], 1)
        self.assertEqual(original, [ET.tostring(event) for event in events])

    def test_post_midnight_arrival_remains_censored_and_twenty_four_hour_bins_are_fixed(self):
        events = self.starting(86390)+[
            self.event('vehicle leaves traffic', 86420, person='p', vehicle='v', link='a'),
            self.event('arrival', 86420, person='p', link='a', legMode='car')]
        result = audit_capacity_events(events, self.LINKS)
        self.assertEqual(result['trips']['departures'], 1)
        self.assertEqual(result['trips']['completed_trips'], 0)
        self.assertEqual(result['trips']['pending_at_horizon'], 1)
        self.assertEqual(result['link_metrics']['a']['occupancy_at_horizon_vehicles'], 1)
        self.assertEqual(result['link_metrics']['a']['vehicle_seconds'], 10)
        self.assertEqual(result['counts']['events_after_window'], 2)
        self.assertEqual(len(result['hour_bins']), 24)
        self.assertEqual(result['hour_bins'][-1], {'start_seconds': 82800, 'end_seconds': 86400})
        for link in result['link_metrics'].values():
            self.assertEqual(len(link['entries_by_hour']), 24)
            self.assertEqual(len(link['exits_by_hour']), 24)

    def test_corridor_throughput_does_not_sum_serial_links_or_injected_origins(self):
        links = dict(self.LINKS, before=('n_before', 'n0', {'car'}), after=('n2', 'n_after', {'car'}))
        events = [self.event('departure', 0, person='p', link='before', legMode='car'),
            self.event('vehicle enters traffic', 0, person='p', vehicle='v', link='before', networkMode='car')]
        for time, source, target in ((1, 'before', 'a'), (2, 'a', 'b'), (3, 'b', 'after')):
            events.extend([self.event('left link', time, vehicle='v', link=source),
                           self.event('entered link', time, vehicle='v', link=target)])
        events.extend([self.event('vehicle leaves traffic', 4, person='p', vehicle='v', link='after'),
            self.event('arrival', 4, person='p', link='after', legMode='car'),
            self.event('departure', 5, person='q', link='a', legMode='car'),
            self.event('vehicle enters traffic', 5, person='q', vehicle='w', link='a', networkMode='car'),
            self.event('left link', 6, vehicle='w', link='a'),
            self.event('entered link', 6, vehicle='w', link='b'),
            self.event('vehicle leaves traffic', 7, person='q', vehicle='w', link='b'),
            self.event('arrival', 7, person='q', link='b', legMode='car')])
        result = audit_capacity_events(events, links, corridor_links={'corridor': {'a', 'b'}})
        self.assertEqual(result['status'], 'ok')
        corridor = result['corridor_throughput']['corridor']
        self.assertEqual(corridor['entries_by_hour'][0], 1)
        self.assertEqual(corridor['exits_by_hour'][0], 1)
        self.assertEqual(corridor['origin_injections'], 1)
        self.assertEqual(result['link_metrics']['b']['entries_by_hour'][0], 2)
        self.assertEqual(len(corridor['entries_by_hour']), 24)

    def test_exact_midnight_arrival_is_closure_and_horizon_abort_never_invents_arrival(self):
        events = self.starting(86399)+[
            self.event('vehicle leaves traffic', 86400, person='p', vehicle='v', link='a'),
            self.event('arrival', 86400, person='p', link='a', legMode='car')]
        result = audit_capacity_events(events, self.LINKS)
        self.assertEqual(result['trips']['completed_trips'], 1)
        self.assertEqual(result['trips']['arrivals_at_closure'], 1)
        self.assertEqual(result['trips']['pending_at_horizon'], 0)
        self.assertEqual(result['link_metrics']['a']['closure']['network_exits'], 1)
        self.assertEqual(result['link_metrics']['a']['vehicle_seconds'], 1)
        self.assertEqual(sum(result['link_metrics']['a']['exits_by_hour']), 0)
        censored = audit_capacity_events(self.starting(86399)+[
            self.event('stuckAndAbort', 86400, person='p', legMode='car')], self.LINKS)
        self.assertEqual(censored['trips']['horizon_abort_events'], 1)
        self.assertEqual(censored['trips']['pending_at_horizon'], 1)
        self.assertEqual(censored['trips']['aborted_before_horizon'], 0)
        self.assertEqual(censored['trips']['arrivals'], 0)

    def test_wait_attempts_and_sparse_observation_span_do_not_become_wait_seconds(self):
        events = self.starting()+[self.event('simz1NativeDecision', time, vehicle='v', link='a',
            reason='storage_wait', decision='WAIT', waitCategory='insufficient_storage', source='fixture')
            for time in (10, 20, 90)]
        result = audit_capacity_events(events, self.LINKS)
        self.assertEqual(result['native']['wait_attempts_by_category']['insufficient_storage'], 3)
        self.assertEqual(result['native']['wait_attempts_by_reason']['storage_wait'], 3)
        repeated = result['persistent_wait']['examples'][0]
        self.assertEqual(repeated['attempts'], 3)
        self.assertEqual(repeated['observed_span_seconds'], 80)
        self.assertEqual(repeated['max_observation_gap_seconds'], 70)
        self.assertEqual(repeated['continuous_wait_seconds_lower_bound'], 0)
        self.assertIsNone(repeated['native_wait_seconds_max'])
        self.assertTrue(repeated['censored_at_horizon'])

    def test_invalid_physical_lane_and_native_signal_decisions_keep_bounded_evidence(self):
        for target, lanes in (('bad', None), ('b', {'a': set()})):
            events = self.starting()+[self.event('left link', 10, vehicle='v', link='a'),
                self.event('entered link', 10, vehicle='v', link=target),
                self.event('simz1NativeDecision', 10, vehicle='v', link='a', reason='turn_go',
                           decision='GO', signalState='RED', nativeHasGreen='false')]
            with self.subTest(target=target, lanes=lanes):
                result = audit_capacity_events(events, self.LINKS, lanes, evidence_limit=1)
                self.assertEqual(result['status'], 'invalid')
                self.assertEqual(result['validation']['invalid_physical_transitions'], 1)
                self.assertEqual(result['validation']['invalid_native_decisions'], 1)
                self.assertEqual(len(result['validation']['evidence']), 1)
                self.assertEqual(result['link_metrics'][target]['max_occupancy_vehicles'], 0)

    def test_progress_with_waits_is_not_thread_deadlock_or_proof_of_stalling(self):
        records = []
        for time, transitions, classification in ((60, 1, 'progress_observed'), (120, 0, 'traffic_wait_observed')):
            records.append(self.event('simz1Progress', time, iteration=0, elapsedSimSeconds=60, stepCount=time,
                processCpuNanos=10, wallNanos=20, linkTransitions=transitions, arrivals=0, activeVehicles=2,
                rerouteCalculations=0, waitSignal=1, waitStorage=2, waitPriority=0, forcedMoves=0,
                threadDeadlocks=0, classification=classification))
        result = audit_capacity_events(records, self.LINKS)
        self.assertEqual(result['native']['progress']['classifications'],
                         {'progress_observed': 1, 'traffic_wait_observed': 1})
        self.assertEqual(result['native']['progress']['link_transitions'], 1)
        self.assertIsNone(result['native']['progress']['wait_congestion'])
        self.assertIsNone(result['native']['progress']['turn_restrictions'])
        self.assertEqual(result['progress']['max_thread_deadlocks'], 0)
        self.assertIsNone(result['progress']['no_advancement_proven'])
        for instrumented in (1, 2):
            mixed = deepcopy(records)
            for record in mixed[:instrumented]:
                record.set('waitCongestion', '3');record.set('turnRestrictions', '0')
            observed = audit_capacity_events(mixed, self.LINKS)['native']
            self.assertEqual(observed['progress_field_availability']['waitCongestion'],
                             {'observed_samples': instrumented, 'total_samples': 2, 'available': instrumented == 2})
            self.assertEqual(observed['progress']['wait_congestion'], 6 if instrumented == 2 else None)
            self.assertEqual(observed['progress']['turn_restrictions'], 0 if instrumented == 2 else None)
        missing = audit_capacity_events([], self.LINKS)
        self.assertFalse(missing['progress']['available'])
        self.assertIsNone(missing['progress']['no_advancement_proven'])
        self.assertIsNone(missing['native']['forced_storage_moves'])

    def test_acceptance_requires_evidence_and_an_explicit_censoring_limit(self):
        report = dict(horizon={'start_seconds': 0, 'end_seconds': 86400},
                      planned={'planned_trips': 10}, event_audit=None)
        self.assertEqual(diagnostics.acceptance(report)['status'], 'incomplete')
        report['event_audit'] = dict(status='ok', native=dict(decisions=1, forced_storage_moves=0,
            storage_stuck_removals=0), trips=dict(departures=10, pending_at_horizon=1, aborted_before_horizon=0),
            progress=dict(available=True, max_thread_deadlocks=0))
        self.assertEqual(diagnostics.acceptance(report)['status'], 'incomplete')
        accepted = diagnostics.acceptance(report, max_censored_fraction=.1)
        self.assertEqual(accepted['status'], 'screening_pass')
        self.assertFalse(accepted['empirical_calibration'])
        self.assertEqual(diagnostics.acceptance(report, max_censored_fraction=0)['status'], 'reject')
        report['event_audit']['trips']['departures'] = 8
        self.assertEqual(diagnostics.acceptance(report, max_censored_fraction=.1)['status'], 'reject',
                         'unstarted planned trips must not disappear from the incomplete fraction')
        report['event_audit']['trips']['departures'] = 10
        report['event_audit']['trips']['aborted_before_horizon'] = 1
        self.assertEqual(diagnostics.acceptance(report, max_censored_fraction=.1)['status'], 'reject')
        report['event_audit']['trips']['aborted_before_horizon'] = 0
        report['event_audit']['native']['forced_storage_moves'] = 1
        self.assertEqual(diagnostics.acceptance(report, max_censored_fraction=.1)['status'], 'reject')
        report['event_audit']['native']['forced_storage_moves'] = 0
        report['event_audit']['progress']['max_thread_deadlocks'] = 1
        self.assertEqual(diagnostics.acceptance(report, max_censored_fraction=.1)['status'], 'reject')
        report['event_audit']['progress']['available'] = False
        self.assertEqual(diagnostics.acceptance(report, max_censored_fraction=.1)['status'], 'incomplete')


class CapacityCollectionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='simz1 capacity fixture ')
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name).resolve()
        (self.directory/'network.xml').write_text(CapacityNetworkTests.NETWORK, encoding='utf-8')
        (self.directory/'config.xml').write_text('''<config><module name="qsim">
            <param name="startTime" value="00:00:00"/><param name="endTime" value="24:00:00"/>
            <param name="flowCapacityFactor" value="1"/><param name="useLanes" value="true"/>
            </module></config>''', encoding='utf-8')
        with gzip.open(self.directory/'lanes.xml.gz', 'wt', encoding='utf-8') as stream:
            stream.write('''<laneDefinitions><lanesToLinkAssignment linkIdRef="a">
                <lane id="a.1"><toLink refId="b"/></lane>
                </lanesToLinkAssignment></laneDefinitions>''')
        event = CapacityEventsTests.event
        records = [event('departure', 0, person='p', link='a', legMode='car'),
            event('vehicle enters traffic', 0, person='p', vehicle='v', link='a', networkMode='car'),
            event('simz1NativeDecision', 1, vehicle='v', link='a', reason='signal_red', decision='WAIT',
                  waitCategory='signal', signalState='RED', nativeHasGreen='false'),
            event('left link', 10, vehicle='v', link='a'),
            event('entered link', 10, vehicle='v', link='b'),
            event('vehicle leaves traffic', 20, person='p', vehicle='v', link='b'),
            event('arrival', 20, person='p', link='b', legMode='car'),
            event('simz1Progress', 86400, iteration=0, elapsedSimSeconds=86400, stepCount=86401,
                processCpuNanos=10, wallNanos=20, linkTransitions=1, arrivals=1, activeVehicles=0,
                rerouteCalculations=0, waitSignal=1, waitStorage=0, waitPriority=0, forcedMoves=0,
                threadDeadlocks=0, classification='progress_observed')]
        root = ET.Element('events');root.extend(records)
        with gzip.open(self.directory/'events.xml.gz', 'wb') as stream:
            stream.write(ET.tostring(root))
        demand = dict(demand_seed=17, plans_sha256='a'*64, xml_verified_counts={'persons': 1, 'trips': 1},
            departures_by_hour={f'{hour:02}:00': int(hour == 0) for hour in range(24)},
            corridor_links={'Elena': ['a', 'b'], 'Missing corridor': []}, corridor_share=.7)
        (self.directory/'demand.json').write_text(json.dumps(demand), encoding='utf-8')
        def artifact(name):
            return dict(path=name, sha256=diagnostics.sha256(self.directory/name))
        manifest = dict(schema_version=1, folder=str(self.directory), run_id='capacity-small-fixture',
            demand_seed=17, matsim_seed=19, status='completed', validation={'status': 'valid'},
            counts={'planned_persons': 1, 'planned_trips': 1}, iterations={'first': 0, 'last': 0},
            time_horizon={'start_seconds': 0, 'end_seconds': 86400},
            temporal_demand={'hourly_probabilities': [1.]+[0.]*23},
            inputs={'config': artifact('config.xml'), 'network': artifact('network.xml'),
                    'plans': {'path': 'plans-not-read.xml', 'sha256': 'a'*64},
                    'demand_report': artifact('demand.json'), 'input:network-laneDefinitionsFile.xml': artifact('lanes.xml.gz')},
            results={'0': {'events': artifact('events.xml.gz'), 'observed_event_end_seconds': 86400,
                           'counts': {'completed_legs': 1}, 'native_qsim': {'forced_storage_moves': 0}}})
        (self.directory/'run-manifest.json').write_text(json.dumps(manifest), encoding='utf-8')

    def fingerprints(self):
        return {path.name: diagnostics.sha256(path) for path in self.directory.iterdir()}

    def test_default_collection_reads_no_events_or_plans_and_only_proposes_experiments(self):
        before = self.fingerprints()
        with patch.object(diagnostics, 'checked_path') as artifact:
            with self.assertRaises(ValueError):
                diagnostics.collect_diagnostics(self.directory, iteration=-1)
            artifact.assert_not_called()
        with patch.object(diagnostics.gzip, 'open', side_effect=AssertionError('Events/lanes must not be opened by default')):
            report = diagnostics.collect_diagnostics(self.directory)
        self.assertIsNone(report['event_audit'])
        self.assertFalse(report['provenance']['plans_and_events_revalidated'])
        self.assertEqual(report['acceptance']['status'], 'incomplete')
        self.assertEqual(len(report['experiments']), 6)
        self.assertEqual(len(report['temporal_experiments']), 6)
        for experiment in report['temporal_experiments']:
            self.assertFalse(experiment['applied'])
            self.assertEqual(len(experiment['expected_departures_by_hour']), 24)
            self.assertAlmostEqual(sum(experiment['expected_departures_by_hour']), experiment['persons'])
        self.assertEqual(self.fingerprints(), before)

    def test_small_completed_collection_reads_gzip_lanes_and_events_without_writing_sources(self):
        before = self.fingerprints()
        report = diagnostics.collect_diagnostics(self.directory, inspect_events=True, max_censored_fraction=0)
        observed = report['event_audit']
        self.assertEqual(observed['status'], 'ok')
        self.assertEqual(observed['trips']['completed_trips'], 1)
        self.assertEqual(observed['trips']['pending_at_horizon'], 0)
        self.assertEqual(observed['link_metrics']['a']['vehicle_seconds'], 10)
        self.assertEqual(observed['link_metrics']['b']['vehicle_seconds'], 10)
        self.assertEqual(observed['corridor_throughput']['Elena']['origin_injections'], 1)
        self.assertEqual(set(observed['corridor_throughput']), {'Elena'})
        self.assertEqual(report['plan_reconciliation']['not_started_by_horizon'], 0)
        self.assertEqual(report['acceptance']['status'], 'screening_pass')
        self.assertFalse(report['acceptance']['empirical_calibration'])
        self.assertTrue(report['provenance']['events_revalidated'])
        self.assertEqual(self.fingerprints(), before)
        json.dumps(report, allow_nan=False)

    def test_cli_forwards_only_explicit_event_audit_and_never_overwrites_output(self):
        report = {'event_audit': None, 'acceptance': {'status': 'incomplete'}}
        argv = ['simz1_capacity_diagnostics.py', '--run-dir', str(self.directory), '--iteration', '0',
                '--events', '--experiment-persons', '150000', '200000', '--corridor-shares', '.7', '.3',
                '--max-censored-fraction', '.1']
        with patch.object(sys, 'argv', argv), patch.object(diagnostics, 'collect_diagnostics', return_value=report) as collect, \
                patch.object(diagnostics, 'brief', return_value='fixture'), contextlib.redirect_stdout(io.StringIO()):
            diagnostics.main()
        collect.assert_called_once_with(self.directory, 0, inspect_events=True, experiment_persons=[150000, 200000],
                                        corridor_shares=[.7, .3], max_censored_fraction=.1)
        sentinel = self.directory/'keep.json';sentinel.write_text('existing result', encoding='utf-8')
        with patch.object(sys, 'argv', argv+['--output', str(sentinel)]), \
                patch.object(diagnostics, 'collect_diagnostics', return_value=report), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as failure:
                diagnostics.main()
        self.assertEqual(failure.exception.code, 1)
        self.assertEqual(sentinel.read_text(encoding='utf-8'), 'existing result')


if __name__ == '__main__':
    unittest.main()
