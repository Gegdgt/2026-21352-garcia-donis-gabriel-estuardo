"""Native gateway checks reject premature or unsupported arrivals."""
import unittest
from simz1_freight_gateways import NativeGatewayAudit

class NativeGatewayTests(unittest.TestCase):
    def setup_audit(self):
        geometry=dict(body_length_m=8.,minimum_gap_m=.1,route_link_start_m={'a':0.},
            entry_distance_from_route_start_m=30.,exit_distance_from_route_start_m=80.)
        audit=NativeGatewayAudit({'truck':{'native_gateway':geometry}})
        audit.consume(dict(type='simz1OccupancyDomain',link='a',corridor='c',linkOffsetMeters='0',linkLengthMeters='100'))
        audit.consume(dict(type='simz1OccupancyReservation',action='ENTER',vehicle='truck',link='a',corridor='c',
            bodyLengthMeters='8',footprintMeters='8.1',reservationOrdinal='1'))
        return audit

    def progress(self,audit,front):
        audit.consume(dict(type='simz1OccupancyProgress',vehicle='truck',link='a',corridor='c',
            modeledFrontLowerBoundMeters=str(front),time='10'))

    def test_full_body_plus_gap_must_clear_before_real_arrival(self):
        for front,valid in ((79.,False),(88.,False),(88.1,True),(99.,True)):
            audit=self.setup_audit();self.progress(audit,front)
            event=dict(type='arrival',person='truck',link='a',time='10',relativePosition='1.0')
            if valid:
                audit.consume(event);self.assertTrue(audit.summary()['complete'])
            else:
                with self.assertRaisesRegex(ValueError,'before full body'):audit.consume(event)

    def test_link_identifier_without_ledger_does_not_prove_arrival(self):
        audit=self.setup_audit()
        with self.assertRaisesRegex(ValueError,'lacks active'):audit.consume(dict(type='arrival',person='truck',link='a',time='10'))

    def test_origin_inside_rejected_and_transfer_requires_new_progress(self):
        audit=self.setup_audit();self.progress(audit,31)
        with self.assertRaisesRegex(ValueError,'already inside'):audit.consume(dict(type='vehicle enters traffic',vehicle='truck',time='10'))
        self.progress(audit,20);audit.consume(dict(type='vehicle enters traffic',vehicle='truck',time='10'))
        self.assertEqual(audit.summary()['entry_evidence_count'],1)
        audit.consume(dict(type='simz1OccupancyReservation',action='TRANSFER',vehicle='truck',link='a',corridor='c',
            bodyLengthMeters='8',footprintMeters='8.1',reservationOrdinal='1'))
        with self.assertRaisesRegex(ValueError,'lacks active'):audit.consume(dict(type='arrival',person='truck',link='a',time='10'))

if __name__=='__main__':unittest.main()
