import unittest
from unittest.mock import patch
from microscopic_traffic import (Profile,Operation,MicroscopicPlayback,following_acceleration,
                                 sample_color,GAP)


class KinematicsTests(unittest.TestCase):
    def test_profiles_and_proportional_emergency(self):
        profiles = [Profile(1,0,kind=k) for k in ('tortuga','normal','liebre')]
        self.assertEqual([following_acceleration(0,20,profile=p) for p in profiles],[.8,2,3])
        p = profiles[1]
        comfortable = following_acceleration(10,10,0,GAP+50,p)
        emergency = following_acceleration(10,10,0,GAP+6,p)
        critical = following_acceleration(10,10,0,GAP+1,p)
        self.assertLess(emergency, comfortable)
        self.assertLess(critical,emergency)

    def test_parking_three_seconds_yellow_and_resumes(self):
        road = dict(length=120,lanes=1,capacity=800,freespeed=10,lane_width=3.8,
                    **{'from':(0,0),'to':(120,0)})
        with patch('microscopic_traffic.random_focal_profile',return_value=Profile(1,0,kind='normal')):
            engine = MicroscopicPlayback({'f':[Operation('a',0,0)]},{'a':road},dt=.5,focal=True)
        frames = list(engine.frames(start_time=0,end_time=120))
        self.assertEqual(engine.completed,1)
        self.assertEqual(len(engine.parking_log),1)
        _,start,end,_,_,distance = engine.parking_log[0]
        self.assertEqual(end-start,3)
        parked = [(t,f['f']) for t,f in frames if 'f' in f and f['f'].state=='parking']
        self.assertEqual([t for t,_ in parked],[start+i*.5 for i in range(6)])
        self.assertTrue(all(s.speed==0 and s.distance==distance and sample_color(s)=='#FFFFFF' for _,s in parked))
        self.assertTrue(any(t>end and f.get('f') and f['f'].speed>0 for t,f in frames))

    def test_faster_follower_never_overlaps_slow_leader(self):
        road = dict(length=200,lanes=1,capacity=800,freespeed=15,
                    **{'from':(0,0),'to':(200,0)})
        routes = {'leader':[Operation('a',0,0,first=.15)],'follower':[Operation('a',0,0)]}
        def profile(agent):
            return Profile(1 if agent=='leader' else 1.5,0,kind='tortuga' if agent=='leader' else 'liebre')
        with patch('microscopic_traffic.agent_profile',side_effect=profile):
            engine = MicroscopicPlayback(routes,{'a':road},dt=.5,synthetic_stops=False)
            frames = list(engine.frames(start_time=0,end_time=180))
        self.assertEqual(engine.completed,2)
        paired = [f for _,f in frames if len(f)==2]
        self.assertTrue(paired)
        self.assertTrue(all(f['leader'].distance-f['follower'].distance>=GAP-1e-8 for f in paired))

if __name__ == '__main__':
    unittest.main()
