"""Bounded-memory, preserving I/O for recovery of SimZ1 paged exports.

These helpers never execute MATSim, recreate motion, or remove an existing or
failed output. Only a successfully published helper-owned staging file is
removed. HTML inspection decodes one movement record at a time.
"""
import errno
import hashlib
from html.parser import HTMLParser
import json
import math
import mmap
import os
from pathlib import Path
import re
import shutil
import tempfile
import uuid


DEFAULT_RESERVE_BYTES = 256 * 1024 * 1024
CHUNK_BYTES = 1024 * 1024
MAX_RECORD_BYTES = 64 * 1024 * 1024
MAX_CONFIG_BYTES = 128 * 1024 * 1024
REPLAY_MARKER = b'<script id="replay-data" type="application/json">'
_TRIPS_ID = re.compile(rb'"id"\s*:\s*"trips"')
_DATA_FIRST = re.compile(rb'\{\s*"@@type"\s*:\s*"ScatterplotLayer"\s*,\s*"data"\s*:\s*\[')
_ID_FIRST = re.compile(rb'\{\s*"id"\s*:\s*"trips"\s*,\s*(?:"@@type"\s*:\s*"ScatterplotLayer"\s*,\s*)?"data"\s*:\s*\[')


class StorageUnavailableError(OSError):
    """The selected volume/directory cannot safely receive an export."""


def storage_parent(path):
    """Resolve the existing directory without silently substituting a drive."""
    path = Path(path).resolve()
    parent = path
    while not parent.exists():
        if parent.parent == parent:
            raise StorageUnavailableError(errno.ENOENT,
                f'Unidad o ruta de almacenamiento no disponible: {path}', str(path))
        parent = parent.parent
    if not parent.is_dir():
        raise StorageUnavailableError(errno.ENOTDIR,
            f'El destino o un componente de su ruta no es una carpeta: {parent}', str(path))
    return path, parent


def filesystem_info(directory):
    """Inspect the real Windows volume, including mounted-volume directories."""
    if os.name != 'nt':
        readonly = bool(getattr(os.statvfs(directory), 'f_flag', 0) & getattr(os, 'ST_RDONLY', 1))
        return dict(format='platform filesystem', readonly=readonly, max_file_bytes=None)
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetVolumePathNameW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
    kernel.GetVolumePathNameW.restype = wintypes.BOOL
    kernel.GetVolumeInformationW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD),
        wintypes.LPWSTR, wintypes.DWORD]
    kernel.GetVolumeInformationW.restype = wintypes.BOOL
    root, filesystem = ctypes.create_unicode_buffer(32768), ctypes.create_unicode_buffer(256)
    flags = wintypes.DWORD()
    if not kernel.GetVolumePathNameW(str(directory), root, len(root)):
        raise ctypes.WinError(ctypes.get_last_error())
    if not kernel.GetVolumeInformationW(root.value, None, 0, None, None,
                                        ctypes.byref(flags), filesystem, len(filesystem)):
        raise ctypes.WinError(ctypes.get_last_error())
    kind = filesystem.value.upper()
    return dict(format=kind, readonly=bool(flags.value & 0x00080000),
                max_file_bytes=2 ** 32 - 1 if kind in ('FAT', 'FAT32') else None)


def preflight_storage(path, required_bytes=0, reserve_bytes=DEFAULT_RESERVE_BYTES,
                      *, probe_write=False, largest_file_bytes=0):
    """Validate storage before reading large HTML or starting any output.

    Diagnostic calls are strictly read-only. A recovery also opens and closes
    one tiny OS-temporary file in the nearest existing directory to test ACLs;
    no recovery directory, large file, or persistent probe is created.
    """
    path, parent = storage_parent(path)
    try:
        filesystem = filesystem_info(parent)
        if filesystem['readonly'] and (probe_write or required_bytes):
            raise PermissionError(errno.EROFS, 'Sistema de archivos de solo lectura', str(path))
        limit = filesystem['max_file_bytes']
        if limit is not None and largest_file_bytes > limit:
            raise StorageUnavailableError(errno.EFBIG,
                f'{filesystem["format"]} no admite el bloque estimado de {largest_file_bytes} bytes '
                f'(limite {limit}); elija otra unidad', str(path))
        result = ensure_space(parent, required_bytes, reserve_bytes)
        # Even the one-byte ACL probe is a temporary file. Verify the real
        # path, filesystem limits and free-space budget before creating it.
        if probe_write:
            with tempfile.TemporaryFile(prefix='.simz1-storage-probe-', dir=parent) as probe:
                probe.write(b'0')
                probe.flush()
                os.fsync(probe.fileno())
    except OSError as exc:
        if exc.errno == errno.ENOSPC or isinstance(exc, StorageUnavailableError):
            raise
        raise StorageUnavailableError(exc.errno or errno.EIO,
            f'Almacenamiento no disponible o no escribible: {path}: {exc}', str(path)) from exc
    return dict(result, requested_path=str(path), filesystem=filesystem,
                writable_verified=probe_write, device=parent.stat().st_dev)


def _unique_object(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError(f'Clave JSON duplicada: {key}')
        result[key] = value
    return result


def _nonfinite(value):
    raise ValueError(f'Numero JSON no finito: {value}')


DECODER = json.JSONDecoder(object_pairs_hook=_unique_object, parse_constant=_nonfinite)


def _loads(raw):
    return json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_nonfinite)


def _json_bytes(value):
    # Match the native exporter's protection against closing its JSON script.
    raw = json.dumps(value, separators=(',', ':'), allow_nan=False, ensure_ascii=True)
    return raw.replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026').encode('ascii')


def ensure_space(path, required_bytes, reserve_bytes=DEFAULT_RESERVE_BYTES):
    """Check the filesystem actually containing a path, including new paths."""
    if required_bytes < 0 or reserve_bytes < 0:
        raise ValueError('Los bytes requeridos y la reserva deben ser no negativos')
    parent = Path(path).resolve()
    while not parent.exists():
        if parent.parent == parent:
            raise FileNotFoundError(str(path))
        parent = parent.parent
    if parent.is_file():
        parent = parent.parent
    usage = shutil.disk_usage(parent)
    if usage.free < required_bytes + reserve_bytes:
        raise OSError(errno.ENOSPC,
            f'Espacio insuficiente en {parent}: {usage.free} bytes libres; '
            f'se requieren {required_bytes} + {reserve_bytes} de reserva', str(path))
    return dict(path=str(parent), free_bytes=usage.free, total_bytes=usage.total,
                required_bytes=required_bytes, reserve_bytes=reserve_bytes)


def _new_stage(parent, name):
    parent = Path(parent)
    parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f'.{name}.', suffix='.partial', dir=parent)
    return Path(name), os.fdopen(descriptor, 'wb')


def _sync_directory(directory):
    # Windows does not expose directory fsync through ordinary os.open.
    if os.name == 'nt':
        return
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _publish_new(staging, destination):
    """Publish without replacing an existing file, even in a concurrent run."""
    destination = Path(destination)
    if os.name == 'nt':
        # Unlike replace(), Windows rename refuses an existing destination.
        os.rename(staging, destination)
    else:
        os.link(staging, destination)
        Path(staging).unlink()  # Our complete, successfully published staging.
    _sync_directory(destination.parent)


def atomic_json_preserve(path, value, reserve_bytes=DEFAULT_RESERVE_BYTES, *, overwrite=True):
    """Atomically replace JSON; any failed unique staging file is preserved."""
    path = Path(path)
    payload = _json_bytes(value) + b'\n'
    ensure_space(path, len(payload), reserve_bytes)
    staging, stream = _new_stage(path.parent, path.name)
    with stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    if overwrite:
        os.replace(staging, path)
        _sync_directory(path.parent)
    else:
        _publish_new(staging, path)
    return path


def atomic_copy_preserve(source, destination, reserve_bytes=DEFAULT_RESERVE_BYTES):
    """Copy to a unique sibling then publish; never overwrite an existing file."""
    source, destination = Path(source), Path(destination)
    if destination.exists():
        raise FileExistsError(str(destination))
    before = source.stat()
    ensure_space(destination, before.st_size, reserve_bytes)
    staging, output = _new_stage(destination.parent, destination.name)
    copied = 0
    with source.open('rb') as incoming, output:
        for chunk in iter(lambda: incoming.read(CHUNK_BYTES), b''):
            ensure_space(destination, len(chunk), reserve_bytes)
            output.write(chunk)
            copied += len(chunk)
        output.flush()
        os.fsync(output.fileno())
    after = source.stat()
    if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino) or copied != before.st_size:
        raise ValueError(f'El origen cambio durante la copia: {source}; se conserva {staging}')
    _publish_new(staging, destination)
    return destination


class _HtmlCompleteness(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.open = {'script': 0, 'html': 0, 'body': 0}
        self.seen = set()
        self.html_ended = False

    def handle_starttag(self, tag, attrs):
        if self.html_ended:
            raise ValueError('Contenido HTML despues de </html>')
        if tag in self.open:
            self.open[tag] += 1
            self.seen.add(tag)

    def handle_endtag(self, tag):
        if tag in self.open:
            self.open[tag] -= 1
            if self.open[tag] < 0:
                raise ValueError(f'Cierre HTML inesperado: {tag}')
            if tag == 'html':
                self.html_ended = True

    def handle_data(self, data):
        if self.html_ended and data.strip():
            raise ValueError('Contenido inesperado despues del HTML')


def _check_html(prefix, suffix):
    if not prefix.endswith(REPLAY_MARKER) or not suffix.startswith(b'</script>'):
        raise ValueError('Limites del script replay incompletos')
    parser = _HtmlCompleteness()
    parser.feed((prefix + b'{}' + suffix).decode('utf-8'))
    parser.close()
    if 'script' not in parser.seen or any(parser.open.values()) or parser.rawdata.strip():
        raise ValueError('HTML truncado o etiquetas finales incompletas')


def _array_scan(path, byte_start):
    """Decode one JSON object at a time; return the exact byte after ']'."""
    vehicles = set()
    segments = 0
    first_record = last_record = previous_interval = None
    positive_min_end, positive_max_start = math.inf, -math.inf
    zero_min, zero_max = math.inf, -math.inf
    with Path(path).open('r', encoding='utf-8', newline='') as stream:
        stream.seek(byte_start)
        buffer, position, base, eof = '', 0, byte_start, False

        def refill():
            nonlocal buffer, position, base, eof
            base += len(buffer[:position].encode('utf-8'))
            buffer = buffer[position:]
            position = 0
            addition = stream.read(CHUNK_BYTES)
            if not addition:
                eof = True
            buffer += addition
            if len(buffer) > MAX_RECORD_BYTES:
                raise ValueError('Registro individual demasiado grande o JSON truncado')

        def char():
            nonlocal position
            while True:
                while position < len(buffer) and buffer[position] in ' \t\r\n':
                    position += 1
                if position < len(buffer):
                    return buffer[position]
                if eof:
                    raise ValueError('Array trips truncado')
                refill()

        if char() != '[':
            raise ValueError('trips.data debe ser un array JSON')
        position += 1
        if char() == ']':
            return dict(array_end=base + len(buffer[:position + 1].encode('utf-8')),
                        segments=0, vehicles=0, sample_records=[],
                        positive_min_end=positive_min_end, positive_max_start=positive_max_start,
                        zero_min=zero_min, zero_max=zero_max)
        while True:
            if char() != '{':
                raise ValueError('Cada movimiento debe ser un objeto JSON')
            while True:
                try:
                    record, end = DECODER.raw_decode(buffer, position)
                    break
                except json.JSONDecodeError as error:
                    if eof:
                        raise ValueError('Registro de movimiento truncado o invalido') from error
                    refill()
            position = end
            if not isinstance(record.get('Motion_Plan'), dict):
                raise ValueError(f'Motion_Plan ausente o invalido en el movimiento {segments}')
            vehicle = record.get('vehicle')
            if not isinstance(vehicle, str) or not vehicle:
                raise ValueError(f'Identidad vehicle invalida en el movimiento {segments}')
            timestamps = record.get('timestamps')
            if (not isinstance(timestamps, list) or len(timestamps) != 2 or
                    any(type(value) not in (int, float) or not math.isfinite(value) for value in timestamps) or
                    timestamps[0] > timestamps[1]):
                raise ValueError(f'Timestamps invalidos en el movimiento {segments}')
            interval = tuple(timestamps)
            if previous_interval is not None and interval < previous_interval:
                raise ValueError(f'Movimientos fuera de orden en el registro {segments}')
            previous_interval = interval
            if interval[0] < interval[1]:
                positive_min_end = min(positive_min_end, interval[1])
                positive_max_start = max(positive_max_start, interval[0])
            else:
                zero_min, zero_max = min(zero_min, interval[0]), max(zero_max, interval[0])
            if first_record is None:
                first_record = record
            last_record = record
            vehicles.add(vehicle)
            segments += 1
            separator = char()
            position += 1
            if separator == ']':
                return dict(array_end=base + len(buffer[:position].encode('utf-8')),
                            segments=segments, vehicles=len(vehicles),
                            sample_records=[first_record] if segments == 1 else [first_record, last_record],
                            positive_min_end=positive_min_end, positive_max_start=positive_max_start,
                            zero_min=zero_min, zero_max=zero_max)
            if separator != ',':
                raise ValueError('Separador de movimientos JSON invalido')
            # The next iteration rejects trailing commas as well as truncation.


def inspect_block(path, expected_identity=None, expected_window=None):
    """Validate a complete emitted block without loading all movements in RAM.

    Supports the native data-first ScatterplotLayer schema and id-first small
    fixtures. All remaining configuration is parsed strictly after replacing
    only the recognized trips array. Legacy blocks may omit a manifest hash;
    the caller must tie those to the verified SQLite identity separately.
    """
    path = Path(path)
    before = path.stat()
    if not before.st_size:
        raise ValueError(f'Bloque vacio: {path}')
    with path.open('rb') as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
        marker_start = data.find(REPLAY_MARKER)
        if marker_start < 0:
            raise ValueError(f'Payload replay ausente: {path}')
        start = marker_start + len(REPLAY_MARKER)
        stop = data.find(b'</script>', start)
        if stop < 0:
            raise ValueError(f'Payload replay truncado: {path}')
        identity_matches = list(_TRIPS_ID.finditer(data, start, stop))
        if len(identity_matches) != 1:
            raise ValueError('La capa trips debe existir exactamente una vez')
        trips_position = identity_matches[0].start()
        match = _ID_FIRST.search(data, start, stop)
        if match is not None:
            array_start = match.end() - 1
        else:
            candidates = list(_DATA_FIRST.finditer(data, start, trips_position))
            if not candidates:
                raise ValueError('Formato de capa trips no reconocido')
            array_start = candidates[-1].end() - 1
        scanned = _array_scan(path, array_start)
        array_end, segments, vehicles = (scanned[key] for key in ('array_end', 'segments', 'vehicles'))
        if array_end > stop:
            raise ValueError('trips.data excede el script replay')
        if array_start - start + stop - array_end > MAX_CONFIG_BYTES:
            raise ValueError('Configuracion sin movimientos demasiado grande')
        config = _loads(data[start:array_start] + b'[]' + data[array_end:stop])
        trips = [layer for layer in config.get('layers', []) if layer.get('id') == 'trips']
        if len(trips) != 1 or trips[0].get('data') != []:
            raise ValueError('La region inspeccionada no corresponde exclusivamente a trips.data')
        pagination = config.get('pagination')
        if not isinstance(pagination, dict) or type(pagination.get('loaded_segments')) is not int or pagination['loaded_segments'] != segments:
            raise ValueError('loaded_segments no coincide con los movimientos completos')
        hud = config.get('hud', {})
        if not hud.get('run_id') or 'iteration' not in hud:
            raise ValueError('Identidad run_id/iteration ausente del bloque')
        if type(hud.get('reconstructed_vehicles')) is not int or hud['reconstructed_vehicles'] != vehicles:
            raise ValueError('hud.reconstructed_vehicles no coincide con los vehiculos completos')
        window = config.get('replay_window', {})
        if (any(type(window.get(key)) not in (int, float) or not math.isfinite(window[key])
                for key in ('start_seconds', 'end_seconds')) or
                not 0 <= window['start_seconds'] < window['end_seconds']):
            raise ValueError('Ventana temporal invalida')
        window_start, window_end = window['start_seconds'], window['end_seconds']
        if (scanned['positive_min_end'] <= window_start or scanned['positive_max_start'] >= window_end or
                scanned['zero_min'] < window_start or scanned['zero_max'] >= window_end):
            raise ValueError('Movimiento fuera de la ventana del bloque')
        provenance = config.get('recovery_identity', {})
        if not isinstance(provenance, dict):
            raise ValueError('Identidad de recuperacion invalida')
        if 'recovery_identity' in config:
            if any(provenance.get(key) != hud[key] for key in ('run_id', 'iteration')):
                raise ValueError('Identidad de recuperacion incompatible con HUD')
            if expected_identity is not None and any(provenance.get(key) != expected
                    for key, expected in expected_identity.items()):
                raise ValueError('Identidad de recuperacion incompleta o incompatible')
        for key, expected in (expected_identity or {}).items():
            actual = hud.get(key) if key in ('run_id', 'iteration') else provenance.get(key, hud.get(key))
            if key not in ('run_id', 'iteration') and actual is None:
                continue  # Legacy provenance must be checked against the spool.
            if (str(actual) != str(expected) if key == 'iteration' else actual != expected):
                raise ValueError(f'Identidad incompatible en {path.name}: {key}')
            if key in provenance and provenance[key] != expected:
                raise ValueError(f'Identidad de recuperacion incompatible: {key}')
        if expected_window is not None:
            if any(window.get(key) != expected_window[key] for key in ('start_seconds', 'end_seconds')):
                raise ValueError(f'Ventana incompatible en {path.name}')
            if 'index' in expected_window and pagination.get('block_index') != expected_window['index']:
                raise ValueError(f'Indice de bloque incompatible en {path.name}')
        prefix, suffix = data[:start], data[stop:]
        _check_html(prefix, suffix)
        digest = hashlib.sha256()
        for offset in range(0, len(data), CHUNK_BYTES):
            digest.update(data[offset:offset + CHUNK_BYTES])
    after = path.stat()
    if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
        raise ValueError(f'El bloque cambio mientras se inspeccionaba: {path}')
    return dict(config=config, sha256=digest.hexdigest(), html_bytes=before.st_size,
                segments=segments, vehicles=vehicles, prefix=prefix, suffix=suffix,
                sample_records=scanned['sample_records'])


def write_block(path, config, records, prefix, suffix, temp_dir,
                reserve_bytes=DEFAULT_RESERVE_BYTES):
    """Stream an original-record iterator and atomically publish a new block.

    Failed staging is never removed. On a different temporary filesystem the
    complete staged file is copied once and removed only after publication.
    The caller supplies a preflight whole-export estimate; this helper also
    checks available space before each bounded write.
    """
    path, temp_dir = Path(path), Path(temp_dir)
    if path.exists():
        raise FileExistsError(str(path))
    _check_html(prefix, suffix)
    # Only the trips-layer marker is changed. Duplicating hundreds of thousands
    # of lane dictionaries here would recreate the old memory pressure.
    config = dict(config)
    config['layers'] = [dict(layer) for layer in config.get('layers', [])]
    trips = [layer for layer in config.get('layers', []) if layer.get('id') == 'trips']
    if len(trips) != 1 or trips[0].get('data') != []:
        raise ValueError('Se requiere exactamente una capa trips vacia')
    sentinel = '__SIMZ1_RECOVERY_TRIPS_' + uuid.uuid4().hex + '__'
    trips[0]['data'] = sentinel
    serialized = _json_bytes(config)
    quoted = _json_bytes(sentinel)
    if serialized.count(quoted) != 1:
        raise ValueError('Marcador interno de trips ambiguo')
    head, tail = serialized.split(quoted)
    trips[0]['data'] = []
    ensure_space(temp_dir, len(prefix) + len(head) + len(tail) + len(suffix) + CHUNK_BYTES, reserve_bytes)
    ensure_space(path, len(prefix) + len(head) + len(tail) + len(suffix), reserve_bytes)
    staging, output = _new_stage(temp_dir, path.name)
    digest, segments, vehicles, size = hashlib.sha256(), 0, set(), 0
    checked_budget = 0
    first_record = last_record = previous_interval = None
    window = config.get('replay_window', {})
    if (any(type(window.get(key)) not in (int, float) or not math.isfinite(window[key])
            for key in ('start_seconds', 'end_seconds')) or
            not 0 <= window['start_seconds'] < window['end_seconds']):
        output.close()
        raise ValueError('Ventana temporal invalida; se conserva el stage')
    window_start, window_end = window['start_seconds'], window['end_seconds']
    with output:
        def write(payload):
            nonlocal size, checked_budget
            for offset in range(0, len(payload), CHUNK_BYTES):
                chunk = payload[offset:offset + CHUNK_BYTES]
                if len(chunk) > checked_budget:
                    checked_budget = max(CHUNK_BYTES, len(chunk))
                    ensure_space(staging, checked_budget, reserve_bytes)
                output.write(chunk)
                checked_budget -= len(chunk)
                digest.update(chunk)
                size += len(chunk)

        write(prefix + head + b'[')
        for record in records:
            if not isinstance(record, dict) or not isinstance(record.get('Motion_Plan'), dict):
                raise ValueError('No se permite publicar un movimiento sin Motion_Plan')
            if not isinstance(record.get('vehicle'), str) or not record['vehicle']:
                raise ValueError('Movimiento sin identidad vehicle')
            timestamps = record.get('timestamps')
            if (not isinstance(timestamps, list) or len(timestamps) != 2 or
                    any(type(value) not in (int, float) or not math.isfinite(value) for value in timestamps) or
                    timestamps[0] > timestamps[1]):
                raise ValueError('Movimiento con timestamps invalidos')
            interval = tuple(timestamps)
            if previous_interval is not None and interval < previous_interval:
                raise ValueError('Los movimientos no estan ordenados por tiempo')
            if not ((interval[0] < window_end and interval[1] > window_start) if interval[0] < interval[1]
                    else window_start <= interval[0] < window_end):
                raise ValueError('Movimiento fuera de la ventana del bloque')
            previous_interval = interval
            if first_record is None:
                first_record = record
            last_record = record
            payload = _json_bytes(record)
            write((b',' if segments else b'') + payload)
            segments += 1
            vehicles.add(record['vehicle'])
        expected = config.get('pagination', {}).get('loaded_segments')
        if type(expected) is not int or expected != segments:
            raise ValueError(f'Cantidad de movimientos incompatible: esperados={expected}, escritos={segments}')
        hud_vehicles = config.get('hud', {}).get('reconstructed_vehicles')
        if type(hud_vehicles) is not int or hud_vehicles != len(vehicles):
            raise ValueError('HUD de vehiculos incompatible; no se publica el bloque')
        write(b']' + tail + suffix)
        output.flush()
        os.fsync(output.fileno())
    path.parent.mkdir(parents=True, exist_ok=True)
    if staging.stat().st_dev == path.parent.stat().st_dev:
        _publish_new(staging, path)
    else:
        atomic_copy_preserve(staging, path, reserve_bytes=reserve_bytes)
        staging.unlink()  # Our complete stage, after durable final publication.
    return dict(config=config, sha256=digest.hexdigest(), html_bytes=size,
                segments=segments, vehicles=len(vehicles), prefix=prefix, suffix=suffix,
                sample_records=[] if not segments else [first_record] if segments == 1 else [first_record, last_record])
