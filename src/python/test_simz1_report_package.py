"""Real filesystem and failure recovery tests; never invoke MATSim."""
from contextlib import contextmanager, redirect_stdout, redirect_stderr
import csv
import ctypes
from ctypes import wintypes
import errno
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image
import simz1_report_package as pkg

PROJECT = Path(__file__).resolve().parents[1]


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding='utf-8')


@contextmanager
def windows_handle_without_delete(path):
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateFileW(str(path), 0x80000000, 3, None, 3, 0x80, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        yield
    finally:
        if not kernel.CloseHandle(handle):
            raise ctypes.WinError(ctypes.get_last_error())


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='simz1-pkg-')
        self.addCleanup(self.temp.cleanup)
        self.run = Path(self.temp.name) / 'run-fixture'
        self.root = self.run / 'entregables'
        save_json(self.run / 'run-manifest.json', {
            'run_id': 'simz1-fixture', 'status': 'completed',
            'validation': {'status': 'valid'}, 'iterations': {'completed': [0]}})
        self.make_iteration(0)
        self.analysis = self.run / 'analysis/it.0'
        self.source = self.analysis / 'graficas_perfiles'
        for rel in ('output/events.xml', 'plans.xml', 'inputs/network.xml',
                    'output/replay.sqlite', 'output/Motion_Plan.json'):
            path = self.run / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(('native sentinel ' + rel).encode())
        self.native_before = self.snapshot_native()
        self.addCleanup(self.assert_native_unchanged)

    def snapshot_native(self):
        return {p.relative_to(self.run).as_posix(): p.read_bytes()
                for p in self.run.rglob('*') if p.is_file()
                and p.parts[len(self.run.parts)] not in ('analysis', 'entregables')}

    def assert_native_unchanged(self):
        self.assertEqual(self.snapshot_native(), self.native_before)

    def make_iteration(self, iteration, revision=0):
        analysis = self.run / 'analysis' / f'it.{iteration}'
        charts = analysis / 'graficas_perfiles'
        charts.mkdir(parents=True, exist_ok=True)
        for name in sorted(pkg.REQUIRED_IMAGES):
            with Image.new('RGB', (4, 4), (iteration * 20, revision, 100)) as img:
                img.save(charts / name)
        save_json(charts / 'resumen_perfiles.json', {'iteration': iteration, 'revision': revision})
        save_json(charts / 'calidad_resultados.json', {'status': 'review_required'})
        (charts / 'estadisticas_por_perfil_hora.csv').write_text(
            f'iteration,revision\n{iteration},{revision}\n', encoding='utf-8')
        save_json(analysis / 'trips.csv.provenance.json', {'iteration': iteration})
        (analysis / 'trips.csv.gz').write_bytes(b'canonical table not copied')
        records = [{'path': p.relative_to(analysis).as_posix(), 'size_bytes': p.stat().st_size,
                    'sha256': pkg.file_sha(p)} for p in sorted(analysis.rglob('*')) if p.is_file()
                   and p.name not in ('analysis-manifest.json', 'analysis-status.json')]
        fingerprint = f'fixture-it{iteration}-revision{revision}'
        save_json(analysis / 'analysis-manifest.json', {
            'status': 'completed', 'run_id': 'simz1-fixture', 'iteration': iteration,
            'fingerprint': fingerprint, 'artifacts': records})
        save_json(analysis / 'analysis-status.json', {
            'status': 'completed', 'run_id': 'simz1-fixture', 'iteration': iteration,
            'fingerprint': fingerprint,
            'manifest_sha256': pkg.file_sha(analysis / 'analysis-manifest.json')})

    def ten_iterations(self):
        for iteration in range(1, 10):
            self.make_iteration(iteration)
        path = self.run / 'run-manifest.json'
        manifest = pkg.read_json(path)
        manifest['iterations']['completed'] = list(range(10))
        save_json(path, manifest)
        self.native_before = self.snapshot_native()

    def final(self, iteration=0):
        return self.root / (self.run.name if iteration == 0 else self.run.name + f'-it.{iteration}')

    def verify_bundle(self, iteration, revision=0):
        report = self.final(iteration)
        self.assertEqual({p.name for p in report.iterdir()}, {'docs', 'graficas'})
        manifest = pkg.read_json(report / 'docs' / pkg.PACKAGE_MANIFEST)
        self.assertEqual(manifest['run_id'], 'simz1-fixture')
        self.assertEqual(manifest['iteration'], iteration)
        self.assertEqual(pkg.read_json(report / 'docs/resumen_perfiles.json'),
                         {'iteration': iteration, 'revision': revision})
        self.assertEqual(pkg.read_json(report / 'docs/calidad_resultados.json')['status'], 'review_required')
        for record in manifest['files']:
            copied = report / record['path']
            original = self.run / record['source']
            self.assertEqual(copied.read_bytes(), original.read_bytes())
            self.assertEqual(pkg.file_sha(copied), record['sha256'])
            if copied.suffix == '.json':
                json.loads(copied.read_text(encoding='utf-8'))
            elif copied.suffix == '.csv':
                with copied.open(encoding='utf-8', newline='') as stream:
                    self.assertEqual(list(csv.DictReader(stream)),
                                     [{'iteration': str(iteration), 'revision': str(revision)}])
            elif copied.suffix == '.png':
                with Image.open(copied) as image:
                    image.load()
                    self.assertEqual(image.getpixel((0, 0)), (iteration * 20, revision, 100))
        self.assertFalse(list(report.rglob('*.gz')))

    def cli(self, *extra):
        return subprocess.run([sys.executable, '-B', str(Path(pkg.__file__)), '--run-dir',
                               str(self.run), *extra], capture_output=True, text=True, timeout=30)

    def test_first_publication_then_reuse_preserves_bytes_and_times(self):
        self.assertFalse(pkg.pack(self.run)['reused'])
        self.verify_bundle(0)
        before = {p: (p.read_bytes(), p.stat().st_mtime_ns)
                  for p in self.final().rglob('*') if p.is_file()}
        self.assertTrue(pkg.pack(self.run)['reused'])
        self.assertEqual(before, {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in before})

    def test_legacy_version_reused_only_with_exact_sources(self):
        pkg.pack(self.run)
        path = self.final() / 'docs' / pkg.PACKAGE_MANIFEST
        manifest = pkg.read_json(path)
        manifest.pop('packager_version')
        save_json(path, manifest)
        before = path.read_bytes()
        self.assertTrue(pkg.pack(self.run)['reused'])
        self.assertEqual(path.read_bytes(), before)
        self.make_iteration(0, 1)
        self.assertFalse(pkg.pack(self.run)['reused'])
        self.verify_bundle(0, 1)

    def test_partial_nonempty_destination_kept_in_backup(self):
        final = self.final()
        final.mkdir(parents=True)
        (final / 'partial.txt').write_text('retain evidence', encoding='utf-8')
        self.assertFalse(pkg.pack(self.run)['reused'])
        self.verify_bundle(0)
        backups = list(self.root.glob('.pkg-old-it.0-*'))
        self.assertEqual(len(backups), 1)
        self.assertEqual((backups[0] / 'partial.txt').read_text(), 'retain evidence')

    def test_corrupt_package_replaced_with_backup(self):
        pkg.pack(self.run)
        (self.final() / 'docs/resumen_perfiles.json').write_text('changed', encoding='utf-8')
        self.assertFalse(pkg.pack(self.run)['reused'])
        self.verify_bundle(0)
        backup = next(self.root.glob('.pkg-old-it.0-*'))
        self.assertEqual((backup / 'docs/resumen_perfiles.json').read_text(), 'changed')

    def test_wrong_identity_version_iteration_empty_records_not_reused(self):
        pkg.pack(self.run)
        for field, value in [('run_id', 'wrong'), ('iteration', 9),
                             ('packager_version', 999), ('files', [])]:
            with self.subTest(field=field):
                path = self.final() / 'docs' / pkg.PACKAGE_MANIFEST
                manifest = pkg.read_json(path)
                manifest[field] = value
                save_json(path, manifest)
                self.assertFalse(pkg.pack(self.run)['reused'])
                self.verify_bundle(0)

    def test_unvalidated_run_rejected(self):
        path = self.run / 'run-manifest.json'
        manifest = pkg.read_json(path)
        manifest['validation']['status'] = 'invalid'
        save_json(path, manifest)
        self.native_before = self.snapshot_native()
        with self.assertRaisesRegex(ValueError, 'completed/valid'):
            pkg.pack(self.run)
        self.assertFalse(self.final().exists())

    def test_corrupt_analysis_rejected(self):
        (self.source / 'carros_por_hora.png').write_bytes(b'corrupted')
        with self.assertRaisesRegex(ValueError, 'modificado'):
            pkg.pack(self.run)
        self.assertFalse(self.final().exists())

    def test_analysis_identity_mismatch_rejected(self):
        path = self.analysis / 'analysis-manifest.json'
        manifest = pkg.read_json(path)
        manifest['fingerprint'] = 'different'
        save_json(path, manifest)
        with self.assertRaisesRegex(ValueError, 'incompatible'):
            pkg.pack(self.run)
        self.assertFalse(self.final().exists())

    def test_expected_run_id_rejects_wrong_directory(self):
        result = self.cli('--expected-run-id', 'wrong')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.final().exists())

    def test_ten_iterations_unique_content_and_second_cli_reuses_all(self):
        self.ten_iterations()
        first = self.cli('--all-iterations')
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        self.assertEqual(first.stdout.count('ENTREGABLE PUBLICADO'), 10)
        for iteration in range(10):
            self.verify_bundle(iteration)
        second = self.cli('--all-iterations')
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertEqual(second.stdout.count('ENTREGABLE REUTILIZADO'), 10)

    def test_failure_iteration_one_then_resume_preserves_other_nine(self):
        self.ten_iterations()
        rename = Path.rename
        def fail_one(source, destination):
            if destination == self.final(1):
                raise PermissionError(errno.EACCES, 'persistent fixture denial')
            return rename(source, destination)
        with patch.object(Path, 'rename', fail_one), patch.object(pkg.time, 'sleep'), \
                redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            code = pkg.main(['--run-dir', str(self.run), '--all-iterations'])
        self.assertEqual(code, 1)
        self.assertTrue(self.final(0).exists())
        self.assertFalse(self.final(1).exists())
        self.assertTrue(self.final(9).exists())
        prior = {p: (p.read_bytes(), p.stat().st_mtime_ns)
                 for n in range(10) if n != 1 for p in self.final(n).rglob('*') if p.is_file()}
        retry = self.cli('--all-iterations')
        self.assertEqual(retry.returncode, 0, retry.stdout + retry.stderr)
        self.assertEqual(retry.stdout.count('ENTREGABLE PUBLICADO'), 1)
        self.assertEqual(retry.stdout.count('ENTREGABLE REUTILIZADO'), 9)
        self.assertEqual(prior, {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in prior})
        for number in range(10):
            self.verify_bundle(number)

    def test_transient_access_has_bounded_retry(self):
        rename = Path.rename
        attempts = []
        def once(source, destination):
            attempts.append((source, destination))
            if len(attempts) == 1:
                raise PermissionError(errno.EACCES, 'transient fixture denial')
            return rename(source, destination)
        with patch.object(Path, 'rename', once), patch.object(pkg.time, 'sleep') as sleep:
            pkg.pack(self.run)
        self.assertEqual(len(attempts), 2)
        self.assertEqual(sleep.call_count, 1)
        self.verify_bundle(0)

    def test_persistent_denial_retains_stage_and_diagnostics(self):
        with patch.object(Path, 'rename', side_effect=PermissionError(errno.EACCES, 'persistent denial')) as rename, \
                patch.object(pkg.time, 'sleep'):
            with self.assertRaises(PermissionError):
                pkg.pack(self.run)
        self.assertEqual(rename.call_count, len(pkg.RETRY_DELAYS) + 1)
        self.assertFalse(self.final().exists())
        self.assertTrue(list(self.root.glob('.pkg-it.0-*')))
        diagnostics = list(self.root.glob('.pkg-failure-it.0-*.json'))
        self.assertTrue(diagnostics)
        diagnostic = pkg.read_json(diagnostics[-1])
        self.assertIn('persistent denial', json.dumps(diagnostic))
        self.assertIn('traceback', diagnostic)
        self.assertEqual(diagnostic['iteration'], 0)
        self.assertEqual(diagnostic['run_id'], 'simz1-fixture')

    @unittest.skipUnless(os.name == 'nt', 'Windows sharing test')
    def test_real_windows_winerror5_recovers_after_handle_closes(self):
        rename = Path.rename
        errors, attempts = [], []
        def held_once(source, destination):
            attempts.append((source, destination))
            if len(attempts) == 1:
                with windows_handle_without_delete(source / 'docs/analysis-manifest.json'):
                    try:
                        return rename(source, destination)
                    except OSError as error:
                        errors.append(error.winerror)
                        raise
            return rename(source, destination)
        with patch.object(Path, 'rename', held_once):
            pkg.pack(self.run)
        self.assertEqual(errors, [5])
        self.assertEqual(len(attempts), 2)
        self.verify_bundle(0)

    @unittest.skipUnless(os.name == 'nt', 'Windows sharing test')
    def test_real_windows_persistent_denial_bounded_then_recovery(self):
        rename = Path.rename
        errors = []
        def held(source, destination):
            with windows_handle_without_delete(source / 'docs/analysis-manifest.json'):
                try:
                    return rename(source, destination)
                except OSError as error:
                    errors.append(error.winerror)
                    raise
        with patch.object(Path, 'rename', held):
            with self.assertRaises(PermissionError):
                pkg.pack(self.run)
        self.assertEqual(errors, [5] * (len(pkg.RETRY_DELAYS) + 1))
        self.assertFalse(self.final().exists())
        self.assertFalse(pkg.pack(self.run)['reused'])
        self.verify_bundle(0)

    def test_failed_replacement_rolls_back_previous_complete_package(self):
        pkg.pack(self.run)
        old = {p.relative_to(self.final()): p.read_bytes() for p in self.final().rglob('*') if p.is_file()}
        self.make_iteration(0, 1)
        rename = Path.rename
        def fail_publication(source, destination):
            if destination == self.final() and not source.name.startswith('.pkg-old-'):
                raise PermissionError(errno.EACCES, 'publication failure')
            return rename(source, destination)
        with patch.object(Path, 'rename', fail_publication), patch.object(pkg.time, 'sleep'):
            with self.assertRaises(PermissionError):
                pkg.pack(self.run)
        self.assertEqual(old, {p.relative_to(self.final()): p.read_bytes()
                               for p in self.final().rglob('*') if p.is_file()})
        self.assertFalse(pkg.pack(self.run)['reused'])
        self.verify_bundle(0, 1)

    def test_failed_rollback_keeps_backup_and_next_call_recovers(self):
        pkg.pack(self.run)
        old_manifest = (self.final() / 'docs' / pkg.PACKAGE_MANIFEST).read_bytes()
        self.make_iteration(0, 1)
        rename = Path.rename
        def fail_both(source, destination):
            if destination == self.final():
                raise PermissionError(errno.EACCES, 'publication and rollback failure')
            return rename(source, destination)
        with patch.object(Path, 'rename', fail_both), patch.object(pkg.time, 'sleep'):
            with self.assertRaises(OSError):
                pkg.pack(self.run)
        self.assertFalse(self.final().exists())
        backup = next(self.root.glob('.pkg-old-it.0-*'))
        self.assertEqual((backup / 'docs' / pkg.PACKAGE_MANIFEST).read_bytes(), old_manifest)
        self.assertTrue(pkg.read_json(self.root / '.package-it.0.json')['transaction_pending'])
        self.assertFalse(pkg.pack(self.run)['reused'])
        self.verify_bundle(0, 1)
        self.assertFalse(pkg.read_json(self.root / '.package-it.0.json')['transaction_pending'])

    def test_backup_failure_never_deletes_old_package(self):
        pkg.pack(self.run)
        old = (self.final() / 'docs' / pkg.PACKAGE_MANIFEST).read_bytes()
        self.make_iteration(0, 1)
        rename = Path.rename
        def deny_backup(source, destination):
            if source == self.final():
                raise PermissionError(errno.EACCES, 'cannot back up')
            return rename(source, destination)
        with patch.object(Path, 'rename', deny_backup), patch.object(pkg.time, 'sleep'):
            with self.assertRaises(PermissionError):
                pkg.pack(self.run)
        self.assertEqual((self.final() / 'docs' / pkg.PACKAGE_MANIFEST).read_bytes(), old)

    def test_nonempty_rename_target_not_retried(self):
        source, target = Path(self.temp.name) / 'source', Path(self.temp.name) / 'target'
        source.mkdir()
        target.mkdir()
        (source / 'new').write_text('new')
        (target / 'old').write_text('old')
        with patch.object(pkg.time, 'sleep') as sleep:
            with self.assertRaises(OSError):
                pkg._rename_directory(source, target)
        self.assertEqual(sleep.call_count, 0)
        self.assertEqual((target / 'old').read_text(), 'old')

    def test_two_real_publishers_same_destination_lock_not_deleted(self):
        script = (
            "import sys; from pathlib import Path; "
            f"sys.path.insert(0,{str(PROJECT / 'python')!r}); "
            "import simz1_report_package as p; original=p.shutil.copy2; paused=False\n"
            "def copy(source,target):\n"
            " global paused\n"
            " if not paused:\n"
            "  paused=True; print('PUBLISHER_READY',flush=True); sys.stdin.readline()\n"
            " return original(source,target)\n"
            "p.shutil.copy2=copy\n"
            "p.pack(Path(sys.argv[1]))\n")
        first = subprocess.Popen([sys.executable, '-B', '-c', script, str(self.run)],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, text=True)
        try:
            for _ in range(20):
                line = first.stdout.readline()
                if 'PUBLISHER_READY' in line:
                    break
                self.assertTrue(line, 'First publisher exited before locking')
            else:
                self.fail('First publisher did not reach copy')
            lock = self.root / '.package-it.0.lock'
            self.assertTrue(lock.is_file())
            second = self.cli()
            self.assertEqual(second.returncode, 1, second.stdout + second.stderr)
            self.assertFalse(self.final().exists())
            self.assertTrue(lock.is_file())
            first.stdin.write('\n')
            first.stdin.flush()
            stdout, stderr = first.communicate(timeout=30)
            self.assertEqual(first.returncode, 0, stdout + stderr)
        finally:
            if first.poll() is None:
                first.kill()
                first.communicate(timeout=10)
        self.verify_bundle(0)
        again = self.cli()
        self.assertEqual(again.returncode, 0, again.stdout + again.stderr)
        self.assertIn('ENTREGABLE REUTILIZADO', again.stdout)

    def test_source_changes_during_copy_never_publish(self):
        original = pkg.shutil.copy2
        def mutate_then_copy(source, destination):
            if source.name == 'estadisticas_por_perfil_hora.csv':
                source.write_text('iteration,revision\n0,99\n', encoding='utf-8')
            return original(source, destination)
        with patch.object(pkg.shutil, 'copy2', mutate_then_copy):
            with self.assertRaisesRegex(ValueError, 'modificado'):
                pkg.pack(self.run)
        self.assertFalse(self.final().exists())
        self.assertTrue(list(self.root.glob('.pkg-it.0-*')))

    def test_journal_write_failure_after_publication_keeps_new_package_and_recovers(self):
        pkg.pack(self.run)
        self.make_iteration(0, 1)
        write_json = pkg._write_json
        def fail_completion(path, value):
            if path == self.root / '.package-it.0.json' and value.get('phase') == 'published':
                raise OSError(errno.EIO, 'journal completion write failed')
            return write_json(path, value)
        with patch.object(pkg, '_write_json', fail_completion):
            with self.assertRaises(OSError):
                pkg.pack(self.run)
        self.verify_bundle(0, 1)
        self.assertTrue(list(self.root.glob('.pkg-old-it.0-*')))
        self.assertTrue(pkg.read_json(self.root / '.package-it.0.json')['transaction_pending'])
        self.assertTrue(pkg.pack(self.run)['reused'])
        self.assertFalse(pkg.read_json(self.root / '.package-it.0.json')['transaction_pending'])
        self.verify_bundle(0, 1)

    def test_recovery_never_starts_subprocess(self):
        with patch.object(subprocess, 'run', side_effect=AssertionError('No subprocess allowed')), \
                patch.object(subprocess, 'Popen', side_effect=AssertionError('No subprocess allowed')):
            pkg.pack(self.run)
            self.assertTrue(pkg.pack(self.run)['reused'])


if __name__ == '__main__':
    unittest.main()
