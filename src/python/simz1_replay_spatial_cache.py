"""Disposable spatial preparation for restarted replay servers only.

A hit is a candidate, never native acceptance: ``load`` always invokes the
caller's normal preparation validator, including every pinned input hash.
Only a server that completed its ordinary full initialization may call ``store``.
An absent, stale, corrupt or oversized entry falls back to that full path.
No routing/generation module, native artifact or acceptance receipt is changed.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile
import threading
import time

from simz1_report_package import PackageLock
from simz1_window_cache import reader_version


MAX_PREPARATION_BYTES = 32 * 1024**2
MAX_TOTAL_BYTES = 128 * 1024**2
HEADER_BYTES = 4096
SCHEMA = 'simz1-replay-spatial-cache-v1'
IDENTITY_KEYS = ('run_id', 'iteration', 'run_manifest_sha256', 'source_version')
PAYLOAD_KEYS = {'identity', 'source_directory', 'source_version', 'spatial',
                'metadata_hashes', 'postprocessor_version'}


def _raw(value):
    # Same encoding/order as ContinuousReplay.spatial_preparation().
    try:
        return json.dumps(value, separators=(',', ':'), allow_nan=False).encode('utf-8')
    except RecursionError as error:
        raise ValueError('Spatial cache nesting exceeds the parser budget') from error


def _sha(value):
    return hashlib.sha256(value).hexdigest()


def _is_sha(value):
    return (isinstance(value, str) and len(value) == 64 and
            all(c in '0123456789abcdef' for c in value))


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate spatial cache field')
        result[key] = value
    return result


def _constant(_):
    raise ValueError('Nonfinite spatial cache value')


def _decode(raw):
    try:
        return json.loads(raw, object_pairs_hook=_object, parse_constant=_constant)
    except RecursionError as error:
        raise ValueError('Spatial cache nesting exceeds the parser budget') from error


def validate_derived_preparation(preparation, directory, manifest):
    """Check every cached derived value against pinned data, without OD routing.

    Use after the ordinary worker-preparation checks. Those rehash all inputs;
    this additional persistent-cache check rehashes its two files as well and
    derives the metadata digests and visual scope incrementally. A self-consistent
    edited envelope/checksum therefore cannot change the replay's coverage or
    per-person metadata validation. This function grants no native acceptance.
    """
    from simz1_run import checked_path, xml_elements
    from simz1_freight import is_freight
    from simz1_temporal import trip_id
    from simz1_freight_completion import observation_contract

    if (not isinstance(preparation, dict) or set(preparation) != {'payload', 'sha256'} or
            not isinstance(preparation['payload'], dict) or
            set(preparation['payload']) != PAYLOAD_KEYS):
        raise ValueError('Persistent spatial preparation shape mismatch')
    payload = preparation['payload']
    encoded = _raw(payload)
    if len(encoded) > MAX_PREPARATION_BYTES or _sha(encoded) != preparation['sha256']:
        raise ValueError('Persistent spatial preparation digest/size mismatch')
    spatial = manifest.get('spatial_demand')
    inputs = manifest.get('inputs', {})
    if (not isinstance(spatial, dict) or spatial.get('mode') != 'balanced-gateway-v1' or
            not all(key in inputs for key in ('network', 'plans'))):
        raise ValueError('Persistent spatial preparation lacks its pinned spatial inputs')
    directory = Path(directory).resolve()
    network = checked_path(directory, inputs['network'])
    plans = checked_path(directory, inputs['plans'])
    links = set()
    for link in xml_elements(network, 'link', 'network'):
        ident = link.get('id')
        if not ident or ident in links:
            raise ValueError('Pinned visual network has missing/duplicate link IDs')
        links.add(ident)
    if not links:
        raise ValueError('Pinned visual network is empty')
    observation = observation_contract(manifest)
    expected_spatial = dict(spatial, visual_link_ids=sorted(links),
                            visual_scope='full_native_network_preserving_anchors_and_services',
                            postprocessor_contract_version='balanced-replay-contract-v1',
                            observation_end_seconds=observation['observation_end_seconds'] if observation else 86400)
    if (payload['spatial'] != expected_spatial or
            payload['postprocessor_version'] != 'balanced-replay-contract-v1'):
        raise ValueError('Persistent spatial scope differs from the pinned native network/observation')
    hashes, people = {}, set()
    for person in xml_elements(plans, 'person', 'population'):
        ident = person.get('id')
        if not ident or ident in people:
            raise ValueError('Pinned plans have missing/duplicate person IDs')
        people.add(ident)
        if is_freight(person):
            continue
        records = _decode(person.findtext("attributes/attribute[@name='simz1SpatialOD']", 'null'))
        key = trip_id(ident, 1)
        if not isinstance(records, dict) or set(records) != {key} or not isinstance(records[key], dict):
            raise ValueError('Pinned plans have an incompatible private spatial ledger')
        record = {k: v for k, v in records[key].items() if k != 'planned_departure'}
        hashes[ident] = _sha(json.dumps(record, sort_keys=True, separators=(',', ':'),
                                       allow_nan=False).encode('utf-8'))
    expected_count = manifest.get('demand_composition', {}).get('private_vehicles')
    if type(expected_count) is not int or len(hashes) != expected_count or payload['metadata_hashes'] != hashes:
        raise ValueError('Persistent spatial metadata differs from every pinned private plan')
    return dict(private_metadata=len(hashes), visual_links=len(links))


class SpatialPreparationCache:
    def __init__(self, root, identity, manifest, *, version=None,
                 max_bytes=MAX_PREPARATION_BYTES, total_max_bytes=MAX_TOTAL_BYTES):
        if (type(max_bytes) is not int or not 0 < max_bytes <= MAX_PREPARATION_BYTES or
                type(total_max_bytes) is not int or not 0 < total_max_bytes <= MAX_TOTAL_BYTES):
            raise ValueError('Spatial cache budgets must be positive and bounded')
        if (not isinstance(identity, dict) or set(identity) != set(IDENTITY_KEYS) or
                not isinstance(identity['run_id'], str) or not identity['run_id'] or
                type(identity['iteration']) is not int or identity['iteration'] < 0 or
                not _is_sha(identity['run_manifest_sha256']) or not _is_sha(identity['source_version'])):
            raise ValueError('Spatial cache requires complete native/source identity')
        if (not isinstance(manifest, dict) or
                any(manifest.get(k) != identity[k] for k in IDENTITY_KEYS[:-1]) or
                manifest.get('source_export_sha256') != identity['source_version'] or
                not isinstance(manifest.get('source_directory'), str)):
            raise ValueError('Spatial cache replay manifest identity mismatch')
        root = Path(root)
        if root.is_symlink():
            raise ValueError('Spatial cache root cannot be a symlink')
        self.root = root.resolve()
        self.max_bytes, self.total_max_bytes = max_bytes, total_max_bytes
        # Detach caller dictionaries so later mutation cannot alter a namespace.
        self.contract = _decode(_raw(dict(schema=SCHEMA, identity=identity, manifest=manifest,
                                         reader_version=version or reader_version())))
        if not isinstance(self.contract['reader_version'], str) or not self.contract['reader_version']:
            raise ValueError('Missing spatial cache reader version')
        self.namespace = _sha(json.dumps(self.contract, sort_keys=True,
                                        separators=(',', ':'), allow_nan=False).encode())
        self.path = self.root / (self.namespace + '.cache')
        self.lock = threading.Lock()
        self.hits = self.misses = self.invalid_entries = self.writes = self.budget_skips = 0
        self.read_seconds = self.validation_seconds = self.write_seconds = 0.0

    def _check_preparation(self, preparation):
        if not isinstance(preparation, dict) or set(preparation) != {'payload', 'sha256'}:
            raise ValueError('Invalid spatial preparation envelope')
        payload = preparation['payload']
        if not isinstance(payload, dict) or set(payload) != PAYLOAD_KEYS:
            raise ValueError('Invalid spatial preparation fields')
        raw = _raw(payload)
        if len(raw) > self.max_bytes or _sha(raw) != preparation['sha256']:
            raise ValueError('Spatial preparation size/digest mismatch')
        identity = self.contract['identity']
        if (payload['identity'] != {k: identity[k] for k in IDENTITY_KEYS[:-1]} or
                payload['source_version'] != identity['source_version'] or
                not isinstance(payload['source_directory'], str) or
                Path(payload['source_directory']).resolve() !=
                Path(self.contract['manifest']['source_directory']).resolve() or
                not isinstance(payload['spatial'], dict) or
                payload['spatial'].get('mode') != 'balanced-gateway-v1' or
                payload['postprocessor_version'] != 'balanced-replay-contract-v1' or
                not isinstance(payload['metadata_hashes'], dict) or
                any(not isinstance(key, str) or not key or not _is_sha(value)
                    for key, value in payload['metadata_hashes'].items())):
            raise ValueError('Spatial preparation identity/metadata mismatch')
        return preparation

    def load(self, validate):
        """Return the callback's verified result, or None; callback is mandatory.

        ``validate`` must be ContinuousReplay.checked_spatial_preparation bound
        to this initialization's already checked source. Expected read/validation
        failures cause a cache miss; programming errors are not swallowed.
        """
        if not callable(validate):
            raise TypeError('Spatial cache load requires its normal validator')
        with self.lock:
            started = time.perf_counter()
            try:
                if self.path.is_symlink():
                    raise ValueError('Spatial cache entry cannot be a symlink')
                with self.path.open('rb') as stream:
                    info = os.fstat(stream.fileno())
                    if not stat.S_ISREG(info.st_mode) or info.st_size > self.max_bytes + HEADER_BYTES:
                        raise ValueError('Spatial cache file exceeds its budget')
                    header = stream.readline(HEADER_BYTES)
                    if not header.endswith(b'\n'):
                        raise ValueError('Spatial cache header incomplete')
                    meta = _decode(header)
                    if (not isinstance(meta, dict) or
                            set(meta) != {'schema', 'namespace', 'bytes', 'sha256'} or
                            meta['schema'] != SCHEMA or meta['namespace'] != self.namespace or
                            type(meta['bytes']) is not int or
                            not 0 < meta['bytes'] <= self.max_bytes + 256 or not _is_sha(meta['sha256'])):
                        raise ValueError('Spatial cache contract mismatch')
                    raw = stream.read(meta['bytes'] + 1)
                if len(raw) != meta['bytes'] or _sha(raw) != meta['sha256']:
                    raise ValueError('Spatial cache content truncated/corrupt')
                preparation = self._check_preparation(_decode(raw))
            except FileNotFoundError:
                self.misses += 1
                return None
            except (OSError, ValueError):
                self.invalid_entries += 1
                self.misses += 1
                return None
            finally:
                self.read_seconds += time.perf_counter() - started
            started = time.perf_counter()
            try:
                result = validate(preparation)
                if result is None:
                    raise ValueError('Spatial preparation was not validated')
            except (OSError, ValueError):
                self.invalid_entries += 1
                self.misses += 1
                return None
            finally:
                self.validation_seconds += time.perf_counter() - started
            self.hits += 1
            return result

    def store(self, preparation):
        """Persist only a preparation from a completed full initialization.

        No eviction is performed. At the disk cap or with a competing writer,
        skip this optional write; serving and full validation remain available.
        """
        started = time.perf_counter()
        with self.lock:
            try:
                self._check_preparation(preparation)
                raw = _raw(preparation)
                header = _raw(dict(schema=SCHEMA, namespace=self.namespace, bytes=len(raw), sha256=_sha(raw)))
                data = header + b'\n' + raw
                if len(header) >= HEADER_BYTES or len(data) > self.max_bytes + HEADER_BYTES:
                    raise ValueError('Spatial cache envelope exceeds its budget')
                self.root.mkdir(parents=True, exist_ok=True)
                lock_path = self.root / '.writer.lock'
                if lock_path.is_symlink() or self.path.is_symlink():
                    raise ValueError('Spatial cache writer cannot follow symlinks')
                with PackageLock(lock_path) as writer:
                    if not writer.acquired:
                        self.budget_skips += 1
                        return False
                    entries = list(self.root.iterdir())
                    # This cache owns a flat directory. Unknown directories or
                    # symlinks cannot hide unaccounted storage under its cap.
                    if any(path.is_symlink() or not path.is_file() for path in entries):
                        self.budget_skips += 1
                        return False
                    total = sum(path.stat().st_size for path in entries)
                    # Include the temporary replacement as well as its old file
                    # so even the atomic-write peak respects the total budget.
                    if (total + len(data) > self.total_max_bytes or
                            shutil.disk_usage(self.root).free < len(data) + 256 * 1024**2):
                        self.budget_skips += 1
                        return False
                    temporary = None
                    try:
                        with tempfile.NamedTemporaryFile(dir=self.root, prefix=self.namespace + '.',
                                                         suffix='.tmp', delete=False) as stream:
                            temporary = Path(stream.name)
                            stream.write(data)
                            stream.flush()
                            os.fsync(stream.fileno())
                        os.replace(temporary, self.path)
                    finally:
                        if temporary is not None and temporary.exists():
                            temporary.unlink()  # Only this call's unpublished temporary file.
                    self.writes += 1
                    return True
            except (OSError, ValueError):
                self.invalid_entries += 1
                return False
            finally:
                self.write_seconds += time.perf_counter() - started

    def summary(self):
        with self.lock:
            return dict(namespace=self.namespace, path=str(self.path),
                        max_bytes=self.max_bytes, total_max_bytes=self.total_max_bytes,
                        hits=self.hits, misses=self.misses, invalid_entries=self.invalid_entries,
                        writes=self.writes, budget_skips=self.budget_skips,
                        read_seconds=self.read_seconds, validation_seconds=self.validation_seconds,
                        write_seconds=self.write_seconds)
