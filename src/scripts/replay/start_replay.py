"""Launch the existing SimZ1 continuous API in the foreground; never build data."""
import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import subprocess
import sys
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, build_opener
from urllib.parse import urlencode
import uuid
import webbrowser


PROJECT = Path(__file__).resolve().parents[2]
IDENTITY = ('run_id', 'iteration', 'run_manifest_sha256')


def expected_replay_window(manifest):
    sys.path.insert(0,str(PROJECT/'python'))
    from simz1_freight_completion import observation_contract
    experimental=observation_contract(manifest)
    if experimental:return dict(start_seconds=0,end_seconds=experimental['observation_end_seconds'])
    policy = manifest.get('temporal_policy')
    if policy is None:
        return dict(start_seconds=0, end_seconds=86400)
    if policy.get('schema_version') != 'simz1-weekday-continuous-v1':
        raise ValueError('Politica temporal desconocida; no se recorta silenciosamente a 24 h')
    window, study = policy['windows']['simulation'], policy['windows']['study']
    if (window != manifest['time_horizon'] or study['end_seconds']-study['start_seconds'] != 86400 or
            window['start_seconds'] < 0 or window['end_seconds'] < study['end_seconds']):
        raise ValueError('Ventanas temporales incompatibles con el manifiesto nativo')
    return dict(window)


def read_object(path):
    raw = Path(path).read_bytes()
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError(f'Se esperaba un objeto JSON: {path}')
    return value, hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class Selection:
    run_directory: str
    replay_directory: str
    run_id: str
    iteration: int
    run_manifest_sha256: str
    selection_source: str
    source_type: str
    source_manifest_sha256: str
    replay_manifest_sha256: str
    database_sha256: str | None
    database_bytes: int | None
    database_mtime_ns: int | None
    planned_persons: int
    replay_start: float = 0
    replay_end: float = 86400
    visual_policy: str | None = None


def resolve_selection(project, run_dir=None, iteration=None, replay_dir=None, visual_policy=None):
    """Read metadata only: no events/plans hashing, SQLite queries or fallback run."""
    if visual_policy not in (None,'partial-native-v1'):raise ValueError('Unsupported partial visual policy')
    if visual_policy is not None and (run_dir is None or iteration is None or replay_dir is None):
        raise ValueError('Partial visual mode requires explicit run, iteration and replay directories')
    project = Path(project).resolve()
    reference = None
    if run_dir is None:
        reference, _ = read_object(project/'scenarios/zona1/montecarlo/latest-successful.json')
        run_dir = reference['folder']
    directory = Path(run_dir).resolve(strict=True)
    manifest, manifest_hash = read_object(directory/'run-manifest.json')
    if (manifest.get('schema_version') != 1 or
            Path(manifest['folder']).resolve() != directory):
        raise ValueError('El manifiesto nativo no corresponde a la carpeta seleccionada')
    run_id = manifest.get('run_id')
    if not isinstance(run_id, str) or not run_id:
        raise ValueError('Identidad de corrida ausente')
    if reference and (reference.get('run_id') != run_id or reference.get('manifest_sha256') != manifest_hash):
        raise ValueError('latest-successful no coincide con su manifiesto; no hay fallback')
    if manifest.get('status') != 'completed' or manifest.get('validation', {}).get('status') != 'valid':
        raise ValueError('Se requiere una corrida completed/valid; no se genera ni ejecuta otra')
    iterations = manifest['iterations']
    selected = iterations['last'] if iteration is None else iteration
    if (type(selected) is not int or selected < 0 or selected not in iterations['completed'] or
            not iterations['first'] <= selected <= iterations['last'] or str(selected) not in manifest['results']):
        raise ValueError('La iteracion solicitada no tiene resultados validados; no se cambia de iteracion')
    expected = dict(run_id=run_id, iteration=selected, run_manifest_sha256=manifest_hash)
    visible = expected_replay_window(manifest)
    candidates = [Path(replay_dir).resolve(strict=True)] if replay_dir is not None else sorted(
        child for child in directory.iterdir() if child.is_dir() and (child/'continuous-manifest.json').is_file())
    compatible = []
    for candidate in candidates:
        export, replay_hash = read_object(candidate/'continuous-manifest.json')
        if (export.get('status') != 'complete' or export.get('sample_rate') != 1 or
                any(export.get(key) != value for key, value in expected.items())):
            if replay_dir is not None:
                raise ValueError(f'ReplayDir no coincide: solicitada={expected}; encontrada='+
                                 str({key: export.get(key) for key in IDENTITY})+
                                 f'; status={export.get("status")}; sample_rate={export.get("sample_rate")}')
            continue
        window = export.get('replay_window', {})
        start, end = window.get('start_seconds'), window.get('end_seconds')
        if (type(start) not in (int, float) or type(end) not in (int, float) or
                not math.isfinite(start) or not math.isfinite(end) or start != visible['start_seconds'] or end < visible['end_seconds']):
            if replay_dir is not None:
                raise ValueError('ReplayDir no cubre la jornada completa y su ventana solicitada: '+str(visible))
            continue
        source_type = export.get('source_type', 'paged-html-v1')
        if source_type not in ('paged-html-v1', 'sqlite-direct-v1'):
            raise ValueError('Tipo de fuente de replay no compatible; no hay fallback')
        source_name = ('sqlite-source-manifest.json' if source_type == 'sqlite-direct-v1'
                       else 'export-manifest.json')
        source, source_hash = read_object(Path(export['source_directory'])/source_name)
        if (source.get('status') != 'complete' or source.get('sample_rate') != 1 or
                source_hash != export.get('source_export_sha256') or
                source.get('source_type', 'paged-html-v1') != source_type or
                any(source.get(key) != value for key, value in expected.items()) or
                Path(source['run_directory']).resolve() != directory):
            raise ValueError('El export fuente del continuo no pertenece a la corrida seleccionada: '+
                             f'solicitada={expected}; encontrada='+str({key: source.get(key) for key in IDENTITY}))
        compatible.append((candidate, export, source, replay_hash))
    if not compatible:
        raise ValueError('No existe un export continuo completo compatible con la ventana solicitada para esta iteracion; no se exporta automaticamente')
    if len(compatible) != 1:
        raise ValueError('Hay varios exports compatibles; indique -ReplayDir / --replay-dir: '+
                         ', '.join(str(item[0]) for item in compatible))
    candidate, export, source, replay_hash = compatible[0]
    return Selection(str(directory), str(candidate), run_id, selected, manifest_hash,
                     'latest-successful' if reference is not None else 'explicit-run',
                     export.get('source_type', 'paged-html-v1'), export['source_export_sha256'],
                     replay_hash, source.get('database_sha256'), export.get('database_bytes'),
                     export.get('database_mtime_ns'), manifest['counts']['planned_persons'],
                     visible['start_seconds'], visible['end_seconds'],visual_policy=visual_policy)


def validate_api_config(config, selection):
    if not isinstance(config, dict):
        raise ValueError('La API no entrega una configuracion valida')
    continuous = config.get('continuous')
    hud = config.get('hud')
    if (not isinstance(continuous, dict) or
            any(continuous.get(key) != getattr(selection, key) for key in IDENTITY) or
            type(continuous.get('iteration')) is not int or
            not isinstance(hud, dict) or hud.get('run_id') != selection.run_id or
            type(hud.get('iteration')) is not int or hud['iteration'] != selection.iteration):
        raise ValueError('La API sirve otra corrida, iteracion o hash; no abrir el navegador: '+
                         f'solicitada={dict((key, getattr(selection, key)) for key in IDENTITY)}; '+
                         f'encontrada={continuous}')
    visual_policy=getattr(selection,'visual_policy',None)
    if continuous.get('visual_policy') != visual_policy:
        raise ValueError('La API sirve otra politica visual')
    partial=config.get('partial_visual_policy')
    if visual_policy is not None:
        if (not isinstance(partial,dict) or partial.get('policy')!=visual_policy or
                partial.get('pending_reason')!='reconstruction_pending' or
                partial.get('body_position_available') is not False or
                partial.get('native_status')!='completed' or partial.get('native_validation')!='valid'):
            raise ValueError('La API no declara la evidencia nativa y limitacion visual parcial')
    elif partial is not None:
        raise ValueError('La API declara una limitacion visual no solicitada')
    provenance = config.get('replay_source', {})
    fields = ('source_type', 'source_manifest_sha256', 'replay_manifest_sha256',
              'database_sha256', 'database_bytes', 'database_mtime_ns')
    if (not isinstance(provenance, dict) or
            any(provenance.get(key) != getattr(selection, key) for key in fields) or
            continuous.get('source_version') != selection.source_manifest_sha256):
        raise ValueError('La API sirve otra procedencia SQLite/replay; solicitada='+
                         str({key: getattr(selection, key) for key in fields})+f'; encontrada={provenance}')
    if hud.get('planned_persons') != selection.planned_persons:
        raise ValueError('La poblacion de la API difiere del manifiesto nativo validado')
    if '_http_hud' in config:
        verified = config['_http_hud']
        if verified.get('visual_policy') != visual_policy:raise ValueError('HUD de otra politica visual')
        if (any(verified.get(key) != getattr(selection, key) for key in IDENTITY) or
                verified.get('source_version') != selection.source_manifest_sha256 or
                verified.get('counts', {}).get('persons_generated') != selection.planned_persons or
                verified.get('replay_window') != config.get('replay_window')):
            raise ValueError('El HUD HTTP no coincide con la fuente solicitada')
    for window in (config.get('replay_window', {}), continuous):
        if (not isinstance(window, dict) or type(window.get('start_seconds')) not in (int, float) or
                type(window.get('end_seconds')) not in (int, float) or
                window['start_seconds'] != selection.replay_start or window['end_seconds'] != selection.replay_end):
            raise ValueError(f'La API no sirve exactamente {selection.replay_start}..{selection.replay_end}; no abrir el navegador')
    return config


def read_api_config(base):
    """Only connection refusal means a free port; errors/timeouts are not reuse."""
    try:
        # Loopback is never sent through a user-configured HTTP proxy.
        opener = build_opener(ProxyHandler({}))
        with opener.open(base+'/api/config', timeout=3) as response:
            config = json.load(response)
        # Query the actual HUD contract, including its full visible window.
        # An old SimZ1 can still be identified for controlled replacement.
        continuous, window = config.get('continuous', {}), config.get('replay_window', {})
        query = {key: continuous[key] for key in IDENTITY}
        query.update({key: window[key] for key in ('start_seconds', 'end_seconds')})
        if 'source_version' in continuous:
            query['source_version'] = continuous['source_version']
        if 'visual_policy' in continuous:query['visual_policy']=continuous['visual_policy']
        with opener.open(base+'/api/hud?'+urlencode(query), timeout=10) as response:
            config['_http_hud'] = json.load(response)
        return config
    except HTTPError as error:
        raise ValueError(f'El puerto responde HTTP {error.code}; no se reemplaza el servicio') from error
    except URLError as error:
        reason = error.reason
        if isinstance(reason, ConnectionRefusedError) or getattr(reason, 'errno', None) in (61, 111, 10061):
            return None
        raise ValueError(f'No se pudo comprobar el puerto local: {reason}') from error


def production_components(directory,*,checkpoint_plan=None,visual_policy=None):
    # Import exactly the existing production server/ContinuousReplay validation.
    # No independent HTTP handler or call to select_run() is introduced here.
    python = str(PROJECT/'python')
    if python not in sys.path:
        sys.path.insert(0, python)
    from serve_simz1_continuous import ContinuousServer, handler_for
    return ContinuousServer, handler_for(directory,checkpoint_plan=checkpoint_plan,
        **({'visual_policy':visual_policy} if visual_policy is not None else {}))


def listener_snapshot(port):
    """Current Windows listener and command, never a saved PID."""
    if sys.platform != 'win32':
        raise ValueError('El reemplazo controlado de servidores requiere Windows; no se detiene otro proceso')
    script = f"""
$ErrorActionPreference = 'Stop'
$items = @(Get-NetTCPConnection -State Listen -LocalPort {int(port)} -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty OwningProcess -Unique)
if ($items.Count -ne 1) {{ throw 'Se requiere exactamente un propietario actual del puerto.' }}
$p = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $items[0])
[pscustomobject]@{{pid=$p.ProcessId; command=$p.CommandLine;
    started=$p.CreationDate.ToUniversalTime().ToString('o'); executable=$p.ExecutablePath}} | ConvertTo-Json -Compress
"""
    result = subprocess.run(['powershell.exe', '-NoProfile', '-Command', script],
        capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def command_arguments(command):
    # CommandLineToArgvW matches the Windows quoting used by Python/PowerShell.
    if sys.platform == 'win32':
        import ctypes
        count = ctypes.c_int()
        function = ctypes.windll.shell32.CommandLineToArgvW
        function.argtypes = (ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_int))
        function.restype = ctypes.POINTER(ctypes.c_wchar_p)
        values = function(command, ctypes.byref(count))
        if not values:
            raise ValueError('No se pudo interpretar el comando del propietario')
        try:
            return [values[index] for index in range(count.value)]
        finally:
            ctypes.windll.kernel32.LocalFree(values)
    import shlex
    return shlex.split(command)


def identified_server(snapshot, config, project=PROJECT):
    args = command_arguments(snapshot['command'])
    if not args or Path(args[0]).name.lower() not in ('python.exe', 'pythonw.exe', 'python', 'python3'):
        raise ValueError('El propietario del puerto no es un servidor Python SimZ1 acreditado')
    def argument(flag):
        if args.count(flag) != 1 or args.index(flag)+1 >= len(args):
            raise ValueError(f'Comando SimZ1 ambiguo: falta {flag}')
        return args[args.index(flag)+1]
    def resolved(value):
        path = Path(value)
        return (path if path.is_absolute() else project/path).resolve()
    scripts = [resolved(value) for value in args[1:] if value.lower().endswith('.py')]
    if scripts == [(project/'python/serve_simz1_continuous.py').resolve()]:
        directory = resolved(argument('--directory'))
    elif scripts == [(project/'scripts/replay/start_replay.py').resolve()]:
        directory = resolved(argument('--replay-dir'))
    else:
        raise ValueError('El comando del propietario no pertenece al servidor SimZ1 de este repositorio')
    old, _ = read_object(directory/'continuous-manifest.json')
    if (old.get('status') != 'complete' or
            any(old.get(key) != config.get('continuous', {}).get(key) for key in IDENTITY)):
        raise ValueError('El comando, carpeta e identidad HTTP del servidor antiguo no coinciden')
    return directory


def replace_simz1_listener(port, config, *, snapshot=listener_snapshot, stop=None,
                           project=PROJECT, record=lambda *args, **kwargs: None):
    """Stop only a revalidated listener after the replacement replay is ready."""
    before = snapshot(port)
    directory = identified_server(before, config, project)
    if snapshot(port) != before:
        raise ValueError('El propietario del puerto cambio; no se detiene ningun proceso')
    record('replacing_server', process=before, replay_directory=str(directory),
           served_identity=config.get('continuous'))
    if stop is not None:
        stop(before)
        return
    # Re-check inside the stopping command, closing the PID-reuse/race window as
    # far as Get-Process exposes it. Only this PID is stopped (no process tree).
    encoded = __import__('base64').b64encode(json.dumps(before).encode('utf-8')).decode('ascii')
    script = f"""
$ErrorActionPreference = 'Stop'
$expected = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{encoded}')) | ConvertFrom-Json
$process = Get-Process -Id $expected.pid
$null = $process.Handle
$current = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $expected.pid)
$owners = @(Get-NetTCPConnection -State Listen -LocalPort {int(port)} | Select-Object -ExpandProperty OwningProcess -Unique)
if ($owners.Count -ne 1 -or $owners[0] -ne $expected.pid -or
    $current.CommandLine -cne $expected.command -or
    $current.CreationDate.ToUniversalTime().ToString('o') -cne $expected.started) {{
    throw 'El proceso cambio antes de detenerlo; no se reemplaza.'
}}
$process.Kill()
$process.WaitForExit(10000) | Out-Null
"""
    subprocess.run(['powershell.exe', '-NoProfile', '-Command', script], check=True)
    deadline = time.monotonic()+10
    base = f'http://127.0.0.1:{port}'
    while read_api_config(base) is not None:
        if time.monotonic() >= deadline:
            raise ValueError('El puerto no quedo libre; no se detiene ningun otro proceso')
        time.sleep(.1)


def viewer_url(base, selection):
    return base+'/index.html?'+urlencode(dict(
        **{key: getattr(selection, key) for key in IDENTITY},
        source_version=selection.source_manifest_sha256,
        **({'visual_policy':selection.visual_policy} if getattr(selection,'visual_policy',None) is not None else {})))


def serve_selected(selection, port, *, no_browser=False, check_only=False,
                   components=production_components, probe=read_api_config,
                   open_browser=webbrowser.open, record=lambda *args, **kwargs: None,
                   replace_existing=False, replace=replace_simz1_listener):
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError('Puerto fuera de 1..65535')
    server_type, handler = components(selection.replay_directory)
    validate_api_config(handler.replay.config, selection)
    if check_only:
        record('checked', **asdict(selection))
        return 'checked'
    base = f'http://127.0.0.1:{port}'
    address = viewer_url(base, selection)
    existing = probe(base)
    if existing is not None:
        try:
            validate_api_config(existing, selection)
        except ValueError:
            if not replace_existing:
                raise
            print('Servidor anterior incompatible; replay solicitado ya validado. Verificando propietario actual para el cambio.', flush=True)
            replace(port, existing, record=record)
            existing = probe(base)
            if existing is not None:
                raise ValueError('El puerto fue ocupado durante el cambio; no se reemplaza otro proceso')
    if existing is not None:
        record('reused', url=address, owns_server=False)
        print('Servidor compatible reutilizado. Este launcher no es su propietario; '
              'Ctrl+C aqui no lo detiene. Use la consola original para cerrarlo.', flush=True)
        print(address, flush=True)
        if not no_browser:
            open_browser(address)
        return 'reused'
    # The bound object below is the only server this launcher may close.
    # A bind race is an error, never permission to stop a different listener.
    server = server_type(('127.0.0.1', port), handler)
    stopped, errors = threading.Event(), []

    def confirm_ready():
        try:
            deadline = time.monotonic()+15
            while not stopped.is_set():
                config = probe(base)
                if config is not None:
                    validate_api_config(config, selection)
                    if stopped.is_set():
                        return
                    record('ready', url=address, owns_server=True)
                    print('Identidad HTTP comprobada: '+selection.run_id+f' | iteracion {selection.iteration} | personas {selection.planned_persons}', flush=True)
                    print(address+' | Ctrl+C detiene este servidor.', flush=True)
                    if not no_browser and not stopped.is_set():
                        open_browser(address)
                    return
                if time.monotonic() >= deadline:
                    raise ValueError('La API no confirmo identidad/horizonte a tiempo')
                stopped.wait(.1)
        except Exception as error:
            if not stopped.is_set():
                errors.append(error)
                record('readiness_failed', error=str(error))
                server.shutdown()

    watcher = threading.Thread(target=confirm_ready, name='simz1-replay-ready', daemon=True)
    watcher_started = False
    try:
        watcher.start()
        watcher_started = True
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stopped.set()
        server.server_close()
        if watcher_started:
            watcher.join(timeout=4)
        record('stopped', owns_server=True)
    if errors:
        raise ValueError('No se abrio el visor: '+str(errors[0]))
    return 'stopped'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, help='Omitir usa exclusivamente latest-successful validada')
    parser.add_argument('--iteration', type=int, help='Omitir usa iterations.last validada; nunca otra iteracion')
    parser.add_argument('--replay-dir', type=Path, help='Export continuo existente; obligatorio si hay varios compatibles')
    parser.add_argument('--port', type=int, default=8792)
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--check-only', action='store_true', help='Validar export existente sin servidor ni navegador')
    parser.add_argument('--checkpoint-plan',type=Path,help='Reconstruir y verificar el soporte causal solicitado antes de servir')
    parser.add_argument('--visual-policy',choices=('partial-native-v1',),help='Apertura parcial: evidencia nativa validada, cuerpos pendientes ocultos, sin indice ni grafo causal')
    parser.add_argument('--replace-simz1', action='store_true', help='Cambiar solo un servidor SimZ1 local identificado, despues de validar el replay solicitado')
    args = parser.parse_args(argv)
    if args.visual_policy is not None and args.checkpoint_plan is not None:
        parser.error('--visual-policy partial-native-v1 cannot be combined with --checkpoint-plan')
    folder = PROJECT/'runtime/replay'
    folder.mkdir(parents=True, exist_ok=True)
    receipt = folder/f'launch-{uuid.uuid4().hex}.jsonl'
    lock = threading.Lock()
    with receipt.open('x', encoding='utf-8') as stream:
        def record(event, **values):
            with lock:
                stream.write(json.dumps(dict(event=event, utc=datetime.now(timezone.utc).isoformat(),
                                             **values), ensure_ascii=False, allow_nan=False)+'\n')
                stream.flush()
        if not args.check_only:
            print(f'Registro: {receipt}', flush=True)
        try:
            selection = resolve_selection(PROJECT, args.run_dir, args.iteration, args.replay_dir,
                **({'visual_policy':args.visual_policy} if args.visual_policy is not None else {}))
            record('selected', **asdict(selection), port=args.port, check_only=args.check_only)
            mode = serve_selected(selection, args.port, no_browser=args.no_browser,
                                  check_only=args.check_only, record=record,
                                  components=(lambda directory:production_components(directory,checkpoint_plan=args.checkpoint_plan,visual_policy=args.visual_policy)),
                                  replace_existing=args.replace_simz1)
            if args.check_only:
                print(json.dumps(dict(status=mode, **asdict(selection),
                    replay_window=dict(start_seconds=selection.replay_start, end_seconds=selection.replay_end), receipt=str(receipt)),
                    ensure_ascii=False, indent=2))
            return 0
        except (OSError, ValueError, KeyError, TypeError, sqlite3.Error, subprocess.CalledProcessError) as error:
            record('failed', error=str(error))
            print(f'No se pudo abrir el replay: {error}', file=sys.stderr)
            return 1


if __name__ == '__main__':
    raise SystemExit(main())
