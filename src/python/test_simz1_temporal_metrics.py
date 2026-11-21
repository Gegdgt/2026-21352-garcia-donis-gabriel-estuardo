import csv
import gzip
import json
from pathlib import Path
import tempfile
import unittest

from simz1_temporal_metrics import (TemporalTrafficAudit, cohort_rows, event_stream,
    analyze_temporal, scheduled_public_departures)
from simz1_trip_distributions import profile_statistics
from simz1_trip_table import COLUMNS, UNIT


def metadata(cohort='main', planned=30):
    return dict(person_id='p', population_cohort=cohort, planned_departure_seconds=planned,
                effective_vehicle_type='Normal', profile='Normal', family='carro', monte_carlo_eligible=True)


def trip(person='p', departure=30, arrival=None, index=1):
    return dict(run_id='test-run', iteration=0, person_id=person, vehicle_id=person, trip_index=index,
        mode='car', profile='Normal', departure=departure, arrival=arrival,
        duration_seconds=arrival-departure if arrival is not None else None,
        status='completed' if arrival is not None else 'censored', abort=None, departure_link='a',
        arrival_link='b' if arrival is not None else '', unit=UNIT, vehicle_ids=json.dumps([person]))


def write_table(path, records):
    with gzip.open(path, 'wt', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=COLUMNS)
        writer.writeheader(); writer.writerows(records)


class TemporalMetricsTests(unittest.TestCase):
    windows = dict(simulation=dict(start_seconds=0, end_seconds=100),
                   study=dict(start_seconds=20, end_seconds=80))

    def audit(self, people=None, events=()):
        audit = TemporalTrafficAudit(people or {'p': metadata()}, self.windows, 25)
        for event in events:
            audit.consume(event)
        return audit

    def event(self, kind, time, person='p', vehicle='p'):
        return dict(type=kind, time=time, person=person, vehicle=vehicle)

    def test_departure_boarding_and_insertion_are_distinct(self):
        audit = self.audit(events=[self.event('departure', 10), self.event('PersonEntersVehicle', 11),
                                  self.event('vehicle enters traffic', 40)])
        values = audit.finish()
        self.assertEqual(values[0]['active_end_main'], 0)
        self.assertEqual(values[0]['pending_end_main'], 1)
        self.assertEqual(values[1]['active_end_main'], 1)
        self.assertEqual(values[1]['pending_end_main'], 0)
        self.assertEqual(sum(v['pending_person_seconds_main'] for v in values), 30)

    def test_snapshot_and_interval_mean_not_interchangeable(self):
        audit = self.audit(events=[self.event('departure', 10), self.event('vehicle enters traffic', 10),
                                  self.event('vehicle leaves traffic', 20), self.event('arrival', 20)])
        values = audit.finish()
        self.assertEqual(values[0]['active_end_main'], 0)
        self.assertEqual(values[0]['active_mean_main'], .4)
        self.assertEqual(len(audit.unique_entered), 1)

    def test_arrival_does_not_double_count_traffic_exit(self):
        audit = self.audit(events=[self.event('departure', 10), self.event('vehicle enters traffic', 12),
                                  self.event('vehicle leaves traffic', 30), self.event('arrival', 30)])
        values = audit.finish()
        self.assertFalse(any(v['active_balance_error_main'] for v in values))
        self.assertEqual(sum(v['traffic_exits_main'] for v in values), 1)
        self.assertEqual(sum(v['arrivals_main'] for v in values), 1)

    def test_explicit_abort_pair_removes_once(self):
        audit = self.audit(events=[self.event('departure', 10), self.event('PersonEntersVehicle', 11),
            self.event('vehicle enters traffic', 12), self.event('vehicle aborts', 30, person=None),
            self.event('stuckAndAbort', 30, vehicle=None)])
        values = audit.finish()
        self.assertEqual(sum(v['explicit_removals_main'] for v in values), 1)
        self.assertFalse(any(v['active_balance_error_main'] for v in values))

    def test_end_cleanup_is_not_observation_empty_network(self):
        audit = self.audit(events=[self.event('departure', 10), self.event('vehicle enters traffic', 12),
                                  self.event('vehicle aborts', 101, person=None)])
        values = audit.finish()
        self.assertEqual(values[-1]['active_end_main'], 1)
        self.assertEqual(audit.outside['vehicle aborts'], 1)

    def test_arrival_exactly_at_technical_end_is_observed_and_conserved(self):
        audit = self.audit(events=[self.event('departure', 10), self.event('vehicle enters traffic', 11),
            self.event('vehicle leaves traffic', 100), self.event('arrival', 100),
            self.event('simz1NativeDecision', 101)])
        values = audit.finish()
        self.assertEqual(sum(row['active_vehicle_seconds_main'] for row in values), 89)
        self.assertEqual(values[-1]['active_end_main'], 0)
        self.assertEqual(values[-1]['traffic_exits_main'], 1)
        self.assertEqual(values[-1]['arrivals_main'], 1)
        self.assertEqual(audit.outside['arrival'], 0)
        self.assertTrue(values[-1]['final_boundary_inclusive'])
        self.assertFalse(any(row['active_balance_error_main'] for row in values))

    def test_departure_exactly_at_end_retains_pending_censor_state(self):
        audit = self.audit(events=[self.event('departure', 100), self.event('PersonEntersVehicle', 100),
            self.event('vehicle aborts', 101, person=None), self.event('stuckAndAbort', 101, vehicle=None)])
        values = audit.finish()
        self.assertEqual(values[-1]['pending_end_main'], 1)
        self.assertEqual(values[-1]['departures_main'], 1)
        self.assertEqual(values[-1]['pending_person_seconds_main'], 0)
        self.assertFalse(any(row['pending_balance_error_main'] for row in values))

    def test_interior_boundary_exit_belongs_to_next_interval(self):
        audit = self.audit(events=[self.event('departure', 10), self.event('vehicle enters traffic', 11),
                                  self.event('vehicle leaves traffic', 25), self.event('arrival', 25)])
        values = audit.finish()
        self.assertEqual(values[0]['active_end_main'], 1)
        self.assertEqual(values[0]['traffic_exits_main'], 0)
        self.assertEqual(values[1]['traffic_exits_main'], 1)
        self.assertEqual(values[1]['active_end_main'], 0)
        self.assertFalse(any(row['active_balance_error_main'] for row in values))

    def test_warmup_vehicle_continues_inside_study(self):
        audit = self.audit(people={'p': metadata('warmup_context', 10)}, events=[
            self.event('departure', 10), self.event('vehicle enters traffic', 15),
            self.event('vehicle leaves traffic', 40), self.event('arrival', 40)])
        values = audit.finish()
        self.assertEqual(values[0]['active_end_context'], 1)
        self.assertEqual(sum(v['active_vehicle_seconds_context'] for v in values), 25)
        self.assertEqual(sum(v['departures_main'] for v in values), 0)

    def test_midnight_trip_arrives_in_extension(self):
        audit = self.audit(events=[self.event('departure', 79), self.event('vehicle enters traffic', 79),
                                  self.event('vehicle leaves traffic', 90), self.event('arrival', 90)])
        self.assertEqual(audit.person_trip['p']['arrival'] - audit.person_trip['p']['departure'], 11)
        self.assertEqual(sum(v['arrivals_main'] for v in audit.finish()), 1)

    def test_public_calendar_driver_starts_not_active_until_entry(self):
        audit = self.audit(events=[dict(type='TransitDriverStarts', time=50, driverId='driver', vehicle='bus'),
            self.event('departure', 50, 'driver', 'bus'), self.event('vehicle enters traffic', 55, 'driver', 'bus'),
            self.event('vehicle leaves traffic', 85, 'driver', 'bus'), self.event('arrival', 85, 'driver', 'bus')])
        values = audit.finish()
        self.assertEqual(sum(v['active_vehicle_seconds_public'] for v in values), 30)
        self.assertEqual(values[0]['active_end_public'], 0)
        self.assertEqual(values[-1]['active_end_public'], 0)

    def test_boundary_service_event_never_inserts_vehicle(self):
        audit = self.audit(events=[dict(type='simz1TransitBoundary', time=40, vehicle='bus', action='entry')])
        self.assertEqual(sum(v['entries_public'] for v in audit.finish()), 0)
        self.assertEqual(audit.boundary_actions['entry'], 1)

    def test_public_schedule_counts_expeditions_without_creating_buses(self):
        audit = TemporalTrafficAudit({}, self.windows, 25, public_schedule=[5, 25, 85, 100, 101])
        values = audit.finish()
        self.assertEqual([v['planned_public'] for v in values], [1, 1, 0, 2])
        self.assertEqual(audit.public_planned_total, 5)
        self.assertEqual(audit.public_planned_outside, 1)
        self.assertFalse(audit.unique_entered)
        self.assertEqual(sum(v['entries_public'] for v in values), 0)

    def test_missing_public_schedule_is_unknown_instead_of_zero(self):
        values = self.audit().finish()
        self.assertTrue(all(v['planned_public'] is None for v in values))
        known_empty = TemporalTrafficAudit({}, self.windows, 25, public_schedule=[])
        self.assertTrue(all(v['planned_public'] == 0 for v in known_empty.finish()))

    def test_absolute_multiday_schedule_stream_and_invalid_times(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'schedule.xml.gz'
            with gzip.open(path, 'wt') as stream:
                stream.write('<transitSchedule><transitLine id="L"><transitRoute id="R"><departures>'
                    '<departure id="a" vehicleRefId="same-bus" departureTime="05:00:00"/>'
                    '<departure id="b" vehicleRefId="same-bus" departureTime="29:00:00"/>'
                    '</departures></transitRoute></transitLine></transitSchedule>')
            self.assertEqual(list(scheduled_public_departures(path)), [18000, 104400])
            for invalid in ['-1', 'NaN', '25:60:00', 'missing']:
                with gzip.open(path, 'wt') as stream:
                    stream.write(f'<transitSchedule><departure departureTime="{invalid}"/></transitSchedule>')
                with self.assertRaises(ValueError): list(scheduled_public_departures(path))

    def test_censor_never_entered_separate_from_circulated(self):
        people = {'p': metadata(planned=30), 'q': dict(metadata(planned=35), person_id='q')}
        audit = self.audit(people, [self.event('departure', 30), self.event('departure', 35, 'q', 'q'),
                                 self.event('vehicle enters traffic', 40, 'q', 'q')])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'table.csv.gz'; write_table(path, [trip(), trip('q', 35)])
            rows = cohort_rows(path, people, audit, dict(windows=self.windows))
        self.assertEqual(rows[0]['censored_never_entered'], 1)
        self.assertEqual(rows[0]['censored_entered'], 1)
        self.assertIsNone(rows[0]['mean_valid_duration_seconds'])

    def test_main_planned_cohort_retains_tick_after_study(self):
        study = dict(start_seconds=21600, end_seconds=108000)
        people = {'p': metadata(planned=107999.25),
                  'context': dict(metadata('warmup_context', 10), person_id='context')}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'table.csv.gz'
            write_table(path, [trip(departure=108000, arrival=108040), trip('context', 10, 21610)])
            report = profile_statistics(path, people, 'test-run', 0, temporal_policy=dict(windows=dict(study=study)))
        self.assertEqual(report['counts']['selected_rows'], 1)
        self.assertEqual(report['counts']['auxiliary_context_rows'], 1)
        self.assertEqual(report['counts']['observed_departures_after_study'], 1)
        last = next(r for r in report['profile_hour'] if r['profile']=='Normal' and r['hour']==23)
        self.assertEqual(last['n_complete'], 1)

    def test_legacy_boundary_remains_explicit_without_inventing_row(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'table.csv.gz'; write_table(path, [trip(departure=86400)])
            report = profile_statistics(path, {'p': metadata()}, 'test-run', 0)
        self.assertEqual(report['counts']['outside_departure_window'], 1)
        self.assertEqual(report['counts']['selected_rows'], 0)

    def test_nonmonotonic_and_invalid_bins_rejected(self):
        audit = self.audit(events=[self.event('departure', 30)])
        with self.assertRaises(ValueError): audit.consume(self.event('vehicle enters traffic', 29))
        with self.assertRaises(ValueError): TemporalTrafficAudit({}, self.windows, 0)

    def test_generated_artifacts_explain_balance_and_separate_cohorts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); events = root/'events.xml'; table=root/'table.csv.gz'
            events.write_text('<events><event type="departure" time="30" person="p" vehicle="p"/><event type="vehicle enters traffic" time="32" person="p" vehicle="p"/><event type="vehicle leaves traffic" time="90" person="p" vehicle="p"/><event type="arrival" time="90" person="p" vehicle="p"/></events>', encoding='utf-8')
            write_table(table, [trip(departure=30, arrival=90)])
            report = analyze_temporal(events, table, {'p':metadata()}, dict(windows=self.windows), root, 'test-run', 0)
            self.assertEqual(report['conservation']['status'], 'passed')
            self.assertEqual(len(list(root.glob('*.png'))), 4)
            self.assertEqual(len(list(event_stream(events))), 4)
            self.assertIn('never subtracted twice', report['definitions']['active'])

    def test_continuous_analysis_and_package_preserve_context_and_midnight(self):
        import xml.etree.ElementTree as ET
        import test_simz1_analysis as fixture_module
        from simz1_run import artifact, atomic_json
        import simz1_report_package as package
        fixture = fixture_module.AnalysisLifecycleTests()
        fixture.setUp(); self.addCleanup(fixture.doCleanups)
        run = fixture.make_run(profiles=('Normal', 'Motociclista'), name='continuous')
        manifest = json.loads((run/'run-manifest.json').read_text(encoding='utf-8'))
        policy = dict(schema_version='simz1-weekday-continuous-v1', timezone='America/Guatemala',
            windows=dict(simulation=dict(start_seconds=0, end_seconds=136800),
                         study=dict(start_seconds=21600, end_seconds=108000)))
        manifest['temporal_policy'] = policy
        manifest['time_horizon']['end_seconds'] = 136800
        manifest['counts'].update(planned_trips=2, principal_cohort_persons=1, context_persons=1)
        plans = ET.parse(run/'plans.xml')
        for person, cohort, planned in zip(plans.getroot().findall('person'), ('main', 'warmup_context'), (107999.25, 10)):
            for name, value in dict(simz1PopulationCohort=cohort, simz1PlannedDepartureSeconds=str(planned), simz1StudyStartSeconds='21600').items():
                ET.SubElement(person.find('attributes'), 'attribute', name=name).text = value
        plans.write(run/'plans.xml', encoding='utf-8')
        manifest['inputs']['plans'] = manifest['results']['0']['plans'] = artifact(run, run/'plans.xml')
        events = ET.Element('events')
        entries = []
        for person, departure, entry, arrival, mode in [('person-0', 108000, 108003, 108040, 'car'), ('person-1', 10, 11, 21610, 'motorcycle')]:
            entries.extend([dict(type='departure', time=departure, person=person, legMode=mode),
                dict(type='vehicle enters traffic', time=entry, person=person, vehicle=person),
                dict(type='vehicle leaves traffic', time=arrival, person=person, vehicle=person),
                dict(type='arrival', time=arrival, person=person, legMode=mode)])
        for entry in sorted(entries, key=lambda item:item['time']):
            ET.SubElement(events, 'event', {key:str(value) for key,value in entry.items()})
        events_path = run/manifest['results']['0']['events']['path']
        with gzip.open(events_path, 'wb') as stream: stream.write(ET.tostring(events))
        manifest['results']['0']['events'] = artifact(run, events_path)
        schedule = run/'transitSchedule.xml'
        schedule.write_text('<transitSchedule><transitLine id="L"><transitRoute id="R"><departures>'
            '<departure id="one" vehicleRefId="bus" departureTime="06:00:00"/>'
            '<departure id="two" vehicleRefId="bus" departureTime="30:00:00"/>'
            '</departures></transitRoute></transitLine></transitSchedule>', encoding='utf-8')
        manifest['inputs']['transit_schedule'] = artifact(run, schedule)
        atomic_json(run/'run-manifest.json', manifest)
        result = fixture.analyze(run)
        self.assertEqual(result['status'], 'completed', result)
        profiles = fixture.report(run)
        self.assertEqual(profiles['counts']['selected_rows'], 1)
        self.assertEqual(profiles['counts']['auxiliary_context_rows'], 1)
        charts = run/'analysis/it.0/graficas_perfiles'
        metrics = json.loads((charts/'metricas_temporales.json').read_text(encoding='utf-8'))
        self.assertEqual(metrics['conservation']['status'], 'passed')
        self.assertEqual(metrics['public_schedule']['planned_expeditions'], 2)
        with (charts/'flujo_ocupacion_15min.csv').open(newline='') as stream:
            self.assertEqual(sum(int(row['planned_public']) for row in csv.DictReader(stream)), 2)
        self.assertEqual(metrics['unique_vehicles_ever_entered'], 2)
        packaged = package.pack(run, 0)
        self.assertEqual(packaged['status'], 'completed')
        folder = run/'entregables'/run.name
        self.assertTrue((folder/'docs/metricas_temporales.json').is_file())
        self.assertTrue((folder/'graficas/ocupacion_y_pendientes.png').is_file())


if __name__ == '__main__':
    unittest.main()
