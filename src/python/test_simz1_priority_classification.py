import csv
import tempfile
import unittest
from pathlib import Path
import xml.etree.ElementTree as ET

from simz1_priority_classification import (
    OVERRIDE_FIELDS, apply_overrides, attributes, catalogue, classify, export, set_attribute,
)


def fixture():
    root = ET.fromstring('''<network><nodes>
      <node id="w" x="-10" y="0"/><node id="s" x="0" y="-10"/>
      <node id="j" x="0" y="0"/><node id="e" x="10" y="0"/>
      </nodes><links>
      <link id="street" from="w" to="j" modes="car" capacity="900" freespeed="8"/>
      <link id="avenue" from="s" to="j" modes="car" capacity="900" freespeed="8"/>
      <link id="exit" from="j" to="e" modes="car" capacity="900" freespeed="8"/>
      </links></network>''')
    links = {link.get('id'): link for link in root.findall('./links/link')}
    nodes = {node.get('id'): node for node in root.findall('./nodes/node')}
    set_attribute(links['street'], 'osm:name', '3a Calle')
    set_attribute(links['street'], 'osm:highway', 'residential')
    set_attribute(links['avenue'], 'osm:name', 'Avenida Elena')
    set_attribute(links['avenue'], 'osm:highway', 'primary')
    return root, links, nodes


class PriorityClassificationTest(unittest.TestCase):
    def test_vertical_service_is_secondary_even_when_named_avenue(self):
        _, links, nodes = fixture()
        link = links['avenue']
        set_attribute(link, 'osm:highway', 'service')
        self.assertEqual(classify(link, nodes), ('street', 'osm_highway_service_assumption'))
        self.assertEqual(classify(link, nodes, 'osm-name-orientation')[0], 'avenue')

    def test_arterial_calle_and_unnamed_connectors_remain_priority(self):
        _, links, nodes = fixture()
        for highway in ('primary', 'secondary', 'primary_link', 'secondary_link'):
            set_attribute(links['street'], 'osm:highway', highway)
            self.assertEqual(classify(links['street'], nodes), ('avenue', 'osm_highway_major_assumption'))
            set_attribute(links['street'], 'osm:name', '')
            self.assertEqual(classify(links['street'], nodes)[0], 'avenue')

    def test_named_horizontal_avenue_and_unnamed_vertical_minor(self):
        _, links, nodes = fixture()
        set_attribute(links['street'], 'osm:name', 'Avenída del Centro')
        self.assertEqual(classify(links['street'], nodes), ('avenue', 'osm_name_assumption'))
        set_attribute(links['avenue'], 'osm:highway', 'residential')
        set_attribute(links['avenue'], 'osm:name', '')
        self.assertEqual(classify(links['avenue'], nodes), ('street', 'osm_highway_minor_assumption'))

    def test_fallback_and_explicit_preserve_verifiable_source(self):
        _, links, nodes = fixture()
        self.assertEqual(classify(links['exit'], nodes), ('street', 'orientation_approximation'))
        with self.assertRaises(ValueError):
            classify(links['exit'], nodes, 'explicit')
        set_attribute(links['exit'], 'simz1:priorityRole', 'avenue')
        self.assertEqual(classify(links['exit'], nodes, 'explicit'), ('avenue', 'network_attribute'))
        set_attribute(links['exit'], 'simz1:priorityRole', 'guess')
        with self.assertRaises(ValueError):
            classify(links['exit'], nodes)

    def test_native_signals_exclude_untagged_junction(self):
        root, _, _ = fixture()
        self.assertEqual(catalogue(root)[2]['eligible_nodes'], 1)
        with tempfile.TemporaryDirectory() as folder:
            signals = Path(folder) / 'signals.xml'
            signals.write_text('<signalSystems xmlns="urn:test"><signalSystem><signals><signal linkIdRef="avenue"/></signals></signalSystem></signalSystems>')
            links, _, summary = catalogue(root, signals)
            self.assertEqual(summary['native_signal_nodes'], 1)
            self.assertEqual(summary['eligible_nodes'], 0)
            self.assertEqual({row['effective_control'] for row in links}, {'not_applied'})

    def test_osm_signals_exclude_and_yield_has_no_stop(self):
        root, links, nodes = fixture()
        set_attribute(links['street'], 'simz1:priorityControl', 'yield')
        rows, _, _ = catalogue(root)
        street = next(row for row in rows if row['link_id'] == 'street')
        self.assertEqual((street['effective_control'], street['stop_seconds']), ('yield', 0))
        set_attribute(nodes['j'], 'osm:highway', 'traffic_signals')
        self.assertEqual(catalogue(root)[2]['eligible_nodes'], 0)
        set_attribute(nodes['j'], 'osm:highway', 'crossing')
        set_attribute(nodes['j'], 'highway', 'traffic_signals')
        self.assertEqual(catalogue(root)[2]['eligible_nodes'], 0)

    def write_table(self, folder, rows):
        path = Path(folder) / 'overrides.csv'
        with path.open('w', newline='', encoding='utf-8') as stream:
            writer = csv.DictWriter(stream, fieldnames=OVERRIDE_FIELDS)
            writer.writeheader()
            writer.writerows(rows)
        return path

    def test_override_is_directed_documented_and_preserves_physics(self):
        root, links, nodes = fixture()
        before = dict(links['avenue'].attrib)
        with tempfile.TemporaryDirectory() as folder:
            table = self.write_table(folder, [dict(link_id='avenue', to_node='j', priority_role='street',
                priority_control='yield', source='synthetic_fixture', rationale='test only; no surveyed sign')])
            self.assertEqual(apply_overrides(root, table), 1)
        self.assertEqual(classify(links['avenue'], nodes)[0], 'street')
        self.assertEqual(attributes(links['avenue'])['simz1:priorityControl'], 'yield')
        self.assertEqual(links['avenue'].attrib, before)
        self.assertNotIn('simz1:priorityRole', attributes(links['street']))

    def test_override_rejects_unknown_duplicate_wrong_node_and_priority_stop_atomically(self):
        good = dict(link_id='street', to_node='j', priority_role='street', priority_control='yield',
                    source='fixture', rationale='test')
        bads = [dict(good, link_id='absent'), dict(good, to_node='wrong'),
                dict(good, priority_role='avenue'), dict(good, priority_control='red'),
                dict(good, source=''), good]
        with tempfile.TemporaryDirectory() as folder:
            for bad in bads:
                root, links, _ = fixture()
                with self.assertRaises(ValueError):
                    apply_overrides(root, self.write_table(folder, [good, bad]))
                self.assertNotIn('simz1:priorityControl', attributes(links['street']))

    def test_catalogue_export_is_deterministic_and_retains_fallback_nodes(self):
        root, _, _ = fixture()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'network.xml'
            ET.ElementTree(root).write(path)
            first = Path(folder) / 'first'
            second = Path(folder) / 'second'
            summary = export(path, first)
            export(path, second)
            self.assertEqual(summary['orientation_fallback_nodes'], ['e'])
            for filename in ('priority-links.csv', 'priority-intersections.csv', 'classification-summary.json'):
                self.assertEqual((first / filename).read_bytes(), (second / filename).read_bytes())

    def test_importer_applies_reviewed_override_without_changing_road_physics(self):
        from prepare_simz1 import prepare
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            source = folder / 'input.osm'
            source.write_text('''<osm><node id="1" lon="-90.518" lat="14.646"/>
                <node id="2" lon="-90.518" lat="14.647"/><way id="10"><nd ref="1"/>
                <nd ref="2"/><tag k="highway" v="residential"/><tag k="name" v="Avenida Prueba"/>
                </way></osm>''', encoding='utf-8')
            original = source.read_bytes()
            table = self.write_table(folder, [dict(link_id='osm_10_0_forward', to_node='2',
                priority_role='street', priority_control='yield', source='synthetic_fixture', rationale='test only')])
            prepare(source, folder / 'base')
            report = prepare(source, folder / 'override', priority_overrides=table)
            base = ET.parse(folder / 'base/network.xml').getroot()
            changed = ET.parse(folder / 'override/network.xml').getroot()
            self.assertEqual([link.attrib for link in base.findall('./links/link')],
                             [link.attrib for link in changed.findall('./links/link')])
            link = changed.find('./links/link[@id="osm_10_0_forward"]')
            self.assertEqual(attributes(link)['simz1:priorityControl'], 'yield')
            self.assertEqual(report['priority_override_count'], 1)
            self.assertEqual(source.read_bytes(), original)
            config = ET.parse(folder / 'override/config-simz1.xml').getroot()
            self.assertEqual(config.find('./module[@name="zona1Priority"]/param[@name="classification"]').get('value'), 'osm-hierarchy')


if __name__ == '__main__':
    unittest.main()
