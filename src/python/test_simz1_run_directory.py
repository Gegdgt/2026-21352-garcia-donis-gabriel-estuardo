"""Unique run allocation and launch contracts; only 1/100-person fixtures, no QSim."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid
import xml.etree.ElementTree as ET

import ejecutar_simz1 as launcher
import generate_montecarlo_z1 as generator
from simz1_run import MANIFEST, load_manifest, parameters, select_run, sha256
from simz1_run_directory import check_new_directory, create_run_directory
from test_simz1_run import fake_matsim


SOURCE_CONFIG = generator.SCENARIO / 'config-simz1.xml'


class RunDirectoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='simz1 automatic runs with spaces ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def test_consecutive_automatic_reservations_are_distinct_and_created(self):
        parent = self.root / 'automatic runs'
        first = create_run_directory(parent=parent)
        second = create_run_directory(parent=parent)
        self.assertNotEqual(first, second)
        for path in (first, second):
            self.assertTrue(path.is_absolute())
            self.assertTrue(path.is_dir())
            self.assertEqual(path.parent, parent)
        self.assertEqual(set(parent.iterdir()), {first, second})

    def test_automatic_uuid_collision_retries_without_touching_existing_files(self):
        first_id, second_id = uuid.UUID(int=1), uuid.UUID(int=2)
        with patch('simz1_run_directory.uuid.uuid4', return_value=first_id):
            first = create_run_directory(parent=self.root)
        sentinel = first / 'results are immutable.txt'
        sentinel.write_text('previous result', encoding='utf-8')
        with patch('simz1_run_directory.uuid.uuid4', side_effect=[first_id, second_id]) as draw:
            second = create_run_directory(parent=self.root)
        self.assertEqual(draw.call_count, 2)
        self.assertNotEqual(first, second)
        self.assertEqual(sentinel.read_text(encoding='utf-8'), 'previous result')

    def test_explicit_empty_completed_interrupted_and_file_paths_are_rejected(self):
        for name in ('empty', 'completed', 'interrupted'):
            with self.subTest(name=name):
                directory = self.root / name
                directory.mkdir()
                if name != 'empty':
                    (directory / MANIFEST).write_text(json.dumps({'status': name}), encoding='utf-8')
                before = {p.name: p.read_bytes() for p in directory.iterdir()}
                for operation in (lambda: check_new_directory(directory),
                                  lambda: create_run_directory(directory, parent=self.root),
                                  lambda: generator.generar(SOURCE_CONFIG, directory, 31,
                                      agents=1, corridor_policy='redistribute')):
                    with self.assertRaisesRegex(ValueError, 'Usar una carpeta nueva para preservar corridas'):
                        operation()
                self.assertEqual(before, {p.name: p.read_bytes() for p in directory.iterdir()})
        existing_file = self.root / 'existing file'
        existing_file.write_text('do not overwrite', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Usar una carpeta nueva para preservar corridas'):
            create_run_directory(existing_file, parent=self.root)
        self.assertEqual(existing_file.read_text(encoding='utf-8'), 'do not overwrite')

    def test_two_processes_reserve_at_the_same_time(self):
        parent = self.root / 'concurrent runs'
        # Both interpreters block on stdin after import. Release both before
        # waiting for either result, exercising atomic mkdir in separate processes.
        script = '''import json,sys
from simz1_run_directory import create_run_directory
print("ready",flush=True)
sys.stdin.readline()
path=create_run_directory(parent=sys.argv[1])
(path/"owner.txt").write_text(str(__import__("os").getpid()),encoding="utf-8")
print(json.dumps(str(path)),flush=True)
'''
        env = os.environ.copy()
        env['PYTHONPATH'] = str(Path(__file__).resolve().parent)
        processes = [subprocess.Popen([sys.executable, '-c', script, str(parent)],
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         text=True, env=env) for _ in range(2)]
        try:
            for process in processes:
                self.assertEqual(process.stdout.readline().strip(), 'ready')
            for process in processes:
                process.stdin.write('go\n')
                process.stdin.flush()
            paths = []
            for process in processes:
                stdout, stderr = process.communicate(timeout=20)
                self.assertEqual(process.returncode, 0, stdout + stderr)
                paths.append(Path(json.loads(stdout.strip())))
            self.assertNotEqual(*paths)
            self.assertEqual(set(parent.iterdir()), set(paths))
            owners = {(path / 'owner.txt').read_text(encoding='utf-8') for path in paths}
            self.assertEqual(len(owners), 2)
        finally:
            for process in processes:
                if process.poll() is None:
                    process.kill()
                process.communicate()

    def test_explicit_path_race_does_not_reuse_the_winning_directory(self):
        directory = self.root / 'explicit contention'
        self.assertEqual(check_new_directory(directory), directory)
        directory.mkdir()  # Another process wins between preflight and reservation.
        sentinel = directory / 'owner.txt'
        sentinel.write_text('other process', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Usar una carpeta nueva para preservar corridas'):
            create_run_directory(directory, parent=self.root)
        self.assertEqual(sentinel.read_text(encoding='utf-8'), 'other process')

    @unittest.skipUnless(os.name == 'nt', 'Windows junction semantics')
    def test_explicit_dangling_junction_is_an_existing_destination(self):
        import _winapi
        target, alias = self.root / 'junction target', self.root / 'junction alias'
        target.mkdir()
        _winapi.CreateJunction(str(target), str(alias))
        target.rmdir()
        try:
            self.assertTrue(os.path.lexists(alias))
            self.assertFalse(alias.exists())
            for operation in (lambda: check_new_directory(alias),
                              lambda: create_run_directory(alias, parent=self.root)):
                with self.assertRaisesRegex(ValueError, 'Usar una carpeta nueva para preservar corridas'):
                    operation()
            self.assertFalse(target.exists())
        finally:
            alias.rmdir()  # Remove only this reparse entry, never its target tree.


class AutomaticLauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='simz1 automatic launches with spaces ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.latest = self.root / 'references' / 'latest-successful.json'
        self.maven = self.root / 'fake maven.cmd'
        self.maven.write_text('', encoding='utf-8')

    def launch_arguments(self, *arguments):
        return ['ejecutar_simz1.py', '--config', str(SOURCE_CONFIG), '--seed', '31',
                '--matsim-seed', '1031', '--corridor-policy', 'redistribute',
                '--iterations', '1', *arguments]

    def launch_fixture(self, agents, side_effect=fake_matsim):
        captured = []
        actual_execute = launcher.ejecutar
        def execute_isolated(directory, maven, offline, iterations):
            captured.append(directory)
            return actual_execute(directory, self.maven, offline, iterations, latest_path=self.latest)
        arguments = self.launch_arguments('--agents', str(agents), '--no-use-lanes',
            '--signals', '--no-within-day-routing', '--temporal-profile', 'full-day')
        with patch.object(sys, 'argv', arguments), patch.object(generator, 'SCENARIO', self.root), \
             patch.object(launcher, 'ejecutar', side_effect=execute_isolated), \
             patch.object(launcher, 'ejecutar_con_salida_en_vivo', side_effect=side_effect), \
             contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            launcher.main()
        self.assertEqual(len(captured), 1)
        return captured[0]

    def test_one_and_hundred_people_launches_validate_without_changing_requested_counts(self):
        selected = []
        for count in (1, 100):
            directory = self.launch_fixture(count)
            state = load_manifest(directory)
            self.assertEqual(state['status'], 'completed')
            self.assertEqual(state['validation']['status'], 'valid')
            self.assertEqual(state['counts']['planned_persons'], count)
            self.assertEqual(state['counts']['planned_trips'], count)
            self.assertEqual(state['iterations']['completed'], [0])
            self.assertEqual(state['demand_seed'], 31)
            self.assertEqual(state['matsim_seed'], 1031)
            persons = ET.parse(directory / 'plans.xml').findall('person')
            self.assertEqual(len(persons), count)
            self.assertEqual(len({p.get('id') for p in persons}), count)
            options = parameters(directory / 'config-simz1.xml')
            self.assertEqual(options['qsim.useLanes'], 'false')
            self.assertEqual(options['signalsystems.useSignalsystems'], 'true')
            self.assertEqual(options['zona1WithinDayRouting.enabled'], 'false')
            self.assertEqual(options['controler.lastIteration'], '0')
            self.assertEqual(json.loads(self.latest.read_text(encoding='utf-8'))['run_id'], state['run_id'])
            attempt = json.loads(self.latest.with_name('latest-attempt.json').read_text(encoding='utf-8'))
            self.assertEqual(attempt['folder'], str(directory))
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(select_run(latest_path=self.latest)['directory'], directory)
            selected.append(directory)
        self.assertNotEqual(*selected)
        self.assertNotEqual(*(load_manifest(path)['run_id'] for path in selected))

    def test_repeated_seed_produces_distinct_folders_but_identical_demand(self):
        with patch.object(generator, 'SCENARIO', self.root), contextlib.redirect_stdout(io.StringIO()):
            reports = [generator.generar(SOURCE_CONFIG, None, 31, agents=1,
                       corridor_policy='redistribute') for _ in range(2)]
        paths = [Path(report['run_dir']) for report in reports]
        self.assertNotEqual(*paths)
        self.assertNotEqual(*(report['run_id'] for report in reports))
        for relative in ('plans.xml', 'inputs/vehicles.xml'):
            self.assertEqual(*(sha256(path / relative) for path in paths))
        for path in paths:
            self.assertEqual(load_manifest(path)['demand_seed'], 31)

    def test_interrupt_preserves_successful_reference_and_records_new_attempt(self):
        previous = self.launch_fixture(1)
        successful_bytes = self.latest.read_bytes()
        with self.assertRaises(SystemExit) as stopped:
            self.launch_fixture(100, KeyboardInterrupt())
        self.assertEqual(stopped.exception.code, 130)
        self.assertEqual(self.latest.read_bytes(), successful_bytes)
        attempt = json.loads(self.latest.with_name('latest-attempt.json').read_text(encoding='utf-8'))
        interrupted = Path(attempt['folder'])
        self.assertNotEqual(previous, interrupted)
        state = load_manifest(interrupted)
        self.assertEqual(state['status'], 'interrupted')
        self.assertEqual(state['counts']['planned_persons'], 100)
        self.assertEqual(state['failure_category'], 'manual_interruption')
        self.assertEqual(state['validation']['status'], 'invalid')
        self.assertEqual(attempt['run_id'], state['run_id'])
        with self.assertRaisesRegex(ValueError, 'Usar una carpeta nueva para preservar corridas'):
            generator.generar(SOURCE_CONFIG, interrupted, 31, agents=100, corridor_policy='redistribute')
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            selection = select_run(latest_path=self.latest)
        self.assertEqual(selection['directory'], previous)
        self.assertIn('interrupted', selection['selection_warning'])

    def test_large_range_is_forwarded_unchanged_without_generating_large_demand(self):
        directory = self.root / 'mock generated run'
        arguments = self.launch_arguments('--massive', '--min-agents', '150000', '--max-agents', '250000',
            '--use-lanes', '--no-signals', '--within-day-routing', '--reroute-budget', '7',
            '--routing-share', '0.25', '--temporal-profile', 'peaks', '--drain-seconds', '2400')
        with patch.object(sys, 'argv', arguments), \
             patch.object(launcher, 'generar', return_value={'run_dir': str(directory)}) as generate, \
             patch.object(launcher, 'ejecutar') as execute:
            launcher.main()
        positional, options = generate.call_args
        self.assertEqual(positional, (SOURCE_CONFIG, None, 31))
        self.assertIsNone(options['agents'])
        self.assertEqual((options['min_agents'], options['max_agents']), (150000, 250000))
        self.assertTrue(options['massive'])
        self.assertEqual(options['matsim_seed'], 1031)
        self.assertTrue(options['use_lanes'])
        self.assertFalse(options['signals'])
        self.assertTrue(options['within_day_routing'])
        self.assertEqual(options['reroute_budget'], 7)
        self.assertEqual(options['routing_share'], 0.25)
        self.assertEqual(options['temporal_profile'], 'peaks')
        self.assertEqual(options['drain_seconds'], 2400)
        execute.assert_called_once_with(directory, None, False, 1)

    def test_explicit_existing_directory_stops_launcher_without_changing_files(self):
        directory = self.root / 'saved run'
        directory.mkdir()
        sentinel = directory / 'original results.txt'
        sentinel.write_text('keep original', encoding='utf-8')
        error = io.StringIO()
        arguments = self.launch_arguments('--run-dir', str(directory), '--agents', '1')
        with patch.object(sys, 'argv', arguments), patch.object(launcher, 'ejecutar') as execute, \
             contextlib.redirect_stderr(error), self.assertRaises(SystemExit) as stopped:
            launcher.main()
        self.assertEqual(stopped.exception.code, 1)
        self.assertIn('Usar una carpeta nueva para preservar corridas', error.getvalue())
        execute.assert_not_called()
        self.assertEqual(sentinel.read_text(encoding='utf-8'), 'keep original')
        self.assertEqual(list(directory.iterdir()), [sentinel])
        self.assertFalse(self.latest.exists())

    def test_standalone_generator_executes_the_returned_automatic_directory(self):
        directory = self.root / 'standalone generated run'
        arguments = ['generate_montecarlo_z1.py', '--config', str(SOURCE_CONFIG),
                     '--seed', '41', '--agents', '1', '--corridor-policy', 'redistribute',
                     '--run-matsim']
        output = io.StringIO()
        with patch.object(sys, 'argv', arguments), \
             patch.object(generator, 'generar', return_value={'run_dir': str(directory)}) as generate, \
             patch.object(launcher, 'ejecutar') as execute, contextlib.redirect_stdout(output):
            generator.main()
        self.assertEqual(generate.call_args.args, (SOURCE_CONFIG, None, 41))
        self.assertEqual(generate.call_args.kwargs['agents'], 1)
        execute.assert_called_once_with(directory)
        self.assertIn(str(directory / 'config-simz1.xml'), output.getvalue())

    def test_invalid_population_and_missing_corridor_policy_create_no_automatic_directory(self):
        cases = ({'agents': 0, 'corridor_policy': 'redistribute'},
                 {'agents': 1, 'min_agents': 1, 'max_agents': 100, 'corridor_policy': 'redistribute'},
                 {'min_agents': 100, 'max_agents': 1, 'corridor_policy': 'redistribute'},
                 {'agents': 1})
        with patch.object(generator, 'SCENARIO', self.root):
            for options in cases:
                with self.subTest(options=options), self.assertRaises(ValueError):
                    generator.generar(SOURCE_CONFIG, None, 31, **options)
                self.assertFalse((self.root / 'montecarlo').exists())


if __name__ == '__main__':
    unittest.main()
