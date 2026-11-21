import json
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET
from unittest.mock import patch

from generate_montecarlo_z1 import generar, SCENARIO
from simz1_signal_offsets import offset_policy, stable_offset
from simz1_signal_replay import SignalReplay, signal_groups, control_signature
from simz1_run import parameters, sha256, select_run
from ejecutar_simz1 import ejecutar
from test_simz1_run import fake_matsim


class SignalReplayTests(unittest.TestCase):
    def test_launcher_propagates_explicit_policy_seed_and_iterations(self):
        import sys
        import ejecutar_simz1 as launcher
        with tempfile.TemporaryDirectory(prefix='signal CLI ') as temporary:
            run=Path(temporary)/'run with spaces'
            args=['ejecutar_simz1.py','--run-dir',str(run),'--agents','1','--seed','19',
                  '--corridor-policy','redistribute','--signal-offset-policy','hash',
                  '--signal-offset-seed','-9','--iterations','2','--no-within-day-routing']
            with patch.object(sys,'argv',args),patch.object(launcher,'ejecutar') as execute:
                launcher.main()
            self.assertEqual(execute.call_args.args[-1],2)
            manifest=json.loads((run/'run-manifest.json').read_text())
            self.assertEqual(manifest['signal_offsets']['seed'],-9)
            self.assertEqual(parameters(run/'config-simz1.xml')['zona1WithinDayRouting.enabled'],'false')

    def test_offsets_reproducible_persisted_isolated_and_phase_settings_unchanged(self):
        source=SCENARIO/'signalControl.xml'
        before=sha256(source)
        original=offset_policy(source)
        self.assertEqual(len(original['plans']),163)
        self.assertEqual({p['before'] for p in original['plans']},{0})
        with tempfile.TemporaryDirectory(prefix='SimZ1 signal offsets ') as temporary:
            root=Path(temporary)
            controls=[]
            for i,seed in enumerate((20261015,20261015,20261016)):
                run=root/f'run {i}'
                generar(SCENARIO/'config-simz1.xml',run,20261015,agents=3,corridor_policy='redistribute',
                        signal_offset_policy='hash',signal_offset_seed=seed)
                control=Path(parameters(run/'config-simz1.xml')['signalsystems.signalcontrol'])
                controls.append(control)
                report=json.loads((run/'run-manifest.json').read_text())['signal_offsets']
                self.assertEqual(report['seed'],seed)
                self.assertTrue(all(0<=p['after']<p['cycle'] for p in report['plans']))
                self.assertGreater(len({p['after'] for p in report['plans']}),1)
                # Only offsets change; preserve groups, cycle, onset, dropping.
                offset_policy(control,'zero',write=True)
                self.assertEqual(control_signature(source),control_signature(control))
                offset_policy(control,'hash',seed,write=True)
            self.assertEqual(sha256(controls[0]),sha256(controls[1]))
            self.assertNotEqual(sha256(controls[0]),sha256(controls[2]))
            self.assertEqual(sha256(root/'run 0/plans.xml'),sha256(root/'run 2/plans.xml'))
        self.assertEqual(sha256(source),before)

    def test_offset_validation_and_golden_hash(self):
        self.assertEqual(stable_offset('2',20261015,80),8)  # Also checked in Java.
        for policy,seed in [('wrong',None),('zero',1),('preserve',1),('hash',2**63)]:
            with self.assertRaises(ValueError): offset_policy(SCENARIO/'signalControl.xml',policy,seed)
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'control.xml'
            for bad in ('-1','80','1.2'):
                path.write_text(f'<signalControl><signalSystem refId="s"><signalPlan id="p"><cycleTime sec="80"/><offset sec="{bad}"/></signalPlan></signalSystem></signalControl>')
                with self.assertRaises(ValueError): offset_policy(path,'zero')

    def test_native_series_initial_states_order_duplicates_unknown_and_permission(self):
        groups=[dict(system_id=s,group_id='same',signals=[dict(signal_id=s,link=s,lanes=['lane'],turning_moves=['next'])])
                for s in ('A','B')]
        replay=SignalReplay(groups)
        def event(system,time,state):
            return dict(type='signalGroupStateChangedEvent',signalSystemId=system,signalGroupId='same',time=str(time),signalGroupState=state)
        for attrs in [event('A',43,'YELLOW'),event('B',43,'YELLOW'),event('B',43,'RED'),
                      event('A',47,'RED'),event('B',49,'GREEN'),event('A',80,'GREEN')]: replay.add(attrs)
        self.assertEqual(replay.series['B','same'],[[43.,'YELLOW'],[43.,'RED'],[49.,'GREEN']])
        self.assertEqual(replay.event_count,6)
        with self.assertRaisesRegex(ValueError,'duplicado'): replay.add(event('A',80,'GREEN'))
        with self.assertRaisesRegex(ValueError,'fuera de orden'): replay.add(event('A',79,'RED'))
        with self.assertRaisesRegex(ValueError,'ajeno'): replay.add(event('other',90,'GREEN'))
        decision=dict(type='simz1NativeDecision',reason='turn_go',link='A',nextLink='next',lane='lane',nativeHasGreen='true')
        replay.add(decision)
        replay.add(event('A',123,'YELLOW')); replay.add(decision)
        replay.add(event('A',127,'RED'))
        with self.assertRaisesRegex(ValueError,'sin permiso'): replay.add(decision)
        self.assertEqual(replay.summary()['permitted_decisions_by_state'],{'GREEN':1,'YELLOW':1})
        audit=SignalReplay(groups,retain_series=False)
        for attrs in [event('A',0,'YELLOW'),event('A',0,'RED'),event('A',10,'GREEN')]: audit.add(attrs)
        self.assertEqual(audit.series['A','same'],[[10.,'GREEN']])
        self.assertEqual(audit.summary()['event_count'],3)
        with self.assertRaisesRegex(ValueError,'duplicado'): audit.add(event('A',10,'GREEN'))
        with self.assertRaises(ValueError): audit.payload()

    def test_exact_signal_group_link_lane_mapping_and_unknown_reference(self):
        from simz1_lane_validation import read_network
        links=read_network(SCENARIO/'network.xml')[1]
        groups=signal_groups(SCENARIO/'signalSystems.xml',SCENARIO/'signalGroups.xml',links,SCENARIO/'lanes.xml')
        self.assertEqual(len({g['system_id'] for g in groups}),163)
        self.assertTrue(all(s['lanes'] for g in groups for s in g['signals']))
        with self.assertRaises(ValueError):
            signal_groups(SCENARIO/'signalSystems.xml',SCENARIO/'signalGroups.xml',{},SCENARIO/'lanes.xml')

    def test_loaded_offset_mismatch_rejects_run_without_publishing(self):
        import gzip
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); run=root/'run'
            executable=root/'fake.cmd'; executable.write_text('')
            generar(SCENARIO/'config-simz1.xml',run,1,agents=1,corridor_policy='redistribute',signal_offset_policy='hash')
            def wrong(*args,**kwargs):
                fake_matsim(*args,**kwargs)
                path=run/'output/output_signal_control_v2.0.xml.gz'
                with gzip.open(path,'rb') as f: tree=ET.parse(f)
                element=next(e for e in tree.getroot().iter() if e.tag.endswith('offset'))
                element.set('sec',str((int(element.get('sec'))+1)%80))
                with gzip.open(path,'wb') as f: f.write(ET.tostring(tree.getroot()))
                return 0
            with patch('ejecutar_simz1.ejecutar_con_salida_en_vivo',wrong),self.assertRaisesRegex(ValueError,'plan semaforico'):
                ejecutar(run,maven=executable,iterations=1,latest_path=root/'latest-successful.json')
            self.assertFalse((root/'latest-successful.json').exists())


if __name__=='__main__': unittest.main()
