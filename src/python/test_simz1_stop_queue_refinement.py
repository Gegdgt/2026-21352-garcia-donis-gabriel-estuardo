"""Derived stop queue splits preserve native routes, bodies and source inputs."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from simz1_stop_proxy import adjust_service_queues, lane_assignments, QUEUE_POLICY, LEGACY_QUEUE_POLICY
from simz1_weekday_transit import (HISTORICAL_DEFAULT as DEFAULT, attach, verify_policy_chain, load_policy, load_routes,
                                 prepared_network, plan_with_service_queues)
from simz1_transit_events import _attributes
from test_simz1_stop_proxy import synthetic_geometry
from test_simz1_weekday_transit import BASE, resolved_config


class StopQueueRefinementTests(unittest.TestCase):
    def test_short_terminal_split_preserves_body_stop_and_every_non_length_lane_property(self):
        geometry=synthetic_geometry()
        network=ET.Element('network');nodes=ET.SubElement(network,'nodes');links=ET.SubElement(network,'links')
        nodes.extend(geometry.nodes.values());links.extend(geometry.links.values())
        root=ET.Element('laneDefinitions')
        for ident,rows in geometry.lanes.items():
            assignment=ET.SubElement(root,'lanesToLinkAssignment',linkIdRef=ident)
            for name,row in rows.items():
                lane=ET.SubElement(assignment,'lane',id=name);lead=ET.SubElement(lane,'leadsTo')
                for target in row['to_lanes']: ET.SubElement(lead,'toLane',refId=target)
                for target in row['to_links']: ET.SubElement(lead,'toLink',refId=target)
                ET.SubElement(lane,'startsAt',meterFromLinkEnd=str(row['start']))
                ET.SubElement(lane,'representedLanes',number='1')
                ET.SubElement(lane,'capacity',vehiclesPerHour='2000')
                ET.SubElement(lane,'alignment').text='0'
        original=ET.tostring(root); before=deepcopy(root)
        source=dict(stop_id='source',link_id='source',role='passenger_stop',
                    proxy_placement=dict(body_length_m=13.5))
        summary=adjust_service_queues(root,network,[source])
        self.assertEqual(summary['adjusted_links'],1)
        self.assertEqual(summary['adjustments'][0]['old_native_service_endpoint_m'],10)
        self.assertEqual(summary['adjustments'][0]['new_native_service_endpoint_m'],98)
        self.assertEqual(lane_assignments(root)['source']['source.terminal']['start'],2)
        for new,old in zip(root.iter(),before.iter()):
            if new.tag=='startsAt': new.attrib.clear();new.attrib.update(old.attrib)
        self.assertEqual(ET.tostring(root),original,'Only terminal startsAt changes; no fictitious extra link length/flow')

    def test_new_snapshot_preserves_more_stations_and_hashes_exact_lane_derivation(self):
        policy,path=load_policy(DEFAULT,'2026-10-23',True); bundle,_=load_routes(policy,path,BASE)
        network=prepared_network(BASE,bundle)
        config=resolved_config()
        source=Path(config.find("module[@name='network']/param[@name='laneDefinitionsFile']").get('value'))
        source_bytes=source.read_bytes()
        new,_=plan_with_service_queues(policy,bundle,network,1,config,BASE.parent)
        historical=deepcopy(policy);historical.pop('stop_queue_policy')
        old,_=plan_with_service_queues(historical,bundle,network,1,config,BASE.parent)
        self.assertEqual(old['stop_queue_summary'],dict(enabled=False,policy=LEGACY_QUEUE_POLICY))
        self.assertEqual({s['stop_id'] for s in old['stops']},{s['stop_id'] for s in new['stops']})
        self.assertEqual(new['roster'],old['roster'])
        self.assertLess(new['stop_proxy_summary']['relocated_stops'],old['stop_proxy_summary']['relocated_stops'])
        self.assertEqual(new['stop_queue_summary']['policy'],QUEUE_POLICY)
        with tempfile.TemporaryDirectory() as directory:
            output=Path(directory)/'fleet';summary=attach(resolved_config(),output,1,DEFAULT,'2026-10-23',True)
            schedule=ET.parse(output/'transitSchedule.xml').getroot();metadata=_attributes(schedule)
            saved,_=verify_policy_chain(output/'transitSchedule.xml',metadata,1)
            queues=saved['stop_queue_summary']
            self.assertEqual(summary['stop_queues'],queues)
            self.assertEqual(queues['source_lanes_sha256'],hashlib.sha256(source_bytes).hexdigest())
            self.assertEqual(queues['generated_lanes_sha256'],hashlib.sha256((output/'lanes.xml').read_bytes()).hexdigest())
            assignments=lane_assignments(ET.parse(output/'lanes.xml').getroot())
            for stop in json.loads((output/'stops.json').read_text(encoding='utf-8')):
                proxy=stop.get('proxy_placement')
                if proxy is None or stop['link_id'] not in assignments: continue
                lanes=assignments[stop['link_id']];original=lanes[proxy['native_queue_id']]
                endpoint=proxy['link_length_m']-max(lanes[x]['start'] for x in original['to_lanes'])
                self.assertAlmostEqual(proxy['native_service_endpoint_m'],endpoint)
                self.assertAlmostEqual(endpoint,proxy['link_length_m']-proxy['end_setback_m'])
                self.assertGreaterEqual(endpoint+1e-9,proxy['body_length_m']+.1+proxy['entry_setback_m'])
            (output/'lanes.xml').write_bytes((output/'lanes.xml').read_bytes()+b'\n')
            with self.assertRaisesRegex(ValueError,'native stop queue lane fingerprint'):
                verify_policy_chain(output/'transitSchedule.xml',metadata,1)
        self.assertEqual(source.read_bytes(),source_bytes,'Imported/base lane file must remain untouched')


if __name__=='__main__': unittest.main()
