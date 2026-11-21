"""Pinned OSM sequence policy shared with Java; no changes to the physical graph."""
import hashlib
import json
from pathlib import Path
import warnings

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / 'src/main/resources/simz1/osm-sequences-v1.json'
SHA256 = '2dc457548aaf57a5551d09928688be8bdc2b84cdbf383fda691f3eb5a4b7d254'


def relation_identity(row):
    return dict(attributes=dict(row.attrib),
                members=[dict(m.attrib) for m in row.findall('member')],
                tags=[dict(t.attrib) for t in row.findall('tag')])


def _read_contract(path):
    raw = Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != SHA256:
        raise ValueError('OSM sequence contract SHA256 mismatch')
    doc = json.loads(raw)
    if doc['schema'] != 'simz1-osm-sequences' or doc['version'] != 1:
        raise ValueError('Unsupported OSM sequence contract')
    return doc


def reviewed_source_paths():
    """Select context only; enforcement still requires all load_contract proofs.

    Historical scenarios must not depend on the availability of another
    scenario's source artifacts. The selector itself remains hash-bound.
    """
    return {meta['role']: (ROOT/name).resolve()
            for name, meta in _read_contract(CONTRACT)['sources'].items()
            if meta['role'] in ('isolated_source_osm', 'directed_mapping', 'ten_preserved_lane_corrections')}


def load_contract(path=CONTRACT, source_root=ROOT):
    doc = _read_contract(path)
    for name, meta in doc['sources'].items():
        if hashlib.sha256((Path(source_root) / name).read_bytes()).hexdigest() != meta['sha256']:
            raise ValueError('OSM source evidence hash mismatch: ' + name)
    return doc


def malformed_disposition(relation, document=None):
    doc = load_contract() if document is None else document
    treatment, = doc['malformed_source_treatments']
    if relation_identity(relation) != treatment['relation']:
        raise ValueError('Outside the exact 17884471 v2 data-quality treatment')
    warnings.warn(treatment['status'] + ': ' + treatment['warning'], RuntimeWarning, stacklevel=2)
    return treatment


class SequenceContract:
    """DFA state = longest suffix that is a proper forbidden-sequence prefix.

    Prefix states retain overlapping/repeated occurrences. No physical links,
    lanes or capacities are cloned. None is a rejected transition.
    """
    def __init__(self, document=None, mode='car'):
        doc = load_contract() if document is None else document
        self.document = doc
        self.patterns = [(tuple(seq), row['relation_id']) for row in doc['restrictions']
                         if mode in row['modes'] and mode not in row['exceptions']
                         for seq in row['sequences']]
        self.via_links = frozenset(link for seq, _ in self.patterns for link in seq[1:-1])
        prefixes = {()}
        for seq, _ in self.patterns:
            prefixes.update(seq[:n] for n in range(1, len(seq)))
        self.prefixes = sorted(prefixes, key=lambda p: (len(p), p))
        self.indices = {p: i for i, p in enumerate(self.prefixes)}
        alphabet = {link for seq, _ in self.patterns for link in seq}
        self.transitions = {}
        for state, prefix in enumerate(self.prefixes):
            for link in alphabet:
                value = prefix + (link,)
                if any(value[-len(seq):] == seq for seq, _ in self.patterns):
                    target = None
                else:
                    target = max((p for p in self.prefixes if not p or value[-len(p):] == p), key=len)
                    target = self.indices[target]
                self.transitions[state, link] = target

    def advance(self, state, link):
        if state is None:
            return None
        return self.transitions.get((state, link), 0)

    def progress(self, path, state=0):
        for link in path:
            state = self.advance(state, link)
            if state is None:
                return None
        return state

    def validate(self, path):
        state = 0
        for index, link in enumerate(path):
            state = self.advance(state, link)
            if state is None:
                raise ValueError(f'Forbidden OSM sequence ending at occurrence {index}: {link}')
