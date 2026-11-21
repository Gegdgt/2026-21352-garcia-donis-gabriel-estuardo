"""Open only the two approved existing viewers; never prepare or run a simulation.

This is a separate, explicit read-only publication contract. Historical launchers
and their experimental fingerprint guards are unchanged. The producer fingerprint
remains provenance, not a claim that today's experimental tree is identical.
Native manifests, recovery receipt, existing replay validation and approved HTML
are mandatory. Runtime reader caches may be used by the unchanged HTTP handler;
--verify-only checks existing metadata/SQLite identity without spatial preparation
and writes nothing. The unchanged handler verifies the full spatial contract once
when it starts, before HTTP becomes available.
"""
import argparse
from contextlib import redirect_stdout
import ctypes
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import socket
import sys

sys.dont_write_bytecode = True
os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
ROOT = Path(__file__).resolve().parents[1]
DELIVERY = ROOT / 'runtime/diagnostics/run10k-v8-thesis-viewer-20261108'
PRODUCER = '1db657d6f60b487c96d2180798e3d4beba8ed58be693de8617f22c5257bbdc17'
RECOVERY = ROOT / 'runtime/recoveries/57c61494b1804a3cbaff53f7afdf797a/recovery-receipt.json'
RECOVERY_SHA = '159383f474d6ffd3c46c9ac49522745e3993d1b12cc0ab2d1d91e92b689b6e78'
INTEGRITY_SHA = '8be30acaa1bc00216d3de9789fca3d96e791f55c3d06fd7ad515488c813fa3ff'
# Reviewed reader implementation for this publication contract, independent of
# the historical producer fingerprint. A change requires review, not a bypass.
READERS = {
    'serve_simz1_continuous.py': '08809f3f89b1f1dfd205678059104638d467fcfe4a852d51ba3d94632f982124',
    'simz1_continuous_replay.py': '43499deb18a7a33790891c50a8a56e9df240b88043c4dcbc6370bf4950da9ce6',
    'simz1_sqlite_source.py': 'f299a4c7f546468f5a588eb07f3402642bdc9411c82a1b55fe5c5c8839862e4e',
    'simz1_replay_workers.py': '04ba95ed73906869b5eb1399eb2374195cfd8024534bf212aae79913fa756add',
    'simz1_window_cache.py': 'bca7a893de4ce1ab349ebe0349556226bf02f99f565c3433d56af48f152c33a0',
    'simz1_replay_spatial_cache.py': 'dcf4e7c5561a631e1743bcfce303445e4f69a8b647ff7ce29c21f8f631207471',
    'simz1_gateway_od.py': '47d52032e101060afe9e802c0c10164e94199a400709f52c2acaa89ef0555995',
    'simz1_freight.py': 'c82e559c2ef0f99248b59d50d9ebcf4d888c21ca6decacbb1d468438a8bc39e6',
    'simz1_visual_lanes.py': 'd4b9917ab9cd31437ff2084dfe3d8ca7f6f29f01f4237346864b33d65ffd342c',
    'simz1_transit_stops.py': '1b136ad9da447d6e9db5b846a1b7bca358b6118df56a505f74f25b0a2e6e942c',
    'simz1_queue_context.py': '92dbef3cd8e827f122afa308bbe5cf632340a06ec38487ed8db824320a7a437c',
    'simz1_replay_work.py': 'b1f3fda1b1c2f22f6034fe92594be3c2387d6b7b4025ec9f0efcf991cbde91b9',
}
RUNS = {
    'run1000': dict(launch_id='a32f15487b1a49ac910ba799175658ca',
        run_id='simz1-9d15f07ccc134aa69c60fdcbc887ea3f', prefix='run-bg1-',
        run_manifest_sha256='3399203616a3884cb17e360d46160cbd43bc006f44eb146e0d08aba1b249a427',
        source_version='4d397b79fe7868ad2745c1189f61ffbd638733f3e748ed934c1a18979911dcca',
        backend='runtime/diagnostics/run1000-v8-delivery-20261108/visual/serve_bus_viewer.py',
        cleanup='cleanup-run1000-20261109', backend_port=8799, presentation_port=8804,
        backend_html_sha256='b6de53d922301d32071d04e8cfeb29f5fe85316d551202dac20d9ac61f9f959b',
        presentation_sha256='98995ffa27a1ef1210577e3bd69e76f276efcde89a67840a04f15a0ebde88bc1',
        evidence_sha256='04954663d9e6858136617b3764c1a453d1ff126a9d9de4117c3f3aa50c07f23f'),
    'run10k': dict(launch_id='e496c091b9ef46ee9ca381576135e299',
        run_id='simz1-cdffd75c4bdb47a7bfb507efe2c8c4e9', prefix='run-bg10-',
        run_manifest_sha256='8d51af2202ceb29ec32aa782f18fa05440436c1fb6a879beeb8f11a086e3213f',
        source_version='c67ad110071192ffa42a2a0c143070d85c717fdba365833eb2b3984a4148dc06',
        backend='runtime/diagnostics/run10k-v8-visual-repair-20261108/visual/serve_bus_viewer.py',
        cleanup='cleanup-20261109', backend_port=8801, presentation_port=8803,
        backend_html_sha256='bccaa1b726dc36f57e18d5fca2529f64066095537579a827e92870eab9424a3a',
        presentation_sha256='917f3831020822b17f6e2db292f8244fc6782c89a48cbd963186cde06977ab1a',
        evidence_sha256='fa4f6cc2aea1fe0b2e9eb7db8ea59ead9e2a20192b3653a0694068ebd9b55635'),
}


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def checked_hash(path, expected):
    actual = sha256(path)
    if actual != expected:
        raise ValueError(f'Approved file changed: {path}')
    return actual


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def expected_identity(name):
    row = RUNS[name]
    return dict(run_id=row['run_id'], launch_id=row['launch_id'], iteration=0,
        run_manifest_sha256=row['run_manifest_sha256'], source_version=row['source_version'],
        source_fingerprint=PRODUCER, visual_policy='partial-native-v1')


def check_identity(actual, expected, keys):
    for key in keys:
        if actual.get(key) != expected[key]:
            raise ValueError(f'Incompatible identity: {key}')


def check_native(name, native, state, receipt=None):
    identity = expected_identity(name)
    check_identity(native, identity, ('run_id',))
    check_identity(state, identity, ('run_id', 'launch_id', 'source_fingerprint'))
    if native.get('status') != 'completed' or native.get('validation', {}).get('status') != 'valid' or '0' not in native.get('results', {}):
        raise ValueError('Native run is not completed/valid at iteration 0')
    if name == 'run1000':
        if state.get('status') != 'completed' or state.get('outcome') != 'PASSED':
            raise ValueError('Run1000 accepted closure is missing')
    else:
        if (not receipt or receipt.get('run_id') != identity['run_id'] or
                receipt.get('original_launch_id') != identity['launch_id'] or
                receipt.get('status') != 'closure_recovered' or receipt.get('native_validation_exit_code') != 0 or
                receipt.get('context', {}).get('source_transition', {}).get('native_source_fingerprint') != PRODUCER):
            raise ValueError('Run10K reviewed recovery closure is missing')


def load_backend(name):
    path = ROOT / RUNS[name]['backend']
    spec = importlib.util.spec_from_file_location('simz1_readonly_backend_' + name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check_presentation(name):
    row = RUNS[name]
    directory = DELIVERY / row['cleanup']
    receipt = read_json(directory / 'presentation-build.json')
    check_identity(receipt['native_identity'], expected_identity(name), expected_identity(name))
    if receipt['presentation_sha256'] != row['presentation_sha256']:
        raise ValueError('Final presentation receipt does not match approved SHA256')
    checked_hash(directory / 'index.html', row['presentation_sha256'])
    if receipt['source_http'] != f"http://127.0.0.1:{row['backend_port']}":
        raise ValueError('Final presentation points to a different source')
    for file, expected in receipt['cleanup_sources'].items():
        checked_hash(directory / file, expected)
    for file, expected in receipt['source_files'].items():
        checked_hash(DELIVERY / 'visual' / file, expected)
    return receipt


def check_evidence(name, backend):
    row = RUNS[name]
    path = (backend.HERE / 'data/buses.json.gz' if name == 'run1000' else
            backend.HERE.parent / 'native/native-presence.json.gz')
    digest = hashlib.sha256()
    prefix = b''
    with gzip.open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            if not prefix:
                prefix = block[:8192]
            digest.update(block)
    if digest.hexdigest() != row['evidence_sha256']:
        raise ValueError('Approved native evidence checksum differs')
    text = prefix.decode('utf-8')
    match = re.search(r'"identity"\s*:\s*', text)
    if not match:
        raise ValueError('Native evidence identity missing')
    identity, _ = json.JSONDecoder().raw_decode(text[match.end():])
    check_identity(identity, expected_identity(name), ('run_id', 'iteration', 'run_manifest_sha256', 'source_version'))
    return dict(path=str(path), sha256=digest.hexdigest(), scope='uncompressed prepared evidence')


def check_replay(name, run):
    from simz1_sqlite_source import checked_source, FILE_NAME
    expected = expected_identity(name)
    directory = run / 'webgl-continuo-it.0'
    manifest = read_json(directory / 'continuous-manifest.json')
    check_identity(manifest, expected, ('run_id', 'iteration', 'run_manifest_sha256'))
    if manifest.get('status') != 'complete' or manifest.get('sample_rate') != 1:
        raise ValueError('Existing continuous replay is incomplete or sampled')
    source, source_manifest, database = checked_source(manifest['source_directory'])
    if source != (run / 'webgl-source-it.0/sqlite-source').resolve() or database != (run / 'webgl-source-it.0/replay.sqlite').resolve():
        raise ValueError('Replay source path is outside the exact native run')
    checked_hash(source / FILE_NAME, expected['source_version'])
    check_identity(source_manifest, expected, ('run_id', 'iteration', 'run_manifest_sha256'))
    if (manifest['source_export_sha256'] != expected['source_version'] or
            manifest['source_blocks'] != source_manifest['blocks'] or
            Path(manifest['database']).resolve() != database or
            manifest.get('source_type') != 'sqlite-direct-v1'):
        raise ValueError('Continuous replay differs from the validated SQLite source')
    stat = database.stat()
    if stat.st_size != manifest['database_bytes'] or stat.st_mtime_ns != manifest['database_mtime_ns']:
        raise ValueError('SQLite size/mtime differs from existing replay')
    checked_hash(directory / 'config.json', manifest['config_sha256'])
    config = read_json(directory / 'config.json')
    continuous = config['continuous']
    check_identity(continuous, expected, ('run_id', 'iteration', 'run_manifest_sha256', 'source_version'))
    if (manifest['replay_window'] != dict(start_seconds=0, end_seconds=86400) or
            config['replay_window'] != manifest['replay_window'] or
            any(continuous[key] != manifest['replay_window'][key] for key in ('start_seconds', 'end_seconds')) or
            any(continuous[key] != manifest[key] for key in ('window_count', 'window_seconds'))):
        raise ValueError('Approved continuous replay/config must retain exact 24-hour window')
    return directory, database


def verify(name):
    row = RUNS[name]
    run = ROOT / 'scenarios/zona1/montecarlo' / (row['prefix'] + row['launch_id'])
    manifest = run / 'run-manifest.json'
    checked_hash(manifest, row['run_manifest_sha256'])
    state = read_json(ROOT / 'runtime/launches' / row['launch_id'] / 'state.json')
    receipt = None
    if name == 'run10k':
        checked_hash(RECOVERY, RECOVERY_SHA)
        receipt = read_json(RECOVERY)
    check_native(name, read_json(manifest), state, receipt)
    inventory = DELIVERY / 'integrity/after.json'
    checked_hash(inventory, INTEGRITY_SHA)
    baseline = read_json(inventory)
    for filename in ('continuous-manifest.json', 'config.json'):
        relative = (run / 'webgl-continuo-it.0' / filename).relative_to(ROOT).as_posix()
        checked_hash(ROOT / relative, baseline['native_files'][relative]['sha256'])
    # Only publication dependencies; never hash multi-GB native files here.
    for relative, proof in baseline['protected_files'].items():
        if relative.startswith('python/') or relative == row['backend']:
            checked_hash(ROOT / relative, proof['sha256'])
    for filename, expected in READERS.items():
        checked_hash(ROOT / 'python' / filename, expected)
    check_presentation(name)
    backend = load_backend(name)
    if hashlib.sha256(backend.application_html().encode('utf-8')).hexdigest() != row['backend_html_sha256']:
        raise ValueError('Approved backend HTML differs')
    evidence = check_evidence(name, backend)
    # Existing validator checks the recorded full integrity receipt and opens
    # only immutable SQLite identity/structure. Full OD/OSM work stays in the
    # unchanged HTTP handler, once per actual server start.
    replay_directory, database = check_replay(name, run)
    return dict(schema='simz1-viewers-readonly-v1', run=name, status='verified_read_only',
        identity=expected_identity(name), backend_port=row['backend_port'], presentation_port=row['presentation_port'],
        backend_script=str(ROOT / row['backend']), presentation_script=str(DELIVERY / row['cleanup'] / 'clean_viewer.py'),
        presentation_sha256=row['presentation_sha256'], backend_html_sha256=row['backend_html_sha256'],
        replay_directory=str(replay_directory), run_directory=str(run), database=str(database),
        evidence=evidence, native_validation='completed/valid', historical_launch_status=state['status'],
        database_validation='existing full SHA256 receipt + current size/mtime + native readonly identity/structure; no full rehash',
        producer_fingerprint_scope='historical provenance; current global fingerprint not asserted',
        reader_contract_sha256=hashlib.sha256(json.dumps(READERS, sort_keys=True).encode()).hexdigest())


def serve_backend(name, verified):
    backend = load_backend(name)
    if sys.platform == 'win32':
        from ctypes import wintypes
        kernel = ctypes.windll.kernel32
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        kernel.SetPriorityClass.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        if not kernel.SetPriorityClass(kernel.GetCurrentProcess(), 0x4000):
            raise OSError('Could not set viewer priority BelowNormal')

    class ExclusiveServer(backend.original.ContinuousServer):
        allow_reuse_address = False

        def server_bind(self):
            if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            super().server_bind()

    # Bind before creating workers/HTTP caches. No historical main or guard is
    # replaced; the unchanged make_handler performs its original replay checks.
    server = ExclusiveServer(('127.0.0.1', verified['backend_port']), None)
    try:
        server.RequestHandlerClass = backend.make_handler()
        check_identity(server.RequestHandlerClass.replay.response_identity, verified['identity'],
                       ('run_id', 'iteration', 'run_manifest_sha256', 'source_version', 'visual_policy'))
        print(json.dumps(dict(verified, state='serving', pid=os.getpid())), flush=True)
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True, choices=RUNS)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--verify-only', action='store_true')
    mode.add_argument('--serve-backend', action='store_true')
    args = parser.parse_args()
    try:
        with redirect_stdout(sys.stderr):
            verified = verify(args.run)
        if args.verify_only:
            print(json.dumps(verified, ensure_ascii=False), flush=True)
        else:
            serve_backend(args.run, verified)
    except (OSError, ValueError, KeyError) as error:
        parser.exit(1, f'Read-only viewer contract rejected: {error}\n')


if __name__ == '__main__':
    main()
