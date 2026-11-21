"""Open traffic intervals preserve presence without fabricated exits/arrivals."""
import json
from pathlib import Path
import tempfile
import unittest

from simz1_paged_replay import SqliteTrajectorySink, windows
from simz1_motion import MotionContext
from simz1_trajectories import extract


LINKS={'a':dict(length=100,freespeed=10,from_node='n0',to_node='n1',
               **{'from':[0,0],'to':[.001,0]})}


def event(kind,time,**attributes):
    return dict(type=kind,time=str(time),**attributes)


def entry(depart=0,entered=10):
    return [event('departure',depart,person='p',link='a'),
            event('PersonEntersVehicle',depart,person='p',vehicle='v'),
            event('vehicle enters traffic',entered,person='p',vehicle='v',link='a',relativePosition='0')]


def wait(time,source='SimZ1_QNode_strict_receiver_v1',reason='storage_wait'):
    return event('simz1NativeDecision',time,vehicle='v',link='a',decision='WAIT',
                 reason=reason,source=source,waitCategory='insufficient_storage')


class ObservedTailTests(unittest.TestCase):
    def run_extract(self,events,horizon=86400):
        stats={}
        records=extract(events,LINKS,lambda _:True,lambda _:[0,0,0],None,stats=stats,horizon=horizon,
                        motion=MotionContext({'v':10}))
        return records,stats

    def test_native_head_stays_present_until_observation_without_arrival(self):
        rows,stats=self.run_extract(entry()+[wait(20),wait(86399),
            event('vehicle aborts',86401,vehicle='v',link='a'),
            event('stuckAndAbort',86401,person='p',link='a')])
        self.assertEqual([r['timestamps'] for r in rows],[[10,20],[20,86400]])
        hold=rows[-1]
        self.assertEqual(hold['path'],[[.001,0],[.001,0]])
        self.assertEqual(hold['Speed_kmh'],0)
        self.assertEqual(hold['Motion_Plan']['status'],'stationary')
        self.assertEqual(hold['Boundary_Provenance']['end'],'observation_end')
        trip=hold['Trip']
        self.assertEqual(trip['Status'],'censored')
        self.assertIsNone(trip['Arrival'])
        self.assertEqual(trip['Traffic_Entry'],10)
        self.assertIsNone(trip['Traffic_Exit'])
        self.assertEqual(trip['Traffic_Retirement'],86401)
        self.assertEqual(len(trip['Traffic_Intervals']),1)
        self.assertEqual(trip['Traffic_Intervals'][0]['end'],86401)
        self.assertEqual(stats['native_queue_hold_intervals'],1)

    def test_unknown_follower_has_presence_but_no_fabricated_position(self):
        events=entry()+[wait(30,source='MATSim15_queue_post_step',reason='congestion_queue'),
                        event('stuckAndAbort',86401,person='p',vehicle='v',link='a')]
        with tempfile.TemporaryDirectory() as folder:
            store=SqliteTrajectorySink(Path(folder)/'replay.sqlite',windows(0,86400,3600))
            try:
                stats={};extract(events,LINKS,lambda _:True,lambda _:[0,0,0],None,
                                 stats=stats,horizon=86400,segment_sink=store)
                self.assertEqual(store.count,0)
                trip=json.loads(store.connection.execute('select metadata from journeys').fetchone()[0])
                self.assertEqual(trip['Traffic_Entry'],10)
                self.assertEqual(trip['Unrepresented_Traffic_Intervals'][0]['start'],10)
                self.assertEqual(trip['Unrepresented_Traffic_Intervals'][0]['end'],86400)
                self.assertEqual(stats['unrepresented_open_link_intervals'],1)
                self.assertIsNone(trip['Arrival'])
            finally:store.close()

    def test_boarding_without_traffic_entry_does_not_create_presence(self):
        events=[event('departure',0,person='p',link='a'),
                event('PersonEntersVehicle',0,person='p',vehicle='v'),
                event('stuckAndAbort',86401,person='p',link='a')]
        with tempfile.TemporaryDirectory() as folder:
            store=SqliteTrajectorySink(Path(folder)/'replay.sqlite',windows(0,86400,3600))
            try:
                extract(events,LINKS,lambda _:True,lambda _:[0,0,0],None,horizon=86400,segment_sink=store)
                trip=json.loads(store.connection.execute('select metadata from journeys').fetchone()[0])
                self.assertEqual(store.count,0)
                self.assertEqual(trip['Traffic_Intervals'],[])
                self.assertIsNone(trip['Traffic_Entry'])
                self.assertIsNone(trip['Traffic_Retirement'])
            finally:store.close()

    def test_arrival_does_not_count_second_traffic_exit_and_crosses_midnight(self):
        rows,_=self.run_extract(entry(86390,86395)+[
            event('vehicle leaves traffic',86420,person='p',vehicle='v',link='a',relativePosition='1'),
            event('arrival',86425,person='p',link='a')],horizon=90000)
        trip=rows[0]['Trip']
        self.assertEqual(trip['Departure'],86390)
        self.assertEqual(trip['Arrival'],86425)
        self.assertEqual(trip['Traffic_Entry'],86395)
        self.assertEqual(trip['Traffic_Exit'],86420)
        self.assertEqual(len(trip['Traffic_Intervals']),1)
        self.assertEqual(trip['Traffic_Intervals'][0]['end'],86420)
        self.assertIsNone(trip['Traffic_Retirement'])
        self.assertEqual(rows[0]['timestamps'],[86395,86420])

    def test_stream_end_cannot_extend_native_anchor_beyond_observed_events(self):
        rows,_=self.run_extract(entry()+[wait(20),wait(35)],horizon=86400)
        self.assertEqual(rows[-1]['timestamps'],[20,35])
        self.assertIsNone(rows[-1]['Trip']['Traffic_Retirement'])
        self.assertIsNone(rows[-1]['Trip']['Traffic_Intervals'][0]['end'])

    def test_wait_anchor_is_not_invented_from_unattributed_reason(self):
        rows,stats=self.run_extract(entry()+[wait(20,source='unknown'),
            event('stuckAndAbort',86401,person='p',vehicle='v',link='a')])
        self.assertEqual(rows,[])
        self.assertEqual(stats['unrepresented_open_link_intervals'],1)


if __name__=='__main__':unittest.main()
