import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from collections import Counter
from unittest.mock import patch
import simz1_workflow_state as workflow
from generate_montecarlo_z1 import synthetic_people, SCENARIO
from simz1_population import population_spec
from simz1_agent_types import load_catalog
from simz1_demand_composition import split
from simz1_experiment_preflight import check


class BalancedDemandTests(unittest.TestCase):
    def test_massive_gate_requires_same_catalog_destinations_and_coordination(self):
        current=dict(manifest_sha256='manifest',quality_sha256='quality',run_id='trial',
                     catalog_sha256='catalog',destination_policy='lane-length-destinations-v1',
                     signal_coordination_policy='short_body_passage_activity_offsets_v2')
        with tempfile.TemporaryDirectory() as temp:
            state=Path(temp)/'trial.json'
            state.write_text(json.dumps(dict(current,run_directory=temp,source_fingerprint='revision')))
            arguments=['require-trial','--state',str(state)]
            with patch.object(workflow,'fingerprint',return_value='revision'), patch.object(workflow,'inspect',return_value=current):
                for flag,key in (('--catalog-sha256','catalog_sha256'),('--destination-policy','destination_policy'),
                                 ('--signal-coordination-policy','signal_coordination_policy')):
                    self.assertEqual(workflow.main(arguments+[flag,current[key]]),0)
                    self.assertEqual(workflow.main(arguments+[flag,'different']),1)

    def test_version_preserves_vehicle_physics_and_calendar(self):
        old=load_catalog(SCENARIO/'agent-types-nonpublic-v1.json')
        new=load_catalog(SCENARIO/'agent-types-balanced-v1.json')
        for key in ('profiles','allocation','temporal_demand'):
            self.assertEqual(old[key],new[key])
        self.assertNotEqual(old['scenario_version'],new['scenario_version'])
        self.assertEqual(split(180000,new)['family_counts'],dict(carro=79200,moto=99000,pesado=1800))
        self.assertEqual(split(220000,new)['family_counts'],dict(carro=96800,moto=121000,pesado=2200))
        self.assertEqual(split(220000,new)['private_profile_counts'],dict(
            Normal=64534, Liebre=16133, Tortuga=16133, MotocicletaLenta=30250,
            Motociclista=60500, MotocicletaRapida=30250, TransportePesado=0))
        self.assertEqual(split(1000,new)['freight_vehicles'],10)
        self.assertEqual(split(180000,old)['freight_vehicles'],4865)

    def test_explicit_policy_mismatch_fails_before_generation(self):
        with self.assertRaisesRegex(ValueError,'Destination policy'):
            check(SCENARIO/'config-simz1.xml',SCENARIO/'agent-types-balanced-v1.json',1000,1000,'uniform-nodes-v1','strict-receiver-v1')

    def test_weighted_destinations_repeatable_and_legacy_unchanged(self):
        with tempfile.TemporaryDirectory() as folder:
            root=ET.Element('network');nodes=ET.SubElement(root,'nodes');links=ET.SubElement(root,'links')
            for i in range(12):
                ET.SubElement(nodes,'node',id=str(i),x=str((i%4)*100),y=str((i//4)*100))
                l=ET.SubElement(links,'link',id=f'l{i}',**{'from':str(i),'to':str((i+1)%12),'modes':'car','length':str(100 if i<6 else 10),'permlanes':'1'})
                ET.SubElement(ET.SubElement(l,'attributes'),'attribute',name='osm:name').text='Avenida Elena'
            path=Path(folder)/'network.xml';ET.ElementTree(root).write(path)
            def sample(policy=None):
                opts={} if policy is None else dict(destination_policy=policy)
                people,report,_=synthetic_people(path,42,population_spec(agents=1800),'redistribute',origin_policy='uniform-nodes-v1',**opts)
                output=[ET.tostring(p) for p in people]
                return output,report
            baseline,_=sample();self.assertEqual(baseline,sample('legacy-gaussian-v1')[0])
            balanced,report=sample('lane-length-destinations-v1')
            self.assertEqual(balanced,sample('lane-length-destinations-v1')[0]);self.assertEqual(report['attraction_centers'],[])
            counts=Counter(ET.fromstring(p).findall('plan/activity')[-1].get('link') for p in balanced)
            self.assertGreater(sum(counts[f'l{i}'] for i in range(6)),1400)
            for p in balanced:
                activities=ET.fromstring(p).findall('plan/activity')
                self.assertNotEqual(activities[0].get('link'),activities[-1].get('link'))

if __name__=='__main__':unittest.main()
