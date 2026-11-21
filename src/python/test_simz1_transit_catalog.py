"""Prepared review fixtures; no simulation, population generation, server or browser."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from simz1_transit_catalog import (DEFAULT_DIRECTORY, FACTUAL_FIELDS, SCHEMA,
                                  SOURCES_SCHEMA, validate, validate_artifacts)


def assumption():
    return {'status': 'scenario_assumption', 'synthetic': True,
            'reason': 'Synthetic in-memory fixture; not a real transit service'}


def fixture():
    """Entirely synthetic names and evidence; never an actual Guatemala service."""
    sources = {'schema_version': SOURCES_SCHEMA, 'sources': [{
        'source_id': 'synthetic-source', 'url': 'https://example.invalid/synthetic-transit',
        'kind': 'synthetic_fixture', 'accessed_on': '2026-10-22', 'published_on': None,
        'license': {'id': None, 'status': 'synthetic_test_only'},
    }]}
    service = {
        'service_id': 'synthetic-loop', 'operator': 'Synthetic operator',
        'line': 'Synthetic line', 'variant': None, 'direction': None,
        'stop_sequences': None, 'coordinates': None, 'route': None,
        'calendar': None, 'schedule': None, 'sources': ['synthetic-source'],
        'review_date': '2026-10-22', 'license': {'id': None, 'status': 'pending'},
        'verification': {'status': 'pending', 'field_status': {
            'operator': assumption(), 'line': assumption(),
            **{field: 'pending' for field in ('variant', 'direction', 'stop_sequences',
                                            'coordinates', 'route', 'calendar', 'schedule')},
        }, 'blockers': ['synthetic_fixture_never_production']},
        'production_enabled': False,
        'domain_intersection': {'status': 'blocked_no_approved_domain', 'parts': None},
    }
    catalog = {'schema_version': SCHEMA, 'review_date': '2026-10-22',
               'production_enabled': False, 'domain': {'approved': False, 'geometry': None,
               'reason': 'approved_domain_not_supplied'}, 'services': [service]}
    return catalog, sources


class TransitCatalogTest(unittest.TestCase):
    def setUp(self):
        self.catalog, self.sources = fixture()
        self.service = self.catalog['services'][0]

    def test_pending_review_is_valid_but_never_operational(self):
        before = copy.deepcopy((self.catalog, self.sources))
        result = validate(self.catalog, self.sources)
        self.assertEqual(result['production_status'], 'blocked')
        self.assertFalse(result['production_enabled'])
        self.assertEqual(result['operational_validation'], 'not_performed')
        self.assertEqual(before, (self.catalog, self.sources))

    def test_unknown_source(self):
        self.service['sources'] = ['not-in-registry']
        with self.assertRaisesRegex(ValueError, 'unknown source'):
            validate(self.catalog, self.sources)

    def test_top_level_location_and_metadata_references_are_checked(self):
        for key, value in (
            ('location_checks', [{'sources': ['unknown-location-source']}]),
            ('metadata', {'source_id': 'unknown-provenance-source'}),
        ):
            with self.subTest(key=key):
                changed = copy.deepcopy(self.catalog)
                changed[key] = value
                with self.assertRaisesRegex(ValueError, 'unknown source'):
                    validate(changed, self.sources)

    def test_duplicate_service_id(self):
        self.catalog['services'].append(copy.deepcopy(self.service))
        with self.assertRaisesRegex(ValueError, 'duplicate service_id'):
            validate(self.catalog, self.sources)

    def test_duplicate_source_id(self):
        self.sources['sources'].append(copy.deepcopy(self.sources['sources'][0]))
        with self.assertRaisesRegex(ValueError, 'duplicate source_id'):
            validate(self.catalog, self.sources)

    def test_enabled_pending_forbidden_at_catalog_and_service(self):
        for value in (self.catalog, self.service):
            with self.subTest(target=value.get('service_id', 'catalog')):
                value['production_enabled'] = True
                with self.assertRaisesRegex(ValueError, 'cannot enable production'):
                    validate(self.catalog, self.sources)
                value['production_enabled'] = False

    def test_no_approved_domain_cannot_claim_intersection(self):
        self.service['domain_intersection'] = {'status': 'verified', 'parts': ['invented-part']}
        with self.assertRaisesRegex(ValueError, 'no approved domain'):
            validate(self.catalog, self.sources)

    def test_download_rectangle_cannot_be_unapproved_domain_geometry(self):
        self.catalog['domain']['geometry'] = {'type': 'Polygon', 'coordinates': []}
        with self.assertRaisesRegex(ValueError, 'no approved domain'):
            validate(self.catalog, self.sources)

    def test_pending_coordinates_must_remain_null(self):
        self.service['coordinates'] = [[0, 0]]
        with self.assertRaisesRegex(ValueError, 'pending field must be null'):
            validate(self.catalog, self.sources)

    def test_verified_data_requires_source(self):
        self.service['verification']['field_status']['operator'] = {
            'status': 'verified', 'sources': []}
        with self.assertRaisesRegex(ValueError, 'requires a source'):
            validate(self.catalog, self.sources)

    def test_every_factual_field_requires_state(self):
        for field in FACTUAL_FIELDS:
            with self.subTest(field=field):
                changed = copy.deepcopy(self.catalog)
                del changed['services'][0]['verification']['field_status'][field]
                with self.assertRaisesRegex(ValueError, 'field_status: missing keys'):
                    validate(changed, self.sources)

    def test_assumptions_need_explicit_synthetic_marker_and_reason(self):
        for state in ('scenario_assumption', {'status': 'scenario_assumption'},
                      {'status': 'scenario_assumption', 'synthetic': False, 'reason': 'test'},
                      {'status': 'scenario_assumption', 'synthetic': True}):
            with self.subTest(state=state):
                self.service['verification']['field_status']['operator'] = state
                with self.assertRaisesRegex(ValueError, 'synthetic|reason'):
                    validate(self.catalog, self.sources)

    def test_synthetic_source_cannot_be_verified_evidence(self):
        self.service['verification']['field_status']['operator'] = {
            'status': 'verified', 'sources': ['synthetic-source'],
            'scope': 'Verified in cited source; current operations not verified'}
        with self.assertRaisesRegex(ValueError, 'synthetic evidence cannot verify'):
            validate(self.catalog, self.sources)

    def test_verified_source_scope_does_not_activate_production(self):
        # Fake registry entry representing an operator publication for this test.
        self.sources['sources'].append({
            **copy.deepcopy(self.sources['sources'][0]),
            'source_id': 'publication-fixture', 'kind': 'operator_publication',
        })
        self.service['sources'].append('publication-fixture')
        self.service['verification']['field_status']['operator'] = {
            'status': 'verified', 'sources': ['publication-fixture'],
            'scope': 'Verified in cited source; current operations not verified'}
        result = validate(self.catalog, self.sources)
        self.assertFalse(result['production_enabled'])
        self.assertEqual(result['operational_validation'], 'not_performed')

    def test_recurring_stop_retained_without_deduplication(self):
        visits = ['synthetic-A', 'synthetic-B', 'synthetic-A']
        self.service['stop_sequences'] = [{
            'stops': visits.copy(), 'order_explicit': True, 'sources': ['synthetic-source']}]
        self.service['verification']['field_status']['stop_sequences'] = assumption()
        validate(self.catalog, self.sources)
        self.assertEqual(self.service['stop_sequences'][0]['stops'], visits)

    def test_inventory_is_not_an_ordered_route(self):
        self.service['stop_sequences'] = [{
            'stops': ['synthetic-A', 'synthetic-B'], 'order_explicit': False,
            'sources': ['synthetic-source']}]
        self.service['verification']['field_status']['stop_sequences'] = assumption()
        with self.assertRaisesRegex(ValueError, 'order must be explicit'):
            validate(self.catalog, self.sources)

    def test_office_hours_cannot_be_trip_departures(self):
        self.service['verification']['field_status']['schedule'] = assumption()
        for schedule in ({'kind': 'office_hours', 'hours': ['08:00', '17:00']},
                         {'kind': 'departures', 'basis': 'office_hours', 'departures': ['08:00']},
                         {'kind': 'service_hours', 'departures': ['08:00']}):
            with self.subTest(schedule=schedule):
                self.service['schedule'] = schedule
                with self.assertRaisesRegex(ValueError, 'office hours|does not establish departures'):
                    validate(self.catalog, self.sources)

    def test_artifact_hash_size_and_path_confinement(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            artifacts = []
            for name in ('municipal-gis.json', 'osm-evidence.json'):
                content = b'{"synthetic_fixture": true}\n'
                (directory / name).write_bytes(content)
                artifacts.append({'path': name, 'bytes': len(content),
                                  'sha256': hashlib.sha256(content).hexdigest()})
            self.catalog['artifacts'] = artifacts
            self.assertEqual(validate_artifacts(self.catalog, directory / 'catalog.json'), 2)
            for key, value, expected in (
                ('bytes', artifacts[0]['bytes'] + 1, 'size mismatch'),
                ('sha256', '0' * 64, 'hash mismatch'),
                ('path', '../municipal-gis.json', 'relative and confined'),
                ('path', str(directory / 'municipal-gis.json'), 'relative and confined'),
            ):
                with self.subTest(key=key, value=value):
                    changed = copy.deepcopy(self.catalog)
                    changed['artifacts'][0][key] = value
                    with self.assertRaisesRegex(ValueError, expected):
                        validate_artifacts(changed, directory / 'catalog.json')

    def test_required_companions_cannot_be_omitted(self):
        with tempfile.TemporaryDirectory() as folder:
            self.catalog['artifacts'] = []
            with self.assertRaisesRegex(ValueError, 'missing companions'):
                validate_artifacts(self.catalog, Path(folder) / 'catalog.json')


class TransitReviewPackageTest(unittest.TestCase):
    """Read the small checked-in review package only; no network or generators."""

    def test_review_package_structure_citations_and_artifact_integrity(self):
        catalog_path = DEFAULT_DIRECTORY / 'catalog.json'
        catalog = json.loads(catalog_path.read_text(encoding='utf-8-sig'))
        sources = json.loads((DEFAULT_DIRECTORY / 'sources.json').read_text(encoding='utf-8-sig'))
        summary = validate(catalog, sources)
        self.assertEqual(summary['services'], 23)
        self.assertEqual(summary['sources'], 37)
        self.assertFalse(summary['production_enabled'])
        self.assertEqual(summary['operational_validation'], 'not_performed')
        self.assertEqual(validate_artifacts(catalog, catalog_path), 2)

    def test_review_gis_references_resolve_to_declared_layers_and_feature_ids(self):
        catalog = json.loads((DEFAULT_DIRECTORY / 'catalog.json').read_text(encoding='utf-8-sig'))
        sources = json.loads((DEFAULT_DIRECTORY / 'sources.json').read_text(encoding='utf-8-sig'))
        gis = json.loads((DEFAULT_DIRECTORY / 'municipal-gis.json').read_text(encoding='utf-8-sig'))
        known_sources = {source['source_id'] for source in sources['sources']}
        declared_artifacts = {artifact['path'] for artifact in catalog['artifacts']}
        features_by_layer = {}
        for layer in gis['layers']:
            source_id = layer['source_id']
            self.assertIn(source_id, known_sources)
            self.assertNotIn(source_id, features_by_layer)
            features = layer['data']['features']
            ids = {feature['id'] for feature in features}
            self.assertEqual(len(ids), len(features), 'A layer must not repeat a feature ID')
            for feature in features:
                self.assertEqual(feature['id'], feature['properties']['FID'])
            features_by_layer[source_id] = ids

        references = []

        def visit(value):
            if isinstance(value, dict):
                if {'artifact', 'layer_source_id', 'feature_ids'} <= value.keys():
                    references.append(value)
                for child in value.values():
                    visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)

        visit(catalog)
        self.assertTrue(references, 'The review must retain its published GIS references')
        for reference in references:
            with self.subTest(layer=reference['layer_source_id'], ids=reference['feature_ids']):
                self.assertIn(reference['artifact'], declared_artifacts)
                self.assertEqual(reference['artifact'], 'municipal-gis.json')
                layer_id = reference['layer_source_id']
                self.assertIn(layer_id, features_by_layer)
                self.assertTrue(reference['feature_ids'])
                self.assertTrue(set(reference['feature_ids']) <= features_by_layer[layer_id])


if __name__ == '__main__':
    unittest.main()
