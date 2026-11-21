"""Bounded diagnostics for two OSM relations. Never authorize a launch.

Run directly with the repository .venv Python and -B. The Java probe only calls
pure routing/validation functions in a six-link fixture: no Controller or QSim.
Production sources and effective scenario files remain read-only.
"""
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

HERE = Path(__file__).resolve().parent
COPY = HERE.parent
OUT = COPY.parent
ROOT = HERE.parents[5]
sys.path.insert(0, str(ROOT / 'python'))
from simz1_balanced_od import BalancedGatewayModel, load_model, native_queue_ends
from simz1_gateway_od import load_gateway_model
from simz1_od_policy import validate_osm_turns
from simz1_osm_turn_audit import inspect_restrictions, load_lanes, load_xml
from simz1_workflow_state import fingerprint, require_balanced_validation
from pyproj import Transformer

A, V, B, C = ('osm_1273145789_0_forward', 'osm_1270930401_0_forward',
               'osm_1273145790_0_forward', 'osm_734011349_14_forward')
SEQUENCE = [A, V, B]
TARGET = 'osm_34993910_0_forward'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def relation_identity(row):
    return {'attributes': dict(row.attrib),
            'members': [dict(m.attrib) for m in row.findall('member')],
            'tags': [dict(t.attrib) for t in row.findall('tag')]}


def malformed_v2_disposition(row):
    """Prepared review ONLY; not called or activated by the production preflight.

    Exact source object, never a generic exemption for incomplete relations.
    """
    full = ET.parse(HERE / 'relation-17884471-full.osm').getroot().find('relation')
    if (row.get('id') != '17884471' or row.get('version') != '2' or
            row.get('changeset') != '178612606' or
            row.get('timestamp') != '2026-02-16T06:36:31Z' or
            row.get('visible') != 'true' or
            [dict(m.attrib) for m in row.findall('member')] !=
            [{'type': 'way', 'ref': '34993910', 'role': 'to'}] or
            [dict(t.attrib) for t in row.findall('tag')] !=
            [{'k': 'restriction', 'v': 'no_straight_on'}, {'k': 'type', 'v': 'restriction'}] or
            relation_identity(row) != relation_identity(full)):
        raise ValueError('Outside the exact 17884471 v2 data-quality review')
    provenance = json.loads((HERE / 'source-provenance.json').read_bytes())
    for name, evidence in provenance['sources'].items():
        if sha(HERE / name) != evidence['sha256']:
            raise ValueError('OSM source evidence hash mismatch: ' + name)
    history = ET.parse(HERE / 'relation-17884471-history.osm').getroot().findall('relation')
    if len(history) != 2 or relation_identity(history[-1]) != relation_identity(full):
        raise ValueError('Relation source history differs')
    way = ET.parse(HERE / 'way-381158225-history.osm').getroot().findall('way')[-1]
    if (way.get('id'), way.get('version'), way.get('visible'), way.get('changeset'), way.get('timestamp')) != (
            '381158225', '11', 'false', '178612606', '2026-02-16T06:36:31Z'):
        raise ValueError('Deleted historical from-way evidence differs')
    return dict(status='MALFORMED_SOURCE_NO_EXECUTABLE_MANEUVER',
                activation='PREPARED_NOT_ACTIVATED_IN_PRODUCTION',
                relation_id='17884471', version=2, changeset='178612606',
                warning='OSM 17884471 v2 lacks from/via in the authoritative source; '
                        'no maneuver can be inferred. Historical from-way 381158225 was deleted. '
                        'This does not establish unrestricted legal access to the destination.',
                relation=relation_identity(row),
                source_sha256={k: v['sha256'] for k, v in provenance['sources'].items()},
                source_repair_applied=False, global_target_ban=False)


def contains(path, sequence=SEQUENCE):
    return any(path[i:i+len(sequence)] == sequence for i in range(len(path)-len(sequence)+1))


class RemainingOsmTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.osm = load_xml(COPY / 'map.osm')
        cls.network = load_xml(COPY / 'network.xml')
        cls.links = {r.get('id'): r for r in cls.network.findall('links/link')}
        cls.moves = load_lanes(COPY / 'lanes.xml')
        cls.audit = inspect_restrictions(COPY/'map.osm', COPY/'network.xml', COPY/'lanes.xml')
        cls.rows = {r['relation_id']: r for r in cls.audit['rows']}
        cls.report = {'status': 'BLOCKED', 'production_exemptions_activated': False,
                      'simulation_started': False, 'massive_preflight_executed': False}

    def test_01_sources_and_local_relations_agree(self):
        sources = json.loads((HERE/'source-provenance.json').read_bytes())['sources']
        for name, meta in sources.items():
            self.assertEqual(sha(HERE/name), meta['sha256'])
        for rid in ('17478998', '17884471'):
            source = ET.parse(HERE/f'relation-{rid}-full.osm').getroot().find('relation')
            self.assertEqual(relation_identity(source),
                             relation_identity(self.osm.find(f"relation[@id='{rid}']")))

    def test_02_exact_sequence_and_no_exceptions(self):
        row = self.rows['17478998']
        self.assertEqual(json.loads(row['directed_sequences']), [SEQUENCE])
        self.assertEqual(row['semantics_review'], '')
        self.assertEqual(row['lanes_admit_sequence'], 'true')
        self.assertEqual(json.loads(row['osm_tags']), {'restriction': 'no_u_turn', 'type': 'restriction'})

    def test_03_other_origin_and_other_destination_remain_legal_by_this_relation(self):
        for path in ([C, V, B], [A, V, 'osm_260940553_0_forward']):
            self.assertFalse(contains(path))
            self.assertTrue(all(b in self.moves[a] for a, b in zip(path, path[1:])))
        self.assertEqual(sorted(k for k, v in self.moves.items() if V in v), sorted([A, C]))

    def test_04_production_rejects_sequence_and_malformed_relation_before_generation(self):
        for call in (
            lambda: validate_osm_turns(COPY/'map.osm',COPY/'network.xml',COPY/'lanes.xml'),
            lambda: load_model(COPY/'network.xml',OUT/'perimeter.geojson',COPY/'lanes.xml',
                               COPY/'map.osm',OUT/'access.json')):
            with self.assertRaisesRegex(ValueError, r'pendientes \(2\): 17478998, 17884471'):
                call()

    def test_05_source_v2_is_malformed_and_not_an_extraction_loss(self):
        result = malformed_v2_disposition(self.osm.find("relation[@id='17884471']"))
        self.assertEqual(result['status'], 'MALFORMED_SOURCE_NO_EXECUTABLE_MANEUVER')
        self.assertEqual(result['activation'], 'PREPARED_NOT_ACTIVATED_IN_PRODUCTION')
        self.report['17884471'] = result

    def test_06_historical_v1_cannot_be_restored_as_a_current_source(self):
        history = ET.parse(HERE/'relation-17884471-history.osm').getroot().findall('relation')
        self.assertEqual([r.get('version') for r in history], ['1', '2'])
        self.assertEqual([dict(m.attrib) for m in history[0].findall('member')], [
            dict(type='way', ref='381158225', role='from'),
            dict(type='node', ref='333864721', role='via'),
            dict(type='way', ref='34993910', role='to')])
        self.assertIsNone(self.osm.find("way[@id='381158225']"))
        self.assertFalse(any(l.get('origid') == '381158225' for l in self.links.values()))

    def test_07_disposition_rejects_other_ids_versions_tags_or_complete_relations(self):
        original = self.osm.find("relation[@id='17884471']")
        for key, value in [('id','999'),('version','3'),('changeset','999'),('visible','false')]:
            row = copy.deepcopy(original); row.set(key, value)
            with self.subTest(key=key), self.assertRaises(ValueError):
                malformed_v2_disposition(row)
        row = copy.deepcopy(original)
        ET.SubElement(row,'member',type='way',ref='381158225',role='from')
        with self.assertRaises(ValueError): malformed_v2_disposition(row)
        row = copy.deepcopy(original); row.find('tag').set('v','no_left_turn')
        with self.assertRaises(ValueError): malformed_v2_disposition(row)

    def test_08_all_ten_existing_corrections_remain_excluded(self):
        previous = json.loads((OUT/'osm-turn-resolution.json').read_bytes())
        self.assertEqual(len(previous['changes']), 10)
        for change in previous['changes']:
            self.assertEqual(self.rows[change['relation_id']]['lanes_admit_prohibited_target'], 'false')
        self.assertEqual(sum(r['removed_targets'] for r in previous['changes']), 22)

    def test_09_other_complete_valid_restriction_still_blocks(self):
        # Isolate one known uncorrected pair from the historical lanes. No full preflight.
        with tempfile.TemporaryDirectory(prefix='simz1-osm-negative-') as folder:
            osm = copy.deepcopy(self.osm)
            for r in list(osm.findall('relation')):
                if r.get('id') != '6008781': osm.remove(r)
            path = Path(folder)/'map.osm'; ET.ElementTree(osm).write(path, encoding='utf-8')
            with self.assertRaisesRegex(ValueError, r'pendientes \(1\): 6008781'):
                validate_osm_turns(path, COPY/'network.xml', ROOT/'scenarios/zona1/lanes.xml')

    def assert_connected(self, path):
        for a, b in zip(path, path[1:]):
            self.assertEqual(self.links[a].get('to'), self.links[b].get('from'))
            if a in self.moves: self.assertIn(b, self.moves[a])
        self.assertFalse(contains(path))

    def test_10_all_four_freight_routes_preserved_and_connected(self):
        bundle = json.loads((COPY/'freight/routes.json').read_bytes())
        self.assertEqual(len(bundle['routes']), 4)
        for row in bundle['routes']: self.assert_connected(row['link_ids'])
        self.report['freight_routes_connected'] = 4

    def test_11_all_transit_parts_connected_l12_l13_target_preserved(self):
        bundle = json.loads((ROOT/'scenarios/zona1/transit/weekday-v2/route-bundle.json').read_bytes())
        additional = {l['id']: l for l in bundle['additional_links']}
        links = {**self.links, **additional}
        uses, count = [], 0
        for service in bundle['services']:
            for part in service['parts']:
                path = part['link_ids']; count += 1
                self.assertFalse(contains(path))
                for a,b in zip(path,path[1:]):
                    self.assertEqual(links[a].get('to'),links[b].get('from'))
                    if a in self.moves and b not in self.moves[a]:
                        # Existing transit preparation adds only documented bus-only
                        # targets. Do not grant a new car turn or modify a lane here.
                        self.assertIn(b,additional)
                        self.assertEqual(additional[b]['modes'],'bus')
                if TARGET in path: uses.append(dict(service_id=service['service_id'], part_id=part['part_id']))
        self.assertEqual(count, 24)
        self.assertEqual({r['service_id'] for r in uses}, {'transmetro_L12', 'transmetro_L13'})
        self.report['transit_parts_connected'] = count
        self.report['transit_target_users'] = uses

    def test_12_bounded_selected_od_connectivity_does_not_claim_global_enforcement(self):
        # Static constructor for diagnostics only: production load_model stays closed.
        base = load_gateway_model(COPY/'network.xml', OUT/'perimeter.geojson', COPY/'lanes.xml')
        project = Transformer.from_crs('EPSG:4326', 'EPSG:32615', always_xy=True)
        for link in base.links.values():
            link['metric_path'] = [project.transform(*xy) for xy in link['path']]
        doc = json.loads((OUT/'access.json').read_bytes())
        graph = BalancedGatewayModel(base, doc, native_queue_ends(COPY/'network.xml',COPY/'lanes.xml'), self.moves)
        self.assertEqual((len(doc['entry_gateways']),len(doc['exit_gateways']),len(doc['internal_origins'])), (10,12,22))
        pairs = json.loads((OUT/'access-review.json').read_bytes())['entry_exit_pairs']
        checked = 0
        for row in pairs:
            if row['status'] != 'static_shortest_path_admissible': continue
            route = graph.route(row['entry'],row['exit']); self.assert_connected(route); checked += 1
        self.assertEqual(checked, 115)
        for body in (4.5, 2.1):
            for kind in ('external-external','external-internal','internal-external','internal-internal'):
                self.assertTrue(graph.origins(kind,body), (kind,body))
        # This interior search does not include B. The selected access candidates
        # therefore do not establish a global sequence restriction on physical lanes.
        distance, _ = graph._tree(A)
        self.assertFalse(B in distance)
        self.report['static_od_pairs_checked'] = checked
        self.report['selected_static_routes_avoid_sequence'] = True
        self.report['global_sequence_enforcement_proven_by_selected_routes'] = False
        self.report['production_generation_available'] = False

    def test_13_java_rerouting_incompatibility_reproduced_without_simulation(self):
        java = Path(r'C:\Program Files\Java\jdk-17\bin')
        deps = (ROOT/'target/simz1-runtime-classpath.txt').read_text(encoding='utf-8-sig').strip()
        classpath = os.pathsep.join([str(ROOT/'target/classes'), deps])
        names = ('SimZ1RouteSafety.java', 'SimZ1TurnRouter.java', 'DrivingProfiles.java')
        sources = [ROOT/'src/main/java/gt/edu/uvg/sim/zona1'/n for n in names]
        with tempfile.TemporaryDirectory(prefix='simz1-osm-probe-') as folder:
            empty = Path(folder)/'empty-source'; empty.mkdir()
            result = subprocess.run([str(java/'javac.exe'),'-encoding','UTF-8','-proc:none',
                '-cp',classpath,'-sourcepath',str(empty),'-d',folder,*map(str,sources),
                str(HERE/'Restriction17478998Probe.java')],cwd=ROOT,capture_output=True,text=True,timeout=60)
            (HERE/'java-probe-compile.log').write_text(result.stdout+result.stderr,encoding='utf-8')
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            result = subprocess.run([str(java/'java.exe'),'-cp',folder+os.pathsep+classpath,
                'gt.edu.uvg.sim.zona1.Restriction17478998Probe'],cwd=ROOT,
                capture_output=True,text=True,timeout=60)
            (HERE/'java-probe.log').write_text(result.stdout+result.stderr,encoding='utf-8')
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            data = json.loads(next(line.split('OSM_PROBE=',1)[1] for line in result.stdout.splitlines()
                                   if line.startswith('OSM_PROBE=')))
        for field in ('forbidden_route_accepted','legal_other_origin_accepted','generated_forbidden_sequence',
                      'reroute_reintroduced_sequence','replacement_validator_accepted','primary_pair_graph_admits_both'):
            self.assertTrue(data[field], 'Counterexample changed; re-review required: '+field)
        self.assertFalse(data['controller_started']); self.assertFalse(data['qsim_started'])
        self.report['java_counterexample'] = data
        self.report['java_compiled_from_current_source_sha256'] = {str(p.relative_to(ROOT)):sha(p) for p in sources}

    def test_14_all_historical_effective_inputs_and_receipt_unchanged(self):
        baseline = json.loads((HERE/'preserved-input-hashes.json').read_bytes())['sha256']
        for path, value in baseline.items(): self.assertEqual(sha(ROOT/path),value,path)
        self.report['preserved_file_count'] = len(baseline)

    def test_15_stale_validate_receipt_is_not_reused(self):
        receipt_path = ROOT/'runtime/workflow/validated-balanced-gateway-v1.json'
        before = sha(receipt_path)
        receipt = json.loads(receipt_path.read_text(encoding='utf-8-sig'))
        current = fingerprint()
        self.assertNotEqual(receipt['source_fingerprint'], current)
        with self.assertRaisesRegex(ValueError,'Falta Validate integrado'): require_balanced_validation()
        self.assertEqual(sha(receipt_path),before)
        self.report['validation_binding'] = dict(receipt_sha256=before,
            approved_fingerprint=receipt['source_fingerprint'],current_fingerprint=current,matches=False,
            validate_executed=False,receipt_modified=False)


if __name__ == '__main__':
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream,verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(RemainingOsmTests))
    output = stream.getvalue()
    (HERE/'focused-tests.log').write_text(output,encoding='utf-8')
    report = RemainingOsmTests.report
    report['tests'] = dict(run=result.testsRun,failures=len(result.failures),errors=len(result.errors),
        skipped=len(result.skipped),diagnostics_passed=result.wasSuccessful(),
        scope='Static source, hash, route diagnostics; passing reproductions are NOT restriction enforcement')
    report['17478998'] = dict(status='BLOCKED_ROUTER_HAS_NO_SEQUENCE_STATE',
        required_enforcement_checks=dict(forbidden_sequence_rejected_by_router=False,
            initial_route_avoids_sequence=False,reroute_cannot_reintroduce_sequence=False),
        production_loader_fail_closed=True,java_engine_modified=False)
    report['required_enforcement_checks_proven'] = False
    (HERE/'remaining-osm-review.json').write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print(output)
    print('BLOCKED: diagnostics do not enforce 17478998; 17884471 treatment is prepared, not activated.')
    sys.exit(0 if result.wasSuccessful() else 1)
