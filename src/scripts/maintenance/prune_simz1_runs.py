"""Prune an explicit audited inventory after a protected replay has been verified.

No discovery-by-date, simulation, server termination, or recursive tree removal.
The default is validation only. The proof is a human/agent verification record,
bound to the current native and SQLite manifests and saved browser/HTTP evidence.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

ROOT = Path(__file__).absolute().parents[2]
SOURCE_EXTENSIONS = {'.py', '.ps1', '.java', '.js', '.cjs', '.jar', '.class', '.osm', '.pbf'}
BACKUP_NAMES = {'run-manifest.json', 'execution-status.json', 'montecarlo-report.json',
                'continuous-manifest.json', 'sqlite-source-manifest.json', 'config-simz1.xml'}


class Refused(ValueError):
    pass


def read_json(path):
    if path.stat().st_size > 16 * 1024 * 1024:
        raise Refused('Metadata too large: ' + str(path))
    return json.loads(path.read_text(encoding='utf-8-sig'))


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def is_link(path):
    stat = path.lstat()
    return path.is_symlink() or bool(getattr(stat, 'st_file_attributes', 0) & 0x400)


def safe_path(root, value, *, must_exist=True):
    """Check lexical ancestors before resolving, so junctions are never traversed."""
    root = Path(root).absolute()
    path = Path(value)
    if not path.is_absolute():
        path = root / path
    if '..' in path.parts or not path.is_relative_to(root):
        raise Refused('Path outside workspace or containing ..: ' + str(path))
    for ancestor in reversed((root, *root.parents)):
        if is_link(ancestor):
            raise Refused('Linked workspace ancestor: ' + str(ancestor))
    current = root
    for part in path.relative_to(root).parts:
        current /= part
        if os.path.lexists(current) and is_link(current):
            raise Refused('Symlink/junction/reparse point: ' + str(current))
    if must_exist and not path.exists():
        raise Refused('Missing path: ' + str(path))
    if not path.resolve().is_relative_to(root.resolve()):
        raise Refused('Resolved path outside workspace: ' + str(path))
    return path


def protected_target(target, protected):
    if target == protected or target.is_relative_to(protected) or protected.is_relative_to(target):
        raise Refused('Protected run, descendant, or ancestor: ' + str(target))


def stat_row(root, path):
    path = safe_path(root, path)
    stat = path.lstat()
    if not path.is_file() and not path.is_dir():
        raise Refused('Special file: ' + str(path))
    if path.is_file() and stat.st_nlink != 1:
        raise Refused('Hard-linked file: ' + str(path))
    return dict(path=str(path), relative_path=path.relative_to(root).as_posix(),
                directory=path.is_dir(), bytes=0 if path.is_dir() else stat.st_size,
                mtime_ns=stat.st_mtime_ns, inode=stat.st_ino)


def snapshot(root, folder):
    rows = []

    def visit(path):
        row = stat_row(root, path)
        rows.append(row)
        if row['directory']:
            for child in sorted(path.iterdir()):
                visit(child)

    visit(folder)
    return rows


def tracked_files(root):
    result = subprocess.run(['git', '-C', str(root), 'ls-files', '-z'], capture_output=True)
    if result.returncode:
        raise Refused('Cannot inspect Git tracked files')
    return set(result.stdout.decode('utf-8').split('\0')) - {''}


def processes():
    if os.name == 'nt':
        script = ('Get-CimInstance Win32_Process -ErrorAction Stop | '
                  'Select-Object ProcessId,Name,CreationDate,CommandLine | ConvertTo-Json -Compress')
        result = subprocess.run(['powershell.exe', '-NoProfile', '-Command', script],
                                capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise Refused('Cannot inspect current processes: ' + result.stderr)
        data = json.loads(result.stdout or '[]')
        return data if isinstance(data, list) else [data]
    rows = []
    for path in Path('/proc').glob('[0-9]*'):
        try:
            rows.append(dict(ProcessId=int(path.name), Name='', CommandLine=(path / 'cmdline')
                             .read_bytes().replace(b'\0', b' ').decode(errors='replace')))
        except (OSError, ValueError):
            continue
    return rows


def check_processes(candidates, rows):
    for row in rows:
        if row.get('ProcessId') == os.getpid():
            continue
        command = row.get('CommandLine')
        if command is None and str(row.get('Name', '')).lower().startswith(('python', 'java')):
            raise Refused('Cannot inspect Python/Java command, PID=' + str(row.get('ProcessId')))
        text = (command or '').replace('\\', '/').casefold()
        for folder in candidates:
            if str(folder).replace('\\', '/').casefold() in text or folder.name.casefold() in text:
                raise Refused('Candidate in use, PID=' + str(row.get('ProcessId')) + ': ' + str(folder))


def check_file_unused(path):
    """Fail closed on Windows sharing/byte-lock holders; no lock or WAL is removed here."""
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        create = kernel.CreateFileW
        create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                           wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        create.restype = wintypes.HANDLE
        handle = create(str(path), 0x80000000, 0, None, 3, 0x80, None)
        if handle == wintypes.HANDLE(-1).value:
            raise Refused('File in use or inaccessible: ' + str(path) +
                          ' (Windows ' + str(ctypes.get_last_error()) + ')')
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle(handle)
    elif path.name.endswith(('.lock', '.sqlite', '-wal', '-shm')):
        import fcntl
        with path.open('rb') as stream:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(stream, fcntl.LOCK_UN)
            except BlockingIOError as error:
                raise Refused('Locked file: ' + str(path)) from error


def check_dependencies(root, protected, candidates, iteration):
    native_path = safe_path(root, protected / 'run-manifest.json')
    native = read_json(native_path)
    replay_path = safe_path(root, protected / 'webgl-continuo/continuous-manifest.json')
    replay = read_json(replay_path)
    source_root = safe_path(root, replay['source_directory'])
    source_path = safe_path(root, source_root / 'sqlite-source-manifest.json')
    source = read_json(source_path)
    identity = (native['run_id'], iteration)
    if (native.get('status') != 'completed' or native.get('validation', {}).get('status') != 'valid'
            or not isinstance(iteration, int) or iteration not in native.get('iterations', {}).get('completed', [])):
        raise Refused('Native run/iteration is not complete and validated')
    horizon = native.get('time_horizon')
    if not horizon or replay.get('replay_window') != horizon:
        raise Refused('Replay horizon does not match native run')
    source_window = source.get('replay_window', {})
    if (source_window.get('start_seconds', float('inf')) > horizon['start_seconds']
            or source_window.get('end_seconds', -1) < horizon['end_seconds']):
        raise Refused('Source does not cover the complete native horizon')
    native_hash, source_hash = digest(native_path), digest(source_path)
    for label, value in [('replay', replay), ('source', source)]:
        if (value.get('run_id'), value.get('iteration')) != identity or value.get('status') != 'complete':
            raise Refused(label + ' is incomplete or has a different identity')
        if value.get('run_manifest_sha256') != native_hash or value.get('sample_rate') != 1.0:
            raise Refused(label + ' has incompatible provenance or sampled population')
        database = safe_path(root, value['database'])
        stat = database.stat()
        if (stat.st_size, stat.st_mtime_ns) != (value['database_bytes'], value['database_mtime_ns']):
            raise Refused(label + ' database changed since publication')
    if replay.get('source_export_sha256') != source_hash:
        raise Refused('Replay source manifest fingerprint mismatch')
    if Path(source.get('run_directory', '')).absolute() != protected:
        raise Refused('Source native directory mismatch')
    # Scan metadata only; never read native events/plans or traverse links. The
    # explicit source and replay metadata are included even if external to the run.
    metadata = {native_path, replay_path, source_path}
    for row in snapshot(root, protected):
        path = Path(row['path'])
        if not row['directory'] and row['bytes'] < 8 * 1024 * 1024 and (
                path.suffix == '.json' or path.name in ('config-simz1.xml', 'output_config.xml')):
            metadata.add(path)
    for path in metadata:
        text = path.read_text(encoding='utf-8-sig').replace('\\\\', '\\').replace('\\', '/').casefold()
        for candidate in candidates:
            if candidate.name.casefold() in text or str(candidate).replace('\\', '/').casefold() in text:
                raise Refused('Protected dependency or ambiguous reference to ' + str(candidate) + ' in ' + str(path))
    for path in (source_root, Path(replay['database']), Path(source['database'])):
        if any(path == c or path.is_relative_to(c) for c in candidates):
            raise Refused('Protected replay depends on deletion candidate: ' + str(path))
    return dict(run_id=native['run_id'], iteration=iteration, run_manifest_sha256=native_hash,
                source_manifest_sha256=source_hash, replay_manifest_sha256=digest(replay_path),
                database=replay['database'], metadata_files_checked=len(metadata))


def check_proof(root, proof, identity, candidates):
    if proof.get('status') != 'passed':
        raise Refused('Massive replay verification has not passed')
    for key in ('run_id', 'iteration', 'run_manifest_sha256', 'source_manifest_sha256', 'replay_manifest_sha256'):
        if proof.get(key) != identity[key]:
            raise Refused('Verification proof does not match current ' + key)
    for name in ('source', 'http', 'browser'):
        check = proof.get('checks', {}).get(name, {})
        if check.get('passed') is not True or (check.get('run_id'), check.get('iteration')) != (
                identity['run_id'], identity['iteration']):
            raise Refused('Missing successful ' + name + ' identity verification')
        path = safe_path(root, check.get('evidence_path', ''))
        if not path.is_file() or not path.stat().st_size or any(path.is_relative_to(c) for c in candidates):
            raise Refused('Evidence must be a nonempty file outside deletion candidates: ' + name)
        if digest(path) != check.get('evidence_sha256'):
            raise Refused('Evidence fingerprint mismatch: ' + name)


def check_baseline(root, baseline):
    errors = []
    for row in baseline['files']:
        try:
            now = stat_row(root, Path(row['path']))
            if any(now[key] != row[key] for key in ('bytes', 'mtime_ns', 'inode', 'directory')):
                errors.append('Changed: ' + row['path'])
            elif row.get('sha256') and digest(Path(row['path'])) != row['sha256']:
                errors.append('Hash changed: ' + row['path'])
        except (OSError, Refused) as error:
            errors.append(str(error))
    return dict(status='passed' if not errors else 'failed', checked_files=len(baseline['files']),
                errors=errors, method='Preserved baseline bytes/mtime/inode and recorded small metadata hashes; no redundant large native reads')


def validate(root, inventory, proof, baseline, *, git_files=None, process_rows=None):
    root = Path(root).absolute()
    if Path(inventory['root']).absolute() != root:
        raise Refused('Inventory belongs to another workspace')
    protected = safe_path(root, inventory['protected'])
    candidates = []
    tracked = tracked_files(root) if git_files is None else git_files
    for run in inventory['candidates']:
        folder = safe_path(root, run['path'])
        protected_target(folder, protected)
        if any(folder == c or folder.is_relative_to(c) or c.is_relative_to(folder) for c in candidates):
            raise Refused('Duplicate or overlapping deletion targets')
        if run.get('exclusion_reasons') or not run.get('ownership_evidence'):
            raise Refused('Ambiguous or excluded target: ' + str(folder))
        candidates.append(folder)
        current = snapshot(root, folder)
        if current != run['entries']:
            raise Refused('Inventory changed; review and re-inventory target: ' + str(folder))
        for row in current:
            path = Path(row['path'])
            if row['relative_path'] in tracked or (not row['directory'] and path.suffix.lower() in SOURCE_EXTENSIONS):
                raise Refused('Tracked/source/tool file in target: ' + str(path))
        if run.get('run_id') == inventory['protected_run_id']:
            raise Refused('Protected identity in deletion target')
    check_processes(candidates, processes() if process_rows is None else process_rows)
    identity = check_dependencies(root, protected, candidates, proof.get('iteration'))
    if identity['run_id'] != inventory['protected_run_id'] or baseline['run_id'] != identity['run_id']:
        raise Refused('Protected native identity does not match inventory/baseline')
    check_proof(root, proof, identity, candidates)
    conservation = check_baseline(root, baseline)
    if conservation['status'] != 'passed':
        raise Refused('Protected baseline changed: ' + '; '.join(conservation['errors'][:5]))
    for run in inventory['candidates']:
        for row in run['entries']:
            if not row['directory']:
                check_file_unused(Path(row['path']))
    return dict(status='validated', identity=identity, conservation=conservation,
                candidate_count=len(candidates), candidate_bytes=sum(x['bytes'] for x in inventory['candidates']))


def apply(root, inventory, proof, baseline, journal, *, git_files=None, process_rows=None):
    root = Path(root).absolute()
    validated = validate(root, inventory, proof, baseline, git_files=git_files, process_rows=process_rows)
    journal = safe_path(root, journal, must_exist=False)
    candidates = [Path(x['path']) for x in inventory['candidates']]
    if any(journal == c or journal.is_relative_to(c) or c.is_relative_to(journal) for c in candidates):
        raise Refused('Journal overlaps a deletion target')
    protected_target(journal, Path(inventory['protected']))
    journal.mkdir(parents=True, exist_ok=False)
    result = dict(status='preparing', started_utc=datetime.now(timezone.utc).isoformat(),
                  validation=validated, removed=[], removed_bytes=0, backups=[], pointer_changes=[])
    log = journal / 'result.json'

    def save():
        log.write_text(json.dumps(result, indent=2), encoding='utf-8')

    save()
    # Preserve identity/provenance metadata outside all targets before first unlink.
    for run in inventory['candidates']:
        for row in run['entries']:
            path = Path(row['path'])
            keep_metadata = ((path.name in BACKUP_NAMES or path.name.endswith('manifest.json'))
                             and row['bytes'] <= 16 * 1024 * 1024)
            keep_small_evidence = path.suffix.lower() in ('.json', '.log') and row['bytes'] <= 1024 * 1024
            if not row['directory'] and (keep_metadata or keep_small_evidence):
                # Repeating the original directory tree under an evidence
                # journal exceeds legacy Windows MAX_PATH for valid sources.
                # Keep a compact flat name; result.json retains the full mapping.
                backup_key = hashlib.sha256(row['relative_path'].encode('utf-8')).hexdigest()[:24]
                dest = journal / 'identity-backups' / (backup_key + path.suffix.lower())
                dest.parent.mkdir(parents=True, exist_ok=True)
                with dest.open('xb') as backup_stream:
                    backup_stream.write(path.read_bytes())
                result['backups'].append(dict(original=str(path), saved=str(dest), sha256=digest(dest)))
                save()
    # Invalidate the 1000-person authorization before deleting its dependency.
    trial = safe_path(root, root / 'runtime/workflow/trial.json', must_exist=False)
    if trial.exists():
        value = read_json(trial)
        if value.get('run_id') in {x['run_id'] for x in inventory['candidates'] if x.get('run_id')} or any(
                c.name in trial.read_text(encoding='utf-8-sig') for c in candidates):
            if trial.relative_to(root).as_posix() in (tracked_files(root) if git_files is None else git_files):
                raise Refused('Trial pointer is Git tracked')
            backup = journal / 'trial.before.json'
            backup.write_bytes(trial.read_bytes())
            check_file_unused(trial)
            trial.unlink()
            result['pointer_changes'].append(dict(path=str(trial), action='invalidated', backup=str(backup),
                reason='Referenced 1000-person trial removed by explicit cleanup; massive review_required is not substituted as approval'))
    result['status'] = 'deleting'
    save()
    try:
        for run in inventory['candidates']:
            check_processes([Path(run['path'])], processes() if process_rows is None else process_rows)
            if snapshot(root, Path(run['path'])) != run['entries']:
                raise Refused('Target changed before deletion: ' + run['path'])
            for row in reversed(run['entries']):
                path = safe_path(root, row['path'])
                protected_target(path, Path(inventory['protected']))
                if row['directory']:
                    # Directory mtime changes as children are unlinked; inode must not.
                    if not path.is_dir() or path.stat().st_ino != row['inode']:
                        raise Refused('Directory replaced: ' + str(path))
                    path.rmdir()
                else:
                    if stat_row(root, path) != row:
                        raise Refused('File changed during deletion: ' + str(path))
                    check_file_unused(path)
                    path.unlink()
                    result['removed_bytes'] += row['bytes']
            result['removed'].append(dict(path=run['path'], run_id=run.get('run_id'), bytes=run['bytes']))
            save()
        result['conservation_after'] = check_baseline(root, baseline)
        result['identity_after'] = check_dependencies(root, Path(inventory['protected']), [], proof['iteration'])
        result['status'] = 'completed' if result['conservation_after']['status'] == 'passed' else 'conservation_failed'
        save()
        return result
    except BaseException as error:
        result.update(status='stopped_partial', error=str(error))
        save()
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inventory', type=Path, required=True)
    parser.add_argument('--proof', type=Path, required=True)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--project', type=Path, default=ROOT)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--journal', type=Path)
    args = parser.parse_args(argv)
    try:
        root = args.project.absolute()
        inventory, proof, baseline = [read_json(safe_path(root, x)) for x in
                                      (args.inventory, args.proof, args.baseline)]
        if args.apply:
            journal = args.journal or root / ('runtime/maintenance/prune-' + uuid.uuid4().hex)
            result = apply(root, inventory, proof, baseline, journal)
            output = {k: v for k, v in result.items() if k not in ('backups',)}
            output['journal'] = str(journal)
        else:
            output = validate(root, inventory, proof, baseline)
        print(json.dumps(output, indent=2))
        return 0
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        print('Selective cleanup refused/stopped: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
