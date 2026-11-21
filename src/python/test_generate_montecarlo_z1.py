from pathlib import Path
import tempfile
import json
import random
import sys
import subprocess
from unittest.mock import patch
import unittest
import xml.etree.ElementTree as E
from generate_montecarlo_z1 import generar, synthetic_people, SCENARIO
from generate_demand_z1 import principal_links
from simz1_population import population_spec, draw_population, verify_population
from simz1_run import sha256, parameters

class MonteCarloTests(unittest.TestCase):
    def test_rerouting_pair_preserves_demand_signals_and_explicit_disable(self):
        with tempfile.TemporaryDirectory(prefix='simz1 routing pair ') as folder:
            root=Path(folder)
            on,off,retained=[root/name for name in ('routing on','routing off','retained off')]
            for target,enabled in ((on,True),(off,False)):
                generar(SCENARIO/'config-simz1.xml',target,20261004,agents=3,
                        corridor_policy='redistribute',within_day_routing=enabled,reroute_budget=7)
            for relative in ('plans.xml','inputs/vehicles.xml'):
                self.assertEqual(sha256(on/relative),sha256(off/relative))
            on_inputs={p.name:sha256(p) for p in (on/'inputs').iterdir()}
            off_inputs={p.name:sha256(p) for p in (off/'inputs').iterdir()}
            self.assertEqual(on_inputs,off_inputs)  # Network, signals, lanes, vehicles and facilities.
            on_params=parameters(on/'config-simz1.xml')
            off_params=parameters(off/'config-simz1.xml')
            self.assertEqual(on_params['zona1WithinDayRouting.enabled'],'true')
            self.assertEqual(off_params['zona1WithinDayRouting.enabled'],'false')
            self.assertEqual(off_params['zona1WithinDayRouting.maxReroutesPerStep'],'7')
            for key in on_params:
                if key != 'zona1WithinDayRouting.enabled':
                    self.assertEqual(on_params[key].replace(str(on),'RUN'),off_params[key].replace(str(off),'RUN'),key)
            manifest=json.loads((off/'run-manifest.json').read_text())
            self.assertTrue(any(change['parameter']=='zona1WithinDayRouting.maxReroutesPerStep'
                                and change['after']=='7' for change in manifest['configuration_overrides']))
            generar(off/'config-simz1.xml',retained,20261004,agents=3,corridor_policy='redistribute')
            self.assertEqual(parameters(retained/'config-simz1.xml')['zona1WithinDayRouting.enabled'],'false')
            self.assertEqual(parameters(retained/'config-simz1.xml')['zona1WithinDayRouting.maxReroutesPerStep'],'7')

    def test_reroute_budget_validation_and_launcher_propagation(self):
        import ejecutar_simz1 as launcher
        with tempfile.TemporaryDirectory() as folder:
            destination=Path(folder)/'new run'
            for invalid in (0,-1,1.5,True,'2'):
                with self.assertRaisesRegex(ValueError,'reroute-budget'):
                    generar(SCENARIO/'config-simz1.xml',destination,1,agents=1,
                            corridor_policy='redistribute',reroute_budget=invalid)
                self.assertFalse(destination.exists())
            for script in ('generate_montecarlo_z1.py','ejecutar_simz1.py'):
                for invalid in ('0','-1','1.5'):
                    result=subprocess.run([sys.executable,str(Path(__file__).parent/script),
                                           '--reroute-budget',invalid],capture_output=True,text=True)
                    self.assertEqual(result.returncode,2,result.stdout+result.stderr)
                    self.assertIn('--reroute-budget',result.stderr)
            arguments=['ejecutar_simz1.py','--run-dir',str(destination),'--seed','1',
                       '--agents','1','--corridor-policy','redistribute','--no-within-day-routing',
                       '--reroute-budget','2','--iterations','2']
            with patch.object(sys,'argv',arguments),patch.object(launcher,'ejecutar') as execute:
                launcher.main()
            execute.assert_called_once()
            params=parameters(destination/'config-simz1.xml')
            self.assertEqual(params['zona1WithinDayRouting.maxReroutesPerStep'],'2')
            self.assertEqual(params['zona1WithinDayRouting.enabled'],'false')

    def test_small_directed_cycle_is_not_restricted_to_snapshot_node_count(self):
        xml='''<network><nodes><node id="a" x="0" y="0"/><node id="b" x="1" y="0"/></nodes>
        <links><link id="ab" from="a" to="b" modes="car"><attributes>
        <attribute name="osm:name">Avenida Elena</attribute></attributes></link>
        <link id="ba" from="b" to="a" modes="car"/></links></network>'''
        with tempfile.TemporaryDirectory() as folder:
            network=Path(folder)/'network.xml';network.write_text(xml)
            people,report,eligible=synthetic_people(network,1,population_spec(agents=10),'redistribute')
            people=list(people)
            self.assertEqual(report['core_nodes'],2)
            self.assertEqual(len(people),10)
            self.assertEqual(set(eligible),{'ab','ba'})
            for person in people:
                activities=person.findall('plan/activity')
                self.assertNotEqual(activities[0].get('link'),activities[1].get('link'))

    def test_exact_xml_counts_and_repeatability_at_requested_sizes(self):
        _, eligible, _, _ = principal_links(SCENARIO/'network.xml')
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder)
            for count in (1, 10, 100):
                hashes=[]
                for repetition in (0, 1):
                    destination=folder/f'{count}-{repetition}'
                    report=generar(SCENARIO/'config-simz1.xml',destination,20261004,
                                   agents=count,corridor_policy='redistribute')
                    ids=set(); trips=0
                    context=E.iterparse(destination/'plans.xml', events=('start','end'))
                    _,root=next(context)
                    for action,person in context:
                        if action=='end' and person.tag=='person':
                            self.assertNotIn(person.get('id'),ids)
                            ids.add(person.get('id'))
                            trips+=len(person.findall('plan/leg'))
                            person.clear(); root.clear()
                    self.assertEqual(len(ids),count)
                    self.assertEqual(trips,count)
                    self.assertIn(f'z1_{count:05}',ids)
                    verified=verify_population(destination/'plans.xml',destination/'inputs/vehicles.xml',count,eligible)
                    self.assertEqual(verified['vehicles'],count)
                    self.assertEqual(report['xml_verified_counts'],verified)
                    manifest=json.loads((destination/'run-manifest.json').read_text())
                    self.assertEqual(manifest['counts']['planned_persons'],count)
                    self.assertEqual(manifest['counts']['planned_trips'],count)
                    self.assertEqual(manifest['demand_mode'],'montecarlo')
                    self.assertEqual(manifest['status'],'prepared')
                    self.assertFalse((destination/'output').exists())
                    hashes.append((report['plans_sha256'],report['vehicles_sha256']))
                self.assertEqual(*hashes)

    def test_range_draw_historical_seed_and_semantic_compatibility(self):
        historical_range=population_spec(min_agents=150000,max_agents=250000,massive=True)
        self.assertEqual(draw_population(historical_range,random.Random(20261004)),172886)
        self.assertEqual(draw_population(population_spec(),random.Random(20261004)),10)
        golden=json.loads((Path(__file__).parent/'fixtures/simz1-demand-compatibility.json').read_text())
        with tempfile.TemporaryDirectory() as folder:
            for name,case in golden['cases'].items():
                destination=Path(folder)/name
                options=dict(agents=10) if name=='fixed' else dict(min_agents=10,max_agents=20)
                report=generar(SCENARIO/'config-simz1.xml',destination,case['seed'],
                               corridor_policy='redistribute',temporal_profile='peaks',**options)
                self.assertEqual(report['agents'],case['count'])
                people=E.parse(destination/'plans.xml').findall('person')
                actual=[dict(id=p.get('id'),profile=p.findtext("attributes/attribute[@name='drivingProfile']"),
                             activities=[a.attrib for a in p.findall('plan/activity')]) for p in people]
                self.assertEqual(actual,case['people'])
            destination=Path(folder)/'safe-default-count'
            report=generar(SCENARIO/'config-simz1.xml',destination,20261004,corridor_policy='redistribute')
            self.assertEqual(report['agents'],10)
            self.assertEqual(report['xml_verified_counts']['persons'],10)
            self.assertEqual(report['agent_range'],[10,10])

    def test_invalid_sizes_and_corridor_policies_leave_no_scenario(self):
        with tempfile.TemporaryDirectory() as folder:
            destination=Path(folder)/'not-created'
            cases=[dict(agents=0),dict(agents=-1),dict(agents=1.5),dict(agents=True),
                   dict(min_agents=1),dict(max_agents=2),dict(min_agents=5,max_agents=4),
                   dict(min_agents=0,max_agents=2),dict(min_agents=1,max_agents=2.5),
                   dict(agents=1,min_agents=1,max_agents=2),
                   dict(mode='debug',agents=2),dict(mode='historical',min_agents=1,max_agents=2),
                   dict(mode='historical',agents=9999),dict(mode='unknown')]
            for options in cases:
                with self.subTest(options=options),self.assertRaises(ValueError):
                    generar(SCENARIO/'config-simz1.xml',destination,1,corridor_policy='redistribute',temporal_profile='peaks',**options)
                self.assertFalse(destination.exists())
            with self.assertRaisesRegex(ValueError,'corridor-policy'):
                generar(SCENARIO/'config-simz1.xml',destination,1,agents=1)
            with self.assertRaisesRegex(ValueError,'Bulevar Asuncion.*Calle Marti'):
                generar(SCENARIO/'config-simz1.xml',destination,1,agents=1,corridor_policy='fail')
            self.assertFalse(destination.exists())
            for script in ('generate_montecarlo_z1.py','ejecutar_simz1.py'):
                for flags in (['--agents','1.5'],['--agents','0'],['--agents','1','--min-agents','1','--max-agents','2']):
                    result=subprocess.run([sys.executable,str(Path(__file__).parent/script),
                                           '--run-dir',str(destination),*flags],capture_output=True,text=True)
                    self.assertNotEqual(result.returncode,0,result.stdout)
                    self.assertFalse(destination.exists())

    def test_modes_isolated_and_launcher_propagation(self):
        import ejecutar_simz1 as launcher
        from generate_demand_z1 import generate as debug_generate
        config=SCENARIO/'config-simz1.xml'
        originals={path:sha256(path) for path in (config,SCENARIO/'plans.xml',SCENARIO/'vehicle-types.xml')}
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder)
            debug=folder/'debug'; historical=folder/'historical'; mc=folder/'montecarlo'
            generar(config,debug,17,mode='debug')
            before=sha256(debug/'plans.xml')
            self.assertEqual(E.parse(debug/'plans.xml').find('person').get('id'),'agente_prueba_01')
            self.assertEqual(parameters(debug/'config-simz1.xml')['qsim.startTime'],'07:59:00')
            report=generar(config,historical,17,mode='historical',corridor_policy='redistribute')
            self.assertEqual(report['agents'],10000)
            self.assertIn('not a replay',report['historical_reference'])
            argv=['ejecutar_simz1.py','--mode','montecarlo','--run-dir',str(mc),'--seed','17',
                  '--min-agents','2','--max-agents','4','--corridor-policy','redistribute','--iterations','1']
            with patch.object(sys,'argv',argv),patch.object(launcher,'ejecutar') as run:
                launcher.main()
                run.assert_called_once_with(mc,None,False,1)
            manifest=json.loads((mc/'run-manifest.json').read_text())
            self.assertEqual(manifest['population_generation']['selection'],population_spec(min_agents=2,max_agents=4))
            self.assertEqual(sha256(debug/'plans.xml'),before)
            with self.assertRaisesRegex(ValueError,'carpeta nueva'):
                generar(config,historical,17,mode='debug')
            with self.assertRaisesRegex(ValueError,'overwrite'):
                debug_generate(SCENARIO/'network.xml',historical/'plans.xml')
            self.assertFalse((mc/'output').exists())
        self.assertEqual({p:sha256(p) for p in originals},originals)

    def test_corrupt_vehicle_reference_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder)/'run'
            generar(SCENARIO/'config-simz1.xml',folder,1,agents=1,corridor_policy='redistribute')
            plans=folder/'plans.xml'
            plans.write_text(plans.read_text().replace('{"car":"z1_00001"}','{"car":"missing"}'))
            _,eligible,_,_=principal_links(SCENARIO/'network.xml')
            with self.assertRaisesRegex(ValueError,'Referencia de vehiculo'):
                verify_population(plans,folder/'inputs/vehicles.xml',1,eligible)

    def test_seed_volume_routes_times_and_coordinates(self):
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder)
            a,b,c=[folder/n for n in ('a','b','c')]
            config=SCENARIO/'config-simz1.xml'
            original=config.read_bytes()
            first=generar(config,a,123,agents=1000,corridor_policy='redistribute',temporal_profile='peaks');second=generar(config,b,123,agents=1000,corridor_policy='redistribute',temporal_profile='peaks');third=generar(config,c,124,agents=1000,corridor_policy='redistribute',temporal_profile='peaks')
            self.assertEqual((a/'plans.xml').read_bytes(),(b/'plans.xml').read_bytes())
            self.assertNotEqual(first['plans_sha256'],third['plans_sha256'])
            for report in (first,second,third):
                self.assertEqual(report['agents'],1000)
                self.assertEqual(report['agent_range'],[1000,1000])
            self.assertEqual(config.read_bytes(),original)
            for report in (first,second,third):
                self.assertEqual(sum(report['agents_by_peak'].values()),report['agents'])
                self.assertTrue(.4<report['agents_by_peak']['0']/report['agents']<.6)
                self.assertTrue(.65<report['origins_by_source']['Avenida Elena']/report['agents']<.75)
                self.assertIn('Calle Marti',report['missing_corridors'])
                self.assertIn('Bulevar Asuncion',report['missing_corridors'])
                self.assertEqual(report['concentrated_corridor'],'Avenida Elena')
                self.assertEqual(report['corridor_probabilities'],
                                 {'Bulevar Asuncion':0.,'Calle Marti':0.,'Avenida Elena':.7})
                self.assertEqual(sum(report['origins_by_source'].values()),1000)
                self.assertGreaterEqual(report['physical_origins_by_corridor']['Avenida Elena'],
                                        report['origins_by_source']['Avenida Elena'])
            generated=E.parse(a/'config-simz1.xml')
            self.assertIsNotNone(generated.find("module[@name='network']/param[@name='laneDefinitionsFile']"))
            self.assertEqual(generated.find("module[@name='qsim']/param[@name='useLanes']").get('value'),'true')
            signal_file=generated.find("module[@name='signalsystems']/param[@name='signalsystems']").get('value')
            self.assertEqual(len(E.parse(signal_file).findall('.//{*}signal/{*}lane')),
                             len(E.parse(SCENARIO/'signalSystems.xml').findall('.//{*}signal/{*}lane')))
            for name in ('signalsystems','signalgroups','signalcontrol'):
                path=Path(generated.find(f"module[@name='signalsystems']/param[@name='{name}']").get('value'))
                self.assertTrue(path.is_absolute() and path.is_file())
            self.assertEqual(generated.find("module[@name='zona1WithinDayRouting']/param[@name='enabled']").get('value'),'true')
            self.assertEqual(generated.find("module[@name='qsim']/param[@name='endTime']").get('value'),'24:00:00')
            self.assertEqual(generated.find("module[@name='qsim']/param[@name='startTime']").get('value'),'05:30:00')
            self.assertEqual(generated.find("module[@name='travelTimeCalculator']/param[@name='maxTime']").get('value'),'86400')
            core,eligible,_,_=principal_links(SCENARIO/'network.xml');eligible=set(eligible)
            net=E.parse(SCENARIO/'network.xml').getroot()
            links={l.get('id'):l for l in net.findall('links/link')}
            nodes={n.get('id'):n for n in net.findall('nodes/node')}
            population=E.parse(a/'plans.xml').getroot()
            self.assertEqual(len(population),first['agents'])
            for person in population:
                profile=person.find("attributes/attribute[@name='drivingProfile']")
                self.assertIn(profile.text, ('Liebre','Tortuga','Normal'))
                self.assertEqual(profile.get('class'), 'java.lang.String')
                origin,leg,dest=list(person.find('plan'))
                self.assertNotEqual(origin.get('link'),dest.get('link'))
                departure=int(origin.get('end_time'))
                self.assertTrue(21600<=departure<30600 or 61200<=departure<70200)
                for act,key in ((origin,'from'),(dest,'to')):
                    self.assertIn(act.get('link'),eligible)
                    node=nodes[links[act.get('link')].get(key)]
                    self.assertEqual(float(act.get('x')),float(node.get('x')))
                    self.assertEqual(float(act.get('y')),float(node.get('y')))
            with self.assertRaises(ValueError):generar(config,a,125)
            from collections import Counter
            counts=Counter(p.find("attributes/attribute[@name='drivingProfile']").text for p in population)
            self.assertEqual(dict(counts),first['driving_profiles'])
            for profile,probability in first['driving_profile_probabilities'].items():
                self.assertAlmostEqual(counts[profile]/len(population),probability,delta=.06)

if __name__=='__main__':unittest.main()
