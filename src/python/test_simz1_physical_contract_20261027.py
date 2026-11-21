"""Versioned body contract checks; no QSim or fabricated measurements."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from simz1_freight import BODY_CONTRACT, attach, preflight, presentation_dimensions, verified_contract
from simz1_run import artifact

ROOT=Path(__file__).resolve().parents[1]
SERVICE=ROOT/'scenarios/zona1/freight/weekday-v1/service.json'
CONFIG=ROOT/'scenarios/zona1/config-simz1.xml'


class PhysicalBodyContractTests(unittest.TestCase):
    def test_python_preflight_rejects_sub_decimeter_gap_and_accepts_exact_boundary(self):
        from simz1_config_validation import validate_configuration, ConfigurationError
        for gap in (.09, .09999999999999999, .1):
            root=ET.parse(CONFIG).getroot()
            module=ET.SubElement(root,'module',name='simz1LanePolicy')
            ET.SubElement(module,'param',name='minimumGapM',value=str(gap))
            if gap < .1:
                with self.assertRaisesRegex(ConfigurationError,'minimumGapM'):
                    validate_configuration(root)
            else:
                result=validate_configuration(root)
                self.assertFalse(result['lane_policy']['requested_enabled'])
                self.assertEqual(result['lane_policy']['parameters']['minimumGapM'], .1)

    def test_shared_body_matches_saved_tubus_and_is_not_derived_from_pcu(self):
        service=json.loads(SERVICE.read_text(encoding='utf-8'))
        public=json.loads((ROOT/'scenarios/zona1/transit/weekday-v2/service.json').read_text(encoding='utf-8'))
        bus=next(row for row in public['vehicle_types'] if row['type_id']=='TuBus_RigidProxy')
        body=presentation_dimensions(service,bus)
        self.assertEqual(service['body_contract'],BODY_CONTRACT)
        self.assertEqual(body['length_m'],service['length_m'])
        self.assertEqual(body['width_m'],service['width_m'])
        self.assertEqual((body['length_m'],body['width_m']),(12,2.5))
        changed=deepcopy(service);changed['pcu']=.25
        self.assertEqual(presentation_dimensions(changed,bus),body,'PCU is not body geometry')
        self.assertEqual(presentation_dimensions(service)['length_m'],12,'NoPublicTransport default remains explicit')

    def test_existing_snapshot_keeps_its_original_native_and_visual_dimensions(self):
        legacy=dict(length_m=10,width_m=2.5,pcu=3.5)
        before=deepcopy(legacy)
        self.assertEqual(presentation_dimensions(legacy)['length_m'],12)
        self.assertEqual(presentation_dimensions(legacy,dict(length_m=13,width_m=2.4))['length_m'],13)
        self.assertEqual(legacy,before,'Historic physical body must not be rewritten')

    def test_incompatible_new_body_cannot_silently_override_native_size(self):
        service=json.loads(SERVICE.read_text(encoding='utf-8'))
        with self.assertRaisesRegex(ValueError,'differs from configured'):
            presentation_dimensions(service,dict(length_m=13.5,width_m=2.5))
        bad=dict(service,body_contract='unknown')
        with self.assertRaisesRegex(ValueError,'unsupported'):presentation_dimensions(bad)
        for length in (0,-1,float('nan'),float('inf'),True):
            with self.assertRaisesRegex(ValueError,'invalid'):presentation_dimensions(dict(service,length_m=length))

    def test_native_xml_preflight_and_manifest_share_the_same_saved_body(self):
        with tempfile.TemporaryDirectory() as td:
            run=Path(td);(run/'inputs').mkdir()
            (run/'plans.xml').write_text('<population>\n</population>\n',encoding='utf-8')
            (run/'inputs/vehicles.xml').write_text('<vehicleDefinitions xmlns="http://www.matsim.org/files/dtd"/>',encoding='utf-8')
            manifest=attach(run,CONFIG,SERVICE,vehicles=1)
            flight=preflight(CONFIG,SERVICE,vehicles=1)
            native=ET.parse(run/'inputs/vehicles.xml').getroot().find("{*}vehicleType[@id='FreightTruck']")
            saved=json.loads((run/'inputs/freight-weekday/service.json').read_text(encoding='utf-8'))
            self.assertEqual(manifest['body_contract'],BODY_CONTRACT)
            self.assertEqual(manifest['native_dimensions_m'],flight['native_dimensions_m'])
            self.assertEqual(float(native.find('{*}length').get('meter')),saved['length_m'])
            self.assertEqual(float(native.find('{*}width').get('meter')),saved['width_m'])
            self.assertEqual(native.find("{*}attributes/{*}attribute[@name='simz1FreightBodyContract']").text,BODY_CONTRACT)
            record=dict(freight_transport=manifest,inputs=dict(plans=artifact(run,run/'plans.xml')))
            record['inputs']['input:vehicles.xml']=artifact(run,run/'inputs/vehicles.xml')
            for name in ('service.json','routes.json','roster.json'):
                record['inputs']['input:freight-weekday/'+name]=artifact(run,run/'inputs/freight-weekday'/name)
            self.assertEqual(len(verified_contract(run,record)),1)
            bad=deepcopy(record);bad['freight_transport']['native_dimensions_m']['length_m']=10
            with self.assertRaisesRegex(ValueError,'differs from manifest'):verified_contract(run,bad)
            # A re-fingerprinted but inconsistent native type must also fail;
            # hashes alone do not establish agreement between saved artifacts.
            tree=ET.parse(run/'inputs/vehicles.xml')
            tree.getroot().find("{*}vehicleType[@id='FreightTruck']/{*}length").set('meter','10')
            tree.write(run/'inputs/vehicles.xml',encoding='utf-8')
            record['inputs']['input:vehicles.xml']=artifact(run,run/'inputs/vehicles.xml')
            with self.assertRaisesRegex(ValueError,'native VehicleType differs'):verified_contract(run,record)


if __name__=='__main__':unittest.main()
