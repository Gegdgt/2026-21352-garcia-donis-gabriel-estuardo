"""Lifecycle fixtures. Prepared for manual execution; no historical run is read."""
import gzip
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET
from simz1_freight import (FreightAudit, WINDOWS, LEGACY_WINDOWS, OVERNIGHT_POLICY,
                           LEGACY_RESIDENCE_POLICY, require_approved_results)


def audit_at(start=34320, legacy=False):
    return FreightAudit({'h': dict(vehicle_id='h', driver_id='h', departure_seconds=start,
        link_ids=['a', 'b', 'c'], allowed_windows_seconds=LEGACY_WINDOWS if legacy else WINDOWS,
        residence_policy=LEGACY_RESIDENCE_POLICY if legacy else OVERNIGHT_POLICY)})


def send(audit, kind, time, link='a'):
    audit.consume(dict(type=kind, time=str(time), link=link, person='h', vehicle='h'))


def begin(audit, start, entry=None):
    send(audit, 'departure', start)
    if entry is not None:
        send(audit, 'vehicle enters traffic', entry)


def finish(audit, time):
    send(audit, 'entered link', time, 'b')
    send(audit, 'entered link', time+1, 'c')
    send(audit, 'vehicle leaves traffic', time+2, 'c')
    send(audit, 'arrival', time+3, 'c')


class FreightClosureTests(unittest.TestCase):
    def test_synthetic_27_outcomes_three_day_violations_and_one_night_abort(self):
        # Deliberately synthetic IDs/times: this is not a replay of Run1000.
        contract = {f'synthetic_h{i:02d}': dict(vehicle_id=f'synthetic_h{i:02d}',
                    departure_seconds=78000 if i == 26 else 34500,
                    link_ids=['a', 'b', 'c'], allowed_windows_seconds=WINDOWS,
                    residence_policy=OVERNIGHT_POLICY) for i in range(27)}
        audit = FreightAudit(contract)
        for i, (ident, row) in enumerate(contract.items()):
            def emit(kind, stamp, link='a'):
                audit.consume(dict(type=kind, time=stamp, person=ident, vehicle=ident, link=link))
            start = row['departure_seconds']
            emit('departure', start); emit('vehicle enters traffic', start+1)
            if i < 23:
                emit('entered link', start+10, 'b'); emit('entered link', start+20, 'c')
                emit('vehicle leaves traffic', start+30, 'c'); emit('arrival', start+30, 'c')
            else:
                if i < 26:
                    emit('simz1NativeDecision', 57600)
                    emit('simz1NativeDecision', 57601)
                    emit('simz1NativeDecision', 75601)  # A later window never clears the finding.
                emit('stuckAndAbort', 86401); emit('vehicle aborts', 86401)
        result = audit.summary()
        self.assertEqual(result['technical_integrity'], 'valid')
        self.assertEqual(result['status'], 'invalid')
        self.assertEqual(result['restricted_window_violations'], 3)
        self.assertEqual({v['vehicle_id'] for v in result['violations']},
                         {'synthetic_h23', 'synthetic_h24', 'synthetic_h25'})
        self.assertTrue(all(v['observed_seconds'] == 57600 for v in result['violations']))
        self.assertEqual(result['arrivals_observed'], 23)
        self.assertEqual(result['aborted_expeditions'], 4)
        self.assertEqual(result['active_or_censored'], 0)
        self.assertEqual(result['missing_departures'], 0)
        self.assertEqual(set(result['terminal_events']), set(contract))
        self.assertEqual(sum(t['status'] == 'completed' for t in result['terminal_events'].values()), 23)
        self.assertTrue(all(len(result['terminal_events'][f'synthetic_h{i:02d}']['sources']) == 2
                            for i in range(23, 27)))
        with self.assertRaisesRegex(ValueError, 'not approved'):
            require_approved_results(dict(results={'0': dict(freight_transport_events=result)}))
        audit.reset()
        self.assertEqual(audit.summary()['missing_departures'], 27)
        self.assertEqual(audit.summary()['terminal_events'], {})
        self.assertEqual(audit.summary()['violations'], [])

    def test_day_valid_and_retained_until_cleanup(self):
        good = audit_at(); begin(good, 34320, 34320); finish(good, 34400)
        self.assertEqual(good.summary()['status'], 'valid')
        bad = audit_at(); begin(bad, 34320, 34320)
        send(bad, 'stuckAndAbort', 86401)
        send(bad, 'vehicle aborts', 86401)
        result = bad.summary()
        self.assertEqual(result['technical_integrity'], 'valid')
        self.assertEqual(result['schedule_compliance'], 'violated')
        self.assertEqual(result['aborted_expeditions'], 1)
        self.assertEqual(result['active_or_censored'], 0)
        self.assertEqual(result['violations'][0]['entry_seconds'], 34320)
        self.assertEqual(result['violations'][0]['evidence'], 'terminal_residence')
        self.assertEqual(result['status'], 'invalid')

    def test_waiting_insertion_is_not_road_residence(self):
        audit = audit_at(); begin(audit, 34320)
        self.assertEqual(audit.summary()['waiting_for_insertion'], 1)
        send(audit, 'vehicle enters traffic', 77400); finish(audit, 86400)
        self.assertEqual(audit.summary()['status'], 'valid')
        audit = audit_at(); begin(audit, 34320); send(audit, 'stuckAndAbort', 86401)
        self.assertEqual(audit.summary()['restricted_window_violations'], 0)
        self.assertEqual(audit.summary()['trip_outcome'], 'incomplete')
        audit = audit_at(); begin(audit, 34320, 60000)
        self.assertEqual(audit.summary()['restricted_window_violations'], 1)

    def test_night_and_historical_policy(self):
        for legacy, expected in ((False, 'valid'), (True, 'invalid')):
            audit = audit_at(77400, legacy); begin(audit, 77400, 77400); finish(audit, 86400)
            self.assertEqual(audit.summary()['status'], expected)

    def test_half_open_boundaries_and_exit_before_restriction(self):
        for start, end in ((0,18000), (32400,57600), (75600,104400)):
            for offset, violations in ((-1,0),(0,1)):
                audit = audit_at(start); begin(audit, start, start)
                send(audit, 'stuckAndAbort', end+offset)
                self.assertEqual(audit.summary()['restricted_window_violations'], violations)
        audit = audit_at(); begin(audit,34320,34320)
        send(audit,'entered link',57596,'b'); send(audit,'entered link',57597,'c')
        send(audit,'vehicle leaves traffic',57599,'c'); send(audit,'arrival',57600,'c')
        self.assertEqual(audit.summary()['status'],'valid')

    def test_exit_then_terminal_cleanup_does_not_extend_residence(self):
        audit = audit_at(); begin(audit,34320,34320)
        send(audit,'vehicle leaves traffic',57599)
        send(audit,'vehicle aborts',86401)
        send(audit,'stuckAndAbort',86401)
        self.assertEqual(audit.summary()['restricted_window_violations'],0)
        self.assertEqual(audit.summary()['status'],'invalid')
        self.assertEqual(audit.summary()['aborted_expeditions'],1)

    def test_violation_survives_arrival_abort_and_unrelated_cleanup(self):
        for terminal in ('arrival','stuckAndAbort'):
            audit = audit_at(); begin(audit,34320,34320)
            send(audit,'left link',57600)
            if terminal == 'arrival': finish(audit,77400)
            else: send(audit,terminal,77400)
            first = audit.summary()['violations']
            send(audit,'actstart',86401,'c')
            self.assertEqual(audit.summary()['violations'],first)
            self.assertEqual(audit.summary()['status'],'invalid')
            self.assertFalse(audit.active)
            self.assertFalse(audit.traffic)

    def test_strict_structure_and_reset_two_iterations(self):
        audit = audit_at(); begin(audit,34320,34320)
        send(audit,'stuckAndAbort',86401)
        with self.assertRaisesRegex(ValueError,'without active departure'):
            send(audit,'arrival',86401,'c')
        audit.reset(); audit.reset()
        begin(audit,34320,34320); finish(audit,34400)
        self.assertEqual(audit.summary()['status'],'valid')
        with self.assertRaisesRegex(ValueError,'duplicate'):
            send(audit,'departure',34404)

    def test_runner_rejects_after_retaining_results(self):
        bad = audit_at(); begin(bad,34320,34320); finish(bad,86400)
        state = dict(results={'0': dict(freight_transport_events=bad.summary())})
        with self.assertRaisesRegex(ValueError,'not approved'): require_approved_results(state)
        self.assertEqual(state['validation']['status'],'invalid')
        self.assertEqual(state['results']['0']['freight_transport_events']['arrivals_observed'],1)
        self.assertEqual(state['freight_validation']['iterations']['0']['restricted_window_violations'],1)
        good = audit_at(); begin(good,34320,34320); finish(good,34400)
        require_approved_results(dict(results={'0':dict(freight_transport_events=good.summary())}))


class FixedDayFreightInterpretationTests(unittest.TestCase):
    """Inert production audit events; no QSim, generation or historical events."""
    @staticmethod
    def pending(start=75600, enter=True, abort_before_cut=False):
        from simz1_freight_completion import POLICY
        from simz1_day_observation import classify
        geometry=dict(body_length_m=8.,minimum_gap_m=.1,route_link_start_m={'a':0.},
                      entry_distance_from_route_start_m=30.,exit_distance_from_route_start_m=80.)
        contract={'h':dict(vehicle_id='h',departure_seconds=start,link_ids=['a'],
                          completion_policy=POLICY,native_gateway=geometry)}
        audit=FreightAudit(contract,fixed_day=True)
        send(audit,'departure',start)
        if enter:
            audit.consume(dict(type='simz1OccupancyDomain',time=str(start),link='a',corridor='c',
                               linkOffsetMeters='0',linkLengthMeters='100'))
            audit.consume(dict(type='simz1OccupancyReservation',time=str(start),action='ENTER',
                vehicle='h',link='a',corridor='c',bodyLengthMeters='8',footprintMeters='8.1',reservationOrdinal='1'))
            audit.consume(dict(type='simz1OccupancyProgress',time=str(start),vehicle='h',link='a',
                               corridor='c',modeledFrontLowerBoundMeters='0'))
            send(audit,'vehicle enters traffic',start)
        if abort_before_cut:send(audit,'stuckAndAbort',start+100)
        audit.consume(dict(type='simz1DayCut',time='86400'))
        if not abort_before_cut:send(audit,'stuckAndAbort',86400)
        census=classify(dict(family='pesado',scheduled_departure=start,departure=start,
                            traffic_entry=start if enter else None,
                            abort_before_cleanup=start+100 if abort_before_cut else None))
        census['cleanup_abort_events']=int(not abort_before_cut)
        audit.day_census={'h':census}
        return audit

    def test_night_censored_duration_three_hours_is_not_future_window_failure(self):
        result=self.pending().summary();row=result['completion_records'][0]
        self.assertEqual(result['status'],'valid')
        self.assertEqual(result['experimental_acceptance'],'not_evaluable')
        self.assertEqual(row['observed_traffic_seconds'],10800)
        self.assertFalse(row['deadline_evaluable_at_cut'])
        self.assertFalse(row['window_close_observed_at_cut'])
        self.assertEqual(row['observed_delay_since_window_close_lower_bound_seconds'],0)
        self.assertIsNone(row['arrival_seconds']);self.assertIsNone(row['delay_seconds'])
        self.assertEqual(result['restricted_window_violations'],0)
        state=dict(results={'0':dict(freight_transport_events=result)})
        require_approved_results(state)
        self.assertEqual(state['freight_validation']['experimental_acceptance'],'not_evaluable')
        self.assertEqual(state['freight_validation']['status'],'valid')

    def test_day_pending_delay_is_observed_separately_from_traffic_duration(self):
        result=self.pending(start=100).summary();row=result['completion_records'][0]
        self.assertEqual(row['observed_traffic_seconds'],86300)
        self.assertEqual(row['observed_delay_since_window_close_lower_bound_seconds'],68400)
        self.assertTrue(row['window_close_observed_at_cut']);self.assertTrue(row['deadline_evaluable_at_cut'])
        self.assertEqual(row['delay_observation_at_seconds'],86400)
        self.assertIn('not_trip_duration_or_imputed_arrival',row['delay_observation_basis'])
        self.assertIsNone(row['delay_seconds']);self.assertIsNone(row['arrival_seconds'])
        self.assertEqual(result['restricted_window_violations'],1)
        self.assertEqual(result['violations'][0]['observed_seconds'],86400)
        waiting=self.pending(start=100,enter=False).summary()['completion_records'][0]
        self.assertIsNone(waiting['observed_traffic_seconds'])
        self.assertEqual(waiting['observed_delay_since_window_close_lower_bound_seconds'],68400)

    def test_actual_excess_and_mixed_iteration_aggregate_are_not_hidden_by_censoring(self):
        from test_simz1_final_experiment import FreightAuditPolicyTests
        good=FreightAuditPolicyTests().audit(17999).summary()
        excess=FreightAuditPolicyTests().audit(21600.01).summary()
        pending=self.pending().summary()
        self.assertEqual(excess['completion_classifications']['excess_tolerance'],1)
        self.assertEqual(excess['experimental_acceptance'],'not_satisfied')
        self.assertEqual(excess['restricted_window_violations'],1)
        self.assertAlmostEqual(excess['completion_records'][0]['delay_seconds'],3600.01)
        for records,expected in (([good],'satisfied'),([pending],'not_evaluable'),
                ([good,pending],'not_evaluable'),([excess],'not_satisfied'),
                ([good,pending,excess],'not_satisfied')):
            state=dict(results={str(i):dict(freight_transport_events=r) for i,r in enumerate(records)})
            require_approved_results(state)
            self.assertEqual(state['freight_validation']['experimental_acceptance'],expected)
            self.assertEqual(list(state['freight_validation']['iterations'].values()),
                             [r['experimental_acceptance'] for r in records])

    def test_real_abort_and_unknown_acceptance_state_still_rejected(self):
        result=self.pending(abort_before_cut=True).summary()
        self.assertEqual(result['aborted_expeditions'],1);self.assertEqual(result['censored_at_horizon'],0)
        with self.assertRaisesRegex(ValueError,'not approved'):
            require_approved_results(dict(results={'0':dict(freight_transport_events=result)}))
        result=self.pending().summary();result['experimental_acceptance']='invented'
        with self.assertRaisesRegex(ValueError,'Unknown freight'):
            require_approved_results(dict(results={'0':dict(freight_transport_events=result)}))


class FreightEvidenceReaderTests(unittest.TestCase):
    """Synthetic streams only; never opens any production events or diagnostics."""
    def payload(self):
        root = ET.Element('events')
        ET.SubElement(root, 'event', type='departure', time='34500', person='synthetic_a', link='a')
        for i in range(20):
            ET.SubElement(root, 'event', type='entered link', time=str(34501+i), vehicle='synthetic_a', link=str(i))
        ET.SubElement(root, 'event', type='simz1NativeDecision', time='57600', vehicle='synthetic_a', link='19', decision='WAIT')
        ET.SubElement(root, 'event', type='stuckAndAbort', time='86401', person='synthetic_a', link='19')
        ET.SubElement(root, 'event', type='vehicle aborts', time='86401', vehicle='synthetic_a', link='19')
        ET.SubElement(root, 'event', type='arrival', time='86401', person='unrelated', link='z')
        return ET.tostring(root)

    def scan(self, path, **limits):
        from inspect_simz1_freight_failure import scan_events
        return scan_events(path, {'synthetic_a', 'synthetic_b'}, ['synthetic_a'], {'synthetic_a': 57600},
                           max_bytes=limits.get('max_bytes', 100000), max_seconds=5)

    def test_complete_stream_fixed_samples_and_no_invented_arrival(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td)/'events.xml.gz'
            original = gzip.compress(self.payload()); path.write_bytes(original)
            result = self.scan(path)
            self.assertTrue(result['gzip_crc_and_xml_complete'])
            row = result['affected_events']['synthetic_a']
            self.assertEqual(len(row['recent_movements']), 8)
            self.assertEqual(row['last_movement']['link'], '19')
            self.assertEqual(row['decision_at_reported_first_violation']['time'], '57600')
            self.assertNotIn('arrival', row['first_events'])
            self.assertEqual(result['event_counts']['synthetic_b'], {})
            self.assertEqual(path.read_bytes(), original)

    def test_limits_truncation_bad_crc_and_incomplete_xml_never_certify_eof(self):
        raw = self.payload(); compressed = gzip.compress(raw)
        corrupted = bytearray(compressed); corrupted[-8] ^= 1
        cases = [('budget', compressed, 64, 'limit_reached'),
                 ('truncated', compressed[:-8], 100000, 'invalid_stream'),
                 ('crc', bytes(corrupted), 100000, 'invalid_stream'),
                 ('xml', gzip.compress(raw[:-9]), 100000, 'invalid_stream')]
        with tempfile.TemporaryDirectory() as td:
            path = Path(td)/'events.xml.gz'
            for label, contents, limit, status in cases:
                with self.subTest(case=label):
                    path.write_bytes(contents)
                    result = self.scan(path, max_bytes=limit)
                    self.assertEqual(result['status'], status)
                    self.assertFalse(result['gzip_crc_and_xml_complete'])
                    self.assertEqual(result['counts_scope'], 'partial_prefix_only')
                    self.assertEqual(path.read_bytes(), contents)

    def test_inspector_pins_run_identity_and_saved_inputs(self):
        from inspect_simz1_freight_failure import inspect_run
        with tempfile.TemporaryDirectory() as td:
            run = Path(td).resolve()
            saved = run/'inputs/freight-weekday'; saved.mkdir(parents=True)
            output = run/'output/ITERS/it.0'; output.mkdir(parents=True)
            (output/'0.events.xml.gz').write_bytes(gzip.compress(self.payload()))
            (output/'0.simz1-freight-audit.csv').write_text(
                'vehicle,trip_outcome,schedule_compliance,violation_observed\n'
                'synthetic_a,aborted,violated,57600\n', encoding='utf-8')
            manifest = dict(run_id='synthetic-run', folder=str(run), status='failed',
                            iterations={'last': 0}, inputs={})
            inputs = {'roster.json': [dict(vehicle_id='synthetic_a', departure_seconds=34500,
                                          route_id='synthetic-route', link_ids=['a', 'b'])],
                      'service.json': dict(vehicles=1, allowed_windows_seconds=WINDOWS,
                                           residence_policy=OVERNIGHT_POLICY)}
            for name, value in inputs.items():
                data = json.dumps(value).encode('utf-8'); (saved/name).write_bytes(data)
                manifest['inputs']['input:freight-weekday/'+name] = dict(
                    path='inputs/freight-weekday/'+name, sha256=hashlib.sha256(data).hexdigest())
            original = json.dumps(manifest).encode('utf-8')
            (run/'run-manifest.json').write_bytes(original)
            result = inspect_run(run, 'synthetic-run', 0, 100000, 5)
            self.assertTrue(result['extraction']['gzip_crc_and_xml_complete'])
            self.assertEqual(result['run_status_unchanged'], 'failed')
            self.assertEqual(result['native_outcomes'], {'aborted': ['synthetic_a']})
            self.assertEqual((run/'run-manifest.json').read_bytes(), original)
            with self.assertRaisesRegex(ValueError, 'identity'):
                inspect_run(run, 'another-run', 0, 100000, 5)
            (saved/'service.json').write_text('{}', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'hash mismatch'):
                inspect_run(run, 'synthetic-run', 0, 100000, 5)


if __name__ == '__main__': unittest.main()
