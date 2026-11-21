"""Temporary cache fixtures; no historical cache, run or native event is edited."""
from concurrent.futures import ThreadPoolExecutor
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET

from simz1_replay_spatial_cache import (SpatialPreparationCache, MAX_PREPARATION_BYTES,
                                      MAX_TOTAL_BYTES, SCHEMA, validate_derived_preparation)


def raw(value):
    return json.dumps(value, separators=(',', ':'), allow_nan=False).encode()


def sha(value):
    return hashlib.sha256(value).hexdigest()


class SpatialPreparationCacheTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.cache_root = self.root / 'cache'
        self.source = self.root / 'source'
        self.source.mkdir()
        self.identity = dict(run_id='synthetic-native', iteration=0,
                             run_manifest_sha256='a' * 64, source_version='b' * 64)
        self.manifest = dict(run_id=self.identity['run_id'], iteration=0,
                             run_manifest_sha256=self.identity['run_manifest_sha256'],
                             source_export_sha256=self.identity['source_version'],
                             source_directory=str(self.source), config_sha256='c' * 64,
                             window_seconds=120, sample_rate=1)
        self.payload = dict(identity={k: v for k, v in self.identity.items() if k != 'source_version'},
                            source_directory=str(self.source), source_version=self.identity['source_version'],
                            spatial=dict(mode='balanced-gateway-v1', allowed_links=['native-link']),
                            metadata_hashes={'person': 'd' * 64},
                            postprocessor_version='balanced-replay-contract-v1')
        self.preparation = self.envelope(self.payload)
        self.cache = self.create()

    @staticmethod
    def envelope(payload):
        return dict(payload=payload, sha256=sha(raw(payload)))

    def create(self, **kwargs):
        return SpatialPreparationCache(self.cache_root, kwargs.pop('identity', self.identity),
                                       kwargs.pop('manifest', self.manifest), version=kwargs.pop('version', 'reader-v1'),
                                       **kwargs)

    def write_entry(self, preparation=None, header_changes=None, content=None):
        content = raw(preparation if preparation is not None else self.preparation) if content is None else content
        meta = dict(schema=SCHEMA, namespace=self.cache.namespace, bytes=len(content), sha256=sha(content))
        meta.update(header_changes or {})
        self.cache.path.parent.mkdir(parents=True, exist_ok=True)
        self.cache.path.write_bytes(raw(meta) + b'\n' + content)

    def native_fixture(self):
        from simz1_continuous_replay import ContinuousReplay
        from simz1_freight import SCHEMA as FREIGHT_SCHEMA
        from simz1_temporal import trip_id
        network = self.root / 'network.xml'
        network.write_text('<network><nodes/><links><link id="link-b"/><link id="service-only"/>'
                           '<link id="link-a"/></links></network>', encoding='utf-8')
        plans = self.root / 'plans.xml'
        population = ET.Element('population')
        person = ET.SubElement(population, 'person', id='person')
        attributes = ET.SubElement(person, 'attributes')
        metadata = dict(route_link_ids=['link-a', 'link-b'], body_length_m=4.5, origin_link='link-a')
        ET.SubElement(attributes, 'attribute', name='simz1SpatialOD').text = json.dumps({trip_id('person', 1): metadata})
        freight = ET.SubElement(population, 'person', id='freight')
        ET.SubElement(ET.SubElement(freight, 'attributes'), 'attribute', name='simz1FreightService').text = FREIGHT_SCHEMA
        ET.ElementTree(population).write(plans, encoding='utf-8', xml_declaration=True)
        native_spatial = dict(mode='balanced-gateway-v1', allowed_links=['link-a'])
        native = dict(spatial_demand=native_spatial, demand_composition=dict(private_vehicles=1),
                      inputs={path.stem: dict(path=path.name, sha256=sha(path.read_bytes())) for path in (network, plans)})
        payload = dict(self.payload, spatial=dict(native_spatial, visual_link_ids=['link-a', 'link-b', 'service-only'],
                                                 visual_scope='full_native_network_preserving_anchors_and_services',
                                                 postprocessor_contract_version='balanced-replay-contract-v1',
                                                 observation_end_seconds=86400),
                       metadata_hashes={'person': sha(json.dumps(metadata, sort_keys=True, separators=(',', ':')).encode())})
        preparation = self.envelope(payload)
        replay = object.__new__(ContinuousReplay)
        replay.identity, replay.manifest, replay.native_run = payload['identity'], self.manifest, native
        source = {'run_directory': str(self.root)}
        return native, preparation, lambda p: replay.checked_persistent_spatial_preparation(p, source)

    def test_empty_cache_requires_full_path_and_never_calls_validator(self):
        validate = Mock()
        self.assertIsNone(self.cache.load(validate))
        validate.assert_not_called()
        self.assertFalse(self.cache_root.exists())
        self.assertEqual(self.cache.summary()['misses'], 1)

    def test_restart_returns_callback_result_and_records_separate_timings(self):
        self.assertTrue(self.cache.store(self.preparation))
        restarted = self.create()
        verified = object()
        validate = Mock(return_value=verified)
        self.assertIs(restarted.load(validate), verified)
        validate.assert_called_once_with(self.preparation)
        summary = restarted.summary()
        self.assertEqual(summary['hits'], 1)
        self.assertEqual(summary['writes'], 0, 'a hit need not rewrite a cache')
        self.assertGreater(summary['read_seconds'], 0)
        self.assertGreater(summary['validation_seconds'], 0)
        self.assertEqual(summary['write_seconds'], 0)

    def test_complete_identity_manifest_and_reader_changes_are_misses(self):
        self.assertTrue(self.cache.store(self.preparation))
        changes = [dict(identity=dict(self.identity, run_id='another')),
                   dict(identity=dict(self.identity, iteration=1)),
                   dict(identity=dict(self.identity, run_manifest_sha256='e' * 64)),
                   dict(identity=dict(self.identity, source_version='f' * 64)),
                   dict(version='reader-v2'), dict(manifest=dict(self.manifest, window_seconds=60)),
                   dict(manifest=dict(self.manifest, config_sha256='e' * 64))]
        for change in changes:
            with self.subTest(change=change):
                if 'identity' in change:
                    changed = change['identity']
                    change['manifest'] = dict(self.manifest, **{k: changed[k] for k in ('run_id', 'iteration', 'run_manifest_sha256')},
                                              source_export_sha256=changed['source_version'])
                other = self.create(**change)
                validate = Mock()
                self.assertIsNone(other.load(validate))
                validate.assert_not_called()
                self.assertNotEqual(other.namespace, self.cache.namespace)

    def test_namespace_detaches_mutable_constructor_inputs(self):
        namespace = self.cache.namespace
        self.identity['run_id'] = 'mutated'
        self.manifest['config_sha256'] = 'mutated'
        self.assertTrue(self.cache.store(self.preparation))
        self.assertEqual(self.cache.namespace, namespace)
        self.assertEqual(self.cache.load(lambda item: item), self.preparation)

    def test_callback_mandatory_expected_rejection_falls_back_bugs_propagate(self):
        with self.assertRaises(TypeError):
            self.cache.load(None)
        self.assertTrue(self.cache.store(self.preparation))
        for error in (ValueError('pinned input changed'), OSError('input absent')):
            with self.subTest(error=type(error).__name__):
                self.assertIsNone(self.cache.load(Mock(side_effect=error)))
        self.assertIsNone(self.cache.load(lambda _: None))
        self.assertEqual(self.cache.summary()['hits'], 0)
        for error in (RuntimeError('programming defect'), TypeError('bad callback')):
            with self.subTest(error=type(error).__name__), self.assertRaises(type(error)):
                self.cache.load(Mock(side_effect=error))

    def test_real_worker_validator_rehashes_inputs_config_and_od_artifact(self):
        from simz1_continuous_replay import ContinuousReplay
        records = []
        for name in ('network.xml', 'effective-config.xml', 'od-proof.json'):
            path = self.root / name
            path.write_bytes(('synthetic ' + name).encode())
            records.append(dict(path=name, sha256=sha(path.read_bytes())))
        replay = SimpleNamespace(identity=self.payload['identity'], manifest=self.manifest,
                                 native_run=dict(spatial_demand=self.payload['spatial'],
                                                 inputs={'network': records[0]},
                                                 effective_config=records[1], balanced_od={'audit': records[2]}))
        validate = lambda p: ContinuousReplay.checked_spatial_preparation(replay, p, {'run_directory': str(self.root)})
        self.assertTrue(self.cache.store(self.preparation))
        self.assertEqual(dict(self.cache.load(validate)), self.payload['spatial'])
        for record in records:
            path = self.root / record['path']
            original = path.read_bytes()
            for missing in (False, True):
                with self.subTest(path=record['path'], missing=missing):
                    if missing:
                        path.unlink()
                    else:
                        path.write_bytes(original + b' mutation')
                    self.assertIsNone(self.cache.load(validate))
                    path.write_bytes(original)
        self.assertEqual(self.cache.summary()['hits'], 1)

    def test_persistent_wrapper_derives_all_links_and_private_metadata_without_routing(self):
        native, preparation, validate = self.native_fixture()
        self.assertEqual(validate_derived_preparation(preparation, self.root, native),
                         dict(private_metadata=1, visual_links=3))
        self.assertTrue(self.cache.store(preparation))
        with patch('simz1_gateway_od.validated_spatial_demand', side_effect=AssertionError('OD reconstruction forbidden')):
            result = self.cache.load(validate)
        self.assertEqual(dict(result), preparation['payload']['spatial'])
        self.assertEqual(result.metadata_hashes, preparation['payload']['metadata_hashes'])
        self.assertNotIn('freight', result.metadata_hashes)
        self.assertIn('service-only', result['visual_link_ids'], 'all native links remain visible')

    def test_recalculated_digests_cannot_change_drop_or_add_private_metadata(self):
        _, preparation, validate = self.native_fixture()
        changed_maps = [{}, {'person': '0' * 64},
                        dict(preparation['payload']['metadata_hashes'], extra='a' * 64),
                        dict(preparation['payload']['metadata_hashes'], freight='b' * 64)]
        for metadata_hashes in changed_maps:
            with self.subTest(metadata_hashes=metadata_hashes):
                payload = copy.deepcopy(preparation['payload'])
                payload['metadata_hashes'] = metadata_hashes
                self.write_entry(preparation=self.envelope(payload))
                self.assertIsNone(self.cache.load(validate))
        self.assertEqual(self.cache.summary()['hits'], 0)
        self.assertEqual(self.cache.summary()['invalid_entries'], len(changed_maps))

    def test_recalculated_digests_cannot_change_link_coverage_scope_horizon_or_extra_fields(self):
        _, preparation, validate = self.native_fixture()
        changes = [('visual_link_ids', ['link-a', 'link-b']),
                   ('visual_link_ids', ['link-a', 'link-b', 'service-only', 'invented']),
                   ('visual_link_ids', ['service-only', 'link-b', 'link-a']),
                   ('visual_link_ids', ['link-a', 'link-a', 'link-b', 'service-only']),
                   ('visual_scope', 'partial'), ('observation_end_seconds', 108000),
                   ('postprocessor_contract_version', 'future'), ('unknown_extra', True)]
        for key, value in changes:
            with self.subTest(key=key, value=value):
                payload = copy.deepcopy(preparation['payload'])
                payload['spatial'][key] = value
                self.write_entry(preparation=self.envelope(payload))
                self.assertIsNone(self.cache.load(validate))
        self.assertEqual(self.cache.summary()['hits'], 0)

    def test_derived_check_rehashes_its_pinned_network_and_plans_independently(self):
        native, preparation, _ = self.native_fixture()
        for record in native['inputs'].values():
            path = self.root / record['path']
            original = path.read_bytes()
            with self.subTest(path=path):
                path.write_bytes(original + b'<!-- changed -->')
                with self.assertRaises(ValueError):
                    validate_derived_preparation(preparation, self.root, native)
                path.write_bytes(original)
        with self.assertRaises(ValueError):
            validate_derived_preparation(preparation, self.root, dict(native, demand_composition=dict(private_vehicles=2)))

    def test_derived_check_rejects_duplicate_network_and_person_identity(self):
        for field, duplicate in (('network', '<link id="link-a"/>'), ('plans', '<person id="person"/>')):
            native, preparation, _ = self.native_fixture()
            path = self.root / native['inputs'][field]['path']
            data = path.read_text(encoding='utf-8')
            closing = '</links>' if field == 'network' else '</population>'
            path.write_text(data.replace(closing, duplicate + closing), encoding='utf-8')
            native['inputs'][field]['sha256'] = sha(path.read_bytes())
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_derived_preparation(preparation, self.root, native)

    def test_derived_metadata_digest_uses_canonical_record_and_excludes_planned_departure(self):
        native, preparation, _ = self.native_fixture()
        path = self.root / native['inputs']['plans']['path']
        tree = ET.parse(path)
        attribute = tree.getroot().find("person/attributes/attribute[@name='simz1SpatialOD']")
        records = json.loads(attribute.text)
        record = next(iter(records.values()))
        record['planned_departure'] = 12345
        attribute.text = json.dumps(records, sort_keys=True, indent=2)
        tree.write(path, encoding='utf-8', xml_declaration=True)
        native['inputs']['plans']['sha256'] = sha(path.read_bytes())
        self.assertEqual(validate_derived_preparation(preparation, self.root, native),
                         dict(private_metadata=1, visual_links=3))

    def test_derived_check_rejects_incomplete_private_ledger_and_envelope(self):
        native, preparation, _ = self.native_fixture()
        with self.assertRaises(ValueError):
            validate_derived_preparation(dict(preparation, sha256='0' * 64), self.root, native)
        path = self.root / native['inputs']['plans']['path']
        tree = ET.parse(path)
        tree.getroot().find("person/attributes/attribute[@name='simz1SpatialOD']").text = '{}'
        tree.write(path, encoding='utf-8', xml_declaration=True)
        native['inputs']['plans']['sha256'] = sha(path.read_bytes())
        with self.assertRaises(ValueError):
            validate_derived_preparation(preparation, self.root, native)

    def test_malformed_headers_lengths_truncation_and_extra_data_reject_before_callback(self):
        changes = [dict(schema='wrong'), dict(namespace='0' * 64), dict(bytes=True), dict(bytes=-1),
                   dict(bytes=MAX_PREPARATION_BYTES + 257), dict(sha256='0' * 64), dict(extra='unknown')]
        for change in changes:
            with self.subTest(change=change):
                self.write_entry(header_changes=change)
                validate = Mock()
                self.assertIsNone(self.cache.load(validate))
                validate.assert_not_called()
        self.write_entry()
        valid = self.cache.path.read_bytes()
        for data in (valid[:-1], valid + b'extra', b'x' * 4096, b'[]\n{}', b'\xff\n{}'):
            with self.subTest(length=len(data)):
                self.cache.path.write_bytes(data)
                validate = Mock()
                self.assertIsNone(self.cache.load(validate))
                validate.assert_not_called()

    def test_payload_identity_shape_and_digest_reject_even_with_valid_outer_digest(self):
        cases = []
        for field, value in (('identity', dict(self.payload['identity'], run_id='other')),
                             ('identity', dict(self.payload['identity'], iteration=1)),
                             ('identity', dict(self.payload['identity'], run_manifest_sha256='e' * 64)),
                             ('source_version', 'e' * 64), ('source_directory', str(self.root / 'other')),
                             ('spatial', dict(mode='network/legacy-gaussian-v1')),
                             ('postprocessor_version', 'future'), ('metadata_hashes', {'person': 'not-a-hash'})):
            changed = copy.deepcopy(self.payload)
            changed[field] = value
            cases.append(self.envelope(changed))
        cases.extend([dict(self.preparation, sha256='0' * 64), dict(self.preparation, extra=True),
                      self.envelope(dict(self.payload, extra=True)), {'payload': []}, []])
        for preparation in cases:
            with self.subTest(preparation=preparation):
                self.write_entry(preparation=preparation)
                validate = Mock()
                self.assertIsNone(self.cache.load(validate))
                validate.assert_not_called()

    def test_duplicate_fields_nonfinite_and_excessive_nesting_rejected(self):
        for content in (b'{"payload":{},"payload":{},"sha256":"x"}',
                        b'{"payload":NaN,"sha256":"x"}', b'[' * 2000 + b'0' + b']' * 2000):
            with self.subTest(length=len(content)):
                self.write_entry(content=content)
                validate = Mock()
                self.assertIsNone(self.cache.load(validate))
                validate.assert_not_called()

    def test_oversize_storage_and_read_never_truncate_or_raise_global_caps(self):
        limited = self.create(max_bytes=128)
        self.assertFalse(limited.store(self.preparation))
        self.assertFalse(limited.path.exists())
        self.assertTrue(self.cache.store(self.preparation))
        before = self.cache.path.read_bytes()
        self.assertIsNone(limited.load(Mock()))
        self.assertEqual(self.cache.path.read_bytes(), before)
        for budget in (0, -1, True, MAX_PREPARATION_BYTES + 1):
            with self.subTest(max_bytes=budget), self.assertRaises(ValueError):
                self.create(max_bytes=budget)
        with self.assertRaises(ValueError):
            self.create(total_max_bytes=MAX_TOTAL_BYTES + 1)

    def test_total_budget_counts_atomic_peak_and_preserves_all_existing_files(self):
        self.assertTrue(self.cache.store(self.preparation))
        original = self.cache.path.read_bytes()
        other = self.cache_root / 'other-namespace.cache'
        other.write_bytes(b'preserved cache')
        existing = sum(p.stat().st_size for p in self.cache_root.iterdir())
        limited = self.create(total_max_bytes=existing + len(original) - 1)
        self.assertFalse(limited.store(self.preparation))
        self.assertEqual(limited.summary()['budget_skips'], 1)
        self.assertEqual(self.cache.path.read_bytes(), original)
        self.assertEqual(other.read_bytes(), b'preserved cache')
        self.assertFalse(list(self.cache_root.glob('*.tmp')))

    def test_low_disk_and_unknown_directory_skip_optional_writes(self):
        usage = SimpleNamespace(free=1)
        with patch('simz1_replay_spatial_cache.shutil.disk_usage', return_value=usage):
            self.assertFalse(self.cache.store(self.preparation))
        self.assertFalse(self.cache.path.exists())
        (self.cache_root / 'unexpected-directory').mkdir()
        self.assertFalse(self.cache.store(self.preparation))
        self.assertFalse(self.cache.path.exists())
        self.assertEqual(self.cache.summary()['budget_skips'], 2)

    def test_symlink_entry_and_lock_are_not_followed(self):
        self.assertTrue(self.cache.store(self.preparation))
        before = self.cache.path.read_bytes()
        original = Path.is_symlink
        for target in (self.cache.path, self.cache_root / '.writer.lock'):
            with self.subTest(target=target):
                with patch.object(Path, 'is_symlink', lambda path: path == target or original(path)):
                    self.assertFalse(self.cache.store(self.preparation))
                    if target == self.cache.path:
                        validate = Mock()
                        self.assertIsNone(self.cache.load(validate))
                        validate.assert_not_called()
        self.assertEqual(self.cache.path.read_bytes(), before)

    def test_concurrent_writer_skips_without_replacing_unpublished_partial_data(self):
        import os
        entered, release = threading.Event(), threading.Event()
        original_replace = os.replace

        def delayed_replace(source, destination):
            entered.set()
            if not release.wait(5):
                raise RuntimeError('test writer timeout')
            original_replace(source, destination)

        other = self.create()
        with ThreadPoolExecutor(max_workers=1) as pool:
            with patch('simz1_replay_spatial_cache.os.replace', side_effect=delayed_replace):
                future = pool.submit(self.cache.store, self.preparation)
                try:
                    self.assertTrue(entered.wait(5))
                    self.assertFalse(other.store(self.preparation), 'kernel writer lock must be exclusive')
                    self.assertIsNone(other.load(Mock()), 'unpublished temporary is not a cache entry')
                finally:
                    release.set()
                self.assertTrue(future.result(timeout=5))
        self.assertEqual(other.load(lambda item: item), self.preparation)
        self.assertFalse(list(self.cache_root.glob('*.tmp')))

    def test_failed_atomic_replace_preserves_previous_entry_and_cleans_only_own_temp(self):
        self.assertTrue(self.cache.store(self.preparation))
        original = self.cache.path.read_bytes()
        unrelated = self.cache_root / 'unrelated.tmp'
        unrelated.write_bytes(b'preserve')
        with patch('simz1_replay_spatial_cache.os.replace', side_effect=OSError('replace denied')):
            self.assertFalse(self.cache.store(self.preparation))
        self.assertEqual(self.cache.path.read_bytes(), original)
        self.assertEqual(list(self.cache_root.glob('*.tmp')), [unrelated])
        self.assertEqual(unrelated.read_bytes(), b'preserve')

    def test_incomplete_constructor_identity_is_rejected(self):
        for identity in ({}, dict(self.identity, iteration=True), dict(self.identity, run_manifest_sha256='missing'),
                         dict(self.identity, extra='unknown')):
            with self.subTest(identity=identity), self.assertRaises(ValueError):
                self.create(identity=identity)
        with self.assertRaises(ValueError):
            self.create(manifest=dict(self.manifest, source_export_sha256='e' * 64))


if __name__ == '__main__':
    unittest.main()
