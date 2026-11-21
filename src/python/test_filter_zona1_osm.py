import hashlib
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET
from filter_zona1_osm import filter_osm, validate_critical, SCENARIO, CROSSINGS


class FilterZona1Tests(unittest.TestCase):
    def test_export_and_reference_integrity(self):
        source = SCENARIO/'map.osm'
        digest = hashlib.sha256(source.read_bytes()).digest()
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)/'vehicles.osm'
            report = filter_osm(source, output)
            root = ET.parse(output).getroot()
            nodes = {n.get('id'): n for n in root.findall('node')}
            ways = {w.get('id'): w for w in root.findall('way')}
            self.assertEqual(len(report['critical_validation']['crossings']), 3)
            self.assertEqual(root.get('upload'), 'never')
            for way in ways.values():
                self.assertTrue(all(n.get('ref') in nodes for n in way.findall('nd')))
                highway = way.find("tag[@k='highway']").get('v')
                self.assertNotIn(highway, ('footway', 'steps', 'pedestrian', 'path', 'busway'))
            for relation in root.findall('relation'):
                for member in relation.findall('member'):
                    self.assertIn(member.get('ref'), nodes if member.get('type') == 'node' else ways)
            for _, nid, _ in CROSSINGS:
                self.assertEqual(nodes[nid].find("tag[@k='highway']").get('v'), 'traffic_signals')
            # Coincident positions with a different ID do not count as an intersection.
            cross = ways[CROSSINGS[0][2]]
            cross.find("nd[@ref='333831813']").set('ref', 'duplicate_at_same_position')
            with self.assertRaisesRegex(ValueError, 'Unshared node'):
                validate_critical(nodes, ways)
        self.assertEqual(hashlib.sha256(source.read_bytes()).digest(), digest)

    def test_missing_signal_or_avenue_fails_before_output(self):
        for mutation in ('signal', 'avenue'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as folder:
                root = ET.parse(SCENARIO/'map.osm').getroot()
                if mutation == 'signal':
                    root.find("node[@id='333831813']/tag[@k='highway']").set('v', 'crossing')
                else:
                    root.remove(root.find("way[@id='30279769']"))
                source, output = Path(folder)/'input.osm', Path(folder)/'output.osm'
                ET.ElementTree(root).write(source)
                with self.assertRaises(ValueError): filter_osm(source, output)
                self.assertFalse(output.exists())

    def test_original_cannot_be_overwritten(self):
        with self.assertRaisesRegex(ValueError, 'differ'):
            filter_osm(SCENARIO/'map.osm', SCENARIO/'map.osm')


if __name__ == '__main__': unittest.main()
