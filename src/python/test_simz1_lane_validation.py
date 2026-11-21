"""Prompt 3 structural tests; no simulated traffic or mass demand is launched."""
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from generate_montecarlo_z1 import generar, SCENARIO
from simz1_config_validation import ConfigurationError
from simz1_lane_validation import audit_configuration, queue_storage
from simz1_run import load_manifest, sha256


class LaneInputTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.folder = Path(self.temporary.name)/'lane model with spaces'
        self.folder.mkdir()
        (self.folder/'network.xml').write_text('''<network><nodes>
          <node id="a" x="0" y="0"/><node id="b" x="6" y="0"/>
          <node id="c" x="12" y="6"/><node id="d" x="12" y="-6"/>
          </nodes><links capperiod="01:00:00" effectivecellsize="7.5">
          <link id="in" from="a" to="b" length="6" permlanes="2" capacity="4000" freespeed="10" modes="car"/>
          <link id="left" from="b" to="c" length="9" permlanes="1" capacity="2000" freespeed="10" modes="car"/>
          <link id="right" from="b" to="d" length="9" permlanes="1" capacity="2000" freespeed="10" modes="car"/>
          <link id="return" from="b" to="a" length="6" permlanes="1" capacity="2000" freespeed="10" modes="car"/>
          </links></network>''', encoding='utf-8')
        self.lanes = ET.Element('laneDefinitions')
        assignment = ET.SubElement(self.lanes, 'lanesToLinkAssignment', linkIdRef='in')
        for ident in ('in.0', 'in.1', 'in.original'):
            e = ET.SubElement(assignment, 'lane', id=ident)
            leads = ET.SubElement(e, 'leadsTo')
            original = ident == 'in.original'
            for target in (('in.0', 'in.1') if original else ('left', 'right', 'return')):
                ET.SubElement(leads, 'toLane' if original else 'toLink', refId=target)
            ET.SubElement(e, 'representedLanes', number='2' if original else '1')
            ET.SubElement(e, 'capacity', vehiclesPerHour='4000' if original else '2000')
            ET.SubElement(e, 'startsAt', meterFromLinkEnd='6' if original else '4.8')
            ET.SubElement(e, 'alignment').text = '0'
        ET.ElementTree(self.lanes).write(self.folder/'lanes.xml')
        (self.folder/'signals.xml').write_text('''<signalSystems><signalSystem id="s"><signals>
          <signal id="s1" linkIdRef="in"><lane refId="in.0"/><lane refId="in.1"/></signal>
          </signals></signalSystem></signalSystems>''', encoding='utf-8')
        (self.folder/'config.xml').write_text('''<config>
          <module name="network"><param name="inputNetworkFile" value="network.xml"/>
          <param name="laneDefinitionsFile" value="lanes.xml"/></module>
          <module name="qsim"><param name="useLanes" value="true"/></module>
          <module name="signalsystems"><param name="useSignalsystems" value="true"/>
          <param name="signalsystems" value="signals.xml"/></module></config>''', encoding='utf-8')
        self.config = self.folder/'config.xml'

    def tearDown(self):
        self.temporary.cleanup()

    def test_two_lanes_preserve_all_turns_length_flow_but_change_queue_discretization(self):
        report = audit_configuration(self.config)
        self.assertEqual(report['counts']['assignments'], 1)
        self.assertEqual(report['counts']['all_lane_definitions'], 3)
        metrics = report['baseline_queue_metrics']
        self.assertEqual(metrics['terminal_queues'], 2)
        self.assertEqual(metrics['uturn_terminal_movements'], 2)
        self.assertAlmostEqual(metrics['standard_geometric_pcu'], metrics['detailed_geometric_pcu'])
        self.assertGreater(metrics['detailed_threshold_pcu'], metrics['standard_threshold_pcu'])
        self.assertGreater(metrics['detailed_unit_pcu_admissions'], metrics['standard_unit_pcu_admissions'])
        self.assertFalse(report['physical_stability_proven'])

    def test_each_structural_failure_is_rejected_with_evidence(self):
        baseline = ET.tostring(self.lanes)
        cases = [
            (".//lane[@id='in.0']/leadsTo/toLink", 'refId', 'unknown', 'toLink desconectado'),
            (".//lane[@id='in.original']/leadsTo/toLane", 'refId', 'missing', 'toLane colgante'),
            (".//lane[@id='in.0']/capacity", 'vehiclesPerHour', '9000', 'capacidad de flujo'),
            (".//lane[@id='in.0']/representedLanes", 'number', '3', 'representados terminales'),
            (".//lane[@id='in.0']/startsAt", 'meterFromLinkEnd', '9', 'longitudes efectivas'),
            (".//lane[@id='in.original']/startsAt", 'meterFromLinkEnd', '5', 'origen de cola'),
        ]
        for selector, attribute, value, message in cases:
            root = ET.fromstring(baseline)
            root.find(selector).set(attribute, value)
            ET.ElementTree(root).write(self.folder/'lanes.xml')
            with self.subTest(message=message), self.assertRaisesRegex(ConfigurationError, message):
                audit_configuration(self.config)
        root = ET.fromstring(baseline)
        leads = root.find(".//lane[@id='in.0']/leadsTo")
        leads.remove(leads.find("toLink[@refId='return']"))
        ET.ElementTree(root).write(self.folder/'lanes.xml')
        with self.assertRaisesRegex(ConfigurationError, 'movimientos car no alcanzables'):
            audit_configuration(self.config)

    def test_signal_references_and_explicit_disabled_lane_adaptation(self):
        root = ET.parse(self.config)
        root.find("module[@name='qsim']/param").set('value', 'false')
        root.write(self.config)
        with self.assertRaisesRegex(ConfigurationError, 'useLanes=false'):
            audit_configuration(self.config)
        report = audit_configuration(self.config, allow_signal_lane_stripping=True)
        self.assertEqual(report['counts']['planned_signal_lane_reference_removals'], 2)
        (self.folder/'signals.xml').write_text('''<signalSystems><signalSystem id="s"><signals>
          <signal id="s1" linkIdRef="in"><lane refId="foreign.lane"/></signal>
          </signals></signalSystem></signalSystems>''')
        with self.assertRaisesRegex(ConfigurationError, 'cola terminal inexistente'):
            audit_configuration(self.config, allow_signal_lane_stripping=True)

    def test_missing_and_duplicate_references_have_configuration_errors(self):
        baseline = ET.tostring(self.lanes)
        for duplicate in (False, True):
            root = ET.fromstring(baseline)
            leads = root.find(".//lane[@id='in.0']/leadsTo")
            if duplicate:
                ET.SubElement(leads, 'toLink', refId='left')
            else:
                leads[0].attrib.pop('refId')
            ET.ElementTree(root).write(self.folder/'lanes.xml')
            with self.subTest(duplicate=duplicate), self.assertRaisesRegex(ConfigurationError, 'referencia ausente o duplicada'):
                audit_configuration(self.config)
        ET.ElementTree(ET.fromstring(baseline)).write(self.folder/'lanes.xml')
        root = ET.parse(self.folder/'signals.xml')
        root.find('.//lane').attrib.pop('refId')
        root.write(self.folder/'signals.xml')
        with self.assertRaisesRegex(ConfigurationError, 'referencia ausente o duplicada'):
            audit_configuration(self.config)

    def test_qsim_storage_formula_does_not_treat_cell_size_as_hard_minimum_length(self):
        result = queue_storage(1.2, 2, 4000, 10, 7.5, 1, 1, 1, 'queue')
        self.assertAlmostEqual(result['geometric_pcu'], .32)
        self.assertAlmostEqual(result['threshold_pcu'], 4000/3600)
        self.assertEqual(result['unit_pcu_admissions'], 2)
        self.assertTrue(result['enlarged'])

    def test_storage_screening_uses_active_queues_and_serialized_zero_timeout(self):
        root = ET.parse(self.config)
        qsim = root.find("module[@name='qsim']")
        ET.SubElement(qsim, 'param', name='stuckTime', value='00:00:00.0')
        root.write(self.config)
        report = audit_configuration(self.config)['storage_screening']
        self.assertEqual(report['stuck_time_seconds'], 0)
        self.assertEqual(report['counts']['queues_screened'], 6)
        self.assertEqual(report['examples'][0]['role'], 'receiving')
        qsim.find("param[@name='useLanes']").set('value', 'false')
        root.write(self.config)
        report = audit_configuration(self.config, allow_signal_lane_stripping=True)['storage_screening']
        self.assertEqual(report['counts']['queues_screened'], 4)
        self.assertTrue(all(row['role'] == 'undivided' for row in report['examples']))

    def test_matsim_serialized_time_step_matches_numeric_seconds(self):
        root = ET.parse(self.config)
        parameter = ET.SubElement(root.find("module[@name='qsim']"), 'param', name='timeStepSize')
        for numeric, serialized in [('1', '00:00:01'), ('0.5', '00:00:00.5')]:
            parameter.set('value', numeric)
            root.write(self.config)
            before = audit_configuration(self.config)
            # Exact representation emitted by MATSim 15 output_config.xml in
            # the first real Prompt 3 run (1s), plus fractional serialization.
            parameter.set('value', serialized)
            root.write(self.config)
            after = audit_configuration(self.config)
            self.assertEqual(before['baseline_parameters'], after['baseline_parameters'])
            self.assertEqual(before['baseline_queue_metrics'], after['baseline_queue_metrics'])
        for invalid in ('00:01', '00:00:NaN', '0'):
            parameter.set('value', invalid)
            root.write(self.config)
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ConfigurationError, 'timeStepSize'):
                audit_configuration(self.config)

    def test_generator_rejects_broken_lane_input_before_writing_run(self):
        self.lanes.find(".//lane[@id='in.original']/leadsTo/toLane").set('refId', 'not a lane')
        ET.ElementTree(self.lanes).write(self.folder/'lanes.xml')
        target = self.folder/'rejected generation'
        before = sha256(self.folder/'lanes.xml')
        with self.assertRaisesRegex(ConfigurationError, 'toLane colgante'):
            generar(self.config, target, 7, agents=1, corridor_policy='redistribute')
        self.assertFalse(target.exists())
        self.assertEqual(sha256(self.folder/'lanes.xml'), before)

    def test_actual_snapshot_counts_are_observations_not_universal_invariants(self):
        report = audit_configuration(SCENARIO/'config-simz1.xml')
        self.assertEqual(report['counts']['assignments'], 6148)
        self.assertEqual(report['counts']['links_shorter_than_7_5m'], 2446)
        self.assertEqual(report['baseline_queue_metrics']['terminal_queues'], 7468)
        # The unrelated four-link fixture also passed: no snapshot node/link count is enforced.
        self.assertEqual(audit_configuration(self.config)['counts']['network_links'], 4)

    def test_generator_records_both_lane_choices_and_preserves_source(self):
        before = {name: sha256(SCENARIO/name) for name in ('network.xml', 'lanes.xml', 'signalSystems.xml')}
        plans = []
        for enabled in (False, True):
            destination = self.folder/f'generated lanes {enabled}'
            generar(SCENARIO/'config-simz1.xml', destination, 20261015, agents=1,
                    corridor_policy='redistribute', use_lanes=enabled, within_day_routing=False)
            state = load_manifest(destination)
            audit = state['lane_configuration_validation']
            self.assertEqual(audit['use_lanes'], enabled)
            self.assertEqual(audit['selection_source'], 'explicit CLI')
            self.assertEqual(audit['counts']['signal_lane_references'], 484 if enabled else 0)
            self.assertEqual(audit['signatures']['network'], audit_configuration(SCENARIO/'config-simz1.xml')['signatures']['network'])
            plans.append(sha256(destination/'plans.xml'))
        self.assertEqual(plans[0], plans[1])
        self.assertEqual(before, {name: sha256(SCENARIO/name) for name in before})


if __name__ == '__main__':
    unittest.main()
