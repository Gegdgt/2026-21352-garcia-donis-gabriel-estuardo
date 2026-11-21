"""Real bounded preparation, service derivation and fail-closed physical checks.

No execution child is permitted. Preflight parity stops before the massive
iterator, after its real service/access checks, and compares the N=100 proof.
"""
from collections import Counter
from contextlib import redirect_stdout
import copy
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

import generate_montecarlo_z1 as generator
from simz1_balanced_od_audit import check_effective_network, validate_manifest
from simz1_effective_access import review
from simz1_lane_validation import audit_configuration
from simz1_run import checked_path, parameters, sha256
from simz1_sequence_contract import SequenceContract
from test_simz1_lane_policy_integration import (ROOT, SOURCE, CONFIG, OD, CATALOG, PUBLIC,
    FREIGHT, SEED, generation_options)


class EffectiveAccessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        destination = os.environ.get('SIMZ1_EFFECTIVE_TEST_EVIDENCE')
        if destination:
            cls.folder = Path(destination).resolve()
            cls.folder.mkdir(parents=True, exist_ok=False)
        else:
            cls.temp = tempfile.TemporaryDirectory(prefix='simz1-effective-access-tests-')
            cls.addClassCleanup(cls.temp.cleanup)
            cls.folder = Path(cls.temp.name)
        protected = [ROOT/'scenarios/zona1/od/balanced-gateway-v1', ROOT/'scenarios/zona1/transit',
                     ROOT/'runtime/lane-policy-repair', ROOT/'runtime/workflow', ROOT/'src/main/java',
                     ROOT/'src/main/resources/simz1']
        cls.hashes = {p: sha256(p) for folder in protected for p in folder.rglob('*') if p.is_file()}
        cls.runs, cls.reports, cls.manifests = [], [], []
        import simz1_weekday_transit as transit
        import simz1_balanced_od_audit as od_audit
        validated = []
        def observed_validation(*args, **kwargs):
            result = validate_manifest(*args, **kwargs)
            validated.append(result)
            return result
        for index in range(2):
            directory = cls.folder/f'prepared-100-{index+1}'
            with (cls.folder/f'generation-{index+1}.log').open('w', encoding='utf-8') as log, \
                    redirect_stdout(log), patch.object(subprocess, 'Popen', side_effect=AssertionError('No process may start')) as child, \
                    patch.object(transit, 'attach', wraps=transit.attach) as attached, \
                    patch.object(od_audit, 'validate_manifest', side_effect=observed_validation):
                report = generator.generar(CONFIG, directory, SEED, **generation_options())
                child.assert_not_called()
                if attached.call_count != 1:
                    raise AssertionError('Service must be attached exactly once per preparation')
            cls.runs.append(directory)
            cls.reports.append(report)
            cls.manifests.append(json.loads((directory/'run-manifest.json').read_text(encoding='utf-8')))
        cls.directory, cls.manifest = cls.runs[0], cls.manifests[0]
        cls.proof = json.loads((cls.directory/'inputs/effective-access-review.json').read_text(encoding='utf-8'))
        if len(validated) != 2:
            raise AssertionError('Both normal generator calls must finish their real manifest validator')
        cls.model, cls.records = validated[0]
        evidence = dict(status='prepared_pending_not_simulated', runs=[str(p) for p in cls.runs],
            counts=cls.manifest['counts'], od_counts=cls.manifest['spatial_demand']['target_class_counts'],
            source_lane_audit_status=cls.manifest['source_lane_configuration_validation']['status'],
            effective_lane_audit_status=cls.manifest['lane_configuration_validation']['status'],
            access_review_status=cls.proof['status'], endpoint_changes=len(cls.proof['changed_endpoints']),
            manifest_status=cls.manifest['status'], validation_status=cls.manifest['validation']['status'],
            service_attach_calls_per_preparation=1, controller_started=False, qsim_started=False,
            child_processes_started=0, source_files_unchanged=all(sha256(p)==h for p,h in cls.hashes.items()))
        (cls.folder/'integration-evidence.json').write_text(json.dumps(evidence, indent=2)+'\n', encoding='utf-8')

    def test_complete_preparation_counts_inputs_and_pending_manifest(self):
        self.assertEqual(self.manifest['status'], 'prepared')
        self.assertEqual(self.manifest['validation']['status'], 'pending')
        self.assertEqual(self.manifest['demand_composition']['family_counts'], dict(carro=44, moto=55, pesado=1))
        self.assertEqual(self.manifest['counts']['public_transport_vehicles_configured'], 269)
        self.assertEqual(len(self.records), 99)
        self.assertEqual(self.manifest['spatial_demand']['target_class_counts'], dict(
            EXTERNAL_EXTERNAL_THROUGH=49, EXTERNAL_INTERNAL=20, INTERNAL_EXTERNAL=20, INTERNAL_INTERNAL=10))
        for record in self.manifest['inputs'].values():
            path = checked_path(self.directory, record)
            if path.suffix == '.xml':
                ET.parse(path)
        self.assertFalse((self.directory/'output').exists())
        self.assertEqual(len(ET.parse(self.directory/'plans.xml').getroot().findall('person')), 100)

    def test_real_changes_example_and_resource_intersections(self):
        previous = json.loads((ROOT/'runtime/lane-policy-repair/integration-evidence.json').read_text())
        changes = self.proof['changed_endpoints']
        self.assertEqual(len(changes), 46)
        self.assertEqual([{k: row[k] for k in ('link_id','source_m','effective_m')} for row in changes],
                         sorted(previous['changed_endpoints'], key=lambda r:r['link_id']))
        example = next(r for r in changes if r['link_id']=='osm_384762167_1_forward')
        self.assertEqual(example['source_m'], 10.488502634659277)
        self.assertEqual(example['effective_m'], 50.44251317329641)
        self.assertEqual(self.proof['effective_sha256']['lanes'], previous['endpoint']['effective_lanes_sha256'])
        self.assertEqual(self.proof['status'], 'accepted_for_preparation')
        self.assertTrue(all(not r['removed'] for r in self.proof['destination_eligibility'].values()))
        self.assertTrue(all(r['useful_length_m'] <= r['effective_native_endpoint_m'] for r in self.proof['access_resources']))
        self.assertTrue(all('gateway_chains' in r and 'internal_egress' in r for r in changes))

    def test_repeated_preparation_does_not_accumulate_fleet_stops_or_geometry(self):
        one, two = self.runs
        for name in ('network.xml','lanes.xml','transitVehicles.xml','transitSchedule.xml','stops.json','roster.json','weekday-policy.json'):
            self.assertEqual(sha256(one/'inputs/transit-weekday'/name), sha256(two/'inputs/transit-weekday'/name), name)
        self.assertEqual(sha256(one/'plans.xml'), sha256(two/'plans.xml'))
        for path, tag in (('transitVehicles.xml','vehicle'), ('transitSchedule.xml','transitStops/stopFacility')):
            from simz1_gateway_od import _xml
            ids = [r.get('id') for r in _xml(one/'inputs/transit-weekday'/path).findall(tag)]
            self.assertGreater(len(ids), 0)
            if tag == 'vehicle':
                self.assertEqual(len(ids), 269)
            self.assertEqual(len(ids), len(set(ids)))
        import simz1_weekday_transit as transit
        before = {p:sha256(p) for p in (one/'inputs/transit-weekday').iterdir()}
        with self.assertRaisesRegex(ValueError, 'output exists'):
            transit.attach(ET.parse(one/'config-simz1.xml').getroot(), one/'inputs/transit-weekday',99,PUBLIC,'2026-10-23',True)
        self.assertEqual(before, {p:sha256(p) for p in before})

    def checked_mutation(self, kind, mutate):
        with tempfile.TemporaryDirectory(dir=self.folder) as temp:
            directory = Path(temp)
            network = self.directory/'inputs/transit-weekday/network.xml'
            lanes = self.directory/'inputs/transit-weekday/lanes.xml'
            original = network if kind=='network' else lanes
            from simz1_gateway_od import _xml
            root = _xml(original)
            mutate(root)
            changed = directory/(kind+'.xml')
            ET.ElementTree(root).write(changed, encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'undeclared'):
                review(SOURCE/'network.xml', SOURCE/'lanes.xml', changed if kind=='network' else network,
                    changed if kind=='lanes' else lanes, OD/'perimeter.geojson', SOURCE/'map.osm', OD/'access.json',
                    self.directory/'inputs/transit-weekday')

    def test_undeclared_endpoint_rejected(self):
        self.checked_mutation('lanes', lambda root: root.find("lanesToLinkAssignment[@linkIdRef='osm_384762167_1_forward']/lane[@id='osm_384762167_1_forward.lane.0']/startsAt").set('meterFromLinkEnd','3.0'))

    def test_declaring_an_arbitrary_endpoint_does_not_authorize_it(self):
        with tempfile.TemporaryDirectory(dir=self.folder) as temp:
            service = Path(temp)/'transit'
            shutil.copytree(self.directory/'inputs/transit-weekday', service)
            path = service/'weekday-policy.json'
            policy = json.loads(path.read_text())
            row = next(r for r in policy['stop_queue_summary']['adjustments'] if r['link_id']=='osm_384762167_1_forward')
            row['new_native_service_endpoint_m'] -= 1
            row['new_terminal_starts_m']['osm_384762167_1_forward.lane.0'] = 3
            path.write_text(json.dumps(policy), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'declared queue adjustments differ'):
                review(SOURCE/'network.xml',SOURCE/'lanes.xml', service/'network.xml', service/'lanes.xml',
                       OD/'perimeter.geojson',SOURCE/'map.osm',OD/'access.json',service)

    def test_xml_serialization_is_distinct_from_physical_transformation(self):
        from simz1_gateway_od import _xml
        with tempfile.TemporaryDirectory(dir=self.folder) as temp:
            service = self.directory/'inputs/transit-weekday'
            network, lanes = Path(temp)/'network.xml', Path(temp)/'lanes.xml'
            net = _xml(service/'network.xml')
            for row in net.findall('links/link'):
                origid = row.attrib.pop('origid', None)
                if origid is not None:
                    attrs = row.find('attributes')
                    if attrs is None:
                        attrs = ET.SubElement(row,'attributes')
                    ET.SubElement(attrs,'attribute',name='origid',**{'class':'java.lang.String'}).text = origid
            ET.indent(net)
            ET.ElementTree(net).write(network,encoding='utf-8')
            tree = _xml(service/'lanes.xml'); ET.indent(tree)
            ET.ElementTree(tree).write(lanes,encoding='utf-8')
            _, proof = review(SOURCE/'network.xml',SOURCE/'lanes.xml',network,lanes,
                OD/'perimeter.geojson',SOURCE/'map.osm',OD/'access.json',service)
            self.assertNotEqual(proof['effective_sha256'],self.proof['effective_sha256'])
            self.assertEqual(proof['semantic_signatures'],self.proof['semantic_signatures'])
            self.assertEqual(proof['transformation_identity'],self.proof['transformation_identity'])

    def test_capacity_length_and_movements_remain_rejected(self):
        for field in ('length','capacity'):
            with self.subTest(field=field):
                self.checked_mutation('network', lambda root: root.find("links/link[@id='osm_384762167_1_forward']").set(field,'999'))
        self.checked_mutation('lanes', lambda root: root.find("lanesToLinkAssignment[@linkIdRef='osm_384762167_1_forward']/lane/capacity").set('vehiclesPerHour','999'))
        self.checked_mutation('lanes', lambda root: root.find("lanesToLinkAssignment[@linkIdRef='osm_384762167_1_forward']/lane/leadsTo/toLink").set('refId','osm_384762167_1_forward'))

    def test_final_guard_still_rejects_endpoint_changes_after_review(self):
        with tempfile.TemporaryDirectory(dir=self.folder) as temp:
            from simz1_gateway_od import _xml
            lane_path = self.directory/'inputs/transit-weekday/lanes.xml'
            root = _xml(lane_path)
            root.find("lanesToLinkAssignment[@linkIdRef='osm_384762167_1_forward']/lane[@id='osm_384762167_1_forward.lane.0']/startsAt").set('meterFromLinkEnd','3.0')
            target = Path(temp)/'lanes.xml'; ET.ElementTree(root).write(target, encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'Native activity endpoint changed'):
                check_effective_network(self.model,self.directory/'inputs/transit-weekday/network.xml',target)

    def test_both_preflights_reach_identical_effective_model_before_massive_iteration(self):
        from simz1_balanced_launch import check as balanced
        from simz1_experiment_preflight import check as experiment
        class StopBeforeMassiveIterator(RuntimeError):
            pass
        captured = []
        def stop(model, *args, **kwargs):
            captured.append(copy.deepcopy(model.summary))
            raise StopBeforeMassiveIterator()
        options = dict(transit_service=PUBLIC,transit_service_date='2026-10-23',accept_transit_route_assumptions=True)
        with patch.object(generator,'gateway_people',side_effect=stop), \
                patch.object(subprocess,'Popen',side_effect=AssertionError('No child')):
            with self.assertRaises(StopBeforeMassiveIterator):
                balanced(CONFIG,CATALOG,180000,OD/'perimeter.geojson',OD/'access.json',OD/'mix.json',SEED,**options)
            with self.assertRaises(StopBeforeMassiveIterator):
                experiment(CONFIG,CATALOG,180000,180000,'lane-length-access-v1','strict-receiver-v1',
                    freight_service=FREIGHT,freight_service_date='2026-10-23',whole_vehicle_reservation=True,
                    qsim_threads=1,destination_policy='lane-length-destinations-v1',od_mode='balanced-gateway-v1',
                    zone_boundary=OD/'perimeter.geojson',od_access_catalog=OD/'access.json',od_mix_file=OD/'mix.json',**options)
        self.assertEqual(len(captured),2)
        self.assertEqual(captured[0],self.model.summary)
        self.assertEqual(captured[1],self.model.summary)

    def test_17478998_sequence_is_rejected_and_private_routes_are_checked(self):
        contract = SequenceContract()
        from simz1_sequence_contract import load_contract
        restriction = next(r for r in load_contract()['restrictions'] if r['relation_id']=='17478998')
        for path in restriction['sequences']:
            with self.assertRaises(ValueError):
                contract.validate(path)
        for record in self.records.values():
            contract.validate(record['route_link_ids'])

    def test_sources_receipts_historical_evidence_and_access_catalog_unchanged(self):
        self.assertEqual(self.hashes,{p:sha256(p) for p in self.hashes})
        self.assertEqual(sha256(self.directory/'inputs/od-access-catalog.json'),sha256(OD/'access.json'))
        self.assertEqual(self.proof['source_sha256']['lanes'],sha256(SOURCE/'lanes.xml'))
        self.assertEqual(self.manifest['source_lane_configuration_validation']['status'],'valid')
        self.assertEqual(self.manifest['lane_configuration_validation']['status'],'valid')


class NonBalancedInputCompatibilityTests(unittest.TestCase):
    def test_disabled_null_lane_input_retains_existing_network_preparation(self):
        with tempfile.TemporaryDirectory(prefix='simz1-null-lanes-') as temp:
            folder = Path(temp)
            # Historical network mode supports disabled lanes. The reviewed
            # balanced source correctly rejects removal of its OSM controls.
            source = ROOT/'scenarios/zona1'
            root = ET.parse(source/'config-simz1.xml').getroot()
            for module in root.findall('module'):
                for param in module.findall('param'):
                    value = param.get('value', '')
                    if value and (source/value).is_file():
                        param.set('value',str((source/value).resolve()))
            root.find("module[@name='network']/param[@name='laneDefinitionsFile']").set('value','null')
            for name in ('signalsystems','signalgroups','signalcontrol'):
                root.find(f"module[@name='signalsystems']/param[@name='{name}']").set('value','null')
            config = folder/'config.xml'; ET.ElementTree(root).write(config,encoding='utf-8')
            with redirect_stdout(io.StringIO()), patch.object(subprocess,'Popen',side_effect=AssertionError('No child')):
                generator.generar(config,folder/'one-person',SEED,agents=1,agent_catalog=CATALOG,
                    corridor_policy='redistribute',origin_policy='uniform-nodes-v1',
                    destination_policy='lane-length-destinations-v1',use_lanes=False,signals=False)
            manifest = json.loads((folder/'one-person/run-manifest.json').read_text())
            self.assertEqual(manifest['status'],'prepared')
            self.assertEqual(manifest['validation']['status'],'pending')


if __name__ == '__main__':
    unittest.main()
