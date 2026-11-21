"""Native receiving-queue stop proxies preserve source stations and chronology."""
import json
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from simz1_stop_proxy import StopGeometry, POLICY
from simz1_weekday_transit import (HISTORICAL_DEFAULT as DEFAULT, load_policy, load_routes, prepared_network, build_plan,
                                 stop_proxy_lanes, attach, verify_policy_chain)
from simz1_transit_events import _attributes
from test_simz1_weekday_transit import resolved_config, BASE


def synthetic_geometry(short_receiving_queue=True):
    nodes={str(i):ET.Element('node',id=str(i),x=str(x),y='0')
           for i,x in enumerate((0,20,120,220,240))}
    links={ident:ET.Element('link',id=ident,attrib={'from':str(i),'to':str(i+1),'length':str(length),
               'permlanes':'1','modes':'car,bus'}) for i,(ident,length) in enumerate((('entry',20),('safe',100),('source',100),('exit',20)))}
    lanes={}
    for ident, endpoint in [('safe',50),('source',10 if short_receiving_queue else 50)]:
        lanes[ident]={ident+'.original':dict(start=100,to_lanes=[ident+'.terminal'],to_links=[]),
                      ident+'.terminal':dict(start=100-endpoint,to_lanes=[],to_links=['exit'])}
    return StopGeometry(links,nodes,lanes)


class StopProxyTests(unittest.TestCase):
    def test_nominal_setback_matches_published_native_java_fixture_domains(self):
        fixture=json.loads((Path(__file__).parent/'fixtures/simz1_stop_proxy_native_geometry.json').read_text(encoding='utf-8'))
        nodes={row['id']:ET.Element('node',attrib=row) for row in fixture['nodes']}
        links={row['id']:ET.Element('link',attrib=row) for row in fixture['links']}
        geometry=StopGeometry(links,nodes)
        self.assertTrue(fixture['native_last_link_setbacks'])
        for link,expected in fixture['native_last_link_setbacks'].items():
            self.assertAlmostEqual(geometry.setback(link),expected,places=9)

    def test_long_link_with_short_original_queue_cannot_host_bus(self):
        geometry=synthetic_geometry()
        source=dict(stop_id='source-station',link_index=2,source_position=[-90.5,14.6])
        row=geometry.place(['entry','safe','source','exit'],[source],13.5)[0]
        proxy=row['proxy_placement']
        self.assertEqual(row['stop_id'],'source-station')
        self.assertEqual(row['link_index'],1)
        self.assertEqual(proxy['original_link_id'],'source')
        self.assertEqual(proxy['original_native_position_xy'],[220,0])
        self.assertEqual(proxy['source_position'],[-90.5,14.6])
        self.assertEqual(proxy['native_service_endpoint_m'],50)
        self.assertEqual(proxy['native_queue_id'],'safe.original')
        self.assertEqual(proxy['modeled_front_fraction'],.5)
        self.assertEqual(source['link_index'],2,'Never mutate dated route evidence')

    def test_no_safe_queue_fails_instead_of_placing_bus_in_intersection(self):
        geometry=synthetic_geometry()
        geometry.lanes['safe']['safe.terminal']['start']=95
        with self.assertRaisesRegex(ValueError,'no body-safe ordered proxy'):
            geometry.place(['entry','safe','source','exit'],[dict(stop_id='s',link_index=2)],13.5)

    def test_repeated_stops_remain_distinct_and_ordered(self):
        geometry=synthetic_geometry(False)
        rows=geometry.place(['entry','safe','source','exit'],
            [dict(stop_id='first',link_index=1),dict(stop_id='second',link_index=2)],12)
        self.assertEqual([(row['stop_id'],row['link_index']) for row in rows],[('first',1),('second',2)])
        self.assertTrue(all(not row['proxy_placement']['relocated'] for row in rows))

    def test_nominal_crossing_setback_accounts_for_reverse_lanes(self):
        geometry=synthetic_geometry(False)
        geometry.nodes.update(south=ET.Element('node',id='south',x='220',y='-20'),
                              north=ET.Element('node',id='north',x='220',y='20'))
        for ident,start,end in [('cross','south','3'),('reverse','3','south')]:
            geometry.links[ident]=ET.Element('link',id=ident,attrib={'from':start,'to':end,'length':'20','permlanes':'2','modes':'car'})
        geometry=StopGeometry(geometry.links,geometry.nodes)
        self.assertEqual(geometry.setback('source'),8.)  # 2m base + 0.5*3m*four nominal lanes.

    def test_all_published_proxies_fit_actual_receiving_queues_and_keep_original_sources(self):
        policy,path=load_policy(DEFAULT,'2026-10-23',True)
        bundle,_=load_routes(policy,path,BASE); network=prepared_network(BASE,bundle)
        config=resolved_config();lanes=stop_proxy_lanes(config,BASE.parent)
        plan=build_plan(policy,bundle,network,1,lanes)
        proxies=[stop for stop in plan['stops'] if stop['role']!='gateway']
        self.assertTrue(plan['stop_proxy_summary']['enabled'])
        self.assertTrue(any(stop['proxy_placement']['relocated'] for stop in proxies))
        for stop in proxies:
            record=stop['proxy_placement']
            self.assertEqual(record['policy'],POLICY)
            self.assertGreaterEqual(record['modeled_front_fraction']*record['link_length_m']+1e-8,
                                    record['body_length_m']+.1+record['entry_setback_m'])
            self.assertLessEqual(record['modeled_front_fraction']*record['link_length_m'],record['native_service_endpoint_m']+1e-8)
            self.assertEqual(record['source_position'],stop['source_position'])
        legacy=dict(policy);legacy.pop('stop_placement_policy')
        historical=build_plan(legacy,bundle,network,1,lanes)
        self.assertFalse(historical['stop_proxy_summary']['enabled'])
        self.assertTrue(all('proxy_placement' not in stop for stop in historical['stops']))
        self.assertEqual(len(plan['roster']),len(historical['roster']))

    def test_saved_proxy_manifest_is_hashed_and_native_schedule_must_match(self):
        with tempfile.TemporaryDirectory() as directory:
            output=Path(directory)/'service';config=resolved_config()
            summary=attach(config,output,1,DEFAULT,'2026-10-23',True)
            schedule=ET.parse(output/'transitSchedule.xml').getroot();meta=_attributes(schedule)
            policy,_=verify_policy_chain(output/'transitSchedule.xml',meta,1)
            self.assertEqual(summary['stop_proxy_manifest_sha256'],policy['stop_proxy_manifest_sha256'])
            for route in schedule.findall('.//transitRoute'):
                self.assertEqual(route.find('routeProfile').findall('stop')[-1].get('awaitDeparture'),'false')
            row=next(s for s in schedule.findall('transitStops/stopFacility') if _attributes(s).get('simz1:stopProxy'))
            row.set('x',str(float(row.get('x'))+1))
            ET.ElementTree(schedule).write(output/'transitSchedule.xml')
            with self.assertRaisesRegex(ValueError,'stop proxy differs'):
                verify_policy_chain(output/'transitSchedule.xml',meta,1)


if __name__=='__main__':unittest.main()
