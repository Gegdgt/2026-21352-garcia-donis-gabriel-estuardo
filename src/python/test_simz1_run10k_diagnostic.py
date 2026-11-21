"""Run10K quota regressions; only 99 private vehicles are serialized synthetically.

No historical run, events, SQLite, QSim, trial inspector, or replay is accessed.
The small geometry comes from the existing explicitly synthetic OD fixture.
"""
from collections import Counter
import copy
import json
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from generate_montecarlo_z1 import gateway_people
from simz1_agent_demand import typed_people, verify_type_ledger
from simz1_agent_types import load_catalog, vehicle_types_xml
from simz1_demand_composition import split, freight_options
from simz1_od_policy import allocate, named_percentages, percentage_document
from simz1_population import write_population, verify_population
from simz1_temporal import temporal_spec
from simz1_transit_accounting import distinct_fleet_by_system
from test_simz1_balanced_gateway_od import model

ROOT=Path(__file__).resolve().parents[1]
CATALOG=ROOT/'scenarios/zona1/agent-types-balanced-v1.json'
MIX=ROOT/'scenarios/zona1/od/balanced-gateway-v1/mix.json'
PUBLIC=ROOT/'scenarios/zona1/transit/weekday-v2/service-fleet-176-93-v1.json'
FREIGHT=ROOT/'scenarios/zona1/od/balanced-gateway-v1/access-review-v2/freight/service-composition-v3.json'
SEED=20261023


class Run10KDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.catalog=load_catalog(CATALOG)
        self.mix=json.loads(MIX.read_text(encoding='utf8'))

    def test_exact_nonpublic_and_profile_denominators(self):
        quota=split(10000,self.catalog)
        self.assertEqual(quota['family_counts'],dict(carro=4400,moto=5500,pesado=100))
        self.assertEqual((quota['private_vehicles'],quota['freight_vehicles']),(9900,100))
        self.assertEqual(quota['private_profile_counts'],dict(Normal=2934,Liebre=733,Tortuga=733,
            MotocicletaLenta=1375,Motociclista=2750,MotocicletaRapida=1375,TransportePesado=0))
        self.assertEqual(sum(quota['private_profile_counts'].values()),9900)
        self.assertFalse(quota['public_transport_in_total'])
        self.assertFalse(quota['empirical_calibration'])

    def test_fixed_freight_is_reserved_once_and_cannot_be_silently_disabled(self):
        quota=split(10000,self.catalog)
        for override in (None,100):
            self.assertEqual(freight_options(quota,FREIGHT,'2026-10-23',override,False),
                             (FREIGHT,'2026-10-23',100,False))
        for override in (0,99,101,10000):
            with self.subTest(override=override),self.assertRaisesRegex(ValueError,'included in N'):
                freight_options(quota,FREIGHT,'2026-10-23',override,False)
        with self.assertRaises(ValueError):freight_options(quota,FREIGHT,'2026-10-23',None,True)
        with self.assertRaises(ValueError):freight_options(quota,None,'2026-10-23',None,False)

    def test_four_od_classes_use_private_9900_and_preserve_seed(self):
        shares=named_percentages(self.mix)
        assigned,counts=allocate(split(10000,self.catalog)['private_vehicles'],shares,SEED)
        self.assertEqual(counts,{'external-external':4950,'external-internal':1980,
            'internal-external':1980,'internal-internal':990})
        self.assertEqual(Counter(assigned),counts)
        self.assertEqual((assigned,counts),allocate(9900,shares,SEED))
        self.assertNotEqual(assigned,allocate(9900,shares,SEED+1)[0])
        # Invalid hypotheses do not acquire implicit normalization or a fifth class.
        changed=dict(self.mix,INTERNAL_INTERNAL=11)
        with self.assertRaises(ValueError):percentage_document(changed)
        changed=dict(self.mix);changed.pop('INTERNAL_INTERNAL')
        with self.assertRaises(ValueError):percentage_document(changed)

    def test_fixed_public_vehicles_are_distinct_from_repeated_duties(self):
        service=json.loads(PUBLIC.read_text(encoding='utf8'))
        self.assertEqual(service['fleet_counts'],dict(transmetro=176,tubus=93))
        fleet=[];rows=[]
        for entry in service['services']:
            ids=['fixture-'+entry['service_id']+'-'+str(i) for i in range(entry['buses'])]
            fleet.extend(ids)
            rows.append(dict(system=entry['system'],configured_vehicle_ids=ids,
                scheduled_expeditions=40*len(ids)))
        self.assertEqual(len(fleet),269)
        self.assertEqual(distinct_fleet_by_system(rows,fleet),dict(transmetro=176,tubus=93))
        self.assertEqual(distinct_fleet_by_system(rows+copy.deepcopy(rows),fleet),dict(transmetro=176,tubus=93))
        self.assertEqual(10000+len(fleet),10269)
        self.assertGreater(sum(row['scheduled_expeditions'] for row in rows),len(fleet))
        changed=copy.deepcopy(rows);changed[-1]['configured_vehicle_ids'].append(fleet[0])
        with self.assertRaisesRegex(ValueError,'two systems'):distinct_fleet_by_system(changed,fleet)

    def test_small_real_generator_serializes_99_private_vehicles_and_keeps_freight_separate(self):
        quota=split(100,self.catalog);graph=model()
        def generate(directory):
            temporal=temporal_spec()
            people,report,allowed=gateway_people(graph,SEED,dict(mode='montecarlo',kind='fixed',minimum=99,maximum=99),
                named_percentages(self.mix),temporal,catalog=self.catalog,
                balanced_composition=quota,balanced_percentages=self.mix)
            people=typed_people(people,report,self.catalog,99,SEED,1,temporal,directory/'types.jsonl',
                preserve_departures=True,preserve_catalog_departures=True)
            ET.ElementTree(vehicle_types_xml(self.catalog)).write(directory/'types.xml',encoding='utf8',xml_declaration=True)
            write_population(directory/'plans.xml',directory/'vehicles.xml',people,directory/'types.xml',
                'Explicitly synthetic 99-private fixture, not a Run10K or observed traffic')
            verified=verify_population(directory/'plans.xml',directory/'vehicles.xml',99,allowed,1,True,spatial_model=graph)
            verify_type_ledger(directory/'plans.xml',directory/'types.jsonl',self.catalog)
            return report,verified
        with tempfile.TemporaryDirectory(prefix='run10k-small-inputs-') as temporary:
            first,second=(Path(temporary)/part for part in ('first','second'))
            first.mkdir();second.mkdir()
            report,verified=generate(first);again,reverified=generate(second)
            self.assertEqual(report,again);self.assertEqual(verified,reverified)
            self.assertEqual((first/'plans.xml').read_bytes(),(second/'plans.xml').read_bytes())
            self.assertEqual((first/'vehicles.xml').read_bytes(),(second/'vehicles.xml').read_bytes())
            people=ET.parse(first/'plans.xml').getroot().findall('person')
            vehicles=ET.parse(first/'vehicles.xml').getroot().findall('{*}vehicle')
            self.assertEqual(len({row.get('id') for row in people}),99)
            self.assertEqual({row.get('id') for row in people},{row.get('id') for row in vehicles})
            self.assertEqual(Counter(row.findtext("attributes/attribute[@name='simz1VehicleFamily']") for row in people),
                             dict(carro=44,moto=55))
            self.assertNotIn('TransportePesado',{row.get('type') for row in vehicles})
            audit=report['balanced_od_audit']
            self.assertEqual((audit['requested_non_public'],audit['private_vehicles'],audit['freight_vehicles']),(100,99,1))
            self.assertEqual(verified['spatial_od_counts'],allocate(99,named_percentages(self.mix),SEED)[1])
            self.assertTrue(all(value is None for value in audit['observed'].values()))
            self.assertFalse((first/'run-manifest.json').exists())


if __name__=='__main__':unittest.main()
