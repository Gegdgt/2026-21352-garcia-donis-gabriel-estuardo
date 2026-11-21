"""Read-only validation of SimZ1 transit evidence, never a service activator.

This review schema deliberately cannot authorize production. A valid document
can retain unresolved evidence and conflicts without implying an operational
schedule, route geometry, permission, or approved modelling boundary.
"""
from __future__ import annotations

import argparse
from datetime import date
import hashlib
import json
from pathlib import Path
from urllib.parse import urlparse


SCHEMA = 'simz1-transit-evidence-v1'
SOURCES_SCHEMA = 'simz1-transit-sources-v1'
DEFAULT_DIRECTORY = (Path(__file__).resolve().parents[1] / 'scenarios' / 'zona1'
                     / 'transit' / 'review-2026-10-22')
FIELD_STATES = {'verified', 'scenario_assumption', 'pending'}
FACTUAL_FIELDS = {'operator', 'line', 'variant', 'direction', 'stop_sequences',
                  'coordinates', 'route', 'calendar', 'schedule'}
ARTIFACT_NAMES = {'municipal-gis.json', 'osm-evidence.json'}
SERVICE_KEYS = {
    'service_id', 'operator', 'line', 'variant', 'direction', 'stop_sequences',
    'coordinates', 'route', 'calendar', 'schedule', 'sources', 'review_date',
    'license', 'verification', 'production_enabled', 'domain_intersection',
}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _object(value, location: str) -> dict:
    _require(isinstance(value, dict), f'{location}: expected object')
    return value


def _keys(value: dict, keys: set[str], location: str) -> None:
    missing = keys - value.keys()
    _require(not missing, f'{location}: missing keys {sorted(missing)}')


def _text(value, location: str) -> str:
    _require(isinstance(value, str) and bool(value.strip()),
             f'{location}: expected nonempty text')
    return value


def _date(value, location: str, *, nullable: bool = False) -> None:
    if value is None and nullable:
        return
    _text(value, location)
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f'{location}: expected ISO date YYYY-MM-DD') from error
    _require(parsed.isoformat() == value, f'{location}: expected ISO date YYYY-MM-DD')


def _license(value, location: str) -> None:
    value = _object(value, location)
    _keys(value, {'id', 'status'}, location)
    _text(value['status'], f'{location}.status')
    if value['id'] is not None:
        _text(value['id'], f'{location}.id')


def _source_refs(value, known: set[str], location: str) -> list[str]:
    _require(isinstance(value, list), f'{location}: expected source ID list')
    for item in value:
        _text(item, location)
        _require(item in known, f'{location}: unknown source {item!r}')
    _require(len(value) == len(set(value)), f'{location}: duplicate source reference')
    return value


def _nested_refs(value, known: set[str], location: str) -> None:
    """Check field/claim citations too, without constraining evidence payloads."""
    if isinstance(value, dict):
        if value.get('status') == 'scenario_assumption':
            _assumption(value, location)
        for key, item in value.items():
            if key == 'sources':
                _source_refs(item, known, f'{location}.{key}')
            elif key == 'source_id':
                _text(item, f'{location}.{key}')
                _require(item in known, f'{location}.{key}: unknown source {item!r}')
            else:
                _nested_refs(item, known, f'{location}.{key}')
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _nested_refs(item, known, f'{location}[{index}]')


def _assumption(value, location: str) -> None:
    _require(isinstance(value, dict) and value.get('synthetic') is True,
             f'{location}: scenario assumption requires explicit synthetic:true')
    _text(value.get('reason'), f'{location}.reason')


def _sequences(value, known: set[str], location: str) -> None:
    if value is None:
        return
    _require(isinstance(value, list) and bool(value), f'{location}: expected nonempty sequence list')
    for index, sequence in enumerate(value):
        label = f'{location}[{index}]'
        sequence = _object(sequence, label)
        _keys(sequence, {'stops', 'order_explicit', 'sources'}, label)
        _require(sequence['order_explicit'] is True,
                 f'{label}: stop order must be explicit in the cited source')
        _require(isinstance(sequence['stops'], list) and len(sequence['stops']) >= 2,
                 f'{label}.stops: expected at least two ordered visits')
        for stop in sequence['stops']:
            _require((isinstance(stop, str) and bool(stop.strip())) or
                     (isinstance(stop, dict) and bool(stop)), f'{label}: invalid stop visit')
        # Repeated stops are intentional visits in a circular or branching route.
        _require(bool(_source_refs(sequence['sources'], known, f'{label}.sources')),
                 f'{label}: ordered visits require a source')


def _schedule(value, location: str) -> None:
    if value is None:
        return
    value = _object(value, location)
    _keys(value, {'kind'}, location)
    _require(value['kind'] in {'service_hours', 'departures', 'headway'},
             f'{location}: office hours are not service hours or trip departures')
    if value['kind'] == 'service_hours':
        _require(not value.get('departures') and not value.get('headway_seconds'),
                 f'{location}: a service opening interval does not establish departures/headway')
    if value.get('basis') in {'office_hours', 'agency_hours', 'customer_service_hours'}:
        raise ValueError(f'{location}: office hours cannot establish trip departures')


def validate(catalog: dict, sources: dict) -> dict:
    """Validate review structure and citations; return an explicitly blocked summary."""
    catalog = _object(catalog, 'catalog')
    sources = _object(sources, 'sources')
    _keys(catalog, {'schema_version', 'review_date', 'production_enabled', 'domain', 'services'}, 'catalog')
    _keys(sources, {'schema_version', 'sources'}, 'sources')
    _require(catalog['schema_version'] == SCHEMA, 'catalog: unsupported schema_version')
    _require(sources['schema_version'] == SOURCES_SCHEMA, 'sources: unsupported schema_version')
    _date(catalog['review_date'], 'catalog.review_date')
    _require(catalog['production_enabled'] is False,
             'catalog.production_enabled: review schema cannot enable production')
    _require(isinstance(sources['sources'], list), 'sources.sources: expected list')
    source_ids, synthetic_sources = set(), set()
    for index, source in enumerate(sources['sources']):
        label = f'sources.sources[{index}]'
        source = _object(source, label)
        _keys(source, {'source_id', 'url', 'kind', 'accessed_on', 'published_on', 'license'}, label)
        source_id = _text(source['source_id'], f'{label}.source_id')
        _require(source_id not in source_ids, f'{label}: duplicate source_id {source_id!r}')
        source_ids.add(source_id)
        parsed_url = urlparse(_text(source['url'], f'{label}.url'))
        _require(parsed_url.scheme in {'http', 'https'} and bool(parsed_url.netloc),
                 f'{label}.url: expected public http(s) source URL')
        kind = _text(source['kind'], f'{label}.kind')
        if kind.startswith('synthetic') or kind == 'scenario_assumption' or source.get('synthetic') is True:
            synthetic_sources.add(source_id)
        _date(source['accessed_on'], f'{label}.accessed_on')
        _date(source['published_on'], f'{label}.published_on', nullable=True)
        _license(source['license'], f'{label}.license')
    # References also occur in location checks and provenance metadata outside
    # services. Validate the entire document after building the source registry.
    _nested_refs(catalog, source_ids, 'catalog')
    domain = _object(catalog['domain'], 'catalog.domain')
    _keys(domain, {'approved', 'geometry', 'reason'}, 'catalog.domain')
    _require(type(domain['approved']) is bool, 'catalog.domain.approved: expected boolean')
    if not domain['approved']:
        _require(domain['geometry'] is None,
                 'catalog.domain.geometry: no approved domain; keep geometry null')
        _text(domain['reason'], 'catalog.domain.reason')
    else:
        _require(domain['geometry'] is not None, 'catalog.domain.geometry: approved domain requires geometry')
    _require(isinstance(catalog['services'], list), 'catalog.services: expected list')
    service_ids = set()
    states = {state: 0 for state in sorted(FIELD_STATES)}
    blockers = {'review_schema_never_enables_production'}
    if not domain['approved']:
        blockers.add('approved_domain_not_supplied')
    for index, service in enumerate(catalog['services']):
        label = f'catalog.services[{index}]'
        service = _object(service, label)
        _keys(service, SERVICE_KEYS, label)
        service_id = _text(service['service_id'], f'{label}.service_id')
        _require(service_id not in service_ids, f'{label}: duplicate service_id {service_id!r}')
        service_ids.add(service_id)
        _require(service['production_enabled'] is False,
                 f'{label}.production_enabled: review schema cannot enable production')
        _date(service['review_date'], f'{label}.review_date')
        _license(service['license'], f'{label}.license')
        citations = _source_refs(service['sources'], source_ids, f'{label}.sources')
        verification = _object(service['verification'], f'{label}.verification')
        _keys(verification, {'status', 'field_status', 'blockers'}, f'{label}.verification')
        _require(verification['status'] == 'pending',
                 f'{label}.verification.status: review services must remain pending')
        _require(isinstance(verification['blockers'], list) and bool(verification['blockers']),
                 f'{label}.verification.blockers: pending service requires explicit blockers')
        for blocker in verification['blockers']:
            blockers.add(_text(blocker, f'{label}.verification.blockers'))
        field_status = _object(verification['field_status'], f'{label}.verification.field_status')
        _keys(field_status, FACTUAL_FIELDS, f'{label}.verification.field_status')
        for field, field_state in field_status.items():
            _require(field in service, f'{label}: field_status references missing field {field!r}')
            if isinstance(field_state, dict):
                _keys(field_state, {'status'}, f'{label}.field_status.{field}')
                state = field_state['status']
                field_sources = field_state.get('sources', citations)
            else:
                state, field_sources = field_state, citations
            _require(isinstance(state, str) and state in FIELD_STATES,
                     f'{label}.{field}: unknown verification state {state!r}')
            states[state] += 1
            if state == 'pending':
                _require(service[field] is None, f'{label}.{field}: pending field must be null')
            elif state == 'verified':
                _require(service[field] is not None, f'{label}.{field}: verified field cannot be null')
                _require(bool(_source_refs(field_sources, source_ids, f'{label}.{field}.sources')),
                         f'{label}.{field}: verified data requires a source')
                _require(not (set(field_sources) & synthetic_sources),
                         f'{label}.{field}: synthetic evidence cannot verify real-world data')
                if isinstance(field_state, dict) and 'scope' in field_state:
                    _text(field_state['scope'], f'{label}.{field}.scope')
            else:
                _require(service[field] is not None, f'{label}.{field}: scenario assumption cannot be null')
                _assumption(field_state, f'{label}.verification.field_status.{field}')
        _sequences(service['stop_sequences'], source_ids, f'{label}.stop_sequences')
        _schedule(service['schedule'], f'{label}.schedule')
        intersection = _object(service['domain_intersection'], f'{label}.domain_intersection')
        _keys(intersection, {'status', 'parts'}, f'{label}.domain_intersection')
        if not domain['approved']:
            _require(intersection['status'] == 'blocked_no_approved_domain' and intersection['parts'] is None,
                     f'{label}.domain_intersection: no approved domain; intersection must remain blocked/null')
        elif str(intersection['status']).startswith('blocked'):
            _require(intersection['parts'] is None, f'{label}.domain_intersection: blocked parts must be null')
    return {
        'schema_version': SCHEMA, 'review_date': catalog['review_date'],
        'validation': 'structure_and_citations_valid', 'operational_validation': 'not_performed',
        'production_enabled': False, 'production_status': 'blocked',
        'services': len(service_ids), 'sources': len(source_ids), 'field_status_counts': states,
        'blockers': sorted(blockers),
    }


def validate_artifacts(catalog: dict, catalog_path: Path) -> int:
    """Read only the two declared companion files, confined to the catalog directory.

    This checks bytes and provenance consistency, not the accuracy of GIS features
    or their validity as directed MATSim routes. Kept separate from pure validate.
    """
    base = catalog_path.resolve().parent
    artifacts = catalog.get('artifacts')
    _require(isinstance(artifacts, list), 'catalog.artifacts: expected companion file list')
    seen = set()
    for index, artifact in enumerate(artifacts):
        label = f'catalog.artifacts[{index}]'
        artifact = _object(artifact, label)
        _keys(artifact, {'path', 'sha256', 'bytes'}, label)
        name = _text(artifact['path'], f'{label}.path')
        relative = Path(name)
        _require(not relative.is_absolute() and '..' not in relative.parts,
                 f'{label}.path: artifact must be relative and confined to the catalog directory')
        resolved = (base / relative).resolve()
        _require(resolved.parent == base,
                 f'{label}.path: artifact must be confined to the catalog directory')
        _require(name in ARTIFACT_NAMES, f'{label}.path: unsupported companion file {name!r}')
        _require(name not in seen, f'{label}.path: duplicate artifact {name!r}')
        seen.add(name)
        expected_bytes = artifact['bytes']
        _require(type(expected_bytes) is int and expected_bytes >= 0,
                 f'{label}.bytes: expected nonnegative integer')
        digest = artifact['sha256']
        _require(isinstance(digest, str) and len(digest) == 64 and
                 all(character in '0123456789abcdef' for character in digest),
                 f'{label}.sha256: expected lowercase SHA-256 digest')
        _require(resolved.is_file(), f'{label}.path: companion file missing')
        actual = hashlib.sha256()
        actual_bytes = 0
        with resolved.open('rb') as stream:
            for chunk in iter(lambda: stream.read(65536), b''):
                actual.update(chunk)
                actual_bytes += len(chunk)
        _require(actual_bytes == expected_bytes, f'{label}.bytes: companion size mismatch')
        _require(actual.hexdigest() == digest, f'{label}.sha256: companion hash mismatch')
    _require(seen == ARTIFACT_NAMES,
             f'catalog.artifacts: missing companions {sorted(ARTIFACT_NAMES - seen)}')
    return len(seen)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog', type=Path, default=DEFAULT_DIRECTORY / 'catalog.json')
    parser.add_argument('--sources', type=Path, default=DEFAULT_DIRECTORY / 'sources.json')
    parser.add_argument('--strict-production', action='store_true',
                        help='Exit 2 for valid review data, which cannot enable production.')
    args = parser.parse_args(argv)
    try:
        catalog = json.loads(args.catalog.read_text(encoding='utf-8-sig'))
        sources = json.loads(args.sources.read_text(encoding='utf-8-sig'))
        summary = validate(catalog, sources)
        summary['artifact_integrity_checks'] = validate_artifacts(catalog, args.catalog)
    except (OSError, ValueError, TypeError) as error:
        print(json.dumps({'validation': 'invalid', 'error': str(error), 'production_enabled': False},
                         ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 2 if args.strict_production else 0


if __name__ == '__main__':
    raise SystemExit(main())
