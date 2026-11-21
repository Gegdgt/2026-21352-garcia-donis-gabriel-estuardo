"""Automatic SimZ1 analysis contracts; only temporary event fixtures, never MATSim."""
from collections import namedtuple
from contextlib import redirect_stderr, redirect_stdout
import csv
import errno
import gzip
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

import simz1_analysis
from simz1_road_catalog import IDENTITIES, SCHEMA
from simz1_run import MANIFEST, artifact, atomic_json, load_manifest, select_run, sha256
from simz1_trip_distributions import profile_statistics


PROFILES = ('Normal', 'Tortuga', 'Liebre', 'Motociclista',
            'MotocicletaLenta', 'MotocicletaRapida')
IMAGES = ('carros_por_hora.png', 'motos_por_hora.png',
          'comparacion_familias_por_hora.png', 'comparacion_global_perfiles.png',
          'completitud_por_hora.png', 'duration_distribution.png')
CSVS = ('estadisticas_por_perfil_hora.csv', 'estadisticas_por_familia_hora.csv',
        'estadisticas_globales.csv', 'categorias_separadas.csv',
        'categorias_separadas_por_hora.csv')


def fixture_renderer(table, destination, run_id, iteration, metadata, *,
                     min_sample=30, provenance=None):
    """Exercise real streaming statistics while keeping lifecycle tests inexpensive.

    The independent integration test uses the real renderer and verifies PNGs.
    """
    report = profile_statistics(table, metadata, run_id, iteration, min_sample)
    report['distribution'].pop('values_minutes')
    report['provenance'] = provenance or {}
    destination = Path(destination)
    destination.mkdir(parents=True)
    for filename in IMAGES:
        (destination / filename).write_bytes(b'fixture plot: ' + filename.encode('ascii'))
    records = (report['profile_hour'], report['family_hour'],
               report['profiles'] + report['families'], report['separate_categories'],
               report['separate_categories_hour'])
    for filename, values in zip(CSVS, records):
        fields = sorted({field for row in values for field in row}) or ['profile']
        with (destination / filename).open('w', encoding='utf-8', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(values)
    atomic_json(destination / 'resumen_perfiles.json', report)
    return report


class AnalysisLifecycleTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='simz1 analysis contract ')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.latest = self.root / 'latest-successful.json'

    def make_run(self, profiles=PROFILES, *, iterations=(0,), status='completed',
                 validation='valid', name='validated fixture'):
        directory = self.root / name
        output = directory / 'output'
        output.mkdir(parents=True)
        plans = ET.Element('population')
        for index, profile in enumerate(profiles):
            person = ET.SubElement(plans, 'person', id=f'person-{index}')
            attrs = ET.SubElement(person, 'attributes')
            family, driving, _ = IDENTITIES[profile]
            for key, value in dict(simz1AgentSchema=SCHEMA, simz1AgentType=profile,
                                   effectiveVehicleType=profile, simz1VehicleFamily=family,
                                   drivingProfile=driving).items():
                ET.SubElement(attrs, 'attribute', name=key).text = value
            plan = ET.SubElement(person, 'plan', selected='yes')
            ET.SubElement(plan, 'leg', mode='car' if family == 'carro' else 'motorcycle')
        plan_path = directory / 'plans.xml'
        plan_path.write_bytes(ET.tostring(plans))
        network = directory / 'network.xml'
        network.write_text('<network><nodes/><links/></network>', encoding='utf-8')
        config = directory / 'config-simz1.xml'
        config.write_text('<config/>', encoding='utf-8')
        results = {}
        for iteration in iterations:
            folder = output / 'ITERS' / f'it.{iteration}'
            folder.mkdir(parents=True)
            events = ET.Element('events')
            entries = []
            for index, profile in enumerate(profiles):
                mode = 'car' if IDENTITIES[profile][0] == 'carro' else 'motorcycle'
                for hour in range(24):
                    # Hour 0 deliberately crosses 01:00 but belongs to departure hour 0.
                    departure = 3590 if hour == 0 else hour * 3600 + 600
                    common = dict(person=f'person-{index}', legMode=mode)
                    entries.extend([
                        dict(type='departure', time=departure, **common),
                        dict(type='vehicle enters traffic', time=departure + 1,
                             person=f'person-{index}', vehicle=f'vehicle-{index}-{hour}'),
                        dict(type='arrival', time=departure + (index + 1) * 60 + iteration, **common)])
            for entry in sorted(entries, key=lambda row: row['time']):
                ET.SubElement(events, 'event', {key: str(value) for key, value in entry.items()})
            events_path = folder / f'{iteration}.events.xml.gz'
            with gzip.open(events_path, 'wb') as stream:
                stream.write(ET.tostring(events))
            results[str(iteration)] = dict(network=artifact(directory, network),
                                           plans=artifact(directory, plan_path),
                                           events=artifact(directory, events_path))
        manifest = dict(schema_version=1, folder=str(directory), run_id='fixture-' + name,
                        status=status, validation=dict(status=validation), demand_seed=17,
                        matsim_seed=23, counts=dict(planned_persons=len(profiles),
                                                  planned_trips=len(profiles) * 24),
                        time_horizon=dict(start_seconds=0, end_seconds=90000),
                        iterations=dict(first=min(iterations), last=max(iterations),
                                        requested=len(iterations), completed=list(iterations)),
                        results=results, inputs=dict(plans=artifact(directory, plan_path)),
                        effective_config=artifact(directory, config), metrics=[])
        atomic_json(directory / MANIFEST, manifest)
        return directory

    def analyze(self, directory, **kwargs):
        with redirect_stdout(io.StringIO()):
            return simz1_analysis.analyze_run(directory, latest_path=self.latest, **kwargs)

    def analysis_folder(self, directory, iteration=0):
        return directory / 'analysis' / f'it.{iteration}'

    def snapshot(self, folder):
        return {path.relative_to(folder).as_posix(): (path.read_bytes(), path.stat().st_mtime_ns)
                for path in folder.rglob('*') if path.is_file()}

    def report(self, directory, iteration=0):
        path = self.analysis_folder(directory, iteration) / 'graficas_perfiles' / 'resumen_perfiles.json'
        return json.loads(path.read_text(encoding='utf-8'))

    def test_short_windows_stage_path_avoids_max_path_and_long_paths_fail_early(self):
        # The former .analysis-staging/TIMESTAMP-UUID generated 261-character
        # PNG paths in the user's real Windows worktree; cars/motos saved but
        # comparacion_familias_por_hora.png then failed with WinError 2.
        from pathlib import PureWindowsPath
        root = PureWindowsPath(
            r'C:\Users\gegdg\Documents\.UVG\Sim\matsim-guatemala\scenarios\zona1\montecarlo'
            r'\run-massive-fixed-97e840b02c044fc39497debc91300a6d\analysis\it.0'
        )
        long = root / '.analysis-staging' / ('20261022T225751-' + 'a'*32) / 'graficas_perfiles' / 'comparacion_familias_por_hora.png'
        short = root / '.stg' / ('a'*16) / 'graficas_perfiles' / 'comparacion_familias_por_hora.png'
        self.assertGreaterEqual(len(str(long)), 260)
        self.assertLess(len(str(short)), 248)
        simz1_analysis.validate_windows_paths(self.root / 'short', 'a'*16, windows=True)
        with self.assertRaises(OSError) as caught:
            simz1_analysis.validate_windows_paths(self.root / ('z'*230), 'a'*16, windows=True)
        self.assertEqual(caught.exception.errno, __import__('errno').ENAMETOOLONG)

    def test_validated_run_real_six_profile_artifacts_and_provenance(self):
        directory = self.make_run()
        original_manifest = (directory / MANIFEST).read_bytes()
        result = self.analyze(directory)
        self.assertEqual(result['status'], 'completed')
        folder = self.analysis_folder(directory)
        analysis = json.loads((folder / 'analysis-manifest.json').read_text(encoding='utf-8'))
        state = json.loads((folder / 'analysis-status.json').read_text(encoding='utf-8'))
        self.assertEqual(state['status'], 'completed')
        self.assertEqual(analysis['run_id'], load_manifest(directory)['run_id'])
        self.assertEqual(analysis['iteration'], 0)
        self.assertTrue(analysis['generated_utc'])
        self.assertTrue(analysis['sources'])
        self.assertTrue(analysis['fingerprint'])
        for item in analysis['artifacts']:
            target = folder / item['path']
            self.assertEqual(item['sha256'], sha256(target))
            self.assertEqual(item['size_bytes'], target.stat().st_size)
        tracked = {item['path'] for item in analysis['artifacts']}
        self.assertIn('trips.csv.gz', tracked)
        self.assertTrue({f'graficas_perfiles/{filename}' for filename in IMAGES}.issubset(tracked))
        from PIL import Image
        for filename in IMAGES:
            with Image.open(folder / 'graficas_perfiles' / filename) as picture:
                self.assertEqual(picture.format, 'PNG')
                self.assertGreater(picture.width, 500)
        report = self.report(directory)
        self.assertEqual(report['distribution']['n_complete'], 144)
        self.assertEqual({row['profile'] for row in report['profiles'] if row['n_complete']}, set(PROFILES))
        self.assertEqual({row['hour'] for row in report['profile_hour']}, set(range(24)))
        self.assertEqual(report['distribution']['mean_minutes'], 3.5)
        self.assertEqual((directory / MANIFEST).read_bytes(), original_manifest)
        self.assertEqual(len(list(folder.rglob('*.png'))), 6)
        self.assertFalse(list(directory.rglob('*.html')))
        self.assertFalse(list(directory.rglob('*.sqlite')))
        self.assertFalse(list(directory.rglob('*Motion_Plan*')))

    def test_absent_motorcycles_remain_without_data(self):
        directory = self.make_run(PROFILES[:3])
        with patch('simz1_analysis.plot_profile_analysis', side_effect=fixture_renderer):
            self.assertEqual(self.analyze(directory)['status'], 'completed')
        report = self.report(directory)
        self.assertEqual(report['distribution']['n_complete'], 72)
        for group in report['profiles']:
            if group['profile'] in PROFILES[3:]:
                self.assertEqual(group['n_complete'], 0)
                self.assertIsNone(group['mean_minutes'])
                self.assertEqual(group['sample_status'], 'sin datos')
        self.assertEqual(sum(group['n_complete'] for group in report['families']), 72)

    def test_failed_running_or_unvalidated_run_is_rejected_before_processing(self):
        for status, validation in [('failed', 'invalid'), ('running', 'pending'), ('completed', 'invalid')]:
            with self.subTest(status=status, validation=validation):
                directory = self.make_run(name=status + '-' + validation, status=status, validation=validation)
                before = self.snapshot(directory)
                with patch('simz1_analysis.export_table', side_effect=AssertionError('no event processing')):
                    with self.assertRaisesRegex(ValueError, 'Corrida no valida'):
                        self.analyze(directory)
                self.assertEqual(self.snapshot(directory), before)

    def test_repeated_execution_reuses_identical_results_without_replay_or_rewrite(self):
        directory = self.make_run()
        with patch('simz1_analysis.plot_profile_analysis', side_effect=fixture_renderer):
            self.assertEqual(self.analyze(directory)['status'], 'completed')
        folder = self.analysis_folder(directory)
        before = self.snapshot(folder / 'graficas_perfiles')
        canonical = folder / 'trips.csv.gz'
        table_before = (canonical.read_bytes(), canonical.stat().st_mtime_ns)
        manifest_before = (folder / 'analysis-manifest.json').read_bytes()
        with patch('simz1_analysis.plot_profile_analysis', side_effect=AssertionError('no duplicate plots')), \
                patch('simz1_trip_table.write_events', side_effect=AssertionError('no event replay')):
            second = self.analyze(directory)
        self.assertEqual(second['status'], 'completed')
        self.assertTrue(second['iterations'][0]['reused'])
        self.assertEqual(before, self.snapshot(folder / 'graficas_perfiles'))
        self.assertEqual(table_before, (canonical.read_bytes(), canonical.stat().st_mtime_ns))
        self.assertEqual(manifest_before, (folder / 'analysis-manifest.json').read_bytes())

    def test_two_iterations_get_independent_tables_profiles_and_identities(self):
        directory = self.make_run(iterations=(0, 1))
        with patch('simz1_analysis.plot_profile_analysis', side_effect=fixture_renderer) as render:
            result = self.analyze(directory, all_iterations=True)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(render.call_count, 2)
        self.assertEqual([item['iteration'] for item in result['iterations']], [0, 1])
        for iteration in (0, 1):
            report = self.report(directory, iteration)
            self.assertEqual(report['iteration'], iteration)
            self.assertEqual(report['run_id'], load_manifest(directory)['run_id'])
            self.assertAlmostEqual(report['distribution']['mean_minutes'], 3.5 + iteration / 60)
        self.assertNotEqual(sha256(self.analysis_folder(directory, 0) / 'trips.csv.gz'),
                            sha256(self.analysis_folder(directory, 1) / 'trips.csv.gz'))

    def test_interrupted_analysis_keeps_science_and_retry_completes(self):
        directory = self.make_run(PROFILES[:3])
        scientific = self.snapshot(directory)

        def interrupted(table, destination, *args, **kwargs):
            Path(destination).mkdir(parents=True)
            (Path(destination) / 'partial.png').write_bytes(b'incomplete staging')
            raise KeyboardInterrupt()

        with patch('simz1_analysis.plot_profile_analysis', side_effect=interrupted):
            failed = self.analyze(directory)
        self.assertEqual(failed['status'], 'analysis_failed')
        self.assertTrue(failed['iterations'][0]['interrupted'])
        self.assertEqual(load_manifest(directory)['status'], 'completed')
        self.assertEqual(load_manifest(directory)['validation']['status'], 'valid')
        self.assertFalse((self.analysis_folder(directory) / 'analysis-manifest.json').exists())
        for name, state in scientific.items():
            path = directory / name
            self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), state)
        with patch('simz1_analysis.plot_profile_analysis', side_effect=fixture_renderer):
            self.assertEqual(self.analyze(directory)['status'], 'completed')
        self.assertEqual(self.report(directory)['distribution']['n_complete'], 72)
        self.assertFalse((self.analysis_folder(directory) / 'graficas_perfiles' / 'partial.png').exists())

    def test_insufficient_disk_does_not_process_events_or_change_scientific_outputs(self):
        directory = self.make_run(PROFILES[:3])
        original = self.snapshot(directory)
        usage = namedtuple('usage', 'total used free')(1024, 1024, 0)
        with patch('simz1_analysis.shutil.disk_usage', return_value=usage), \
                patch('simz1_analysis.export_table', side_effect=AssertionError('must fail before processing')):
            result = self.analyze(directory)
        self.assertEqual(result['status'], 'analysis_failed')
        self.assertRegex(result['iterations'][0]['error'].lower(), 'espacio|disco|space')
        for name, state in original.items():
            path = directory / name
            self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), state)
        self.assertFalse((self.analysis_folder(directory) / 'analysis-manifest.json').exists())

    def test_enospc_during_new_analysis_preserves_previous_valid_graphs_and_manifest(self):
        directory = self.make_run(PROFILES[:3])
        with patch('simz1_analysis.plot_profile_analysis', side_effect=fixture_renderer):
            self.assertEqual(self.analyze(directory)['status'], 'completed')
        folder = self.analysis_folder(directory)
        before = self.snapshot(folder / 'graficas_perfiles')
        manifest_before = (folder / 'analysis-manifest.json').read_bytes()
        science_before = (directory / MANIFEST).read_bytes()

        def disk_full(table, destination, *args, **kwargs):
            Path(destination).mkdir(parents=True)
            (Path(destination) / 'partial.png').write_bytes(b'partial write')
            raise OSError(errno.ENOSPC, 'No space left on device')

        with patch('simz1_analysis.plot_profile_analysis', side_effect=disk_full):
            result = self.analyze(directory, min_sample=31)
        self.assertEqual(result['status'], 'analysis_failed')
        self.assertRegex(result['iterations'][0]['error'].lower(), 'espacio|disco|space')
        self.assertEqual(self.snapshot(folder / 'graficas_perfiles'), before)
        self.assertEqual((folder / 'analysis-manifest.json').read_bytes(), manifest_before)
        self.assertEqual((directory / MANIFEST).read_bytes(), science_before)
        self.assertEqual(load_manifest(directory)['validation']['status'], 'valid')
        with patch('simz1_analysis.plot_profile_analysis', side_effect=fixture_renderer):
            retried = self.analyze(directory, min_sample=31)
        self.assertEqual(retried['status'], 'completed')
        self.assertFalse(retried['iterations'][0]['reused'])

    def test_manual_cli_all_iterations_forwards_flags_and_analysis_failure_exit_code(self):
        import generar_graficas_z1
        directory = self.root / 'old run with spaces'
        output = self.root / 'alternative analysis'
        arguments = ['generar_graficas_z1.py', '--run-dir', str(directory),
                     '--profiles-only', '--all-iterations', '--analysis-dir', str(output),
                     '--min-sample', '12']
        completed = dict(status='completed', run_id='fixture', iterations=[
            dict(status='completed', iteration=0, directory=str(output / 'it.0'), reused=True)])
        with patch.object(sys, 'argv', arguments), redirect_stdout(io.StringIO()), \
                patch('simz1_analysis.analyze_run', return_value=completed) as analyze:
            generar_graficas_z1.main()
        analyze.assert_called_once_with(directory, all_iterations=True, analysis_dir=output, min_sample=12)
        failed = dict(status='analysis_failed', run_id='fixture', iterations=[
            dict(status='analysis_failed', iteration=0, directory=str(output / 'it.0'),
                 error='fixture disk full')])
        with patch.object(sys, 'argv', arguments), redirect_stdout(io.StringIO()), \
                redirect_stderr(io.StringIO()), patch('simz1_analysis.analyze_run', return_value=failed):
            with self.assertRaises(SystemExit) as exited:
                generar_graficas_z1.main()
        self.assertEqual(exited.exception.code, 2)

    def test_manual_cli_single_iteration_uses_only_requested_profile_analysis(self):
        import generar_graficas_z1
        directory = self.make_run(iterations=(0, 1))
        arguments = ['generar_graficas_z1.py', '--run-dir', str(directory),
                     '--profiles-only', '--iteration', '0']
        with redirect_stdout(io.StringIO()):
            selection = select_run(directory, 0, latest_path=self.latest, require_events=False)
        with patch.object(sys, 'argv', arguments), redirect_stdout(io.StringIO()), \
                patch('simz1_run.select_run', return_value=selection) as select, \
                patch('simz1_analysis.plot_profile_analysis', side_effect=fixture_renderer), \
                patch('simz1_trip_distributions.plot_distributions', side_effect=AssertionError('no legacy images')), \
                patch('simz1_trip_distributions.follow_person', side_effect=AssertionError('no individual images')):
            generar_graficas_z1.main()
        select.assert_called_once_with(directory, 0, require_events=False)
        self.assertTrue(self.analysis_folder(directory, 0).is_dir())
        self.assertFalse(self.analysis_folder(directory, 1).exists())

    def test_documented_massive_launcher_command_parses_and_forwards_without_running(self):
        import ejecutar_simz1
        directory = self.root / 'future massive run'
        config = self.root / 'config-simz1.xml'
        maven = self.root / 'mvnw.cmd'
        arguments = [
            'ejecutar_simz1.py', '--config', str(config), '--maven', str(maven),
            '--run-dir', str(directory), '--mode', 'montecarlo', '--massive',
            '--min-agents', '150000', '--max-agents', '250000', '--seed', '20261022',
            '--matsim-seed', '20261022', '--iterations', '1', '--od-mode', 'network',
            '--corridor-policy', 'redistribute', '--no-incidents', '--qsim-threads', '4',
            '--temporal-profile', 'full-day', '--trips-per-person', '1', '--drain-seconds', '0']
        with patch.object(sys, 'argv', arguments), \
                patch('ejecutar_simz1.generar', return_value=dict(run_dir=str(directory))) as generate, \
                patch('ejecutar_simz1.ejecutar', return_value=dict(analysis=dict(status='completed'))) as execute:
            ejecutar_simz1.main()
        self.assertEqual(generate.call_args.args, (config, directory, 20261022))
        options = generate.call_args.kwargs
        for field, value in dict(mode='montecarlo', massive=True, min_agents=150000,
                                 max_agents=250000, matsim_seed=20261022, od_mode='network',
                                 corridor_policy='redistribute', incidents=False, qsim_threads=4,
                                 temporal_profile='full-day', trips_per_person=1, drain_seconds=0).items():
            self.assertEqual(options[field], value)
        execute.assert_called_once_with(directory, maven, False, 1)
        self.assertFalse(directory.exists())
        with patch.object(sys, 'argv', arguments), redirect_stderr(io.StringIO()), \
                patch('ejecutar_simz1.generar', return_value=dict(run_dir=str(directory))), \
                patch('ejecutar_simz1.ejecutar', return_value=dict(analysis=dict(status='analysis_failed'))):
            with self.assertRaises(SystemExit) as exited:
                ejecutar_simz1.main()
        self.assertEqual(exited.exception.code, 2)

    def test_generator_run_matsim_cli_reports_analysis_failed_separately(self):
        import generate_montecarlo_z1
        directory = self.root / 'mock generated run'
        arguments = ['generate_montecarlo_z1.py', '--run-dir', str(directory),
                     '--agents', '2', '--run-matsim']
        with patch.object(sys, 'argv', arguments), redirect_stdout(io.StringIO()), \
                redirect_stderr(io.StringIO()), \
                patch('generate_montecarlo_z1.generar', return_value=dict(run_dir=str(directory))), \
                patch('ejecutar_simz1.ejecutar', return_value=dict(analysis=dict(status='analysis_failed'))) as execute:
            with self.assertRaises(SystemExit) as exited:
                generate_montecarlo_z1.main()
        self.assertEqual(exited.exception.code, 2)
        execute.assert_called_once_with(directory)
        self.assertFalse(directory.exists())

    def test_post_analysis_exception_cannot_change_published_matsim_state(self):
        import ejecutar_simz1
        directory = self.make_run(PROFILES[:3])
        before = (directory / MANIFEST).read_bytes()
        reference = dict(run_id=load_manifest(directory)['run_id'], folder=str(directory),
                         manifest_sha256=sha256(directory / MANIFEST))
        atomic_json(self.latest, reference)
        reference_before = self.latest.read_bytes()
        with patch('simz1_analysis.analyze_run', side_effect=RuntimeError('fixture analysis failure')) as analyze, \
                redirect_stderr(io.StringIO()):
            result = ejecutar_simz1.run_post_analysis(directory, self.latest)
        analyze.assert_called_once_with(directory, all_iterations=True, latest_path=self.latest)
        self.assertEqual(result['status'], 'analysis_failed')
        self.assertEqual((directory / MANIFEST).read_bytes(), before)
        self.assertEqual(self.latest.read_bytes(), reference_before)
        self.assertEqual(load_manifest(directory)['status'], 'completed')
        self.assertEqual(load_manifest(directory)['validation']['status'], 'valid')

    def test_launcher_publishes_validated_science_before_analysis_and_does_not_run_it_on_failure(self):
        import ejecutar_simz1
        from generate_montecarlo_z1 import generar, SCENARIO
        from test_simz1_run import fake_matsim
        directory = self.root / 'launcher successful fixture'
        failed_directory = self.root / 'launcher failed fixture'
        maven = self.root / 'fake-maven.cmd'
        maven.write_text('', encoding='utf-8')
        recorded = {}

        def after_publication(run_dir, latest_path):
            self.assertEqual(run_dir, directory)
            self.assertEqual(latest_path, self.latest)
            state = load_manifest(run_dir)
            self.assertEqual(state['status'], 'completed')
            self.assertEqual(state['validation']['status'], 'valid')
            self.assertEqual(state['iterations']['completed'], [0, 1])
            self.assertNotIn('analysis', state)
            reference = json.loads(self.latest.read_text(encoding='utf-8'))
            self.assertEqual(reference['manifest_sha256'], sha256(run_dir / MANIFEST))
            recorded['manifest'] = (run_dir / MANIFEST).read_bytes()
            recorded['reference'] = self.latest.read_bytes()
            return dict(status='analysis_failed', run_id=state['run_id'], iterations=[], error='fixture')

        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            generar(SCENARIO / 'config-simz1.xml', directory, 31, agents=2,
                    corridor_policy='redistribute', drain_seconds=0)
            with patch('ejecutar_simz1.ejecutar_con_salida_en_vivo', side_effect=fake_matsim), \
                    patch('ejecutar_simz1.run_post_analysis', side_effect=after_publication) as post:
                state = ejecutar_simz1.ejecutar(directory, maven, iterations=2, latest_path=self.latest)
            post.assert_called_once_with(directory, self.latest)
            self.assertEqual(state['analysis']['status'], 'analysis_failed')
            self.assertEqual(state['status'], 'completed')
            self.assertEqual((directory / MANIFEST).read_bytes(), recorded['manifest'])
            self.assertEqual(self.latest.read_bytes(), recorded['reference'])
            generar(SCENARIO / 'config-simz1.xml', failed_directory, 32, agents=2,
                    corridor_policy='redistribute', drain_seconds=0)
            with patch('ejecutar_simz1.ejecutar_con_salida_en_vivo', return_value=7), \
                    patch('ejecutar_simz1.run_post_analysis') as not_started:
                with self.assertRaisesRegex(RuntimeError, 'codigo 7'):
                    ejecutar_simz1.ejecutar(failed_directory, maven, iterations=1, latest_path=self.latest)
            not_started.assert_not_called()
        self.assertEqual(load_manifest(failed_directory)['status'], 'failed')
        self.assertEqual(self.latest.read_bytes(), recorded['reference'])

    def test_failure_during_publication_rolls_back_all_previous_results_and_retry_succeeds(self):
        directory = self.make_run(PROFILES[:3])
        with patch('simz1_analysis.plot_profile_analysis', side_effect=fixture_renderer):
            self.assertEqual(self.analyze(directory)['status'], 'completed')
        folder = self.analysis_folder(directory)
        before = {name: self.snapshot(folder / name) if (folder / name).is_dir()
                  else ((folder / name).read_bytes(), (folder / name).stat().st_mtime_ns)
                  for name in simz1_analysis.MANAGED_NAMES}
        original_replace = Path.replace
        interrupted = []

        def fail_one_replace(source, target):
            if (source.name == 'graficas_perfiles' and '.stg' in source.parts
                    and Path(target) == folder / 'graficas_perfiles' and not interrupted):
                interrupted.append(True)
                raise OSError(errno.ENOSPC, 'fixture ENOSPC during publication')
            return original_replace(source, target)

        with patch('simz1_analysis.plot_profile_analysis', side_effect=fixture_renderer), \
                patch.object(Path, 'replace', fail_one_replace):
            result = self.analyze(directory, min_sample=31)
        self.assertEqual(result['status'], 'analysis_failed')
        self.assertTrue(interrupted)
        self.assertFalse((folder / simz1_analysis.JOURNAL_NAME).exists())
        for name, state in before.items():
            path = folder / name
            actual = self.snapshot(path) if path.is_dir() else (path.read_bytes(), path.stat().st_mtime_ns)
            self.assertEqual(actual, state)
        with patch('simz1_analysis.plot_profile_analysis', side_effect=fixture_renderer):
            self.assertEqual(self.analyze(directory, min_sample=31)['status'], 'completed')

    def test_kernel_lock_prevents_duplicate_analysis_and_releases_for_retry(self):
        directory = self.make_run(PROFILES[:3])
        lock_path = directory / 'analysis' / '.it.0.analysis.lock'
        with simz1_analysis.AnalysisLock(lock_path) as owner:
            self.assertTrue(owner.acquired)
            with patch('simz1_analysis.export_table', side_effect=AssertionError('duplicate processing')):
                result = self.analyze(directory)
            self.assertEqual(result['iterations'][0]['status'], 'analysis_running')
            self.assertFalse((self.analysis_folder(directory) / simz1_analysis.STATUS_NAME).exists())
        with patch('simz1_analysis.plot_profile_analysis', side_effect=fixture_renderer):
            self.assertEqual(self.analyze(directory)['status'], 'completed')

    def test_tampered_embedded_specification_is_not_reused(self):
        directory = self.make_run(PROFILES[:3])
        with patch('simz1_analysis.plot_profile_analysis', side_effect=fixture_renderer):
            self.assertEqual(self.analyze(directory)['status'], 'completed')
        path = self.analysis_folder(directory) / simz1_analysis.MANIFEST_NAME
        corrupted = json.loads(path.read_text(encoding='utf-8'))
        corrupted['specification']['parameters']['min_sample'] = 999
        atomic_json(path, corrupted)
        with patch('simz1_analysis.plot_profile_analysis', side_effect=fixture_renderer) as renderer:
            result = self.analyze(directory)
        self.assertEqual(result['status'], 'completed')
        self.assertFalse(result['iterations'][0]['reused'])
        self.assertEqual(renderer.call_count, 1)
        self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['specification']['parameters']['min_sample'], 30)

    def test_reusing_valid_previous_outputs_repairs_stale_failure_status(self):
        directory = self.make_run(PROFILES[:3])
        with patch('simz1_analysis.plot_profile_analysis', side_effect=fixture_renderer):
            self.assertEqual(self.analyze(directory)['status'], 'completed')
        with patch('simz1_analysis.plot_profile_analysis', side_effect=RuntimeError('failed new parameters')):
            self.assertEqual(self.analyze(directory, min_sample=31)['status'], 'analysis_failed')
        folder = self.analysis_folder(directory)
        self.assertEqual(json.loads((folder / simz1_analysis.STATUS_NAME).read_text(encoding='utf-8'))['status'], 'analysis_failed')
        previous = self.snapshot(folder / 'graficas_perfiles')
        with patch('simz1_analysis.plot_profile_analysis', side_effect=AssertionError('must reuse valid outputs')):
            retried = self.analyze(directory)
        self.assertEqual(retried['status'], 'completed')
        self.assertTrue(retried['iterations'][0]['reused'])
        self.assertEqual(self.snapshot(folder / 'graficas_perfiles'), previous)
        self.assertEqual(json.loads((folder / simz1_analysis.STATUS_NAME).read_text(encoding='utf-8'))['status'], 'completed')


if __name__ == '__main__':
    unittest.main()
