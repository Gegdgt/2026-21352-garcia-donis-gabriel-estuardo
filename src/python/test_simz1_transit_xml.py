"""Regression for weekday event attributes: dict and real streaming XML input."""
import gzip
from pathlib import Path
import tempfile
from types import MappingProxyType
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from simz1_run import xml_elements
from simz1_transit_events import TransitEventAudit, verified_transit_contract
from simz1_run import checked_path
import test_simz1_transit_events as original_tests


class TransitXMLTests(unittest.TestCase):
    def contract(self):
        return dict(vehicle_modes={'b': 'bus'}, domain_scope='computational_network',
                    domain_links={'a', 'z'}, departures={
                        ('line', 'r', dep): dict(vehicle='b', links=('a', 'z'), opens_seconds=100,
                                               closes_seconds=500, transfer_kind='exterior',
                                               transfer_seconds=30)
                        for dep in ('d1', 'd2')})

    @staticmethod
    def boundary(action='entry', time=100, ready=100, dep='d1'):
        return dict(type='simz1TransitBoundary', time=str(time), readyAt=str(ready), vehicle='b',
                    driver='driver', service='line', departure=dep, action=action)

    @staticmethod
    def dispatch(time=100, dep='d1'):
        return dict(type='TransitDriverStarts', time=str(time), driverId='driver', vehicleId='b',
                    transitLineId='line', transitRouteId='r', departureId=dep)

    def sequence(self):
        rows = []
        for start, dep in ((100, 'd1'), (160, 'd2')):
            rows.extend([
                self.boundary(time=start, ready=start, dep=dep), self.dispatch(start, dep),
                dict(type='departure', time=str(start), person='driver', link='a', legMode='car'),
                dict(type='vehicle enters traffic', time=str(start), person='driver', vehicle='b',
                     link='a', networkMode='car'),
                dict(type='left link', time=str(start+10), vehicle='b', link='a'),
                dict(type='entered link', time=str(start+10), vehicle='b', link='z'),
                dict(type='vehicle leaves traffic', time=str(start+20), person='driver', vehicle='b', link='z'),
                dict(type='arrival', time=str(start+20), person='driver', link='z', legMode='car'),
                self.boundary('outside_start', start+20, start+50, dep),
            ])
        rows.append(self.boundary('service_finished', 210, 210, 'd2'))
        return rows

    def test_boundary_xml_reproduces_original_failure(self):
        raw = ET.fromstring('<event type="simz1TransitBoundary" time="100" readyAt="100" '
                            'vehicle="b" driver="driver" service="line" departure="d1" action="entry"/>')
        self.assertTrue(TransitEventAudit(self.contract(), {'road'}).consume(raw))

    def test_native_dispatch_xml_with_hours_reproduces_second_failure(self):
        raw = ET.Element('event', self.dispatch())
        self.assertTrue(TransitEventAudit(self.contract(), {'road'}).consume(raw))

    def test_complete_dict_readonly_mapping_and_xml_sequences_are_equivalent(self):
        summaries = []
        for factory in (dict, MappingProxyType, lambda row: ET.Element('event', row)):
            audit = TransitEventAudit(self.contract(), {'road'})
            for row in self.sequence():
                raw = factory(dict(row))
                before = ET.tostring(raw) if ET.iselement(raw) else dict(raw)
                self.assertTrue(audit.consume(raw))
                after = ET.tostring(raw) if ET.iselement(raw) else dict(raw)
                self.assertEqual(before, after)
            summaries.append(audit.summary())
        self.assertEqual(summaries[0], summaries[1])
        self.assertEqual(summaries[0], summaries[2])
        self.assertEqual(summaries[0]['observed_expedition_starts'], 2)
        self.assertEqual(summaries[0]['transit_drivers_internal_observed'], 1)
        self.assertEqual(summaries[0]['active_public_vehicles_network'], 0)
        self.assertEqual(summaries[0]['road_demand_persons'], 1)

    def test_gzip_streaming_uses_the_production_xml_reader(self):
        expected = TransitEventAudit(self.contract(), {'road'})
        for row in self.sequence():
            expected.consume(row)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'output_events.xml.gz'
            root = ET.Element('events')
            root.extend(ET.Element('event', row) for row in self.sequence())
            with gzip.open(path, 'wb') as stream:
                stream.write(ET.tostring(root))
            before = path.read_bytes()
            audit = TransitEventAudit(self.contract(), {'road'})
            for raw in xml_elements(path, 'event', 'events'):
                self.assertTrue(ET.iselement(raw))
                audit.consume(raw)
            self.assertEqual(audit.summary(), expected.summary())
            self.assertEqual(path.read_bytes(), before)

    def test_boundary_timing_and_identity_guards_still_reject_both_formats(self):
        cases = [self.boundary(time=99, ready=99), self.boundary(time=500, ready=500),
                 self.boundary('outside_start', 130, 131), self.boundary('made-up', 140, 140),
                 {**self.boundary(), 'driver': 'road'}, {**self.boundary(), 'vehicle': 'unknown'},
                 {**self.boundary(), 'departure': 'unknown'}, self.boundary(time=120, ready=119)]
        for values in cases:
            for xml in (False, True):
                with self.subTest(values=values, xml=xml), self.assertRaises(ValueError):
                    raw = ET.Element('event', values) if xml else values
                    TransitEventAudit(self.contract(), {'road'}).consume(raw)

    def test_missing_or_nonfinite_required_time_is_not_defaulted(self):
        for template, fields in ((self.boundary(), ('time', 'readyAt')), (self.dispatch(), ('time',))):
            for field in fields:
                for bad in (None, 'nan', 'inf', '-1', 'not-a-number'):
                    for xml in (False, True):
                        values = dict(template)
                        if bad is None:
                            values.pop(field)
                        else:
                            values[field] = bad
                        with self.subTest(kind=template['type'], field=field, bad=bad, xml=xml):
                            raw = ET.Element('event', values) if xml else values
                            with self.assertRaises(ValueError):
                                TransitEventAudit(self.contract(), {'road'}).consume(raw)

    def test_early_reentry_and_retirement_are_not_relaxed(self):
        for xml in (False, True):
            convert = lambda row: ET.Element('event', row) if xml else row
            audit = TransitEventAudit(self.contract(), {'road'})
            audit.consume(convert(self.boundary('outside_start', 130, 160)))
            with self.assertRaisesRegex(ValueError, 'readiness'):
                audit.consume(convert(self.boundary(time=159, ready=159, dep='d2')))
            audit.consume(convert(self.boundary(time=160, ready=160, dep='d2')))
            audit.consume(convert(self.boundary('cancelled_remaining_after_closing', 480, 510, 'd2')))
            with self.assertRaisesRegex(ValueError, 'retirement'):
                audit.consume(convert(self.boundary(time=490, ready=490, dep='d2')))

    def test_dispatch_outside_hours_still_rejected_with_xml(self):
        for time in (99, 500):
            with self.assertRaisesRegex(ValueError, 'operating hours'):
                TransitEventAudit(self.contract(), {'road'}).consume(ET.Element('event', self.dispatch(time)))

    def test_real_output_validation_loop_receives_weekday_boundary_xml(self):
        """Use actual gzip/iterparse/validate_outputs; only fixture configuration is isolated."""
        fixture = original_tests.TransitEventsTest()
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            manifest, params, links = fixture.fixture(folder)
            contract = verified_transit_contract(folder, manifest, params, checked_path,
                                                {'pt_real_road_person'}, links)
            contract['domain_scope'] = 'computational_network'
            for row in contract['departures'].values():
                row.update(opens_seconds=0, closes_seconds=100, transfer_kind='exterior', transfer_seconds=2)
            rows = fixture.events()
            for time, action, ready, dep in [(2, 'entry', 2, 'out-bus-a'),
                                              (4, 'outside_start', 6, 'out-bus-a'),
                                              (10, 'entry', 10, 'back-bus-a'),
                                              (13, 'service_finished', 13, 'back-bus-a')]:
                rows.append(ET.Element('event', dict(type='simz1TransitBoundary', time=str(time),
                    readyAt=str(ready), action=action, vehicle='bus-a', driver='native-no-prefix',
                    service='synthetic-service', departure=dep)))
            rows.sort(key=lambda row: (float(row.get('time')),
                0 if row.get('type') == 'simz1TransitBoundary' and row.get('action') == 'entry' else 1))
            # Do not mock consume, the XML reader, chronological or physical checks.
            with patch('simz1_transit_events.verified_transit_contract', return_value=contract):
                fixture.validate(folder, manifest, rows)
            public = manifest['results']['0']['public_transport_events']
            self.assertEqual(manifest['validation']['status'], 'valid')
            self.assertEqual(public['event_counts']['boundary_entry'], 2)
            self.assertEqual(public['observed_expedition_starts'], 2)
            self.assertEqual(public['active_public_vehicles_network'], 0)
            self.assertEqual(manifest['results']['0']['counts']['observed_persons'], 1)


if __name__ == '__main__':
    unittest.main()
