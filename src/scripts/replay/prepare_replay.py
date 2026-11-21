"""Prepare only the explicitly selected visual source; never run simulations."""
import argparse
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from start_replay import PROJECT, IDENTITY, command_arguments, read_object, resolve_selection, expected_replay_window


def active_writers(run, output, *, processes=None):
    if processes is None:
        if sys.platform != 'win32':
            raise ValueError('No se puede acreditar ausencia de escritores en esta plataforma')
        result = subprocess.run(['powershell.exe', '-NoProfile', '-Command',
            "Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^python(w)?\\.exe$' } | "
            "Select-Object ProcessId,CreationDate,CommandLine | ConvertTo-Json -Compress"],
            check=True, capture_output=True, text=True)
        processes = json.loads(result.stdout or '[]')
        if isinstance(processes, dict):
            processes = [processes]
    matches = []
    for process in processes:
        command = process.get('CommandLine') or ''
        args = command_arguments(command)
        if not any(Path(value).name in ('visualizador_z1.py', 'simz1_continuous_replay.py',
                                        'prepare_replay.py') for value in args):
            continue
        # Compare actual path arguments, never a substring of a similarly named run.
        for flag, expected in (('--run-dir', run), ('--output', output)):
            if flag in args and args.index(flag)+1 < len(args):
                actual = Path(args[args.index(flag)+1]).resolve()
                if actual == expected:
                    matches.append(process)
                    break
    return matches


@contextmanager
def preparation_lock(run):
    """OS-held lock released on process exit; no stale lockfile deletion needed."""
    directory = PROJECT/'runtime/replay'
    directory.mkdir(parents=True, exist_ok=True)
    name = hashlib.sha256(str(run).casefold().encode()).hexdigest()
    with (directory/f'prepare-{name}.lock').open('a+b') as stream:
        if stream.tell() == 0:
            stream.write(b'0'); stream.flush()
        stream.seek(0)
        if sys.platform == 'win32':
            import msvcrt
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as error:
                raise ValueError('Otro workflow prepara esta corrida; no se inicia un segundo escritor') from error
            try:
                yield
            finally:
                stream.seek(0); msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield


def validate_native(run, iteration):
    manifest, fingerprint = read_object(run/'run-manifest.json')
    selected = manifest['iterations']['last'] if iteration is None else iteration
    if (Path(manifest['folder']).resolve() != run or manifest.get('status') != 'completed' or
            manifest.get('validation', {}).get('status') != 'valid' or type(selected) is not int or
            selected not in manifest['iterations']['completed'] or str(selected) not in manifest['results'] or
            not manifest['iterations']['first'] <= selected <= manifest['iterations']['last']):
        raise ValueError(f'Corrida/iteracion no validada: solicitada={run}, iteracion={selected}')
    return manifest, dict(run_id=manifest['run_id'], iteration=selected, run_manifest_sha256=fingerprint)


def validate_partial_replay(replay, expected, source_version, window=None):
    if not replay.exists() or not any(replay.iterdir()):
        return
    config_path = replay/'config.json'
    if not config_path.is_file():
        raise ValueError('Replay parcial sin configuracion que acredite su procedencia; se conserva sin sobrescribir')
    config, _ = read_object(config_path)
    continuous = config.get('continuous', {})
    if (any(continuous.get(key) != value for key, value in expected.items()) or
            continuous.get('source_version') != source_version or
            continuous.get('window_seconds') != 120 or continuous.get('sample_rate') != 1 or
            config.get('replay_window') != (window or dict(start_seconds=0, end_seconds=86400))):
        raise ValueError(f'Replay parcial incompatible o sin huella de fuente: solicitada={expected}; '+
                         f'fuente={source_version}; encontrada={continuous}. Se conserva sin sobrescribir')


def reuse_published_replay(run, replay, expected):
    """Use the published source reference, never a guessed canonical source."""
    selection = resolve_selection(PROJECT, run, expected['iteration'], replay)
    exported, _ = read_object(replay/'continuous-manifest.json')
    sys.path.insert(0, str(PROJECT/'python'))
    from simz1_sqlite_source import checked_source
    source, actual, _ = checked_source(exported['source_directory'])
    window = actual.get('replay_window', {})
    if (any(actual.get(key) != value for key, value in expected.items()) or
            Path(actual.get('run_directory', '')).resolve() != run or
            actual.get('source_type') != 'sqlite-direct-v1' or
            window.get('start_seconds') != selection.replay_start or window.get('end_seconds', 0) < selection.replay_end):
        raise ValueError(f'Fuente del replay publicado incompatible: solicitada={expected}; '+
                         f'encontrada={actual.get("run_id")}, iteracion={actual.get("iteration")}, '+
                         f'directorio={actual.get("run_directory")}, horizonte={window}')
    print('Preparacion SQLite: fuente validada del replay publicado reutilizada: '+str(source)+
          '; sin extraccion de eventos.', flush=True)
    print('Publicacion replay: manifiesto completo compatible reutilizado. Sigue comprobacion HTTP.', flush=True)
    return selection


def prepare(run, iteration=None, *, sqlite_budget_gib=8, scratch_budget_gib=4,
            writers=active_writers, execute=subprocess.run):
    run = Path(run).resolve(strict=True)
    manifest, expected = validate_native(run, iteration)
    window = expected_replay_window(manifest)
    source_root, replay, scratch = run/'webgl-source', run/'webgl-continuo', run/'webgl-scratch'
    if manifest.get('experiment'):
        source_root,replay,scratch=(run/(name+'-it.'+str(expected['iteration'])) for name in ('webgl-source','webgl-continuo','webgl-scratch'))
    source = source_root/'sqlite-source'
    print(f'Solicitada: {expected["run_id"]} | iteracion {expected["iteration"]} | personas {manifest["counts"]["planned_persons"]}', flush=True)
    print('Preparacion visual: la URL abierta anteriormente NO acredita esta corrida hasta la comprobacion HTTP final.', flush=True)
    # The OS lock prevents two new workflows; process discovery also protects
    # exporters already started by older workflow versions without this lock.
    with preparation_lock(run):
        found = [item for item in writers(run, source_root/'index.html')
                 if item.get('ProcessId') != __import__('os').getpid() and
                 'prepare_replay.py' not in (item.get('CommandLine') or '')]
        if found:
            raise ValueError('Preparacion SQLite ya activa; conservar SQLite/WAL/SHM/checkpoints y esperar su finalizacion: '+
                             json.dumps(found, ensure_ascii=False))
        if (replay/'continuous-manifest.json').is_file():
            # A completed replay may deliberately point at a distinct verified
            # source while the old canonical spool is retained for evidence.
            # Never inspect or replace that unrelated partial when reopening.
            return reuse_published_replay(run, replay, expected)
        published = source/'sqlite-source-manifest.json'
        database = source_root/'replay.sqlite'
        checkpoint = source_root/'spool-ready.json.gz'
        if not published.is_file() and database.exists() and not checkpoint.is_file():
            # select_run() verifies large native files before invoking the
            # exporter. Reject this known non-resumable state first, without
            # another native read or any mutation of the interrupted spool.
            raise ValueError('SQLite parcial sin finalizacion acreditada: '+str(database)+
                f'; solicitada={expected}. No existe {published} ni {checkpoint}. '+
                'No hay reanudacion verificada: se conservan SQLite/WAL/SHM y staging; '+
                'no se releen eventos/planes, no se sobrescribe y no se inicia otra exportacion. '+
                'Revisar el resultado de la terminal del exportador original.')
        if published.is_file():
            sys.path.insert(0, str(PROJECT/'python'))
            from simz1_sqlite_source import checked_source
            _, actual, _ = checked_source(source)
            if any(actual.get(key) != value for key, value in expected.items()):
                raise ValueError(f'Fuente SQLite incompatible: solicitada={expected}; encontrada='+
                                 str({key: actual.get(key) for key in IDENTITY}))
            print('Preparacion SQLite: fuente completa compatible reutilizada; sin extraccion de eventos.', flush=True)
        else:
            print(f'Preparacion SQLite: limite {sqlite_budget_gib} GiB; scratch {scratch_budget_gib} GiB; reserva 2 GiB. Se comprueba espacio antes de escribir.', flush=True)
            execute([sys.executable, '-B', str(PROJECT/'python/visualizador_z1.py'),
                '--run-dir', str(run), '--iteration', str(expected['iteration']), '--sqlite-direct',
                '--output', str(source_root/'index.html'), '--temp-dir', str(scratch),
                '--sqlite-budget-gib', str(sqlite_budget_gib), '--scratch-budget-gib', str(scratch_budget_gib),
                '--window-seconds', '900', '--replay-start', str(window['start_seconds']), '--replay-end', str(window['end_seconds'])], check=True)
        if (replay/'continuous-manifest.json').is_file():
            return reuse_published_replay(run, replay, expected)
        else:
            # A direct replay has no temporal extraction to recover; only reuse
            # its small partial config when both native and source identities
            # are provable. Historical unversioned partials remain untouched.
            _, source_version = read_object(published)
            validate_partial_replay(replay, expected, source_version, window)
            print('Publicacion replay: preparando solamente la iteracion solicitada desde SQLite validado.', flush=True)
            execute([sys.executable, '-B', str(PROJECT/'python/simz1_continuous_replay.py'),
                '--source', str(source), '--output', str(replay), '--run-dir', str(run),
                '--iteration', str(expected['iteration']), '--window-seconds', '120',
                '--start', str(window['start_seconds']), '--end', str(window['end_seconds']), '--resume-incomplete'], check=True)
        selection = resolve_selection(PROJECT, run, expected['iteration'], replay)
        print('Publicacion terminada: identidad y procedencia verificadas. Sigue comprobacion del servidor HTTP.', flush=True)
        return selection


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--iteration', type=int)
    parser.add_argument('--sqlite-budget-gib', type=int, default=8)
    parser.add_argument('--scratch-budget-gib', type=int, default=4)
    args = parser.parse_args(argv)
    if min(args.sqlite_budget_gib, args.scratch_budget_gib) <= 0:
        parser.error('Los presupuestos deben ser positivos')
    try:
        prepare(args.run_dir, args.iteration, sqlite_budget_gib=args.sqlite_budget_gib,
                scratch_budget_gib=args.scratch_budget_gib)
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        print(f'Preparacion detenida sin cambiar de corrida: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
