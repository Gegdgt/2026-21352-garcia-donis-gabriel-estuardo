"""Phase 6 launch/evidence tests. Small synthetic data only; never invokes QSim."""
import gzip
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from simz1_balanced_execute import arguments
from simz1_balanced_launch import identity, manifest_identity, check
from simz1_balanced_launch_report import Observation, GrowingEvents, report
from simz1_balanced_od import ACCESS_SCHEMA, BOUNDARY_SCHEMA, digest
from simz1_workflow_state import require_balanced_validation
# Import fixture builders, not TestCase classes; no Correction 5 test is run here.
from test_simz1_balanced_gateway_od import model, record, MIX, reviewed


def files(folder):
    boundary, access, mix = (folder/name for name in ('perimeter.geojson','access.json','mix.json'))
    # Shape is immaterial to identity(); load_model still validates actual geometry.
    boundary.write_text('{}',encoding='utf-8')
    review = dict(verified=True,version='review-v1',source='local review record',
                  reviewed_by='reviewer',reviewed_at='2026-11-01')
    access.write_text(json.dumps(dict(schema_version=ACCESS_SCHEMA,review=review,
        perimeter=dict(review,schema_version=BOUNDARY_SCHEMA,sha256=digest(boundary)))),encoding='utf-8')
    mix.write_text(json.dumps(MIX),encoding='utf-8')
    return boundary,access,mix


class LaunchContracts(unittest.TestCase):
    def test_no_perimeter_or_mix_has_no_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            boundary,access,mix = files(Path(tmp))
            boundary.unlink()
            with self.assertRaisesRegex(ValueError,'zone-boundary'):
                identity(boundary,access,mix)
            with self.assertRaisesRegex(ValueError,'OdMixFile'):
                identity(boundary,access,None)

    def test_unverified_and_synthetic_access_cannot_launch(self):
        with tempfile.TemporaryDirectory() as tmp:
            b,a,m = files(Path(tmp))
            doc = json.loads(a.read_text())
            doc['review']['verified'] = False
            a.write_text(json.dumps(doc))
            with self.assertRaises(ValueError): identity(b,a,m)
            doc['review'] = reviewed()
            a.write_text(json.dumps(doc))
            with self.assertRaisesRegex(ValueError,'ejemplo/prueba'): identity(b,a,m)

    def test_trial_identity_binds_perimeter_access_and_mix(self):
        with tempfile.TemporaryDirectory() as tmp:
            b,a,m = files(Path(tmp))
            original = identity(b,a,m)
            manifest = dict(origin_policy=original['origin_policy'],
                spatial_demand=dict(mode=original['od_mode'],hypothesis=dict(sha256=original['hypothesis_sha256'])),
                inputs=dict(zone_boundary=dict(sha256=original['boundary_sha256'])),
                balanced_od=dict(access_catalog=dict(sha256=original['access_sha256'])))
            self.assertEqual(manifest_identity(manifest),original)
            self.assertNotEqual(manifest_identity({'origin_policy':'uniform-nodes-v1'}),original)
            b.write_text('{"changed":true}')
            self.assertNotEqual(identity(b,a,m),original)
            m.write_text(json.dumps(dict(zip(MIX,(10,20,30,40)))))
            self.assertNotEqual(identity(b,a,m)['hypothesis_sha256'],original['hypothesis_sha256'])

    def test_invalid_percentages_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            b,a,m = files(Path(tmp))
            m.write_text(json.dumps(dict(MIX,INTERNAL_INTERNAL=24)))
            with self.assertRaisesRegex(ValueError,'exactly to 100'): identity(b,a,m)

    def test_adapter_preserves_decimal_json_as_one_argument(self):
        import argparse
        from generate_montecarlo_z1 import add_generation_options, generation_options, spatial_options
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'mix with spaces.json'
            raw = '{"INTERNAL_INTERNAL":33.3,"INTERNAL_EXTERNAL":33.3,"EXTERNAL_INTERNAL":33.3,"EXTERNAL_EXTERNAL_THROUGH":0.1}'
            path.write_text(raw)
            result = arguments(['--od-mix-file',str(path),'--od-mode','balanced-gateway-v1','--iterations','1'])
            self.assertEqual(result[-2:],['--od-mix',raw])
            self.assertEqual(result[:4],['--od-mode','balanced-gateway-v1','--iterations','1'])
            parser = argparse.ArgumentParser()
            parser.add_argument('--iterations',type=int)
            add_generation_options(parser)
            parsed = parser.parse_args(result)
            self.assertIsNone(generation_options(parsed)['corridor_policy'])
            # The balanced generator must reject the historical corridor flag.
            with self.assertRaisesRegex(ValueError,'corridor-policy'):
                spatial_options('balanced-gateway-v1',path,None,mode='montecarlo',
                    trips_per_person=1,temporal_profile=None,corridor_policy='redistribute')
            with self.assertRaises(ValueError):
                arguments(['--od-mix-file',str(path),'--od-mode','network'])
            with self.assertRaises(ValueError):
                arguments(['--od-mix-file',str(path),'--od-mode','balanced-gateway-v1','--od-mix','{}'])
            with self.assertRaises(ValueError):
                arguments(['--od-mix-file',str(path),'--od-mode','balanced-gateway-v1','--od-mix={}'])

    def test_preflight_cannot_launch_other_N_or_seed(self):
        with tempfile.TemporaryDirectory() as tmp:
            b,a,m = files(Path(tmp))
            for total,seed in ((220000,20261023),(110000,5)):
                with self.subTest(total=total,seed=seed),self.assertRaisesRegex(ValueError,'Balanced scale'):
                    check('missing-config','missing-catalog',total,b,a,m,seed)

    def test_stale_integrated_validation_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            directory = root/'runtime/workflow'; directory.mkdir(parents=True)
            receipt = directory/'validated-balanced-gateway-v1.json'
            receipt.write_text(json.dumps(dict(status='integrated_validate_pass',od_mode='balanced-gateway-v1',source_fingerprint='old')))
            with patch('simz1_workflow_state.PROJECT',root),patch('simz1_workflow_state.fingerprint',return_value='current'):
                with self.assertRaises(ValueError): require_balanced_validation()
                doc = json.loads(receipt.read_text()); doc['source_fingerprint']='current'
                receipt.write_text(json.dumps(doc))
                require_balanced_validation()


class ObservationContracts(unittest.TestCase):
    def test_minute_hour_counters_distinguish_waiting_and_active_services(self):
        obs = Observation(model(),{},freight_ids={'truck'},bus_ids={'bus'})
        def event(at,kind,**kw): obs.consume(dict(time=str(at),type=kind,**kw))
        event(0,'departure',person='truck',link='a')
        self.assertEqual(obs.snapshot()['waiting_to_incorporate'],1)
        event(1,'vehicle enters traffic',vehicle='truck',link='a')
        event(1,'entered link',vehicle='truck',link='a')
        event(2,'left link',vehicle='truck',link='a')
        event(2,'entered link',vehicle='truck',link='b')
        event(3,'simz1NativeDecision',vehicle='truck',reason='storage_wait')
        event(30,'vehicle enters traffic',vehicle='bus',link='a')
        event(3600,'simz1Progress')
        self.assertEqual(obs.hours[0]['transitions'],1)
        self.assertEqual(obs.hours[0]['entries'],2)
        self.assertEqual(obs.minutes[0]['storage_wait_attempts'],1)
        self.assertEqual(obs.snapshot()['waiting_to_incorporate'],0)
        self.assertEqual(obs.snapshot()['freight_active'],1)
        self.assertEqual(obs.snapshot()['buses_active'],1)
        event(3601,'vehicle leaves traffic',vehicle='truck',link='b')
        self.assertEqual(obs.counts['arrivals'],0)
        event(3601,'arrival',person='truck',link='b')
        self.assertEqual(obs.counts['freight_arrivals'],1)

    def test_unproven_exterior_arrival_never_increments_gateway(self):
        row = dict(record(),planned_departure=0.)
        obs = Observation(model(),{'private':row})
        with self.assertRaises(ValueError):
            obs.consume(dict(type='arrival',person='private',link=row['destination_link'],time='86400'))
        self.assertEqual(dict(obs.gateway_exits),{})

    def test_live_gzip_prefix_is_provisional_and_can_continue(self):
        data = gzip.compress(b'<events><event time="0" type="simz1Progress"/></events>')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'events.xml.gz'
            path.write_bytes(data[:-8])
            reader = GrowingEvents(path)
            try:
                self.assertEqual(len(list(reader.poll())),1)
                self.assertFalse(reader.decoder.eof)
                with path.open('ab') as stream: stream.write(data[-8:])
                self.assertEqual(list(reader.poll()),[])
                self.assertTrue(reader.decoder.eof)
                self.assertTrue(reader.closed_xml)
            finally: reader.close()

    def test_invalid_xml_does_not_become_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'events.xml.gz'
            path.write_bytes(gzip.compress(b'<events><event time="0"></events>'))
            reader = GrowingEvents(path)
            try:
                with self.assertRaises(ET.ParseError): list(reader.poll())
            finally: reader.close()

    def test_failed_manifest_cannot_publish_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch('simz1_balanced_launch_report.load_manifest',return_value=dict(status='failed',validation=dict(status='valid'))):
                with self.assertRaisesRegex(ValueError,'completed/valid'): report(root)
            self.assertFalse((root/'analysis').exists())


if __name__ == '__main__':
    unittest.main()
