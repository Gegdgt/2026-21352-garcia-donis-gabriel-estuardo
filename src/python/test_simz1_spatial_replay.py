"""Small in-memory OD replay contracts; no MATSim, export or source fixture is run."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from simz1_motion import MotionContext, load_selected
from simz1_trajectories import extract
from simz1_continuous_replay import ContinuousReplay


class SpatialReplayTests(unittest.TestCase):
    spatial = dict(allowed_links=['entry', 'exit'], internal_links=[],
                   entry_gateways={'entry': {}}, exit_gateways={'exit': {}})
    od = dict(od_type='external-external', origin_link='entry', destination_link='exit',
              origin_gateway='entry', destination_gateway='exit',
              origin_zone='synthetic-exterior-entry:entry', destination_zone='synthetic-exterior-exit:exit',
              scope='observed_z1_only', door_to_door_seconds=None, metadata_source='synthetic_gateway_od')
    key = 'p:trip:0001'

    def context(self):
        context = MotionContext({'v': 10})
        context.spatial_demand = copy.deepcopy(self.spatial)
        context.spatial_od = {self.key: copy.deepcopy(self.od)}
        return context

    def events(self):
        return [dict(type=kind, time=str(time), **attrs) for kind, time, attrs in (
            ('departure', 0, dict(person='p', link='entry')),
            ('vehicle enters traffic', 0, dict(person='p', vehicle='v', link='entry', relativePosition='0')),
            ('left link', 10, dict(vehicle='v', link='entry')),
            ('entered link', 10, dict(vehicle='v', link='exit')),
            ('vehicle leaves traffic', 20, dict(person='p', vehicle='v', link='exit', relativePosition='1')))]

    def extract(self, events, context):
        links = {name: dict(length=100, freespeed=10, from_node=str(i), to_node=str(i+1),
                           **{'from': [i*.001, 0], 'to': [(i+1)*.001, 0]})
                 for i, name in enumerate(('entry', 'exit'))}
        return extract(events, links, lambda _: True, lambda _: [1, 2, 3],
                       SimpleNamespace(inv=lambda *args: (0, 0, 100)), motion=context, horizon=86400)

    def test_observed_completion_and_censorship_keep_spatial_metadata_separate(self):
        context = self.context()
        native = copy.deepcopy(context.spatial_od)
        segments = self.extract(self.events()+[dict(type='arrival', time='21', person='p', link='exit')], context)
        self.assertEqual(segments[0]['Trip']['OD'], self.od)
        self.assertEqual(segments[0]['Trip']['Arrival'], 21)
        self.assertIs(segments[0]['Trip'], segments[1]['Trip'])
        censored = self.extract(self.events()+[dict(type='stuckAndAbort', time='86400', person='p')], self.context())
        self.assertEqual(censored[0]['Trip']['Status'], 'censored')
        self.assertIsNone(censored[0]['Trip']['Arrival'])
        self.assertIsNone(censored[0]['Trip']['OD']['door_to_door_seconds'])
        self.assertEqual(context.spatial_od, native)

    def test_missing_or_wrong_od_fails_before_publishing_a_spatial_trip(self):
        context = self.context(); context.spatial_od.clear()
        with self.assertRaisesRegex(ValueError, 'Salida sin OD'):
            self.extract(self.events(), context)
        with self.assertRaisesRegex(ValueError, 'Llegada fuera'):
            self.extract(self.events()+[dict(type='arrival', time='21', person='p', link='entry')], self.context())

    def test_four_od_native_entry_exit_and_duration_are_not_external_trip_time(self):
        context = self.context()
        context.spatial_od[self.key]['od_class'] = 'EXTERNAL_EXTERNAL_THROUGH'
        events = self.events()
        events[1]['time'] = '3'  # QSim admission later than the scheduled departure.
        segments = self.extract(events+[dict(type='arrival', time='25', person='p', link='exit')], context)
        trip = segments[0]['Trip']
        self.assertEqual((trip['System_Entry'], trip['System_Exit'], trip['Observed_Duration_Seconds']), (3, 20, 17))
        self.assertEqual(trip['Arrival']-trip['Departure'], 25)
        self.assertIsNone(trip['OD']['door_to_door_seconds'])
        partial = self.extract(events[:-1], context)[0]['Trip']
        self.assertIsNone(partial['System_Exit'])
        self.assertIsNone(partial['Observed_Duration_Seconds'])

    def test_person_metadata_survives_loading_and_matches_canonical_ledger(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            config = directory/'config.xml';config.write_text('<config/>', encoding='utf-8')
            plans = directory/'plans.xml'
            root = ET.Element('population');person = ET.SubElement(root, 'person', id='p')
            attrs = ET.SubElement(person, 'attributes')
            ledger = [dict(id=self.key, index=1, planned_departure=0, origin_link='entry', destination_link='exit')]
            for name, value in [('simz1Trips', ledger), ('simz1SpatialOD', {self.key: self.od})]:
                ET.SubElement(attrs, 'attribute', name=name).text = json.dumps(value)
            ET.ElementTree(root).write(plans, encoding='utf-8')
            artifact = lambda path: dict(path=path.name, sha256=hashlib.sha256(path.read_bytes()).hexdigest())
            manifest = dict(effective_config=artifact(config), inputs={'config': artifact(config)},
                            results={'0': {'plans': artifact(plans)}})
            selection = dict(directory=directory, manifest=manifest, plans=plans, iteration=0)
            with patch('simz1_gateway_od.validated_spatial_demand', return_value=copy.deepcopy(self.spatial)):
                context = load_selected(selection)
                self.assertEqual(context.spatial_od, {self.key: self.od})
                person.find("attributes/attribute[@name='simz1Trips']").text = json.dumps([{**ledger[0], 'origin_link': 'exit'}])
                ET.ElementTree(root).write(plans, encoding='utf-8')
                with self.assertRaisesRegex(ValueError, 'viaje planificado'):
                    load_selected(selection)
            with patch('simz1_gateway_od.validated_spatial_demand', return_value=None):
                with self.assertRaisesRegex(ValueError, 'sin dominio validado'):
                    load_selected(selection)

    def test_continuous_metadata_rejects_bad_identity_or_exterior_coordinates(self):
        replay = object.__new__(ContinuousReplay);replay.spatial = self.spatial
        trip = dict(Person_ID='p', Trip_Index=1, Trip_ID=self.key, OD=copy.deepcopy(self.od))
        replay.validate_spatial_trip(trip)
        for changed in ({**trip, 'Trip_ID': 'other'}, {**trip, 'OD': {**self.od, 'origin_xy': [0, 0]}},
                        {**trip, 'OD': None}):
            with self.assertRaises(ValueError):
                replay.validate_spatial_trip(changed)


if __name__ == '__main__':
    unittest.main()
