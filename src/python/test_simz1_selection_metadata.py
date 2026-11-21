"""Selection lifetime comes from trip events, never the last drawn segment."""
import unittest
from types import SimpleNamespace

from simz1_motion import MotionContext
from simz1_trajectories import extract


class SelectionMetadataTests(unittest.TestCase):
    links = {'l': dict(length=100, freespeed=10, from_node='a', to_node='b',
                       **{'from':[0,0], 'to':[.001,0]})}

    @staticmethod
    def event(kind, time, **attrs):
        return dict(type=kind, time=str(time), **attrs)

    def boundaries(self, start=0, end=10, *, person='p', vehicle='vehicle-other'):
        return [self.event('departure',start,person=person,link='l'),
                self.event('vehicle enters traffic',start,person=person,vehicle=vehicle,link='l',relativePosition='0'),
                self.event('vehicle leaves traffic',end,person=person,vehicle=vehicle,link='l',relativePosition='1')]

    def run_extract(self, events, **kwargs):
        stats = {}
        segments = extract(events, self.links, lambda _: True, lambda _: [1,2,3],
            SimpleNamespace(inv=lambda *args: (0,0,100)), stats=stats,
            motion=MotionContext({'vehicle-other':10}), **kwargs)
        return segments,stats

    def test_completion_is_real_arrival_even_after_geometry_ends(self):
        segments,_ = self.run_extract(self.boundaries()+[
            self.event('arrival',15,person='p',link='l')],horizon=50)
        self.assertEqual(len(segments),1)
        self.assertEqual(segments[0]['timestamps'],[0,10])
        trip=segments[0]['Trip']
        self.assertEqual((trip['Departure'],trip['Arrival'],trip['Last_Observed_Time']),(0,15,15))
        self.assertEqual((trip['Person_ID'],trip['Trip_Index'],trip['Status']),('p',1,'completed'))
        self.assertEqual(trip['Observation_End'],50)
        self.assertEqual(trip['Observation_End_Provenance'],'configured_horizon')
        self.assertIsNone(trip['Abort'])

    def test_intermediate_gap_keeps_one_trip_until_real_arrival(self):
        events=self.boundaries()+[
            self.event('vehicle enters traffic',20,person='p',vehicle='vehicle-other',link='l',relativePosition='0'),
            self.event('vehicle leaves traffic',30,person='p',vehicle='vehicle-other',link='l',relativePosition='1'),
            self.event('arrival',35,person='p',link='l')]
        segments,_=self.run_extract(events)
        self.assertEqual([s['timestamps'] for s in segments],[[0,10],[20,30]])
        self.assertIs(segments[0]['Trip'],segments[1]['Trip'])
        self.assertEqual(segments[0]['Trip']['Arrival'],35)
        self.assertEqual(segments[0]['Trip']['Observation_End'],35)
        self.assertEqual(segments[0]['Trip']['Observation_End_Provenance'],'last_event_in_stream')

    def test_two_trips_same_person_and_vehicle_have_independent_lifetimes(self):
        events=self.boundaries()+[self.event('arrival',15,person='p',link='l')]
        events+=self.boundaries(30,40)+[self.event('arrival',45,person='p',link='l')]
        segments,_=self.run_extract(events)
        first,second=(segment['Trip'] for segment in segments)
        self.assertEqual((first['Trip_ID'],second['Trip_ID']),('p:trip:0001','p:trip:0002'))
        self.assertEqual((first['Departure'],first['Arrival'],first['Last_Observed_Time']),(0,15,15))
        self.assertEqual((second['Departure'],second['Arrival'],second['Last_Observed_Time']),(30,45,45))

    def test_censoring_does_not_use_other_person_or_global_event_as_last_observation(self):
        events=self.boundaries()+[self.event('signalGroupStateChanged',100,signalGroup='g'),
            self.event('departure',110,person='other',link='l')]
        for horizon,end,provenance in ((None,110,'last_event_in_stream'),(200,200,'configured_horizon')):
            segments,_=self.run_extract(events,horizon=horizon)
            trip=segments[0]['Trip']
            self.assertEqual((trip['Status'],trip['Last_Observed_Time']),('censored',10))
            self.assertIsNone(trip['Arrival']);self.assertIsNone(trip['Abort'])
            self.assertEqual((trip['Observation_End'],trip['Observation_End_Provenance']),(end,provenance))

    def test_arrival_releases_old_vehicle_before_person_uses_a_different_one(self):
        events=self.boundaries()+[self.event('arrival',15,person='p',link='l')]
        events+=self.boundaries(20,30,vehicle='second-vehicle')+[
            self.event('simz1NativeDecision',40,vehicle='vehicle-other',link='l',decision='WAIT'),
            self.event('vehicle aborts',45,vehicle='vehicle-other',link='l')]
        segments,_=self.run_extract(events)
        first,second=(segment['Trip'] for segment in segments)
        self.assertEqual((first['Status'],first['Last_Observed_Time']),('completed',15))
        self.assertEqual((second['Status'],second['Last_Observed_Time']),('censored',30))
        self.assertIsNone(second['Abort'])
        self.assertEqual(second['Observation_End'],45)

    def test_reused_vehicle_does_not_belong_to_person_with_delayed_arrival_or_abort(self):
        for terminal in ('arrival','stuckAndAbort'):
            events=self.boundaries()+[
                self.event('departure',11,person='new-owner',link='l'),
                self.event('vehicle enters traffic',12,person='new-owner',vehicle='vehicle-other',link='l',relativePosition='0'),
                self.event(terminal,13,person='p',link='l'),
                self.event('simz1NativeDecision',15,vehicle='vehicle-other',link='l',decision='WAIT',reason='storage'),
                self.event('vehicle leaves traffic',20,person='new-owner',vehicle='vehicle-other',link='l',relativePosition='1'),
                self.event('arrival',22,person='new-owner',link='l')]
            segments,_=self.run_extract(events,horizon=100)
            self.assertEqual([s['timestamps'] for s in segments],[[0,10],[12,20]])
            first,second=(segment['Trip'] for segment in segments)
            self.assertEqual((first['Person_ID'],first['Last_Observed_Time']),('p',13))
            self.assertEqual((second['Person_ID'],second['Status'],second['Last_Observed_Time']),('new-owner','completed',22))
            self.assertEqual(segments[1]['Observed_Waits']['storage']['first'],15)
            self.assertIsNone(second['Abort'])

    def test_reassignment_with_an_open_interval_is_an_error(self):
        events=self.boundaries()[:2]+[
            self.event('departure',1,person='new-owner',link='l'),
            self.event('vehicle enters traffic',2,person='new-owner',vehicle='vehicle-other',link='l',relativePosition='0')]
        with self.assertRaisesRegex(ValueError,'Vehiculo reasignado con intervalo abierto'):
            self.run_extract(events)

    def test_last_event_in_stream_is_observation_not_an_exclusive_horizon(self):
        segments,_=self.run_extract(self.boundaries())
        trip=segments[0]['Trip']
        self.assertEqual(trip['Observation_End_Provenance'],'last_event_in_stream')
        self.assertEqual((trip['Last_Observed_Time'],trip['Observation_End']),(10,10))
        self.assertEqual(trip['Status'],'censored')
        self.assertIsNone(trip['Arrival']);self.assertIsNone(trip['Abort'])

    def test_individual_wait_extends_observation_without_inventing_a_segment(self):
        events=self.boundaries()+[
            self.event('vehicle enters traffic',20,person='p',vehicle='vehicle-other',link='l',relativePosition='0'),
            self.event('simz1NativeDecision',25,vehicle='vehicle-other',link='l',decision='WAIT',reason='storage'),
            self.event('signalGroupStateChanged',100,signalGroup='g')]
        segments,stats=self.run_extract(events,horizon=100)
        self.assertEqual(len(segments),1)
        self.assertEqual(segments[0]['Trip']['Last_Observed_Time'],25)
        self.assertIsNone(segments[0]['Trip']['Arrival'])
        self.assertEqual(stats['pending_link_intervals'],1)

    def test_abort_and_native_duplicate_close_before_next_trip(self):
        events=self.boundaries()+[
            self.event('vehicle enters traffic',20,person='p',vehicle='vehicle-other',link='l',relativePosition='0'),
            self.event('vehicle aborts',25,vehicle='vehicle-other',link='l'),
            self.event('stuckAndAbort',25,person='p',link='l')]
        events+=self.boundaries(30,40)+[self.event('arrival',45,person='p',link='l')]
        segments,stats=self.run_extract(events,horizon=100)
        self.assertEqual(len(segments),2)  # No fabricated movement from 20 to 25.
        trip=segments[0]['Trip']
        self.assertEqual((trip['Status'],trip['Abort'],trip['Last_Observed_Time']),('aborted',25,25))
        self.assertIsNone(trip['Arrival'])
        self.assertEqual(segments[1]['Trip']['Trip_Index'],2)
        self.assertEqual(segments[1]['Trip']['Status'],'completed')
        self.assertEqual(stats['observed_trip_aborts'],1)
        self.assertEqual(stats['unclosed_intervals_at_abort'],1)

    def test_horizon_abort_is_censoring_and_midnight_stays_absolute(self):
        segments,_=self.run_extract(self.boundaries(86390,86410)+[
            self.event('stuckAndAbort',86501,person='p',link='l')],horizon=86500)
        trip=segments[0]['Trip']
        self.assertEqual((trip['Status'],trip['Abort'],trip['Last_Observed_Time']),('censored',86501,86501))
        self.assertEqual(trip['Observation_End'],86500)
        self.assertEqual(trip['Departure'],86390)
        self.assertIsNone(trip['Arrival'])
        self.assertEqual(segments[0]['timestamps'],[86390,86410])

    def test_invalid_horizons_fail_without_invented_boundary(self):
        for horizon in (-1,float('inf'),float('nan')):
            with self.assertRaisesRegex(ValueError,'Horizonte'):
                self.run_extract(self.boundaries(),horizon=horizon)


if __name__=='__main__': unittest.main()
