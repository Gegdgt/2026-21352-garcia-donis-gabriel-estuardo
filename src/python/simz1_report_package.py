"""Package verified SimZ1 analytical CSV/JSON and PNG into two readable folders.

The canonical scientific and analytical artifacts remain unchanged. This is a
small, restartable copy of already published analytics, not a MATSim/export step.
"""
from __future__ import annotations

import argparse
import csv
import errno
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time
import traceback
import uuid


REQUIRED_IMAGES = frozenset({
    'carros_por_hora.png', 'motos_por_hora.png',
    'comparacion_familias_por_hora.png', 'comparacion_global_perfiles.png',
    'completitud_por_hora.png', 'duration_distribution.png',
})
PACKAGE_MANIFEST = 'reporte-manifest.json'
PACKAGER_VERSION = 2
# Version 1 has the same payload contract. Accept it only after the full current
# identity, inventory and source hash checks; do not rewrite a valid old bundle.
COMPATIBLE_VERSIONS = (1, PACKAGER_VERSION)
RETRY_DELAYS = (0.2, 0.4, 0.8)


class PackageLock:
    """Nonblocking kernel lock per iteration; never unlink another lock inode."""
    def __init__(self, path):
        self.path, self.stream, self.acquired = Path(path), None, False

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.stream = self.path.open('a+b')
        try:
            self.stream.seek(0, os.SEEK_END)
            if not self.stream.tell():
                self.stream.write(b'\0')
                self.stream.flush()
            self.stream.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.acquired = True
        except OSError as exc:
            self.stream.close()
            self.stream = None
            if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                raise
        return self

    def __exit__(self, *_):
        # Closing releases the kernel lock, including on exceptions/process exit.
        if self.stream is not None:
            self.stream.close()
        self.stream, self.acquired = None, False


def _write_json(path, value):
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex[:12] + '.tmp')
    with temporary.open('w', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def _rename_directory(source, destination):
    """Bounded retry only while destination is absent, never replace a directory."""
    for attempt in range(len(RETRY_DELAYS) + 1):
        if destination.exists():
            raise FileExistsError(f'Destino ya existe; no renombrar encima: {destination}')
        try:
            source.rename(destination)
            return
        except OSError as exc:
            transient = (getattr(exc, 'winerror', None) in (5, 32, 33)
                         or exc.errno in (errno.EACCES, errno.EBUSY, errno.EPERM))
            if not transient or destination.exists() or attempt == len(RETRY_DELAYS):
                raise
            print(f'REINTENTO PUBLICACION | intento={attempt + 1}/{len(RETRY_DELAYS) + 1}'
                  f' | origen={source} | destino={destination} | {type(exc).__name__}'
                  f' errno={exc.errno} winerror={getattr(exc, "winerror", None)}: {exc}', flush=True)
            time.sleep(RETRY_DELAYS[attempt])


def file_sha(path: Path) -> str:
    checksum = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            checksum.update(chunk)
    return checksum.hexdigest()


def read_json(path: Path) -> dict:
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict):
        raise ValueError(f'JSON no es un objeto: {path}')
    return data


def _artifact_map(analysis: Path, report: dict) -> dict:
    result = {}
    for item in report.get('artifacts', []):
        rel = item.get('path')
        if not isinstance(rel, str):
            raise ValueError('Manifiesto analitico contiene ruta invalida')
        path = (analysis / rel).resolve()
        if not path.is_relative_to(analysis.resolve()) or not path.is_file():
            raise ValueError(f'Archivo analitico faltante o fuera de carpeta: {rel}')
        if path.stat().st_size != item.get('size_bytes') or file_sha(path) != item.get('sha256'):
            raise ValueError(f'Producto analitico modificado o incompleto: {rel}')
        if rel in result:
            raise ValueError(f'Producto analitico duplicado: {rel}')
        result[rel] = path
    return result


def _source_files(run: Path, iteration: int) -> tuple[dict, dict, dict, dict[str, Path]]:
    native_path = run / 'run-manifest.json'
    native = read_json(native_path)
    if native.get('status') != 'completed' or native.get('validation', {}).get('status') != 'valid':
        raise ValueError('No se empacan corridas MATSim sin completed/valid')
    if iteration not in native.get('iterations', {}).get('completed', []):
        raise ValueError(f'Iteracion no validada: {iteration}')
    analysis = (run / 'analysis' / f'it.{iteration}').resolve()
    analyzed = read_json(analysis / 'analysis-manifest.json')
    status = read_json(analysis / 'analysis-status.json')
    if (analyzed.get('status') != 'completed' or status.get('status') != 'completed'
            or analyzed.get('run_id') != native.get('run_id')
            or status.get('run_id') != native.get('run_id')
            or analyzed.get('iteration') != iteration or status.get('iteration') != iteration
            or analyzed.get('fingerprint') != status.get('fingerprint')
            or status.get('manifest_sha256') != file_sha(analysis / 'analysis-manifest.json')):
        raise ValueError('Analisis incompleto o identidad de manifiestos incompatible')
    artifacts = _artifact_map(analysis, analyzed)
    charts = {rel.split('/', 1)[1]: path for rel, path in artifacts.items()
              if rel.startswith('graficas_perfiles/') and '/' not in rel[len('graficas_perfiles/'):]
              and Path(rel).suffix.lower() in ('.png', '.csv', '.json')}
    if not REQUIRED_IMAGES.issubset({name for name in charts if name.endswith('.png')}):
        raise ValueError('Faltan graficas oficiales requeridas en el manifiesto')
    if not any(name.endswith('.csv') for name in charts) or not any(name.endswith('.json') for name in charts):
        raise ValueError('Faltan las tablas CSV o JSON del analisis')
    occupancy = native.get('results', {}).get(str(iteration), {}).get('corridor_occupancy')
    if (occupancy or {}).get('enabled'):
        from simz1_occupancy_audit import report_summary
        expected = dict(run_id=native['run_id'], iteration=iteration, corridor_occupancy=report_summary(occupancy))
        source = charts.get('corridor_occupancy.json')
        if (source is None or read_json(source) != expected or
                analyzed.get('specification', {}).get('corridor_occupancy') != expected['corridor_occupancy']):
            raise ValueError('Falta el resumen de ocupacion nativa compatible con esta corrida e iteracion')
    docs = {
        'run-manifest.json': native_path,
        'analysis-manifest.json': analysis / 'analysis-manifest.json',
        'analysis-status.json': analysis / 'analysis-status.json',
        'trips.csv.provenance.json': artifacts.get('trips.csv.provenance.json'),
    }
    if any(path is None for path in docs.values()):
        raise ValueError('Falta proveniencia del CSV canonico')
    destinations = {'docs/' + name: source for name, source in docs.items()}
    proxy_record = native.get('public_transport', {}).get('stop_proxy_manifest')
    if proxy_record is not None:
        from simz1_run import checked_path
        destinations['docs/transit-stop-proxies.json'] = checked_path(native_path.parent, proxy_record)
    if native.get('freight_transport', {}).get('enabled'):
        from simz1_run import checked_path
        for name in ('service.json', 'routes.json', 'roster.json'):
            record = native['inputs']['input:freight-weekday/'+name]
            destinations['docs/freight-'+name] = checked_path(native_path.parent, record)
    if native.get('short_link_signal_coordination', {}).get('enabled'):
        from simz1_run import checked_path
        destinations['docs/signal-coordination.json'] = checked_path(native_path.parent,
            native['short_link_signal_coordination']['artifact'])
        destinations['docs/signal-control-before-coordination.xml'] = checked_path(native_path.parent,
            native['inputs']['input:signal-control-before-coordination.xml'])
    for name, source in charts.items():
        rel = ('graficas/' if name.endswith('.png') else 'docs/') + name
        if rel in destinations or rel == 'docs/' + PACKAGE_MANIFEST:
            raise ValueError(f'Nombre analitico reservado o duplicado: {rel}')
        destinations[rel] = source
    if native.get('experiment'):
        from simz1_day_observation import enabled
        fixed_day=enabled(native)
        balanced=analysis/'balanced-launch'
        report=read_json(balanced/'report.json')
        if (report.get('run_id')!=native['run_id'] or report.get('iteration')!=iteration or
                report.get('manifest_sha256')!=file_sha(native_path) or
                report.get('events')!=native['results'][str(iteration)]['events'] or
                report.get('postprocessor_version')!=('balanced-report-fixed-day-v1' if fixed_day else 'balanced-report-v2') or not report.get('files')):
            raise ValueError('Balanced evidence identity/version mismatch')
        if fixed_day and (report.get('day_observation')!=native['results'][str(iteration)].get('day_observation') or
                report.get('followup_window') is not None or report.get('observation_coverage_seconds')!=86400):
            raise ValueError('Fixed-day evidence differs from native census acceptance')
        destinations['docs/balanced-launch/report.json']=balanced/'report.json'
        for name,digest in report['files'].items():
            source=balanced/name
            if Path(name).name!=name or not source.is_file() or file_sha(source)!=digest:
                raise ValueError('Balanced evidence missing or mutated: '+name)
            destinations[('graficas/' if name.endswith('.png') else 'docs/')+'balanced-launch/'+name]=source
    return native, analyzed, status, destinations


def _validate_existing(directory: Path, expected: dict, inputs=None) -> bool:
    try:
        manifest = read_json(directory / 'docs' / PACKAGE_MANIFEST)
        if (manifest.get('schema_version') != 1
                or manifest.get('packager_version', 1) not in COMPATIBLE_VERSIONS
                or any(manifest.get(k) != v for k, v in expected.items())):
            return False
        records = manifest['files']
        if not records or len(records) != len({item['path'] for item in records}):
            return False
        names = {item['path'] for item in records}
        required = {'graficas/' + name for name in REQUIRED_IMAGES} | {
            'docs/' + name for name in ('run-manifest.json', 'analysis-manifest.json',
                                       'analysis-status.json', 'trips.csv.provenance.json')}
        if (not required.issubset(names) or not any(name.startswith('docs/') and name.endswith('.csv') for name in names)
                or not isinstance(manifest.get('run_id'), str) or not manifest['run_id']
                or type(manifest.get('iteration')) is not int):
            return False
        if inputs is not None and {item['path'] for item in records} != set(inputs):
            return False
        actual = {p.relative_to(directory).as_posix() for p in directory.rglob('*') if p.is_file()}
        if actual != {item['path'] for item in records} | {'docs/' + PACKAGE_MANIFEST}:
            return False
        for item in records:
            lexical = directory / item['path']
            path = lexical.resolve()
            if not path.is_relative_to(directory.resolve()) or not path.is_file() or lexical.is_symlink():
                return False
            if path.stat().st_size != item['bytes'] or file_sha(path) != item['sha256']:
                return False
            if inputs is not None:
                source = inputs[item['path']]
                # Source mapping matters as well as bytes: never label it.0 as it.1.
                run = source
                while run != run.parent and not (run / 'run-manifest.json').is_file():
                    run = run.parent
                if (item.get('source') != source.relative_to(run).as_posix()
                        or file_sha(source) != item['sha256']):
                    return False
        return True
    except (FileNotFoundError, ValueError, KeyError, TypeError, AttributeError):
        return False


def _read_payload(directory):
    from PIL import Image
    for path in directory.rglob('*'):
        if path.suffix == '.json':
            json.loads(path.read_text(encoding='utf-8'))
        elif path.suffix == '.csv':
            with path.open(encoding='utf-8-sig', newline='') as stream:
                for _ in csv.reader(stream, strict=True):
                    pass
        elif path.suffix == '.png':
            with Image.open(path) as image:
                image.verify()
            with Image.open(path) as image:
                image.load()


def _describe(directory):
    result = dict(exists=directory.exists(), complete=False)
    if directory.is_dir():
        result['complete'] = _validate_existing(directory, {})
        try:
            manifest = read_json(directory / 'docs' / PACKAGE_MANIFEST)
            result.update({k: manifest.get(k) for k in ('run_id', 'iteration', 'packager_version')})
        except (FileNotFoundError, ValueError):
            pass
    return result


def _recover(journal, root, final, run_id, iteration):
    if not journal.exists():
        return
    state = read_json(journal)
    if not state.get('transaction_pending'):
        return
    if state.get('run_id') != run_id or state.get('iteration') != iteration:
        raise ValueError(f'Journal de identidad incompatible: {journal}')
    stage, backup = (root / state[k] for k in ('stage_name', 'backup_name'))
    if (any(p.parent != root or p.is_symlink() for p in (stage, backup))
            or not stage.name.startswith('.pkg-') or not backup.name.startswith('.pkg-old-')):
        raise ValueError(f'Rutas inseguras en journal: {journal}')
    if final.exists():
        published = final / 'docs' / PACKAGE_MANIFEST
        if (published.is_file() and file_sha(published) == state['new_manifest_sha256']
                and _validate_existing(final, {})):
            state.update(phase='published', transaction_pending=False)
        elif backup.exists():
            raise FileExistsError(f'Publicacion interrumpida con destino incompatible; conservar {backup} y {stage}')
        else:
            # Interrupted before moving the previous package, or after rollback.
            state.update(phase='previous_preserved', transaction_pending=False)
    elif backup.exists():
        print(f'EMPAQUETANDO | run_id={run_id} | iteracion={iteration} | fase=recuperar_respaldo', flush=True)
        _rename_directory(backup, final)
        state.update(phase='rolled_back', transaction_pending=False)
    elif state['previous_exists']:
        raise FileNotFoundError(f'Publicacion interrumpida sin destino ni respaldo: {journal}')
    else:
        state.update(phase='abandoned_stage_preserved', transaction_pending=False)
    _write_json(journal, state)


def pack(run_dir: Path, iteration: int = 0, expected_run_id=None) -> dict:
    run = Path(run_dir).resolve(strict=True)
    if not run.is_dir():
        raise NotADirectoryError(run)
    native = read_json(run / 'run-manifest.json')
    if expected_run_id is not None and native.get('run_id') != expected_run_id:
        raise ValueError(f'run_id distinto del solicitado: {native.get("run_id")} != {expected_run_id}')
    if type(iteration) is not int or iteration < 0:
        raise ValueError('Iteracion debe ser un entero no negativo')
    root = run / 'entregables'
    # Iteration 0 gets the exact name of its run. Other iterations are separate
    # to preserve the promised immediate docs/ and graficas/ structure.
    folder_name = run.name if iteration == 0 else f'{run.name}-it.{iteration}'
    final = root / folder_name
    token = uuid.uuid4().hex[:12]
    stage = root / f'.pkg-it.{iteration}-{token}'
    backup = root / f'.pkg-old-it.{iteration}-{token}'
    journal = root / f'.package-it.{iteration}.json'
    phase, before, rollback_error = 'lock', None, None
    state = None

    def progress(value):
        nonlocal phase
        phase = value
        print(f'EMPAQUETANDO | run_id={native.get("run_id")} | iteracion={iteration} | fase={phase}', flush=True)

    try:
        progress('validar_fuentes')
        native, analyzed, _, inputs = _source_files(run, iteration)
        if expected_run_id is not None and native['run_id'] != expected_run_id:
            raise ValueError('run_id cambio durante la validacion')
        identity = dict(schema_version=1, run_name=run.name, run_id=native['run_id'],
                        iteration=iteration, run_manifest_sha256=file_sha(run / 'run-manifest.json'),
                        analysis_manifest_sha256=file_sha(run / 'analysis' / f'it.{iteration}' / 'analysis-manifest.json'),
                        analysis_fingerprint=analyzed['fingerprint'])
        progress('lock')
        with PackageLock(root / f'.package-it.{iteration}.lock') as lock:
            if not lock.acquired:
                raise BlockingIOError(errno.EBUSY, f'Otro empaquetador tiene el bloqueo de iteracion {iteration}; reintentar cuando termine')
            progress('recuperar')
            if final.is_symlink() or (final.exists() and not final.is_dir()):
                raise FileExistsError(f'Destino incompatible (no directorio normal): {final}')
            _recover(journal, root, final, native['run_id'], iteration)
            before = _describe(final)
            if _validate_existing(final, identity, inputs):
                _read_payload(final)
                _source_files(run, iteration)
                if (file_sha(inputs['docs/run-manifest.json']) != identity['run_manifest_sha256']
                        or file_sha(inputs['docs/analysis-manifest.json']) != identity['analysis_manifest_sha256']):
                    raise ValueError('Manifiesto fuente modificado durante la reutilizacion')
                _write_json(journal, dict(run_id=native['run_id'], iteration=iteration,
                                         phase='reused', status='completed', transaction_pending=False,
                                         path=str(final)))
                print(f'ENTREGABLE REUTILIZADO | iteracion={iteration} | destino={final}', flush=True)
                return dict(status='completed', reused=True, path=str(final), **identity)
            total = sum(src.stat().st_size for src in inputs.values())
            if shutil.disk_usage(root).free < total + 64 * 1024 * 1024:
                raise OSError(errno.ENOSPC, f'No hay reserva para publicar {total} bytes en {root}')
            if os.name == 'nt' and any(len(str(p / rel)) >= 248
                                      for p in (stage, final, backup) for rel in inputs):
                raise OSError('Ruta demasiado larga para Windows; acorta la ubicacion del repositorio')
            progress('preparar_staging')
            stage.mkdir(exist_ok=False)
            records = []
            for rel, source in sorted(inputs.items()):
                dest = stage / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, dest)
                records.append(dict(path=rel, bytes=dest.stat().st_size, sha256=file_sha(dest),
                                    source=source.relative_to(run).as_posix()))
            _write_json(stage / 'docs' / PACKAGE_MANIFEST,
                        {**identity, 'packager_version': PACKAGER_VERSION, 'files': records,
                         'note': 'Copia de consulta: analysis/it.N y MATSim output conservados.'})
            progress('verificar_staging')
            if not _validate_existing(stage, identity, inputs):
                raise ValueError('Fuente modificada durante la copia o staging incompleto; no publicar')
            _read_payload(stage)  # All image/CSV/JSON handles closed before rename.
            # Revalidate against the analysis artifact ledger, not merely the
            # bytes that happened to be present when copy2 read each source.
            _source_files(run, iteration)
            if (file_sha(run / 'run-manifest.json') != identity['run_manifest_sha256']
                    or file_sha(inputs['docs/analysis-manifest.json']) != identity['analysis_manifest_sha256']):
                raise ValueError('Manifiesto fuente modificado durante la copia; no publicar')
            # Multi-rename transaction is recoverable, NOT an atomic replacement.
            state = dict(run_id=native['run_id'], iteration=iteration, phase='prepared',
                         transaction_pending=True, previous_exists=final.exists(),
                         stage_name=stage.name, backup_name=backup.name, path=str(final),
                         new_manifest_sha256=file_sha(stage / 'docs' / PACKAGE_MANIFEST))
            _write_json(journal, state)
            try:
                if final.exists():
                    progress('respaldar_anterior')
                    _rename_directory(final, backup)
                progress('publicar')
                _rename_directory(stage, final)
                state.update(phase='published', status='completed', transaction_pending=False)
                _write_json(journal, state)
            except BaseException:
                # Do not erase a new publication if a subsequent journal write failed.
                if backup.exists() and not final.exists():
                    failed_phase = phase
                    try:
                        progress('rollback')
                        _rename_directory(backup, final)
                        state.update(phase='rolled_back', transaction_pending=False)
                        _write_json(journal, state)
                    except BaseException as exc:
                        rollback_error = dict(type=type(exc).__name__, message=str(exc),
                                              errno=getattr(exc, 'errno', None),
                                              winerror=getattr(exc, 'winerror', None),
                                              traceback=traceback.format_exc())
                    phase = failed_phase
                raise
            print(f'ENTREGABLE PUBLICADO | iteracion={iteration} | destino={final}', flush=True)
            return dict(status='completed', reused=False, path=str(final), **identity)
    except BaseException as exc:
        evidence = dict(run_id=native.get('run_id'), iteration=iteration, phase=phase,
                        stage=str(stage), destination=str(final), backup=str(backup),
                        destination_before=before, exception_type=type(exc).__name__, message=str(exc),
                        errno=getattr(exc, 'errno', None), winerror=getattr(exc, 'winerror', None),
                        traceback=traceback.format_exc(), rollback_error=rollback_error,
                        destination_exists=final.exists(), backup_exists=backup.exists(),
                        resume=f'--run-dir "{run}" --all-iterations --expected-run-id {native.get("run_id")}')
        try:
            evidence['destination_after'] = _describe(final)
            if root.exists():
                _write_json(root / f'.pkg-failure-it.{iteration}-{token}.json', evidence)
        except Exception as diagnostic_error:
            print(f'No se pudo guardar diagnostico: {diagnostic_error}', file=sys.stderr, flush=True)
        print(f'EMPAQUETADO FALLIDO | iteracion={iteration} | causa={json.dumps(evidence, ensure_ascii=False)}',
              file=sys.stderr, flush=True)
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--expected-run-id', help='Rechaza otra identidad sin elegir latest-successful')
    choice = parser.add_mutually_exclusive_group()
    choice.add_argument('--iteration', type=int, default=0)
    choice.add_argument('--all-iterations', action='store_true')
    args = parser.parse_args(argv)
    published = reused = failed = 0
    try:
        run = args.run_dir.resolve(strict=True)
        if args.all_iterations:
            iterations = read_json(run / 'run-manifest.json')['iterations']['completed']
        else:
            iterations = [args.iteration]
        if (not iterations or any(type(n) is not int or n < 0 for n in iterations)
                or len(iterations) != len(set(iterations))):
            raise ValueError('Lista de iteraciones invalida o vacia')
        for number in iterations:
            try:
                outcome = pack(run, number, args.expected_run_id)
                reused += int(outcome['reused'])
                published += int(not outcome['reused'])
            except Exception:
                failed += 1
                traceback.print_exc()
    except Exception:
        failed += 1
        traceback.print_exc()
    print(f'RESUMEN EMPAQUETADO | publicados={published} | reutilizados={reused} | fallidos={failed}', flush=True)
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
