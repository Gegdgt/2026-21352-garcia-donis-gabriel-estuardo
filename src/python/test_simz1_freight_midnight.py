"""Midnight is permitted circulation; censoring is still an incomplete service."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from simz1_freight import (WINDOWS,LEGACY_WINDOWS,OVERNIGHT_POLICY,LEGACY_RESIDENCE_POLICY,
                           permitted,residence_contract,FreightAudit,prepare)

ROOT=Path(__file__).resolve().parents[1]
CONFIG=ROOT/'scenarios/zona1/config-simz1.xml'
SERVICE=ROOT/'scenarios/zona1/freight/weekday-v1/service.json'


class FreightMidnightTests(unittest.TestCase):
    def test_evening_residence_crosses_midnight_and_finishes_before_next_day_five(self):
        for end in (86399,86400,86401,104399):self.assertTrue(permitted(77400,end))
        self.assertFalse(permitted(77400,104400))
        self.assertFalse(permitted(57599,86400))
        self.assertFalse(permitted(17999,86400))

    def test_legacy_snapshot_is_explicit_and_unchanged(self):
        policy=dict(allowed_windows_seconds=deepcopy(LEGACY_WINDOWS))
        before=deepcopy(policy)
        self.assertEqual(residence_contract(policy),(LEGACY_RESIDENCE_POLICY,LEGACY_WINDOWS))
        self.assertEqual(policy,before)
        self.assertFalse(permitted(77400,86400,windows=LEGACY_WINDOWS))
        with self.assertRaisesRegex(ValueError,'unsupported'):
            residence_contract(dict(policy,residence_policy=OVERNIGHT_POLICY))
        self.assertEqual(residence_contract(json.loads(SERVICE.read_text(encoding='utf-8'))),(OVERNIGHT_POLICY,WINDOWS))

    def test_midnight_departure_day_limit_and_saved_policy(self):
        policy,_,_=prepare(CONFIG,SERVICE,vehicles=1)
        self.assertEqual(policy['residence_policy'],OVERNIGHT_POLICY)
        with tempfile.TemporaryDirectory() as temporary:
            folder=Path(temporary)
            (folder/'routes.json').write_bytes((SERVICE.parent/'routes.json').read_bytes())
            policy['departure_slots_seconds']=[86400]
            (folder/'service.json').write_text(json.dumps(policy),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'departure slots'):
                prepare(CONFIG,folder/'service.json')

    def test_midnight_is_not_restricted_but_censored_or_aborted_expedition_fails(self):
        row=dict(vehicle_id='h',driver_id='h',departure_seconds=77400,link_ids=['a','b','c'],
                 allowed_windows_seconds=WINDOWS,residence_policy=OVERNIGHT_POLICY)
        audit=FreightAudit({'h':row})
        def event(kind,time,link='a'):
            return dict(type=kind,time=str(time),link=link,person='h',vehicle='h')
        audit.consume(event('departure',77400));audit.consume(event('vehicle enters traffic',77400))
        audit.consume(event('left link',86400))
        self.assertEqual(audit.summary()['active_or_censored'],1)
        audit.consume(event('stuckAndAbort',86400))
        self.assertEqual(audit.summary()['aborted_expeditions'],1)
        self.assertEqual(audit.summary()['restricted_window_violations'],0)
        self.assertEqual(audit.summary()['status'],'invalid')
        with self.assertRaisesRegex(ValueError,'without active departure'):
            audit.consume(event('arrival',86403,'c'))
        self.assertEqual(audit.summary()['arrivals_observed'],0)
        self.assertEqual(audit.summary()['residence_window_policies'],[OVERNIGHT_POLICY])


if __name__=='__main__':unittest.main()
