"""Thesis profile statistics: event-derived trips, never motion segments or scores."""
import csv
from contextlib import redirect_stdout
import gzip
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from simz1_trip_table import rows, write_events
from simz1_trip_distributions import profile_statistics, plot_profile_analysis


PROFILES = ('Normal', 'Tortuga', 'Liebre', 'Motociclista',
            'MotocicletaLenta', 'MotocicletaRapida')


class ProfileStatisticsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='simz1 profile fixtures ')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.events = []
        self.metadata = {}
        self.source_profiles = {}

    def person(self, person_id, profile, *, mode=None, source_profile=None,
               family=None, eligible=True, effective_type=None):
        family = family or ('carro' if profile in PROFILES[:3] else 'moto')
        mode = mode or ('car' if family == 'carro' else 'motorcycle')
        self.metadata[person_id] = dict(
            effective_vehicle_type=effective_type or profile,
            family=family, monte_carlo_eligible=eligible,
            identity_source='fixture:scenario-effective-vehicle-type',
            agent_type=profile, profile=profile, planned_modes=[mode])
        self.source_profiles[person_id] = source_profile or profile.lower()
        return mode

    def trip(self, person_id, departure, duration=None, *, mode='car',
             vehicle=None, abort=None, entry_delay=0):
        """Arrival is the only duration source; no arrival means censored."""
        self.events.append(dict(type='departure', time=departure,
                                person=person_id, legMode=mode, link='origin'))
        if vehicle is not None:
            self.events.append(dict(type='vehicle enters traffic',
                                    time=departure + entry_delay,
                                    person=person_id, vehicle=vehicle))
        if duration is not None:
            self.events.append(dict(type='arrival', time=departure + duration,
                                    person=person_id, legMode=mode, link='destination'))
        if abort is not None:
            self.events.append(dict(type='stuckAndAbort', time=abort,
                                    person=person_id, legMode=mode))

    def table(self, *, run_id='fixture-six-profiles', iteration=7, horizon=90000):
        root = ET.Element('events')
        for event in sorted(self.events, key=lambda event: event['time']):
            ET.SubElement(root, 'event', {key: str(value) for key, value in event.items()})
        events = self.root / 'events.xml.gz'
        with gzip.open(events, 'wb') as stream:
            stream.write(ET.tostring(root))
        target = self.root / 'trips.csv.gz'
        write_events(events, target, run_id, iteration, self.source_profiles, horizon)
        return target

    def statistics(self, **kwargs):
        return profile_statistics(self.table(), self.metadata,
                                  'fixture-six-profiles', 7, **kwargs)

    def profile_hour(self, report, profile, hour):
        return next(row for row in report['profile_hour']
                    if row['profile'] == profile and row['hour'] == hour)

    def test_six_profiles_all_24_hours_and_cross_hour_departure_cohort(self):
        for index, profile in enumerate(PROFILES):
            for hour in range(24):
                person = f'person-{index}-{hour}'
                mode = self.person(person, profile)
                self.trip(person, hour * 3600 + 30, (index + 1) * 60,
                          mode=mode, vehicle=f'vehicle-{index}-{hour}')
        self.person('cross-hour', 'Normal')
        self.trip('cross-hour', 3590, 120, vehicle='vehicle-cross-hour', entry_delay=30)
        report = self.statistics()
        self.assertEqual(len(report['profile_hour']), 6 * 24)
        self.assertEqual(len(report['family_hour']), 2 * 24)
        self.assertEqual({row['hour'] for row in report['profile_hour']}, set(range(24)))
        self.assertEqual(report['counts']['selected_rows'], 145)
        self.assertEqual(report['distribution']['n_complete'], 145)
        for index, profile in enumerate(PROFILES):
            for hour in range(24):
                group = self.profile_hour(report, profile, hour)
                if profile == 'Normal' and hour == 0:
                    self.assertEqual(group['n_complete'], 2)
                    self.assertAlmostEqual(group['mean_minutes'], 1.5)
                    self.assertAlmostEqual(group['median_minutes'], 1.5)
                    self.assertAlmostEqual(group['p95_minutes'], 1.95)
                else:
                    self.assertEqual(group['n_complete'], 1)
                    self.assertAlmostEqual(group['mean_minutes'], index + 1)
                self.assertEqual(group['n_excluded'], 0)
                self.assertEqual(group['modes'], ['car' if index < 3 else 'motorcycle'])
                self.assertEqual(group['sample_status'], 'muestra pequeña')
        # The arrival is in hour 1, but the extra completed trip belongs to hour 0.
        self.assertEqual(self.profile_hour(report, 'Normal', 1)['n_complete'], 1)

    def test_multiple_trips_keep_person_vehicle_and_trip_index_distinct(self):
        self.person('person-repeat', 'Normal')
        self.trip('person-repeat', 10, 600, vehicle='vehicle-first', entry_delay=120)
        self.trip('person-repeat', 3610, 120, vehicle='vehicle-second', entry_delay=30)
        path = self.table()
        records = list(rows(path))
        self.assertEqual([row['person_id'] for row in records], ['person-repeat'] * 2)
        self.assertEqual([row['vehicle_id'] for row in records], ['vehicle-first', 'vehicle-second'])
        self.assertEqual([row['trip_index'] for row in records], [1, 2])
        self.assertEqual([row['duration_seconds'] for row in records], [600, 120])
        report = profile_statistics(path, self.metadata, 'fixture-six-profiles', 7)
        normal = next(row for row in report['profiles'] if row['profile'] == 'Normal')
        self.assertEqual(normal['n_complete'], 2)
        self.assertAlmostEqual(normal['mean_minutes'], 6)
        self.assertAlmostEqual(self.profile_hour(report, 'Normal', 0)['mean_minutes'], 10)

    def test_missing_arrival_abort_and_horizon_censor_are_excluded_without_zero(self):
        for person in ('complete', 'abort', 'missing', 'horizon'):
            self.person(person, 'Normal')
        self.trip('complete', 10, 600)
        self.trip('abort', 20, abort=80)
        self.trip('missing', 30)
        self.trip('horizon', 40, abort=90000)
        self.person('only-aborted', 'Tortuga')
        self.trip('only-aborted', 3601, abort=3602)
        report = self.statistics()
        group = self.profile_hour(report, 'Normal', 0)
        self.assertEqual((group['n_total'], group['n_complete'], group['n_excluded']), (4, 1, 3))
        self.assertEqual((group['n_aborted'], group['n_censored']), (1, 2))
        self.assertAlmostEqual(group['completion_rate'], .25)
        self.assertAlmostEqual(group['aborted_rate'], .25)
        self.assertAlmostEqual(group['censored_rate'], .5)
        for metric in ('mean_minutes', 'median_minutes', 'p95_minutes'):
            self.assertAlmostEqual(group[metric], 10)
            self.assertIsNone(self.profile_hour(report, 'Tortuga', 1)[metric])
            self.assertIsNone(self.profile_hour(report, 'MotocicletaRapida', 0)[metric])
        self.assertEqual(self.profile_hour(report, 'Tortuga', 1)['sample_status'], 'sin completos')
        absent = self.profile_hour(report, 'MotocicletaRapida', 0)
        self.assertEqual(absent['sample_status'], 'sin datos')
        self.assertEqual(absent['n_total'], 0)
        self.assertIsNone(absent['completion_rate'])
        self.assertEqual(list(report['distribution']['values_minutes']), [10])

    def test_family_and_global_means_weight_individual_trips_not_subtype_means(self):
        self.person('one-slow', 'Normal')
        self.trip('one-slow', 1, 600)
        for index in range(3):
            person = f'three-fast-{index}'
            self.person(person, 'Tortuga')
            self.trip(person, 2 + index, 120)
        report = self.statistics(min_sample=4)
        family_hour = next(row for row in report['family_hour']
                           if row['family'] == 'Carro' and row['hour'] == 0)
        family = next(row for row in report['families'] if row['family'] == 'Carro')
        for group in (family_hour, family, report['distribution']):
            self.assertEqual(group['n_complete'], 4)
            self.assertAlmostEqual(group['mean_minutes'], 4)
            self.assertAlmostEqual(group['median_minutes'], 2)
            self.assertAlmostEqual(group['p95_minutes'], 8.8)
        self.assertEqual(family['sample_status'], 'ok')
        self.assertEqual(family_hour['sample_status'], 'ok')
        normal = next(row for row in report['profiles'] if row['profile'] == 'Normal')
        turtle = next(row for row in report['profiles'] if row['profile'] == 'Tortuga')
        self.assertEqual((normal['n_complete'], turtle['n_complete']), (1, 3))
        self.assertAlmostEqual(normal['mean_minutes'], 10)
        self.assertAlmostEqual(turtle['mean_minutes'], 2)

    def test_effective_vehicle_type_beats_legacy_label_and_mode_or_speed(self):
        self.person('slow-motorcycle', 'MotocicletaLenta', mode='car', source_profile='Tortuga')
        self.metadata['slow-motorcycle']['profile'] = 'Tortuga'
        self.metadata['slow-motorcycle']['agent_type'] = 'Tortuga'
        self.trip('slow-motorcycle', 1, 1200, mode='car', vehicle='motorcycle-vehicle')
        self.person('fast-car', 'Liebre', mode='car', source_profile='Motociclista')
        self.trip('fast-car', 2, 1, vehicle='fast-car-vehicle')
        self.person('motorcycle-mode', 'Motociclista', mode='motorcycle', source_profile='normal')
        self.trip('motorcycle-mode', 3, 60, mode='motorcycle')
        self.source_profiles['unsupported-motorcycle'] = 'MotocicletaRapida'
        self.trip('unsupported-motorcycle', 4, .5, mode='motorcycle')
        report = self.statistics()
        self.assertEqual(self.profile_hour(report, 'MotocicletaLenta', 0)['n_complete'], 1)
        self.assertEqual(self.profile_hour(report, 'MotocicletaLenta', 0)['modes'], ['car'])
        self.assertEqual(self.profile_hour(report, 'Motociclista', 0)['modes'], ['motorcycle'])
        self.assertEqual(self.profile_hour(report, 'Liebre', 0)['n_complete'], 1)
        self.assertEqual(self.profile_hour(report, 'Tortuga', 0)['n_complete'], 0)
        self.assertEqual(self.profile_hour(report, 'Normal', 0)['n_complete'], 0)
        self.assertEqual(self.profile_hour(report, 'MotocicletaRapida', 0)['sample_status'], 'sin datos')
        self.assertEqual(report['counts']['unclassified_rows'], 1)
        self.assertEqual(report['counts']['selected_rows'], 3)

    def test_global_profile_weights_hours_by_real_completed_trip_count(self):
        self.person('hour-zero', 'Normal')
        self.trip('hour-zero', 1, 600)
        for index in range(3):
            person = f'hour-one-{index}'
            self.person(person, 'Normal')
            self.trip(person, 3601 + index, 120)
        report = self.statistics()
        normal = next(row for row in report['profiles'] if row['profile'] == 'Normal')
        self.assertEqual(normal['n_complete'], 4)
        self.assertAlmostEqual(normal['mean_minutes'], 4)
        self.assertAlmostEqual(normal['median_minutes'], 2)
        self.assertAlmostEqual(normal['p95_minutes'], 8.8)
        self.assertAlmostEqual(self.profile_hour(report, 'Normal', 0)['mean_minutes'], 10)
        self.assertAlmostEqual(self.profile_hour(report, 'Normal', 1)['mean_minutes'], 2)

    def test_bus_heavy_passenger_and_internal_driver_stay_outside_six_profiles(self):
        self.person('monte-carlo-person', 'Normal')
        self.trip('monte-carlo-person', 1, 60)
        self.person('fixed-bus-driver', 'TransitBus', family='bus', eligible=False, mode='pt')
        self.trip('fixed-bus-driver', 2, 1200, mode='pt', vehicle='fleet-bus')
        self.person('heavy-driver', 'TransportePesado', family='pesado', mode='truck')
        self.trip('heavy-driver', 3, 1800, mode='truck', vehicle='heavy-vehicle')
        self.person('passenger', 'TransportePublico', family='passenger', mode='pt')
        self.metadata['passenger']['effective_vehicle_type'] = None
        self.trip('passenger', 4, 1200, mode='pt', vehicle='fleet-bus')
        self.person('internal-car-driver', 'Normal', family='carro', eligible=False)
        self.trip('internal-car-driver', 5, 3600)
        report = self.statistics()
        self.assertEqual(report['counts']['selected_rows'], 1)
        self.assertEqual(report['counts']['separate_rows'], 4)
        self.assertEqual(sum(row['n_total'] for row in report['separate_categories']), 4)
        self.assertEqual(sum(row['n_total'] for row in report['separate_categories_hour']
                             if row['hour'] == 0), 4)
        self.assertEqual(sum(row['n_total'] for row in report['profiles']), 1)
        self.assertEqual(sum(row['n_total'] for row in report['families']), 1)
        self.assertEqual(report['distribution']['n_complete'], 1)
        self.assertAlmostEqual(report['distribution']['mean_minutes'], 1)

    def test_midnight_arrival_stays_in_23_and_next_day_departure_is_not_modulo(self):
        self.person('late', 'Normal')
        self.trip('late', 86370, 120)
        self.person('tomorrow', 'Normal')
        self.trip('tomorrow', 86400, 600)
        report = self.statistics()
        self.assertEqual(report['counts']['total_rows'], 2)
        self.assertEqual(report['counts']['selected_rows'], 1)
        self.assertEqual(report['counts']['outside_departure_window'], 1)
        self.assertEqual(self.profile_hour(report, 'Normal', 0)['n_complete'], 0)
        self.assertAlmostEqual(self.profile_hour(report, 'Normal', 23)['mean_minutes'], 2)
        self.assertEqual(report['distribution']['n_complete'], 1)

    def test_wrong_run_or_iteration_rejected(self):
        self.person('p', 'Normal')
        self.trip('p', 1, 60)
        path = self.table()
        with self.assertRaises(ValueError):
            profile_statistics(path, self.metadata, 'another-run', 7)
        with self.assertRaises(ValueError):
            profile_statistics(path, self.metadata, 'fixture-six-profiles', 8)

    def test_deliverables_have_real_histogram_metadata_counts_and_no_overwrite(self):
        self.person('normal', 'Normal')
        self.trip('normal', 1, 600)
        self.person('moto', 'Motociclista')
        self.trip('moto', 3590, 120, mode='motorcycle')
        self.person('censored', 'Tortuga')
        self.trip('censored', 4000)
        path = self.table()
        old_plot = self.root / 'duration_distribution.png'
        old_plot.write_bytes(b'existing historical plot')
        destination = self.root / 'graficas_perfiles'
        report = plot_profile_analysis(path, destination, 'fixture-six-profiles', 7,
                                       self.metadata, min_sample=30)
        expected_images = {
            'carros_por_hora.png', 'motos_por_hora.png',
            'comparacion_familias_por_hora.png', 'comparacion_global_perfiles.png',
            'completitud_por_hora.png', 'duration_distribution.png'}
        self.assertEqual({item.name for item in destination.glob('*.png')}, expected_images)
        from PIL import Image
        for filename in expected_images:
            with Image.open(destination / filename) as image:
                self.assertEqual(image.format, 'PNG')
                self.assertGreater(image.width, 500)
                self.assertGreater(image.height, 300)
        with (destination / 'estadisticas_por_perfil_hora.csv').open(encoding='utf-8-sig', newline='') as stream:
            records = list(csv.DictReader(stream))
        self.assertEqual(len(records), 144)
        self.assertTrue({'mean_minutes', 'median_minutes', 'p95_minutes', 'n_complete',
                         'n_excluded', 'n_aborted', 'n_censored', 'sample_status'}.issubset(records[0]))
        self.assertEqual({record['hour'] for record in records}, {str(hour) for hour in range(24)})
        saved = json.loads((destination / 'resumen_perfiles.json').read_text(encoding='utf-8'))
        self.assertEqual(saved['run_id'], 'fixture-six-profiles')
        self.assertEqual(saved['iteration'], 7)
        self.assertEqual(saved['distribution']['n_complete'], 2)
        self.assertAlmostEqual(saved['distribution']['median_minutes'], 6)
        self.assertAlmostEqual(saved['distribution']['p95_minutes'], 9.6)
        self.assertNotIn('values_minutes', saved['distribution'])
        self.assertNotIn('values_minutes', report['distribution'])
        self.assertEqual(old_plot.read_bytes(), b'existing historical plot')
        before = {item.name: item.read_bytes() for item in destination.iterdir() if item.is_file()}
        with self.assertRaises((ValueError, FileExistsError)):
            plot_profile_analysis(path, destination, 'fixture-six-profiles', 7, self.metadata)
        self.assertEqual(before, {item.name: item.read_bytes() for item in destination.iterdir() if item.is_file()})

    def test_profiles_only_cli_uses_external_analysis_without_modifying_source_run(self):
        from generar_graficas_z1 import main
        self.person('normal', 'Normal')
        self.trip('normal', 1, 600, vehicle='car-normal')
        fixture_table = self.table()
        source_run = self.root / 'historical source with spaces'
        source_run.mkdir()
        source_table = source_run / 'trips.csv.gz'
        shutil.copyfile(fixture_table, source_table)
        (source_run / 'duration_distribution.png').write_bytes(b'keep existing plot')
        (source_run / 'run-manifest.json').write_text('{"fixture":"unchanged"}', encoding='utf-8')
        selection = dict(directory=source_run, iteration=7,
                         manifest=dict(run_id='fixture-six-profiles', results={}, counts={}))
        external = self.root / 'external thesis analysis'
        destination = external / 'it.7'
        before = {item.relative_to(source_run): item.read_bytes()
                  for item in source_run.rglob('*') if item.is_file()}

        def analyze_fixture(selected, *, analysis_dir, min_sample):
            self.assertIs(selected, selection)
            self.assertEqual(analysis_dir, external)
            self.assertEqual(min_sample, 12)
            output = destination / 'trips.csv.gz'
            output.parent.mkdir(parents=True)
            shutil.copyfile(source_table, output)
            output.with_suffix('.provenance.json').write_text(json.dumps(dict(
                source_kind='fixture_compact', run_id='fixture-six-profiles', iteration=7)), encoding='utf-8')
            plot_profile_analysis(output, destination/'graficas_perfiles', 'fixture-six-profiles', 7,
                                  self.metadata, min_sample=min_sample,
                                  provenance=dict(source_run_directory=str(source_run)))
            return dict(status='completed', directory=str(destination), reused=False)

        arguments = ['generar_graficas_z1.py', '--run-dir', str(source_run), '--iteration', '7',
                     '--profiles-only', '--analysis-dir', str(external), '--min-sample', '12']
        with patch('sys.argv', arguments), \
             patch('simz1_run.select_run', return_value=selection) as select, \
             patch('simz1_analysis.analyze_selection', side_effect=analyze_fixture) as analyze, \
             patch('procesar_eventos_z1.export_selected', side_effect=AssertionError('No replay/segment processing')) as full_export, \
             patch('simz1_trip_distributions.plot_distributions', side_effect=AssertionError('No legacy plot overwrite')) as legacy, \
             redirect_stdout(io.StringIO()):
            main()
        select.assert_called_once_with(source_run, 7, require_events=False)
        analyze.assert_called_once_with(selection, analysis_dir=external, min_sample=12)
        full_export.assert_not_called()
        legacy.assert_not_called()
        summary = json.loads((destination / 'graficas_perfiles/resumen_perfiles.json').read_text(encoding='utf-8'))
        self.assertEqual(summary['min_sample'], 12)
        self.assertEqual(summary['distribution']['n_complete'], 1)
        self.assertEqual(summary['provenance']['source_run_directory'], str(source_run))
        self.assertEqual(len(list((destination / 'graficas_perfiles').glob('*.png'))), 6)
        self.assertEqual(before, {item.relative_to(source_run): item.read_bytes()
                                  for item in source_run.rglob('*') if item.is_file()})
        self.assertFalse((source_run / 'analysis').exists())


if __name__ == '__main__':
    unittest.main()
