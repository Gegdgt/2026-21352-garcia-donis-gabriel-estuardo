"""Bus-only policy regression, native-shaped XML integration; no MATSim execution."""
from contextlib import ExitStack
import copy
import gzip
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from simz1_priority_audit import PriorityAudit, export_selected
from simz1_priority_context import build_bus_context
from simz1_priority_classification import set_attribute
from simz1_run import artifact, atomic_json, checked_path, parameters, sha256
from simz1_transit_events import verified_transit_contract
import test_simz1_transit_events as base
import revalidar_simz1 as repair

PROJECT = Path(__file__).resolve().parents[1]


class PriorityTransitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        self.fixture = base.TransitEventsTest()
        self.manifest, _, self.links = self.fixture.fixture(self.directory)
        self.network = ET.parse(self.directory/'network.xml').getroot()
        nodes = ET.SubElement(self.network, 'nodes')
        for key, x, y in [('a', 0, 0), ('b', 10, 0), ('c', 10, 10)]:
            ET.SubElement(nodes, 'node', id=key, x=str(x), y=str(y))
        set_attribute(self.network.find('./links/link[@id="ab"]'), 'osm:name', 'Calle de prueba')
        set_attribute(self.network.find('./links/link[@id="road"]'), 'simz1:priorityRole', 'avenue')
        self.config = ET.parse(self.directory/'config-simz1.xml').getroot()
        module = ET.SubElement(self.config, 'module', name='zona1Priority')
        for key, value in [('enabled', 'true'), ('classification', 'osm-hierarchy'), ('stopSeconds', '5.0'),
                           ('conflicts', 'geometric'), ('maxYieldSeconds', '30.0')]:
            ET.SubElement(module, 'param', name=key, value=value)
        self.publish_inputs()
        self.contract = verified_transit_contract(self.directory, self.manifest, self.effective,
                                                 checked_path, {'pt_real_road_person'}, self.links)

    def publish_inputs(self):
        ET.ElementTree(self.network).write(self.directory/'network.xml')
        with gzip.open(self.directory/'output/output_network.xml.gz', 'wb') as stream:
            stream.write(ET.tostring(self.network))
        for path in ('config-simz1.xml', 'output/output_config.xml'):
            ET.ElementTree(self.config).write(self.directory/path)
        for key, name in [('network', 'network.xml'), ('config', 'config-simz1.xml')]:
            self.manifest['inputs'][key] = artifact(self.directory, self.directory/name)
        self.effective = parameters(self.directory/'output/output_config.xml')

    def context(self):
        return build_bus_context(self.directory, self.manifest, self.effective, self.contract)

    def policy(self, link='road', modern=False):
        row = dict(self.context()['expected'][('b', link)], type='simz1PriorityPolicy', time='0')
        if modern:
            row['policyCoverage'] = 'car-bus-v2'
        return row

    @staticmethod
    def decision(action='HEAD', time=2):
        row = dict(type='simz1Priority', time=str(time), node='b', link='ab', nextLink='bc', lane='ab',
                   person='native-no-prefix', vehicle='bus-a', visit='6', role='street',
                   classificationSource='osm_name_assumption', headTime='2.0', readyTime='7.0',
                   stopSeconds='5.0', conflictPolicy='geometric', control='stop', appliedStopSeconds='5.0',
                   maxYieldSeconds='30.0', action=action,
                   reason={'HEAD':'queue_head', 'GO':'permission_not_crossing', 'CROSS':'executed', 'WAIT':'priority_stop'}[action])
        return row

    def events(self, modern=False):
        rows = [ET.Element('event', self.policy(modern=modern))]
        if modern:
            for (node, link), policy in self.context()['expected'].items():
                if link != 'road':
                    rows.append(ET.Element('event', dict(policy, type='simz1PriorityPolicy', time='0', policyCoverage='car-bus-v2')))
        original = self.fixture.events()
        for raw in original:
            row = copy.deepcopy(raw)
            # First bus traverses ab -> bc after the five-second stop.
            if float(row.get('time')) in (3, 4) and (row.get('vehicle') == 'bus-a' or row.get('person') == 'native-no-prefix'):
                row.set('time', str(float(row.get('time'))+4))
            rows.append(row)
            if row.get('type') == 'vehicle enters traffic' and row.get('time') == '2':
                rows.extend(ET.Element('event', self.decision(action, t))
                            for action, t in [('HEAD', 2), ('WAIT', 3), ('GO', 7)])
            if row.get('type') == 'entered link' and row.get('time') == '7.0':
                rows.append(ET.Element('event', self.decision('CROSS', 7)))
        # Stable ordering preserves GO -> native leave/enter -> CROSS at equal time.
        rows.sort(key=lambda row: float(row.get('time')))
        return rows

    def audit(self):
        audit = PriorityAudit(legacy_bus_context=self.context())
        audit.consume(self.policy())
        return audit

    def test_event_only_audit_reproduces_missing_bus_policy_in_old_stream(self):
        audit = PriorityAudit()
        audit.consume(self.policy())
        with self.assertRaisesRegex(ValueError, 'politica no registrada'):
            audit.consume(self.decision())

    def test_verified_context_accepts_exact_head_without_changing_event(self):
        row = self.decision()
        before = dict(row)
        audit = self.audit()
        audit.consume(row, verified_transit=True)
        self.assertEqual(row, before)
        summary = audit.summary()
        self.assertEqual(summary['reconstructed_bus_policy_links'], 1)
        self.assertEqual(summary['native_policy_links'], 1)
        self.assertEqual(summary['executed_crossings'], 0)
        self.assertEqual(summary['pending_heads_at_cut'], 1)
        self.assertFalse(summary['policy_reconstruction']['events_modified'])

    def test_native_new_policy_needs_no_reconstruction(self):
        audit = PriorityAudit(legacy_bus_context=self.context())
        audit.consume(self.policy(modern=True))
        audit.consume(self.policy('ab', modern=True))
        audit.consume(self.decision(), verified_transit=True)
        self.assertEqual(audit.summary()['reconstructed_bus_policy_links'], 0)
        self.assertEqual(audit.summary()['native_policy_links'], 2)

    def test_new_emitter_missing_bus_policy_is_rejected_not_recovered(self):
        audit = PriorityAudit(legacy_bus_context=self.context())
        audit.consume(self.policy(modern=True))
        with self.assertRaisesRegex(ValueError, 'car-bus-v2 omitio'):
            audit.consume(self.decision(), verified_transit=True)

    def test_bus_prefix_alone_or_unverified_actor_cannot_recover(self):
        for vehicle, verified in [('ptbus_unregistered', True), ('bus-a', False)]:
            with self.subTest(vehicle=vehicle, verified=verified):
                audit = self.audit()
                with self.assertRaisesRegex(ValueError, 'politica no registrada'):
                    audit.consume(dict(self.decision(), vehicle=vehicle), verified_transit=verified)

    def test_car_and_shared_mode_missing_policy_stay_rejected(self):
        for modes in ('car', 'car,bus'):
            with self.subTest(modes=modes):
                self.network.find('./links/link[@id="ab"]').set('modes', modes)
                self.publish_inputs()
                audit = self.audit()
                with self.assertRaisesRegex(ValueError, 'politica no registrada'):
                    audit.consume(self.decision(), verified_transit=True)

    def test_wrong_node_does_not_select_a_policy_from_other_intersection(self):
        audit = self.audit()
        with self.assertRaisesRegex(ValueError, 'politica no registrada'):
            audit.consume(dict(self.decision(), node='wrong'), verified_transit=True)

    def test_disabled_osm_signal_and_unmixed_intersection_remain_ineligible(self):
        mutations = ('disabled', 'osm:highway', 'highway', 'unmixed')
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                net, config = copy.deepcopy(self.network), copy.deepcopy(self.config)
                if mutation == 'disabled':
                    self.config.find('./module[@name="zona1Priority"]/param[@name="enabled"]').set('value', 'false')
                elif mutation == 'unmixed':
                    set_attribute(self.network.find('./links/link[@id="road"]'), 'simz1:priorityRole', 'street')
                else:
                    set_attribute(self.network.find('./nodes/node[@id="b"]'), mutation, 'traffic_signals')
                self.publish_inputs()
                audit = self.audit()
                with self.assertRaisesRegex(ValueError, 'fuera de cruce elegible'):
                    audit.consume(self.decision(), verified_transit=True)
                self.network, self.config = net, config
                self.publish_inputs()

    def test_native_signalled_junction_remains_ineligible(self):
        self.config.find('./module[@name="signalsystems"]/param').set('value', 'true')
        self.publish_inputs()
        root = ET.fromstring('<signalSystems><signalSystem><signals><signal><linkId refId="road"/></signal></signals></signalSystem></signalSystems>')
        with gzip.open(self.directory/'output/output_signal_systems_v2.0.xml.gz', 'wb') as stream:
            stream.write(ET.tostring(root))
        audit = self.audit()
        with self.assertRaisesRegex(ValueError, 'fuera de cruce elegible'):
            audit.consume(self.decision(), verified_transit=True)

    def test_emitted_contradictory_policy_is_not_replaced(self):
        for field, bad in [('eligible','false'), ('role','avenue'), ('control','yield'),
                           ('classificationSource','invented'), ('stopSeconds','0'),
                           ('maxYieldSeconds','900'), ('controlled','true')]:
            with self.subTest(field=field):
                audit = self.audit()
                row = dict(self.policy('ab'), **{field:bad})
                with self.assertRaisesRegex(ValueError, 'entradas verificadas'):
                    audit.consume(row)

    def test_recovered_decision_cannot_change_role_clock_stop_or_control(self):
        for field, bad in [('role','avenue'), ('classificationSource','invented'), ('stopSeconds','0'),
                           ('control','yield'), ('appliedStopSeconds','0'), ('readyTime','2.0'),
                           ('maxYieldSeconds','900')]:
            with self.subTest(field=field):
                audit = self.audit()
                with self.assertRaises(ValueError):
                    audit.consume(dict(self.decision(), **{field:bad}), verified_transit=True)

    def test_early_go_and_missing_head_or_cross_still_fail(self):
        audit = self.audit()
        audit.consume(self.decision(), verified_transit=True)
        with self.assertRaisesRegex(ValueError, 'parada minima omitida'):
            audit.consume(self.decision('GO', 6), verified_transit=True)
        for missing in ('HEAD', 'CROSS'):
            with self.subTest(missing=missing):
                audit = self.audit()
                if missing != 'HEAD':
                    audit.consume(self.decision(), verified_transit=True)
                    audit.consume(self.decision('GO',7), verified_transit=True)
                with self.assertRaisesRegex(ValueError, 'sin cabecera|sin CROSS'):
                    for kind, link in [('left link','ab'), ('entered link','bc')]:
                        audit.consume(dict(type=kind,time='7',vehicle='bus-a',link=link), verified_transit=True)
                    audit.summary()

    def test_changed_input_hash_and_output_priority_attributes_are_rejected(self):
        original = (self.directory/'network.xml').read_bytes()
        with (self.directory/'network.xml').open('ab') as stream:
            stream.write(b'\n')
        with self.assertRaisesRegex(ValueError, 'Hash'):
            self.context()
        (self.directory/'network.xml').write_bytes(original)
        mutated = copy.deepcopy(self.network)
        set_attribute(mutated.find('./links/link[@id="ab"]'), 'simz1:priorityControl','yield')
        with gzip.open(self.directory/'output/output_network.xml.gz', 'wb') as stream:
            stream.write(ET.tostring(mutated))
        with self.assertRaisesRegex(ValueError, 'priority attributes/topology'):
            self.context()

    def test_missing_effective_settings_are_not_guessed(self):
        self.effective.pop('zona1Priority.stopSeconds')
        with self.assertRaisesRegex(ValueError, 'incomplete effective'):
            self.context()

    def test_xml_output_loop_validates_bus_crossing_and_keeps_population_N(self):
        self.fixture.validate(self.directory, self.manifest, self.events())
        result = self.manifest['results']['0']
        self.assertEqual(result['counts']['observed_persons'], 1)
        self.assertEqual(result['counts']['physical_transitions'], 3)
        self.assertEqual(result['public_transport_events']['public_transport_vehicles_configured'],2)
        self.assertEqual(result['priority_events']['executed_crossings'],1)
        self.assertEqual(result['priority_events']['reconstructed_bus_policy_links'],3)
        self.assertEqual(result['priority_events']['pending_heads_at_cut'],0)
        self.assertEqual(result['priority_events']['minimum_street_head_to_cross_seconds'],5)

    def test_xml_output_loop_with_new_policies_has_zero_reconstructed_links(self):
        self.fixture.validate(self.directory, self.manifest, self.events(modern=True))
        self.assertEqual(self.manifest['results']['0']['priority_events']['reconstructed_bus_policy_links'],0)

    def test_priority_export_uses_the_same_verified_context(self):
        self.fixture.validate(self.directory, self.manifest, self.events())
        before = {p: p.read_bytes() for p in (self.directory/'output').iterdir() if p.is_file()}
        summary = export_selected(dict(directory=self.directory, manifest=self.manifest, iteration=0,
            events=self.directory/'output/output_events.xml.gz', network=self.directory/'output/output_network.xml.gz'),
            self.directory/'priority.json')
        self.assertEqual(summary['executed_crossings'],1)
        catalogue = json.loads((self.directory/'priority.json').read_text())['classification_table']
        self.assertEqual(next(row for row in catalogue if row['link']=='ab')['audit_policy_source'],'verified_run_inputs')
        self.assertTrue(all(p.read_bytes()==data for p,data in before.items()))

    def test_native_factory_instruments_the_same_modes_as_decisions(self):
        factory = (PROJECT/'src/main/java/org/matsim/core/mobsim/qsim/qnetsimengine/Zona1PriorityNetworkFactory.java').read_text()
        self.assertIn('if(UnsignalizedPriority.roadLink(link))',factory)
        self.assertNotIn('if(link.getAllowedModes().contains("car"))',factory)
        self.assertIn('values.put("policyCoverage","car-bus-v2")',factory)

    def test_reported_L12_event_matches_bundled_network_policy(self):
        """Same IDs/event from the user's log; network comes from bundled source, not his output."""
        from simz1_weekday_transit import prepared_network
        bundle = json.loads((PROJECT/'scenarios/zona1/transit/weekday-v2/route-bundle.json').read_text())
        self.network = prepared_network(PROJECT/'scenarios/zona1/network.xml',bundle)
        self.publish_inputs()
        first, second = 'transit_osm_1274975825_0_forward','transit_osm_1057416031_0_forward'
        self.contract = dict(vehicle_modes={'ptbus_transmetro_L12_001':'bus'},domain_links={first,second})
        context = self.context()
        policy = context['bus_only'][first]
        self.assertEqual(policy['node'],'410439024')
        self.assertEqual((policy['role'],policy['classificationSource'],policy['eligible']),
                         ('street','osm_name_assumption','true'))
        row = dict(self.decision(),time='16361.0',node='410439024',link=first,nextLink=second,lane=first,
                   vehicle='ptbus_transmetro_L12_001',person='pt_ptbus_transmetro_L12_001_Transmetro_RigidProxy',
                   headTime='16361.0',readyTime='16366.0')
        audit = PriorityAudit(legacy_bus_context=context)
        audit.consume(row,verified_transit=True)
        self.assertEqual(audit.summary()['pending_heads_at_cut'],1)

    def test_revalidation_preserves_native_outputs_and_reports_inference(self):
        self.fixture.validate(self.directory, self.manifest, self.events())
        self.manifest.update(schema_version=1,folder=str(self.directory),status='failed',phase='validating',
            failure_phase='validating',failure_category='output_validation_error',exception_type='TypeError',
            error=repair.ERROR_TEXT,exception_traceback='simz1_transit_events.py '+repair.ERROR_TEXT,
            validation=dict(status='invalid'),returncode=0,returncode_origin='natural_exit')
        atomic_json(self.directory/'run-manifest.json',self.manifest)
        before = {p:p.read_bytes() for p in self.directory.rglob('*') if p.is_file()}
        baseline = dict(use_lanes=False,signals_enabled=False,baseline_parameters={},
                        signatures=dict(network='fixture',lanes=None,signals=None))
        with ExitStack() as stack:
            stack.enter_context(patch('simz1_run.validate_configuration',return_value={'admission_policy':'matsim15-native'}))
            stack.enter_context(patch('simz1_run.audit_configuration',side_effect=lambda *a,**k:copy.deepcopy(baseline)))
            stack.enter_context(patch('simz1_gateway_od.validated_spatial_demand',return_value=None))
            stack.enter_context(patch('simz1_signal_replay.selected_groups',return_value=[]))
            stack.enter_context(patch('subprocess.Popen',side_effect=AssertionError('unexpected simulation')))
            outcome = repair.revalidate(self.directory,apply=True)
        self.assertEqual(outcome['status'],'completed_valid_revalidated')
        self.assertEqual(outcome['results']['0']['priority_events']['reconstructed_bus_policy_links'],3)
        for path,data in before.items():
            if path.name!='run-manifest.json':
                self.assertEqual(path.read_bytes(),data)
        self.assertEqual(Path(outcome['manifest_backup']).read_bytes(),before[self.directory/'run-manifest.json'])
        self.assertFalse(outcome['matsim_executed'])


if __name__ == '__main__':
    unittest.main()
