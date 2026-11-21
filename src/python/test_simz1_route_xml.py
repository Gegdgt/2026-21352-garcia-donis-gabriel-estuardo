"""Bounded Python -> MATSim 15 XML regression; never runs a simulation.

Run with .venv/Scripts/python.exe -B python/test_simz1_route_xml.py.
Artifacts are retained in a fresh runtime/route-xml-* folder, never receipts.
"""
import copy
from collections import Counter
from contextlib import redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET

from simz1_route_xml import validate_link_route

ROOT = Path(__file__).resolve().parents[1]
from simz1_history_fixtures import dataset, BASE
HISTORY = BASE/'cursor'
HISTORY_SHA = '809d3c6713914258d7fce378d937e0d0e31bd894e23a5bdaaf0ca15bb57ea5ec'
RUN_ID = 'simz1-8545ef106cbe43ce8fabb81bf0bc0a41'
PERSON = 'z1_97936'
HEADER = b'<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE population SYSTEM "http://www.matsim.org/files/dtd/population_v6.dtd">\n<population>\n'


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            digest.update(block)
    return digest.hexdigest()


def write_people(path, people):
    path.write_bytes(HEADER + b'\n'.join(ET.tostring(p, encoding='utf-8') for p in people) + b'\n</population>\n')


def extract_history(folder):
    """Copy the exact pre-deletion fragment, checking its original provenance."""
    import shutil
    source=dataset('cursor')
    index=json.loads((BASE/'provenance.json').read_bytes())['files']['cursor/historical.xml']
    assert index['run_id']==RUN_ID and index['source_sha256']==HISTORY_SHA
    assert index['person_id']==PERSON and index['persons_extracted']==1
    fixture=folder/'historical.xml';shutil.copyfile(source/'historical.xml',fixture)
    assert sha(fixture)==index['sha256']
    (folder/'provenance.json').write_text(json.dumps(index,indent=2)+'\n',encoding='utf-8')
    return fixture



class RouteXmlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = Path(tempfile.mkdtemp(prefix='route-xml-', dir=ROOT/'runtime'))
        print('ROUTE_XML_ARTIFACTS='+str(cls.folder), flush=True)
        cls.receipts = {p:sha(p) for p in (ROOT/'runtime/workflow').glob('*') if p.is_file()}
        cls.java = Path(os.environ.get('SIMZ1_JDK17', r'C:\Program Files\Java\jdk-17'))/'bin'
        ns = {'m':'http://maven.apache.org/POM/4.0.0'}
        assert ET.parse(ROOT/'pom.xml').findtext('m:properties/m:matsim.version', namespaces=ns) == '15.0'
        cls.classpath = (ROOT/'target/simz1-runtime-classpath.txt').read_text(encoding='utf-8-sig').strip()
        assert any(Path(p).name == 'matsim-15.0.jar' for p in cls.classpath.split(os.pathsep))
        cls.run_command('compile', [str(cls.java/'javac.exe'), '--release', '17', '-encoding', 'UTF-8',
            '-proc:none', '-cp', cls.classpath, '-d', str(cls.folder),
            str(ROOT/'src/test/java/gt/edu/uvg/sim/zona1/PopulationRouteXmlCheck.java')])

    @classmethod
    def tearDownClass(cls):
        assert cls.receipts == {p:sha(p) for p in (ROOT/'runtime/workflow').glob('*') if p.is_file()}

    @classmethod
    def run_command(cls, label, command):
        run = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=60)
        (cls.folder/(label+'.log')).write_text(run.stdout+run.stderr, encoding='utf-8')
        (cls.folder/(label+'.command.json')).write_text(json.dumps(dict(command=command, returncode=run.returncode), indent=2), encoding='utf-8')
        if run.returncode:
            raise AssertionError(f'{label}: exit={run.returncode}\n{run.stdout}\n{run.stderr}')
        return run

    def native(self, path, label):
        prefix = self.folder/label
        run = self.run_command(label, [str(self.java/'java.exe'), '-Xmx256m', '-cp',
            str(self.folder)+os.pathsep+self.classpath, 'gt.edu.uvg.sim.zona1.PopulationRouteXmlCheck', str(path), str(prefix)])
        self.assertIn('matsim-15.0.jar', run.stdout)
        self.assertIn('controller_started=false qsim_started=false', run.stdout)
        loaded = ET.parse(str(prefix)+'.loaded.xml').getroot()
        reloaded = ET.parse(str(prefix)+'.reloaded.xml').getroot()
        self.assertEqual(len(loaded), len(reloaded))
        for a,b in zip(sorted(loaded, key=lambda p:p.get('id')), sorted(reloaded, key=lambda p:p.get('id'))):
            self.assertEqual(a.attrib, b.attrib)
            self.assertEqual({r.get('name'):r.text for r in a.findall('attributes/attribute')},
                             {r.get('name'):r.text for r in b.findall('attributes/attribute')})
            self.assertEqual(ET.tostring(a.find('plan/leg')), ET.tostring(b.find('plan/leg')))
            for x,y in zip(a.findall('plan/activity'), b.findall('plan/activity')):
                self.assert_activity(x, y)
        return loaded

    def assert_activity(self, expected, actual):
        self.assertEqual(set(expected.attrib), set(actual.attrib))
        for k,v in expected.attrib.items():
            if k in ('x','y','end_time'):
                self.assertAlmostEqual(float(v), float(actual.get(k)), places=9)
            else:
                self.assertEqual(v, actual.get(k))

    def test_01_historical_native_reproduction(self):
        fixture = extract_history(self.folder)
        original = ET.parse(fixture).find('person')
        loaded = self.native(fixture, 'historical')[0]
        route = loaded.find('plan/leg/route')
        self.assertEqual(loaded.get('id'), PERSON)
        self.assertEqual(route.get('vehicleRefId'), PERSON)
        self.assertEqual(route.get('start_link'), 'osm_762765906_2_forward')
        self.assertEqual(route.get('end_link'), 'osm_1305763184_1_forward')
        self.assertEqual(len(route.text.split()), 73)
        self.assertEqual(route.text.split(), original.find('plan/leg/route').text.split())
        for a,b in zip(original.findall('plan/activity'), loaded.findall('plan/activity')):
            self.assert_activity(a,b)
        self.assertNotEqual(route.get('start_link'), loaded.find('plan/activity').get('link'))

    def assert_person(self, original, loaded, expected):
        ident = original.get('id')
        self.assertEqual(loaded.get('id'), ident)
        for a,b in zip(original.findall('plan/activity'), loaded.findall('plan/activity')):
            self.assert_activity(a,b)
        attrs = {a.get('name'):a.text for a in loaded.findall('attributes/attribute')}
        for a in original.findall('attributes/attribute'):
            value = a.text
            if a.get('name') == 'vehicles':
                value = '{' + ', '.join(k+'='+v for k,v in sorted(json.loads(value).items())) + '}'
            self.assertEqual(attrs[a.get('name')], value)
        route = loaded.find('plan/leg/route')
        if expected is None:
            self.assertIsNone(route)
            return
        acts = original.findall('plan/activity')
        self.assertEqual(validate_link_route(route, expected, origin=acts[0].get('link'),
            destination=acts[-1].get('link'), vehicle_id=ident), expected)
        self.assertEqual(route.get('intermediates').split(), expected[1:-1])

    def test_02_historical_corrected_native_roundtrip(self):
        fixture = self.folder/'historical.xml'
        if not fixture.exists():
            fixture = extract_history(self.folder)
        original = ET.parse(fixture).find('person')
        fixed = copy.deepcopy(original)
        metadata = next(iter(json.loads(original.findtext("attributes/attribute[@name='simz1SpatialOD']")).values()))
        expected = metadata['route_link_ids']
        self.assertEqual(len(expected), 75)
        self.assertEqual((expected[0], expected[-1]), ('osm_762765906_1_forward', 'osm_1305763184_1_backward'))
        self.assertEqual(float(fixed.find('plan/activity').get('end_time')), 0.7991602372870776)
        fixed.find('plan/leg/route').text = ' '.join(expected)
        path = self.folder/'corrected.xml'
        write_people(path, [fixed])
        loaded = self.native(path, 'corrected')[0]
        self.assert_person(original, loaded, expected)
        # Exactly the description changed; no activity/identity/schedule repair.
        restored = copy.deepcopy(fixed)
        restored.find('plan/leg/route').text = original.find('plan/leg/route').text
        self.assertEqual(ET.tostring(restored), ET.tostring(original))

    @staticmethod
    def person(ident, path, text=None):
        person = ET.Element('person', id=ident)
        plan = ET.SubElement(person, 'plan', selected='yes')
        ET.SubElement(plan, 'activity', type='home', link=path[0], end_time='0.7991602372870776')
        leg = ET.SubElement(plan, 'leg', mode='car')
        ET.SubElement(leg, 'route', type='links', start_link=path[0], end_link=path[-1],
                      vehicleRefId=ident).text = ' '.join(path) if text is None else text
        ET.SubElement(plan, 'activity', type='work', link=path[-1])
        return person

    def test_03_short_repeated_and_empty_native_descriptions(self):
        cases = dict(one=['a'], two=['a','b'], three=['a','b','c'],
                     repeated=['a','b','c','b','d'], closed=['a','b','a'])
        people = [self.person(k,v) for k,v in cases.items()]
        # Native empty descriptions retain attributes; these short cases do NOT
        # have the nonempty historical shift. New XML still requires full text.
        people += [self.person('empty_one',['a'],''), self.person('empty_two',['a','b'],'')]
        people += [self.person('old_three',['a','b','c'],'b')]
        path = self.folder/'short.xml'
        write_people(path, people)
        actual = {p.get('id'):p for p in self.native(path, 'short')}
        for original in people[:5]:
            self.assert_person(original, actual[original.get('id')], cases[original.get('id')])
        for ident, expected in [('empty_one',['a']), ('empty_two',['a','b'])]:
            original = next(p for p in people if p.get('id') == ident)
            self.assert_person(original, actual[ident], expected)
            with self.assertRaisesRegex(ValueError,'Explicit links XML'):
                validate_link_route(original.find('plan/leg/route'), expected,
                    origin=expected[0], destination=expected[-1], vehicle_id=ident)
        # This repeated path is topologically legitimate (b traversed twice).
        nodes = dict(a=('0','1'), b=('1','2'), c=('2','1'), d=('2','3'))
        for a,b in zip(cases['repeated'], cases['repeated'][1:]):
            self.assertEqual(nodes[a][1],nodes[b][0])
        route = actual['old_three'].find('plan/leg/route')
        self.assertEqual((route.get('start_link'), route.get('end_link'), route.text), ('b','c','b c'))

    def test_04_contradictions_fail_closed(self):
        expected = ['a','b','c']
        good = self.person('p', expected)
        changes = [('start_link','b'), ('end_link','b'), ('vehicleRefId','other'), ('type','generic')]
        for key,value in changes:
            bad = copy.deepcopy(good)
            bad.find('plan/leg/route').set(key,value)
            with self.subTest(attribute=key), self.assertRaisesRegex(ValueError,'Explicit links XML'):
                validate_link_route(bad.find('plan/leg/route'), expected, origin='a', destination='c', vehicle_id='p')
        for text in ('', 'b', 'b c', 'a b', 'a a b c', 'a b b c'):
            route = self.person('p', expected, text).find('plan/leg/route')
            with self.subTest(text=text), self.assertRaises(ValueError):
                validate_link_route(route, expected, origin='a', destination='c', vehicle_id='p')
        for origin,destination in [('b','c'), ('a','b')]:
            with self.assertRaises(ValueError):
                validate_link_route(good.find('plan/leg/route'), expected, origin=origin, destination=destination, vehicle_id='p')
        with self.assertRaises(ValueError):
            validate_link_route(None, expected, origin='a', destination='c', vehicle_id='p')

    def test_05_production_private_writer_native_four_classes(self):
        from test_simz1_balanced_gateway_od import SmallGenerationTests, CATALOG, SEED
        from test_simz1_sequence_contract import COPY, OUT
        from simz1_balanced_od import load_model
        from simz1_agent_types import load_catalog, sample_departures, vehicle_types_xml
        from simz1_demand_composition import split
        from simz1_population import write_population, verify_population
        graph = load_model(COPY/'network.xml', OUT/'perimeter.geojson', COPY/'lanes.xml', COPY/'map.osm', OUT/'access.json')
        people, report = SmallGenerationTests().generate(self.folder, graph)
        catalog = load_catalog(CATALOG)
        ET.ElementTree(vehicle_types_xml(catalog)).write(self.folder/'types.xml', encoding='utf-8')
        path = self.folder/'private.xml'
        write_population(path, self.folder/'vehicles.xml', people, self.folder/'types.xml', 'Bounded XML regression')
        verify_population(path, self.folder/'vehicles.xml', 99, graph.eligible_links,
                          expected_trips_per_person=1, require_trip_ids=True, spatial_model=graph)
        loaded = {p.get('id'):p for p in self.native(path, 'private')}
        self.assertEqual(set(loaded), {p.get('id') for p in people})
        classes = Counter()
        for p in people:
            ident = p.get('id')
            row = next(iter(json.loads(p.findtext("attributes/attribute[@name='simz1SpatialOD']")).values()))
            classes[row['od_class']] += 1
            self.assert_person(p, loaded[ident], row['route_link_ids'])
            graph.validate_metadata(row)
            graph.validate_route(loaded[ident].find('plan/leg/route').text.split())
            kind = p.findtext("attributes/attribute[@name='simz1AgentType']")
            self.assertEqual(float(loaded[ident].find('plan/activity').get('end_time')), sample_departures(kind,1,SEED,ident,catalog)[0])
        self.assertEqual(dict(classes), report['spatial_demand']['target_class_counts'])
        self.assertEqual(len(classes), 4)
        self.assertEqual(Counter(p.findtext("attributes/attribute[@name='simz1VehicleFamily']") for p in people), dict(carro=44,moto=55))
        # Production keeps its distinct-OD rule even though XML can encode one link.
        bad = copy.deepcopy(people[0]); acts = bad.findall('plan/activity'); acts[-1].set('link', acts[0].get('link'))
        write_people(self.folder/'same-link.xml', [bad])
        with self.assertRaisesRegex(ValueError, 'no distinto'):
            verify_population(self.folder/'same-link.xml', self.folder/'vehicles.xml',1,graph.eligible_links,spatial_model=graph)
        self.assertEqual(split(180000,catalog)['family_counts'], dict(carro=79200,moto=99000,pesado=1800))

    def test_06_production_freight_all_routes_and_network_mode_native(self):
        from generate_montecarlo_z1 import generar
        from simz1_freight import is_freight, verified_contract
        from simz1_run import artifact
        scenario = ROOT/'scenarios/zona1'
        run = self.folder/'freight-network'
        with redirect_stdout(io.StringIO()):
            generar(scenario/'config-simz1.xml', run, 20261023, agents=4, mode='montecarlo',
                corridor_policy='redistribute', origin_policy='uniform-nodes-v1', od_mode='network',
                agent_catalog=scenario/'agent-types-car-moto-v1.json',
                transit_service=scenario/'transit/weekday-v2/service-fleet-176-93-v1.json',
                transit_service_date='2026-10-23', accept_transit_route_assumptions=True,
                freight_service=scenario/'freight/weekday-compact-v3/service-composition-v3.json',
                freight_service_date='2026-10-23', freight_vehicles=4)
        manifest = json.loads((run/'run-manifest.json').read_bytes())
        contract = verified_contract(run, manifest)
        self.assertEqual(len(contract),4)
        self.assertEqual(len({r['route_id'] for r in contract.values()}),4)
        self.assertEqual(manifest['counts']['public_transport_vehicles_configured'],269)
        people = ET.parse(run/'plans.xml').getroot()
        loaded = {p.get('id'):p for p in self.native(run/'plans.xml', 'freight-network')}
        for p in people:
            expected = contract[p.get('id')]['link_ids'] if is_freight(p) else None
            self.assert_person(p, loaded[p.get('id')], expected)
            if expected is None:
                self.assertIsNone(p.find('plan/leg/route'))
        # Re-hashing a tampered small fixture must not bypass the freight auditor.
        original = (run/'plans.xml').read_bytes()
        for attribute in ('start_link', 'end_link', 'vehicleRefId'):
            tree = ET.fromstring(original)
            next(p for p in tree if is_freight(p)).find('plan/leg/route').set(attribute,'wrong')
            write_people(run/'plans.xml', list(tree))
            altered = copy.deepcopy(manifest); altered['inputs']['plans'] = artifact(run,run/'plans.xml')
            with self.assertRaisesRegex(ValueError,'Explicit links XML'):
                verified_contract(run,altered)
        (run/'plans.xml').write_bytes(original)

    def test_07_native_sequence_17478998_still_rejected(self):
        from test_simz1_sequence_contract import A,V,B,C,D
        from simz1_sequence_contract import SequenceContract
        cases = dict(forbidden=[A,V,B], legal_arrival=[C,V,B], legal_exit=[A,V,D])
        path = self.folder/'sequence.xml'
        write_people(path, [self.person(k,v) for k,v in cases.items()])
        for p in self.native(path, 'sequence'):
            sequence = p.find('plan/leg/route').text.split()
            self.assertEqual(sequence,cases[p.get('id')])
            if p.get('id') == 'forbidden':
                with self.assertRaisesRegex(ValueError,'Forbidden OSM sequence'):
                    SequenceContract().validate(sequence)
            else:
                SequenceContract().validate(sequence)

    def test_08_validate_and_fingerprint_include_regression(self):
        from simz1_workflow_state import fingerprint
        from simz1_balanced_od_audit import implementation_signature
        self.assertIn('simz1_route_xml.py',implementation_signature()['source_sha256'])
        workflow = (ROOT/'scripts/simz1_workflow.ps1').read_text(encoding='utf-8')
        self.assertLess(workflow.index('prepare_simz1_runtime.ps1 -RunSmoke'), workflow.index('python\\test_simz1_route_xml.py'))
        self.assertLess(workflow.index('python\\test_simz1_route_xml.py'), workflow.index("'validated-source.txt'"))
        # Exercise the current recursive fingerprint mechanism in an isolated tree.
        folder = self.folder/'fingerprint'; folder.mkdir()
        from test_simz1_freight_version import REQUIRED_FIXTURE_FILES
        files = [*REQUIRED_FIXTURE_FILES,
                 'python/simz1_route_xml.py', 'python/test_simz1_route_xml.py',
                 'src/test/java/gt/edu/uvg/sim/zona1/PopulationRouteXmlCheck.java']
        for name in files:
            target=folder/name; target.parent.mkdir(parents=True,exist_ok=True); target.write_text('fixture',encoding='utf-8')
        for name in files[-3:]:
            before=fingerprint(folder)
            (folder/name).write_text('changed',encoding='utf-8')
            self.assertNotEqual(before,fingerprint(folder),name)


if __name__ == '__main__':
    unittest.main(verbosity=2)
