"""Bounded preparation/preflight/serialization regressions; never starts MATSim.

The balanced N=100 case now reviews the effective service lanes and finishes
preparation. The historical endpoint-rejection evidence remains immutable.
Both use temporary directories and the unchanged fixed transit service.
Large preflight counts are guarded by an iterator sentinel and never sampled.
"""
from contextlib import redirect_stdout
import copy
import gzip
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

import generate_montecarlo_z1 as generator
from simz1_agent_types import load_catalog, sample_departures
from simz1_config_validation import ConfigurationError
from simz1_freight import is_freight
from simz1_lane_validation import audit_configuration
from simz1_od_policy import CLASS_BY_TYPE
from simz1_osm_turn_audit import load_xml
from simz1_run import checked_path, parameters, sha256
from simz1_sequence_contract import SequenceContract


ROOT = Path(__file__).resolve().parents[1]
SCENARIO = ROOT / 'scenarios/zona1'
OD = SCENARIO / 'od/balanced-gateway-v1'
SOURCE = OD / 'access-review-v2'
CONFIG = SOURCE / 'config-simz1.xml'
CATALOG = SCENARIO / 'agent-types-balanced-v1.json'
PUBLIC = SCENARIO / 'transit/weekday-v2/service-fleet-176-93-v1.json'
FREIGHT = SOURCE / 'freight/service-composition-v3.json'
SEED = 20261023


def generation_options():
    return dict(agents=100, agent_catalog=CATALOG,
                od_mode='balanced-gateway-v1', zone_boundary=OD / 'perimeter.geojson',
                od_access_catalog=OD / 'access.json', od_mix=(OD / 'mix.json').read_text(),
                od_osm=SOURCE / 'map.osm', origin_policy='lane-length-access-v1',
                destination_policy='lane-length-destinations-v1', qsim_threads=1,
                storage_policy='strict-receiver-v1', whole_vehicle_reservation=True,
                transit_service=PUBLIC, transit_service_date='2026-10-23',
                accept_transit_route_assumptions=True,
                freight_service=FREIGHT, freight_service_date='2026-10-23')


def isolated_config(folder, mutation):
    """Copy only the mutated lanes; all other effective inputs remain explicit."""
    root = ET.parse(CONFIG).getroot()
    for module in root.findall('module'):
        for param in module.findall('param'):
            value = param.get('value', '')
            if value and (SOURCE / value).is_file():
                param.set('value', str((SOURCE / value).resolve()))
    lanes = load_xml(SOURCE / 'lanes.xml')
    mutation(lanes)
    path = folder / 'lanes.xml'
    ET.ElementTree(lanes).write(path, encoding='utf-8', xml_declaration=True)
    root.find("module[@name='network']/param[@name='laneDefinitionsFile']").set('value', str(path))
    shutil.copyfile(SOURCE / 'map.osm', folder / 'map.osm')
    result = folder / 'config-simz1.xml'
    ET.ElementTree(root).write(result, encoding='utf-8', xml_declaration=True)
    return result


def restore_forbidden(lanes):
    terminal = lanes.find("lanesToLinkAssignment[@linkIdRef='osm_1272828335_0_forward']/lane[@id='osm_1272828335_0_forward.lane.0']/leadsTo")
    ET.SubElement(terminal, 'toLink', refId='osm_1272828334_0_forward')


def remove_legal(lanes):
    # Leave another exit so this tests missing legal reachability, not emptiness.
    for lane in lanes.findall('lanesToLinkAssignment/lane'):
        exits = lane.findall('leadsTo/toLink')
        if len(exits) >= 2:
            lane.find('leadsTo').remove(exits[0])
            return
    raise AssertionError('Fixture has no terminal with two exits')


class SmallFullPreparationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix='simz1-lane-policy-')
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.folder = Path(cls.temporary.name)
        cls.directory = cls.folder / 'network-prepared-6'
        cls.source_hashes = {path: sha256(path) for path in SOURCE.rglob('*') if path.is_file()}
        with redirect_stdout(io.StringIO()), patch.object(generator, 'audit_configuration', wraps=audit_configuration) as audits:
            cls.report = generator.generar(CONFIG, cls.directory, SEED, agents=6,
                agent_catalog=CATALOG, corridor_policy='redistribute',
                origin_policy='uniform-nodes-v1', destination_policy='lane-length-destinations-v1',
                qsim_threads=1, storage_policy='strict-receiver-v1', whole_vehicle_reservation=True,
                transit_service=PUBLIC, transit_service_date='2026-10-23',
                accept_transit_route_assumptions=True)
            cls.audit_calls = list(audits.call_args_list)
        cls.manifest = json.loads((cls.directory / 'run-manifest.json').read_text(encoding='utf-8'))

    def test_six_person_network_preparation_is_not_a_balanced_launch_approval(self):
        self.assertEqual(self.manifest['status'], 'prepared')
        self.assertEqual(self.manifest['validation']['status'], 'pending')
        self.assertEqual(len(self.audit_calls), 2)
        self.assertIsNone(self.audit_calls[0].kwargs.get('osm_path'))  # Reviewed source context is discovered.
        self.assertTrue(self.audit_calls[1].kwargs.get('osm_path'))
        self.assertEqual(self.manifest['counts']['private_vehicles_configured'], 6)
        self.assertEqual(self.manifest['counts']['freight_vehicles_configured'], 0)
        self.assertEqual(self.manifest['counts']['public_transport_vehicles_configured'], 269)
        self.assertNotIn('balanced_od', self.manifest)
        self.assertEqual(len(ET.parse(self.directory / 'plans.xml').getroot().findall('person')), 6)
        self.assertFalse((self.directory / 'output').exists())
        self.assertEqual(self.source_hashes, {path: sha256(path) for path in self.source_hashes})

    def test_transit_derivatives_keep_verified_policy_and_artifacts(self):
        from simz1_run import lane_policy_source
        osm = lane_policy_source(self.directory, self.manifest)
        self.assertEqual(sha256(osm), sha256(SOURCE / 'map.osm'))
        values = parameters(self.directory / 'config-simz1.xml')
        for key in ('network.inputNetworkFile', 'network.laneDefinitionsFile'):
            derived = Path(values[key])
            self.assertEqual(derived.parent, self.directory / 'inputs/transit-weekday')
            self.assertTrue(derived.is_file())
        audit = audit_configuration(self.directory / 'config-simz1.xml', osm_path=osm)
        self.assertEqual(audit['status'], 'valid')
        self.assertEqual(audit['signatures'], self.manifest['lane_configuration_validation']['signatures'])
        self.assertEqual(audit['turn_policy'], self.manifest['lane_configuration_validation']['turn_policy'])
        for record in self.manifest['inputs'].values():
            checked_path(self.directory, record)

    def test_execution_preflight_uses_copied_policy_without_starting_child(self):
        import ejecutar_simz1 as execution
        from simz1_run import lane_policy_source
        reached = []

        class StopAfterAudit(RuntimeError):
            pass

        def audited_then_stop(*args, **kwargs):
            reached.append((kwargs, audit_configuration(*args, **kwargs)))
            raise StopAfterAudit('Test stops after the real structural audit, before execution')

        before = (self.directory / 'run-manifest.json').read_bytes()
        with redirect_stdout(io.StringIO()), patch.object(execution, 'audit_configuration', side_effect=audited_then_stop), \
                patch.object(execution, 'ejecutar_con_salida_en_vivo', side_effect=AssertionError('Child must not start')) as child:
            with self.assertRaises(StopAfterAudit):
                execution.ejecutar(self.directory)
            child.assert_not_called()
        self.assertEqual(len(reached), 1)
        self.assertEqual(reached[0][0]['osm_path'], lane_policy_source(self.directory, self.manifest))
        self.assertEqual(reached[0][1]['status'], 'valid')
        self.assertEqual((self.directory / 'run-manifest.json').read_bytes(), before)
        self.assertFalse((self.directory / 'output').exists())

    def test_native_serialization_preserves_semantics_without_byte_equality(self):
        from simz1_run import lane_policy_source
        osm = lane_policy_source(self.directory, self.manifest)
        values = parameters(self.directory / 'config-simz1.xml')
        original = audit_configuration(self.directory / 'config-simz1.xml', osm_path=osm)
        with tempfile.TemporaryDirectory(dir=self.folder) as temporary:
            folder = Path(temporary)
            exports = {}
            for kind, key in (('network', 'network.inputNetworkFile'), ('lanes', 'network.laneDefinitionsFile'),
                              ('signals', 'signalsystems.signalsystems')):
                root = load_xml(values[key])
                if kind == 'network':
                    for link in root.findall('links/link'):
                        origid = link.attrib.pop('origid', None)
                        if origid is not None:
                            attrs = link.find('attributes')
                            if attrs is None:
                                attrs = ET.SubElement(link, 'attributes')
                            ET.SubElement(attrs, 'attribute', name='origid', **{'class': 'java.lang.String'}).text = origid
                exports[kind + '_path'] = folder / (kind + '.xml.gz')
                with gzip.open(exports[kind + '_path'], 'wb') as stream:
                    stream.write(ET.tostring(root, encoding='utf-8', xml_declaration=True))
                self.assertNotEqual(sha256(exports[kind + '_path']), sha256(values[key]))
            actual = audit_configuration(self.directory / 'config-simz1.xml', osm_path=osm, **exports)
            self.assertEqual(actual['signatures'], original['signatures'])
            self.assertEqual(actual['turn_policy'], original['turn_policy'])
            root = load_xml(exports['network_path'])
            root.find("links/link[@id='osm_1272828335_0_forward']").set('capacity', '9999')
            with gzip.open(exports['network_path'], 'wb') as stream:
                stream.write(ET.tostring(root))
            with self.assertRaisesRegex(ConfigurationError, 'capacidad'):
                audit_configuration(self.directory / 'config-simz1.xml', osm_path=osm, **exports)

    def test_changed_or_missing_policy_artifact_fails_closed(self):
        from simz1_run import lane_policy_source
        modified = copy.deepcopy(self.manifest)
        name = 'osm_turn_policy_source'
        self.assertIn(name, modified['inputs'])
        modified['inputs'][name]['sha256'] = '0' * 64
        with self.assertRaises(ValueError):
            lane_policy_source(self.directory, modified)
        modified = copy.deepcopy(self.manifest)
        modified['inputs'].pop(name)
        modified['inputs'].pop('od_source_osm', None)
        with self.assertRaises(ValueError):
            lane_policy_source(self.directory, modified)


class BalancedPreparationGuardTests(unittest.TestCase):
    def test_99_private_trips_use_reviewed_effective_lanes_and_finish_preparation(self):
        from simz1_balanced_od_audit import validate_manifest
        historical = ROOT / 'runtime/lane-policy-repair/integration-evidence.json'
        before = historical.read_bytes()
        with tempfile.TemporaryDirectory(prefix='simz1-balanced-integration-') as temporary:
            run = Path(temporary) / 'balanced-100'
            with redirect_stdout(io.StringIO()):
                generator.generar(SOURCE/'config-l18-local-v1.xml', run, SEED, **generation_options())
            manifest = json.loads((run / 'run-manifest.json').read_text(encoding='utf-8'))
            model, records = validate_manifest(run, manifest)
            self.assertEqual(manifest['status'], 'prepared')
            self.assertEqual(manifest['validation']['status'], 'pending')
            self.assertEqual(len(records), 99)
            self.assertEqual(model.queue_ends['osm_384762167_1_forward'], 50.44251317329641)
            self.assertEqual(manifest['source_lane_configuration_validation']['status'], 'valid')
            self.assertEqual(manifest['lane_configuration_validation']['status'], 'valid')
            self.assertFalse((run / 'output').exists())
        self.assertEqual(before, historical.read_bytes())


class PreflightPreparationParityTests(unittest.TestCase):
    def test_both_preflights_match_preparation_before_demand_iteration(self):
        from simz1_balanced_launch import check as balanced_check
        from simz1_experiment_preflight import check as experiment_check
        for mutation in (restore_forbidden, remove_legal):
            with self.subTest(mutation=mutation.__name__), tempfile.TemporaryDirectory(prefix='simz1-lane-rejection-') as temporary:
                folder = Path(temporary)
                config = isolated_config(folder, mutation)
                errors = []
                with patch.object(generator, 'gateway_people', side_effect=AssertionError('Demand iteration must not start')) as iterator, \
                        patch.object(generator, 'synthetic_people', side_effect=AssertionError('Demand iteration must not start')) as network_iterator:
                    with self.assertRaises(ConfigurationError) as rejected:
                        # Audit the same effective network/lanes before any
                        # service fingerprints or private population are needed.
                        # The positive test above exercises the full balanced
                        # preparation including all service guards.
                        generator.generar(config, folder / 'not-created', SEED,
                                          agents=1, corridor_policy='redistribute')
                    errors.append(str(rejected.exception))
                    self.assertFalse((folder / 'not-created').exists())
                    with self.assertRaises(ConfigurationError) as rejected:
                        balanced_check(config, CATALOG, 180000, OD / 'perimeter.geojson',
                                       OD / 'access.json', OD / 'mix.json', SEED)
                    errors.append(str(rejected.exception))
                    with self.assertRaises(ConfigurationError) as rejected:
                        experiment_check(config, CATALOG, 180000, 180000,
                            'lane-length-access-v1', 'strict-receiver-v1',
                            transit_service=PUBLIC, transit_service_date='2026-10-23',
                            accept_transit_route_assumptions=True,
                            freight_service=FREIGHT, freight_service_date='2026-10-23',
                            whole_vehicle_reservation=True, qsim_threads=1,
                            destination_policy='lane-length-destinations-v1',
                            od_mode='balanced-gateway-v1', zone_boundary=OD / 'perimeter.geojson',
                            od_access_catalog=OD / 'access.json', od_mix_file=OD / 'mix.json', seed=SEED)
                    errors.append(str(rejected.exception))
                    iterator.assert_not_called()
                    network_iterator.assert_not_called()
                self.assertEqual(len(set(errors)), 1, errors)


if __name__ == '__main__':
    unittest.main()
