from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from simz1_freight import prepare, preflight, permitted, FreightAudit, verified_contract
from simz1_run import population, load_manifest
from generate_montecarlo_z1 import generar

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT/'scenarios/zona1/config-simz1.xml'
SERVICE = ROOT/'scenarios/zona1/freight/weekday-v1/service.json'
CATALOG = ROOT/'scenarios/zona1/agent-types-car-moto-v1.json'


class FreightTests(unittest.TestCase):
    def test_transit_audit_keeps_private_denominator_and_accepts_verified_freight(self):
        from simz1_transit_events import TransitEventAudit
        audit=TransitEventAudit(dict(vehicle_modes={},departures={}), {'car'}, {'freight'})
        self.assertFalse(audit.consume({'type':'departure','person':'freight','vehicle':'freight'}))
        self.assertEqual(audit.road_ids, {'car'})
        with self.assertRaisesRegex(ValueError,'ajena'):
            audit.consume({'type':'departure','person':'unregistered'})
        with self.assertRaisesRegex(ValueError,'overlap'):
            TransitEventAudit(dict(vehicle_modes={},departures={}), {'car'}, {'car'})

    def test_half_open_windows_and_queue_crossing(self):
        for t in (0,17999,32400,57599,75600,86399,86400,104399): self.assertTrue(permitted(t))
        for t in (-1,18000,32399,57600,75599,104400,float('nan')): self.assertFalse(permitted(t))
        self.assertFalse(permitted(17999,32401))
        self.assertFalse(permitted(57599,75601))

    def test_date_quantity_routes_and_departures(self):
        p,b,roster = prepare(CONFIG,SERVICE,vehicles=15)
        self.assertEqual(len(roster),15)
        self.assertEqual(len({r['vehicle_id'] for r in roster}),15)
        self.assertTrue(all(permitted(r['departure_seconds']) for r in roster))
        self.assertEqual(len(b['routes']),4)
        for bad in (0,-1,True,1.5):
            with self.assertRaises(ValueError): prepare(CONFIG,SERVICE,vehicles=bad)
        with self.assertRaisesRegex(ValueError,'Monday-Friday'): prepare(CONFIG,SERVICE,'2026-10-24')
        with self.assertRaisesRegex(ValueError,'one civil day'): preflight(CONFIG,SERVICE,temporal_policy={})

    def test_missing_incomplete_fleet_route_and_window_fail(self):
        row = dict(vehicle_id='h', driver_id='h', departure_seconds=32400,link_ids=['a','b','c'])
        audit = FreightAudit({'h':row})
        self.assertEqual(audit.summary()['missing_departures'], 1)
        self.assertEqual(audit.summary()['status'], 'invalid')
        def ev(kind,t,link,person=True):
            return dict(type=kind,time=str(t),link=link,**({'person':'h'} if person else {'vehicle':'h'}))
        audit.consume(ev('departure',32400,'a'))
        audit.consume(dict(ev('vehicle enters traffic',32400,'a'),vehicle='h'))
        with self.assertRaisesRegex(ValueError,'sequence'): audit.consume(ev('entered link',32410,'c',False))
        audit.consume(ev('entered link',32410,'b',False))
        audit.consume(ev('left link',57600,'b',False))
        audit.consume(ev('entered link',57601,'c',False))
        audit.consume(ev('arrival',57602,'c'))
        self.assertEqual(audit.summary()['vehicles_observed'],1)
        self.assertEqual(audit.summary()['restricted_window_violations'],1)
        self.assertEqual(audit.summary()['status'],'invalid')

    def test_invalid_pbv_and_interior_endpoints_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            folder=Path(td)
            policy=json.loads(SERVICE.read_text(encoding='utf-8'))
            routes=json.loads((SERVICE.parent/'routes.json').read_text(encoding='utf-8'))
            (folder/'routes.json').write_text(json.dumps(routes),encoding='utf-8')
            policy['gross_weight_tonnes']=3.5
            (folder/'service.json').write_text(json.dumps(policy),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'PBV'): prepare(CONFIG,folder/'service.json')
            policy['gross_weight_tonnes']=12
            (folder/'service.json').write_text(json.dumps(policy),encoding='utf-8')
            routes['routes'][0]['link_ids']=routes['routes'][0]['link_ids'][4:-4]
            (folder/'routes.json').write_text(json.dumps(routes),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'boundary'): prepare(CONFIG,folder/'service.json')

    def test_separate_n_fingerprints_and_disable(self):
        with tempfile.TemporaryDirectory() as td:
            rosters=[]
            for n in (10,20):
                folder=Path(td)/str(n)
                generar(CONFIG,folder,42,agents=n,agent_catalog=CATALOG,origin_policy='uniform-nodes-v1',corridor_policy='redistribute',
                        freight_service=SERVICE,freight_vehicles=3)
                m=load_manifest(folder)
                ids,counts=population(folder/'plans.xml')
                self.assertEqual(counts['planned_persons'],n)
                self.assertEqual(len(ids),n+3)
                self.assertEqual(m['counts']['planned_trips'],n)
                self.assertEqual(len(verified_contract(folder,m)),3)
                rosters.append((folder/'inputs/freight-weekday/roster.json').read_bytes())
                bad=deepcopy(m);bad['freight_transport']['vehicles_configured']=4
                with self.assertRaisesRegex(ValueError,'mismatch'): verified_contract(folder,bad)
                bad=deepcopy(m);del bad['inputs']['input:freight-weekday/service.json']
                with self.assertRaisesRegex(ValueError,'Missing'): verified_contract(folder,bad)
                bad=deepcopy(m);bad['freight_transport']['service_date']='2026-10-22'
                with self.assertRaisesRegex(ValueError,'identity/date'): verified_contract(folder,bad)
                (folder/'inputs/freight-weekday/roster.json').write_text('[]',encoding='utf-8')
                with self.assertRaisesRegex(ValueError,'Hash'): verified_contract(folder,m)
            self.assertEqual(*rosters)
            folder=Path(td)/'disabled'
            generar(CONFIG,folder,42,agents=10,agent_catalog=CATALOG,origin_policy='uniform-nodes-v1',corridor_policy='redistribute',no_freight_transport=True)
            self.assertEqual(len(population(folder/'plans.xml')[0]),10)
            self.assertEqual(verified_contract(folder,load_manifest(folder)),{})


if __name__ == '__main__': unittest.main()
