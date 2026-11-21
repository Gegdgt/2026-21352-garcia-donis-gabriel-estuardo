"""Read-only, bounded client/source fingerprint check. Never starts a server.

No SQLite/event/plan scans, exports, browser, or modification of run artifacts.
An HTTP match proves the response now served, not a previously loaded tab.
"""
import argparse
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, build_opener

from simz1_continuous_replay import application_html

LIMIT = 16 * 1024 * 1024
IDENTITY = ('run_id', 'iteration', 'run_manifest_sha256')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read_small(path):
    with Path(path).open('rb') as stream:
        raw = stream.read(LIMIT + 1)
    if len(raw) > LIMIT:
        raise ValueError(f'Metadata exceeds {LIMIT} bytes: {path}')
    return raw


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('Redirect refused; supply the exact loopback URL')


def inspect(directory, url=None):
    directory = Path(directory).resolve(strict=True)
    raw = read_small(directory / 'continuous-manifest.json')
    manifest = json.loads(raw)
    expected = {key: manifest[key] for key in IDENTITY}
    source_type = manifest.get('source_type', 'paged-html-v1')
    if source_type not in ('sqlite-direct-v1', 'paged-html-v1'):
        raise ValueError('Unknown source contract')
    filename = 'sqlite-source-manifest.json' if source_type == 'sqlite-direct-v1' else 'export-manifest.json'
    source_raw = read_small(Path(manifest['source_directory']) / filename)
    source = json.loads(source_raw)
    if sha(source_raw) != manifest['source_export_sha256'] or any(source[key] != expected[key] for key in IDENTITY):
        raise ValueError('Source manifest identity/hash mismatch')
    native_raw = read_small(Path(source['run_directory']) / 'run-manifest.json')
    native = json.loads(native_raw)
    if (sha(native_raw) != expected['run_manifest_sha256'] or native['run_id'] != expected['run_id'] or
            str(expected['iteration']) not in native['results']):
        raise ValueError('Native run identity/hash/iteration mismatch')
    config_raw = read_small(directory / 'config.json')
    config = json.loads(config_raw)
    if (sha(config_raw) != manifest['config_sha256'] or
            any(config['continuous'][key] != expected[key] for key in IDENTITY) or
            any(config['hud'][key] != expected[key] for key in ('run_id', 'iteration'))):
        raise ValueError('Stored config identity/hash mismatch')
    current = application_html().encode('utf-8')
    marker = b'window.simz1ClientBuild=Object.freeze('
    start = current.index(marker) + len(marker)
    build = json.loads(current[start:current.index(b');</script>', start)])
    stored = read_small(directory / 'index.html')
    report = dict(**expected, replay_directory=str(directory), source_type=source_type,
        source_version=sha(source_raw),
        source_directory=manifest['source_directory'], source_manifest_sha256=sha(source_raw),
        continuous_manifest_sha256=sha(raw), current_client_build=build,
        current_application_sha256=sha(current), stored_application_sha256=sha(stored),
        stored_application_matches_current=stored == current,
        planned_persons=config.get('hud', {}).get('planned_persons'),
        evidence_scope='metadata hashes only; no database/event/plan validation or replay execution',
        loaded_browser_client='not_observed', http=None)
    if url:
        parsed = urlsplit(url)
        if (parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', 'localhost', '::1') or
                parsed.username or parsed.password or parsed.query or parsed.fragment or
                parsed.path not in ('', '/', '/index.html')):
            raise ValueError('Only an exact loopback HTTP viewer URL is allowed')
        base = f'{parsed.scheme}://{parsed.netloc}'
        opener = build_opener(ProxyHandler({}), NoRedirect())

        def fetch(path):
            with opener.open(base + path, timeout=3) as response:
                body = response.read(LIMIT + 1)
                if len(body) > LIMIT:
                    raise ValueError('HTTP metadata exceeds size limit')
                return body, response.headers.get('Cache-Control')

        try:
            served, cache = fetch('/index.html')
            served_config, _ = fetch('/api/config')
            served_config = json.loads(served_config)
            identity_matches = all(served_config.get('continuous', {}).get(key) == expected[key] for key in IDENTITY)
            expected_source = dict(source_type=source_type, source_manifest_sha256=sha(source_raw),
                database_sha256=source.get('database_sha256'), database_bytes=manifest.get('database_bytes'),
                database_mtime_ns=manifest.get('database_mtime_ns'), replay_manifest_sha256=sha(raw))
            source_matches = (served_config.get('continuous', {}).get('source_version') == sha(source_raw) and
                all(served_config.get('replay_source', {}).get(key) == value for key, value in expected_source.items()))
            report['http'] = dict(url=base + '/index.html', status='read', cache_control=cache,
                application_sha256=sha(served), application_matches_current=served == current,
                identity_matches=identity_matches, source_matches=source_matches,
                identity={key: served_config.get('continuous', {}).get(key) for key in (*IDENTITY, 'source_version')},
                replay_source=served_config.get('replay_source'))
        except (OSError, ValueError) as error:
            report['http'] = dict(url=url, status='unverified', error=str(error))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--replay-dir', type=Path, required=True)
    parser.add_argument('--url', help='Read an already running loopback server; never launch it')
    args = parser.parse_args()
    try:
        report = inspect(args.replay_dir, args.url)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, f'Cannot verify source: {error}\n')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    remote = report['http']
    return 0 if remote is None or (remote.get('application_matches_current') and
                                  remote.get('identity_matches') and remote.get('source_matches')) else 2


if __name__ == '__main__':
    raise SystemExit(main())
