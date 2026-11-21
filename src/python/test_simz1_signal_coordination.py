import hashlib
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET
from copy import deepcopy

from simz1_signal_coordination import coordinate, feasible_starts, remaining_green, solve_offsets, validate_report


def plan(offset=0):
    return dict(cycle=80, offset=offset, groups={'avenida': (0, 47), 'calle': (49, 78)})


def constraint(*rows):
    return dict(step_seconds=1, signals=[dict(system=s, group=g, traversal_seconds=t) for s,g,t in rows])


def fixture(directory):
    def write(name, text):
        path = directory/name; path.write_text(text, encoding='utf-8'); return path
    write('network.xml', '''<network><nodes>
<node id="w" x="-50" y="0"/><node id="s" x="0" y="-50"/>
<node id="a" x="0" y="0"/><node id="b" x="8" y="0"/>
<node id="c" x="68" y="0"/><node id="d" x="168" y="0"/>
</nodes><links>'''+''.join(f'<link id="{i}" from="{a}" to="{b}" length="{l}" permlanes="1" capacity="2000" freespeed="10" modes="car,bus"/>' for i,a,b,l in (
    ('west','w','a',50),('south','s','a',50),('short','a','b',8),('receipt','b','c',60),('exit','c','d',100)))+'</links></network>')
    write('lanes.xml','<laneDefinitions>'+''.join(f'''<lanesToLinkAssignment linkIdRef="{i}">
<lane id="{i}.original"><startsAt meterFromLinkEnd="{length}"/><representedLanes number="1"/><capacity vehiclesPerHour="2000"/><leadsTo><toLane refId="{i}.lane.0"/></leadsTo></lane>
<lane id="{i}.lane.0"><startsAt meterFromLinkEnd="{min(2,length)}"/><representedLanes number="1"/><capacity vehiclesPerHour="2000"/><leadsTo><toLink refId="{target}"/></leadsTo></lane></lanesToLinkAssignment>'''
    for i,length,target in [('west',50,'short'),('south',50,'short'),('short',8,'receipt'),('receipt',60,'exit')])+'</laneDefinitions>')
    write('systems.xml','''<signalSystems><signalSystem id="A"><signals>
<signal id="west" linkIdRef="west"><lane refId="west.lane.0"/></signal>
<signal id="south" linkIdRef="south"><lane refId="south.lane.0"/></signal>
</signals></signalSystem><signalSystem id="B"><signals>
<signal id="short" linkIdRef="short"><lane refId="short.lane.0"/></signal>
</signals></signalSystem></signalSystems>''')
    write('groups.xml','''<signalGroups><signalSystem refId="A">
<signalGroup id="avenida"><signal refId="west"/></signalGroup>
<signalGroup id="calle"><signal refId="south"/></signalGroup></signalSystem>
<signalSystem refId="B"><signalGroup id="avenida"><signal refId="short"/></signalGroup></signalSystem></signalGroups>''')
    write('control.xml','<signalControl xmlns="http://www.matsim.org/files/dtd">'+''.join(f'''<signalSystem refId="{s}"><signalSystemController>
<controllerIdentifier>Zona1FixedTime</controllerIdentifier><signalPlan id="daily"><start daytime="00:00:00"/><stop daytime="00:00:00"/>
<cycleTime sec="80"/><offset sec="0"/><signalGroupSettings refId="avenida"><onset sec="0"/><dropping sec="47"/></signalGroupSettings>
{('<signalGroupSettings refId="calle"><onset sec="49"/><dropping sec="78"/></signalGroupSettings>' if s=='A' else '')}
</signalPlan></signalSystemController></signalSystem>''' for s in ('A','B'))+'</signalControl>')
    write('vehicles.xml','''<vehicleDefinitions><vehicleType id="Bus"><length meter="12"/><maximumVelocity meterPerSecond="10"/><networkMode networkMode="bus"/></vehicleType>
<vehicleType id="Unused"><length meter="100"/><maximumVelocity meterPerSecond="0.1"/><networkMode networkMode="car"/></vehicleType>
<vehicle id="bus1" type="Bus"/></vehicleDefinitions>''')
    config=ET.fromstring('''<config><module name="network"><param name="inputNetworkFile" value="network.xml"/><param name="laneDefinitionsFile" value="lanes.xml"/></module>
<module name="signalsystems"><param name="useSignalsystems" value="true"/><param name="signalsystems" value="systems.xml"/><param name="signalgroups" value="groups.xml"/><param name="signalcontrol" value="control.xml"/></module>
<module name="vehicles"><param name="vehiclesFile" value="vehicles.xml"/></module></config>''')
    return config


class SignalCoordinationTests(unittest.TestCase):
    def test_short_activity_source_includes_native_buffer_and_terminal_budget(self):
        with tempfile.TemporaryDirectory() as temp:
            directory=Path(temp); config=fixture(directory)
            network=ET.parse(directory/'network.xml')
            network.find("nodes/node[@id='w']").set('x','-4')
            network.find("links/link[@id='west']").set('length','4')
            network.write(directory/'network.xml')
            lanes=ET.parse(directory/'lanes.xml')
            lanes.find(".//lane[@id='west.original']/startsAt").set('meterFromLinkEnd','4')
            lanes.write(directory/'lanes.xml')
            legacy=coordinate(config,directory)
            original=directory/'original.xml'; original.write_bytes((directory/'control.xml').read_bytes())
            report=coordinate(config,directory,write=True,activity_origins=True)
            old=next(c for c in legacy['constraints'] if c['source_link']=='west')
            new=next(c for c in report['constraints'] if c['source_link']=='west')
            self.assertEqual(old['signals'][0]['traversal_seconds'],0)
            self.assertEqual(new['signals'][0]['traversal_seconds'],5)
            self.assertEqual(new['signals'][-1]['traversal_seconds'],11)
            south=next(c for c in report['constraints'] if c['source_link']=='south')
            self.assertEqual(south['signals'][0]['traversal_seconds'],0)
            self.assertNotEqual(report['policy'],legacy['policy'])
            self.assertTrue(all(c['entry_ticks_after']>0 for c in report['constraints']))
            self.assertEqual(validate_report(config,directory,report,control_before_path=original)['status'],'valid')

    def test_amber_end_and_offset_wrap_match_native_clock(self):
        p=plan(10)
        self.assertEqual(remaining_green(p,'avenida',10,10),43)
        self.assertEqual(remaining_green(p,'avenida',53,10),0)
        self.assertEqual(remaining_green(p,'calle',59,10),25)
        self.assertEqual(remaining_green(p,'calle',84,10),0)
        self.assertEqual(remaining_green(p,'avenida',90,10),43)

    def test_disjoint_green_offsets_allow_both_approaches(self):
        plans={'A':plan(),'B':plan()}
        rows=[constraint(('A','avenida',0),('B','avenida',6)),constraint(('A','calle',0),('B','avenida',6))]
        self.assertEqual(feasible_starts(rows[1],plans,{'A':0,'B':0}),[])
        offsets,components=solve_offsets(plans,rows)
        self.assertEqual(offsets['A'],0)
        self.assertEqual(components[0]['minimum_entry_ticks'],15)
        self.assertTrue(all(feasible_starts(row,plans,offsets) for row in rows))
        self.assertEqual(solve_offsets(plans,rows),(offsets,components))

    def test_shared_three_signal_chain_has_one_consistent_clock(self):
        plans={s:plan() for s in 'ABC'}
        rows=[constraint(('A','calle',0),('B','avenida',5),('C','calle',12)),
              constraint(('A','avenida',0),('B','avenida',5))]
        offsets,components=solve_offsets(plans,rows)
        self.assertEqual(len(components),1)
        self.assertEqual(components[0]['assignments_examined'],6400)
        self.assertTrue(all(feasible_starts(row,plans,offsets) for row in rows))

    def test_impossible_budget_fails_instead_of_relaxing_signal(self):
        with self.assertRaisesRegex(ValueError,'no feasible'):
            solve_offsets({'A':plan(),'B':plan()},[constraint(('A','calle',0),('B','avenida',43))])

    def test_incompatible_groups_of_one_controller_fail(self):
        with self.assertRaisesRegex(ValueError,'no feasible'):
            solve_offsets({'A':plan()},[constraint(('A','calle',0),('A','avenida',0))])

    def test_search_limit_and_unequal_cycles_are_explicit(self):
        rows=[constraint(('A','calle',0),('B','avenida',3))]
        with self.assertRaisesRegex(ValueError,'assignment limit'):
            solve_offsets({'A':plan(),'B':plan()},rows,maximum_assignments=2)
        other=plan();other['cycle']=90
        with self.assertRaisesRegex(ValueError,'different signal cycles'):
            solve_offsets({'A':plan(),'B':other},rows)

    def test_geometry_proposal_does_not_modify_files(self):
        with tempfile.TemporaryDirectory() as temp:
            directory=Path(temp);config=fixture(directory)
            before={p.name:p.read_bytes() for p in directory.iterdir()}
            report=coordinate(config,directory)
            self.assertEqual(before,{p.name:p.read_bytes() for p in directory.iterdir()})
            self.assertEqual(report['impossible_before'],1)
            self.assertTrue(all(c['entry_ticks_after']>0 for c in report['constraints']))
            self.assertEqual(report['profiles'][0]['type'],'Bus')
            self.assertEqual(len(report['profiles']),1)
            self.assertEqual(report['constraints'][0]['signals'][-1]['traversal_seconds'],6)

    def test_write_changes_only_offsets_and_control_hash(self):
        with tempfile.TemporaryDirectory() as temp:
            directory=Path(temp);config=fixture(directory)
            before={p.name:p.read_bytes() for p in directory.iterdir()}
            original=ET.parse(directory/'control.xml')
            report=coordinate(config,directory,write=True)
            for path in directory.iterdir():
                if path.name!='control.xml':self.assertEqual(path.read_bytes(),before[path.name])
            after=ET.parse(directory/'control.xml')
            for a,b in zip(original.iter(),after.iter()):
                self.assertEqual(a.tag,b.tag)
                if not a.tag.endswith('offset'):self.assertEqual(a.attrib,b.attrib)
            self.assertNotEqual(report['input_hashes']['control']['sha256'],report['control_sha256_after'])
            repeated=coordinate(config,directory)
            self.assertEqual(repeated['changes'],[])
            self.assertEqual(repeated['impossible_before'],0)

    def test_disabled_signals_remain_unchanged(self):
        root=ET.fromstring('<config/>')
        self.assertFalse(coordinate(root,Path('.'))['enabled'])

    def test_validation_recomputes_effective_and_original_contract(self):
        with tempfile.TemporaryDirectory() as temp:
            directory=Path(temp);config=fixture(directory)
            original=directory/'original.xml';original.write_bytes((directory/'control.xml').read_bytes())
            report=coordinate(config,directory,write=True)
            self.assertEqual(validate_report(config,directory,report,control_before_path=original)['status'],'valid')
            changed=deepcopy(report);changed['constraints'][0]['entry_ticks_after']+=1
            with self.assertRaisesRegex(ValueError,'constraints or resulting windows'):
                validate_report(config,directory,changed)
            changed=deepcopy(report);changed['changes'][0]['before']=7
            with self.assertRaisesRegex(ValueError,'before-state/derivation'):
                validate_report(config,directory,changed,control_before_path=original)
            (directory/'network.xml').write_text((directory/'network.xml').read_text().replace('capacity="2000"','capacity="1999"'))
            with self.assertRaisesRegex(ValueError,'input changed: network'):
                validate_report(config,directory,report)

    def test_validation_rejects_control_and_backup_tampering(self):
        with tempfile.TemporaryDirectory() as temp:
            directory=Path(temp);config=fixture(directory)
            original=directory/'original.xml';original.write_bytes((directory/'control.xml').read_bytes())
            report=coordinate(config,directory,write=True)
            original.write_bytes(original.read_bytes()+b'\n')
            with self.assertRaisesRegex(ValueError,'preserved original'):
                validate_report(config,directory,report,control_before_path=original)
            current=directory/'control.xml';current.write_bytes(current.read_bytes()+b'\n')
            with self.assertRaisesRegex(ValueError,'effective signalcontrol'):
                validate_report(config,directory,report)

    def test_write_rejects_control_outside_isolated_run(self):
        with tempfile.TemporaryDirectory() as temp:
            directory=Path(temp);config=fixture(directory);nested=directory/'run';nested.mkdir()
            for element in config.findall('module/param'):
                if element.get('value','').endswith('.xml'):
                    element.set('value',str(directory/element.get('value')))
            with self.assertRaisesRegex(ValueError,'outside isolated run'):
                coordinate(config,nested,write=True)

    def test_distinct_source_lane_phases_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            directory=Path(temp);config=fixture(directory)
            tree=ET.parse(directory/'lanes.xml');assignment=tree.find("lanesToLinkAssignment[@linkIdRef='west']")
            second=deepcopy(assignment.find("lane[@id='west.lane.0']"));second.set('id','west.lane.1');assignment.append(second)
            ET.SubElement(assignment.find("lane[@id='west.original']/leadsTo"),'toLane',refId='west.lane.1')
            tree.write(directory/'lanes.xml')
            # west.lane.1 is uncontrolled; first slot alone cannot certify it.
            with self.assertRaisesRegex(ValueError,'lane-dependent source phases'):
                coordinate(config,directory)


if __name__=='__main__': unittest.main()
