"""Offline checks of GREEN availability on actual through-freight movements."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest
import xml.etree.ElementTree as ET

from simz1_freight_signals import audit
from simz1_lane_validation import read_lanes
from simz1_run import parameters


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / 'scenarios/zona1/config-simz1.xml'
BUNDLE = ROOT / 'scenarios/zona1/freight/weekday-v2/routes.json'


def xml(path):
    tree = ET.parse(path)
    for row in tree.getroot().iter():
        row.tag = row.tag.rsplit('}', 1)[-1]
    return tree


def copied_config(folder):
    """All references are absolute; only signal fixture copies can be edited."""
    tree = ET.parse(CONFIG)
    files = {}
    for module in tree.getroot().findall('module'):
        for param in module.findall('param'):
            value = param.get('value')
            source = CONFIG.parent / value if value else None
            if source is None or not source.is_file():
                continue
            path = source.resolve()
            if module.get('name') == 'signalsystems' and param.get('name') in (
                    'signalsystems', 'signalgroups', 'signalcontrol'):
                path = folder / source.name
                shutil.copyfile(source, path)
                files[param.get('name')] = path
            param.set('value', str(path))
    target = folder / 'config.xml'
    tree.write(target, encoding='utf-8', xml_declaration=True)
    return target, files


class FreightSignalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle = json.loads(BUNDLE.read_text(encoding='utf-8'))
        cls.baseline = audit(CONFIG, cls.bundle)
        cls.rows = [movement for route in cls.baseline['routes'] for movement in route['movements']]
        cls.lanes = read_lanes(CONFIG.parent / parameters(CONFIG)['network.laneDefinitionsFile'])

    def test_v2_has_positive_green_on_every_controlled_native_lane(self):
        self.assertTrue(self.baseline['enabled'])
        self.assertEqual(len(self.baseline['routes']), 4)
        self.assertTrue(all(route['controlled_movements'] > 0 for route in self.baseline['routes']))
        self.assertTrue(all(row['green_ticks_per_common_cycle'] > 0 for row in self.rows))
        self.assertTrue(all(row['native_lane'] for row in self.rows))
        for route in self.baseline['routes']:
            self.assertEqual(route['controlled_movements'], len({(r['from_link'], r['to_link'])
                                                                for r in route['movements']}))
            self.assertEqual(route['controlled_lane_movements'], len(route['movements']))
            self.assertEqual(len(route['movements']), len({(r['from_link'], r['to_link'], r['native_lane'])
                                                          for r in route['movements']}))
        self.assertFalse(self.baseline['compound_passage_feasibility_proven'])
        self.assertFalse(self.baseline['queue_drainage_proven'])

    def test_zero_green_and_amber_only_phase_rejected(self):
        sid, signal_id = self.rows[0]['signals'][0].split('/', 1)
        for amber_only in (False, True):
            with self.subTest(amber_only=amber_only), tempfile.TemporaryDirectory() as td:
                config, files = copied_config(Path(td))
                groups = xml(files['signalgroups']).getroot()
                group = next(g.get('id') for g in groups.findall(f"signalSystem[@refId='{sid}']/signalGroup")
                             if g.find(f"signal[@refId='{signal_id}']") is not None)
                control = xml(files['signalcontrol'])
                plan = control.getroot().find(f"signalSystem[@refId='{sid}']/.//signalPlan")
                settings = plan.find(f"signalGroupSettings[@refId='{group}']")
                onset = int(settings.find('onset').get('sec'))
                cycle = int(plan.find('cycleTime').get('sec'))
                settings.find('dropping').set('sec', str((onset + (4 if amber_only else 0)) % cycle))
                control.write(files['signalcontrol'], encoding='utf-8', xml_declaration=True)
                with self.assertRaisesRegex(ValueError, 'positive GREEN'):
                    audit(config, self.bundle)

    def test_signal_missing_group_membership_rejected(self):
        sid, signal_id = self.rows[0]['signals'][0].split('/', 1)
        with tempfile.TemporaryDirectory() as td:
            config, files = copied_config(Path(td))
            groups = xml(files['signalgroups'])
            parent = next(g for g in groups.getroot().findall(f"signalSystem[@refId='{sid}']/signalGroup")
                          if g.find(f"signal[@refId='{signal_id}']") is not None)
            parent.remove(parent.find(f"signal[@refId='{signal_id}']"))
            groups.write(files['signalgroups'], encoding='utf-8', xml_declaration=True)
            with self.assertRaisesRegex(ValueError, 'missing group/phase'):
                audit(config, self.bundle)

    def test_signals_apply_only_to_their_native_lane_and_permitted_turn(self):
        for restriction in ('lane', 'turn'):
            candidates = []
            for row in self.rows:
                if restriction == 'lane':
                    alternatives = sorted(name for name, lane in self.lanes[row['from_link']].items()
                                          if name != row['native_lane'] and row['to_link'] in lane['to_links'])
                else:
                    alternatives = sorted({target for lane in self.lanes[row['from_link']].values()
                                           for target in lane['to_links']} - {row['to_link']})
                if alternatives:
                    candidates.append((row, alternatives[0]))
            self.assertTrue(candidates, f'No real {restriction} alternative in the v2 signal fixture')
            row, alternative = candidates[0]
            full_id = row['signals'][0]
            sid, signal_id = full_id.split('/', 1)
            with self.subTest(restriction=restriction), tempfile.TemporaryDirectory() as td:
                config, files = copied_config(Path(td))
                systems = xml(files['signalsystems'])
                signal = systems.getroot().find(f"signalSystem[@id='{sid}']/signals/signal[@id='{signal_id}']")
                if restriction == 'lane':
                    for lane in list(signal.findall('lane')):
                        signal.remove(lane)
                    ET.SubElement(signal, 'lane', refId=alternative)
                else:
                    for turns in list(signal.findall('turningMoveRestrictions')):
                        signal.remove(turns)
                    turns = ET.SubElement(signal, 'turningMoveRestrictions')
                    ET.SubElement(turns, 'toLink', refId=alternative)
                systems.write(files['signalsystems'], encoding='utf-8', xml_declaration=True)
                report = audit(config, self.bundle)
                matching = [movement for route in report['routes'] for movement in route['movements']
                            if movement['from_link'] == row['from_link'] and movement['to_link'] == row['to_link']]
                if restriction == 'lane':
                    controlled_alternative = [movement for movement in matching
                                              if movement['native_lane'] == alternative]
                    self.assertTrue(controlled_alternative)
                    self.assertTrue(all(full_id in movement['signals'] for movement in controlled_alternative))
                    self.assertTrue(all(full_id not in movement['signals'] for movement in matching
                                        if movement['native_lane'] != alternative))
                else:
                    self.assertTrue(all(full_id not in movement['signals'] for movement in matching))

    def test_conflicting_signals_on_another_reachable_terminal_are_rejected(self):
        candidates = []
        for row in self.rows:
            terminals = sorted(name for name, lane in self.lanes[row['from_link']].items()
                               if row['to_link'] in lane['to_links'])
            if len(terminals) >= 2:
                candidates.append((row, terminals[-1]))
        self.assertTrue(candidates, 'The fixture needs a movement with at least two reachable terminals')
        row, alternative = candidates[0]
        sid = row['signals'][0].split('/', 1)[0]
        with tempfile.TemporaryDirectory() as td:
            config, files = copied_config(Path(td))
            systems, groups, control = (xml(files[name]) for name in
                                        ('signalsystems', 'signalgroups', 'signalcontrol'))
            signal_parent = systems.getroot().find(f"signalSystem[@id='{sid}']/signals")
            group_parent = groups.getroot().find(f"signalSystem[@refId='{sid}']")
            plan = control.getroot().find(f"signalSystem[@refId='{sid}']/.//signalPlan")
            cycle = int(plan.find('cycleTime').get('sec'))
            self.assertGreaterEqual(cycle, 24)
            for index, (onset, dropping) in enumerate(((0, cycle//3), (cycle//2, cycle-2))):
                ident = f'test_only_alternate_lane_{index}'
                signal = ET.SubElement(signal_parent, 'signal', id=ident, linkIdRef=row['from_link'])
                ET.SubElement(signal, 'lane', refId=alternative)
                turns = ET.SubElement(signal, 'turningMoveRestrictions')
                ET.SubElement(turns, 'toLink', refId=row['to_link'])
                group = ET.SubElement(group_parent, 'signalGroup', id=ident)
                ET.SubElement(group, 'signal', refId=ident)
                settings = ET.SubElement(plan, 'signalGroupSettings', refId=ident)
                ET.SubElement(settings, 'onset', sec=str(onset))
                ET.SubElement(settings, 'dropping', sec=str(dropping))
            for name, tree in (('signalsystems', systems), ('signalgroups', groups), ('signalcontrol', control)):
                tree.write(files[name], encoding='utf-8', xml_declaration=True)
            with self.assertRaisesRegex(ValueError, 'never has GREEN'):
                audit(config, self.bundle)


if __name__ == '__main__':
    unittest.main()
