"""Fail-closed configuration checks; no scenario generation or QSim execution."""
import unittest
import xml.etree.ElementTree as ET

from simz1_config_validation import ConfigurationError, validate_configuration


def config(enabled='false', duration='1800'):
    root = ET.Element('config')
    module = ET.SubElement(root, 'module', name='simz1IncidentConsequences')
    ET.SubElement(module, 'param', name='enabled', value=enabled)
    ET.SubElement(module, 'param', name='durationSeconds', value=duration)
    return root


class IncidentConfigurationTests(unittest.TestCase):
    def test_missing_or_disabled_has_no_physics_and_does_not_rewrite_xml(self):
        for root in (ET.Element('config'), config()):
            before = ET.tostring(root)
            result = validate_configuration(root)['incident_consequences']
            self.assertFalse(result['requested_enabled'])
            self.assertFalse(result['installed'])
            self.assertEqual(result['physics_effect'], 'none')
            self.assertEqual(result['duration_seconds'], 1800)
            self.assertEqual(ET.tostring(root), before)

    def test_enable_rejected_even_with_strict_lanes_and_four_threads(self):
        root = config('true')
        qsim = ET.SubElement(root, 'module', name='qsim')
        for name, value in [('useLanes', 'true'), ('numberOfThreads', '4'), ('removeStuckVehicles', 'false')]:
            ET.SubElement(qsim, 'param', name=name, value=value)
        network = ET.SubElement(root, 'module', name='network')
        ET.SubElement(network, 'param', name='laneDefinitionsFile', value='lanes.xml')
        admission = ET.SubElement(root, 'module', name='simz1Admission')
        ET.SubElement(admission, 'param', name='storagePolicy', value='strict-receiver-v1')
        with self.assertRaisesRegex(ConfigurationError, 'INCIDENT_CONSEQUENCES_UNAVAILABLE'):
            validate_configuration(root)
        self.assertEqual(root.find("module/param[@name='enabled']").get('value'), 'true')

    def test_boolean_duration_and_parameters_are_not_repaired(self):
        for enabled in ('True', '1', '', 'false '):
            with self.subTest(enabled=enabled), self.assertRaises(ConfigurationError):
                validate_configuration(config(enabled))
        for duration in ('900', '1800.0', '1799.999999', '1800.000001', '-1800', 'NaN', 'inf', 'abc'):
            with self.subTest(duration=duration), self.assertRaises(ConfigurationError):
                validate_configuration(config(duration=duration))
        root = config()
        ET.SubElement(root.find('module'), 'param', name='enabled', value='false')
        with self.assertRaisesRegex(ConfigurationError, 'duplicados'):
            validate_configuration(root)
        root = config()
        ET.SubElement(root.find('module'), 'param', name='enable', value='true')
        with self.assertRaisesRegex(ConfigurationError, 'desconocidos'):
            validate_configuration(root)
        root = config()
        root.append(config().find('module'))
        with self.assertRaisesRegex(ConfigurationError, 'duplicado'):
            validate_configuration(root)

    def test_legacy_incidents_flag_does_not_enable_lane_consequences(self):
        for enabled in ('true', 'false'):
            root = config()
            legacy = ET.SubElement(root, 'module', name='zona1Diagnostics')
            ET.SubElement(legacy, 'param', name='incidentsEnabled', value=enabled)
            result = validate_configuration(root)
            self.assertEqual(result['incidents_enabled'], enabled == 'true')
            self.assertFalse(result['incident_consequences']['installed'])


if __name__ == '__main__':
    unittest.main()
