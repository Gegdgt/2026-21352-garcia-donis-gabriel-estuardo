import unittest
from microscopic_traffic import MicroscopicPlayback, Operation, Vehicle, Profile, intersection_clear


class IntersectionTests(unittest.TestCase):
    def test_exported_stop_line_precedes_avenue_edge(self):
        import gzip
        import xml.etree.ElementTree as ET
        from pathlib import Path
        path = Path(__file__).resolve().parents[1]/'output/labs/08-zona1-right-of-way/output_network.xml.gz'
        if not path.exists():
            self.skipTest('Generate the right-of-way export first')
        with gzip.open(path,'rb') as stream:
            roads = ET.parse(stream).getroot().findall('links/link')
        stops = 0
        for road in roads:
            attrs = {a.get('name'):a.text for a in road.findall('attributes/attribute')}
            if attrs.get('rightOfWay') == 'true':
                self.assertEqual(attrs['stopBeforeAvenue'],'false')
            if attrs.get('stopBeforeAvenue') == 'true':
                stops += 1
                self.assertGreaterEqual(float(attrs['stopLineSetback']),7.05)
                if road.get('to').startswith(('A6_','A7_','A8_','A9_')):
                    self.assertGreaterEqual(float(attrs['stopLineSetback']),10.85-1e-8)
        self.assertGreater(stops,0)

    def test_lateral_approach_and_frontal_gap(self):
        base = dict(length=200,lanes=2,lane_width=3.8,freespeed=12.5,capacity=1600)
        links = {
            'street':dict(base,from_id='w',to_id='j'),
            'out':dict(base,from_id='j',to_id='e'),
            'avenue':dict(base,from_id='s',to_id='j',right_of_way=True),
            'north':dict(base,from_id='j',to_id='n')}
        v = Vehicle('f',[Operation('street',0,0),Operation('out',0,0)],Profile(1,0),visible=True)
        other = Vehicle('other',[Operation('avenue',0,0)],Profile(1,0),visible=True,distance=160,speed=1)
        active = {'f':v,'other':other}
        # Slow priority arrival must include its possible acceleration.
        self.assertFalse(intersection_clear(v,active,links))
        other.distance = 0
        self.assertTrue(intersection_clear(v,active,links))
        other.ops = [Operation('out',0,0)]; other.distance=4
        self.assertFalse(intersection_clear(v,active,links))
        other.ops = [Operation('north',0,0)]; other.distance=3
        self.assertFalse(intersection_clear(v,active,links))
        other.distance=100
        self.assertTrue(intersection_clear(v,active,links))

    def test_street_stops_but_priority_avenue_does_not(self):
        for stop in (False, True):
            road = dict(length=100, lanes=1, lane_width=3.8, freespeed=10, capacity=800,
                        from_id='a', to_id='b', stop_before_avenue=stop,
                        right_of_way=not stop, **{'from':(0,0),'to':(100,0)})
            next_road = dict(road, from_id='b', to_id='c', stop_before_avenue=False,
                             **{'from':(100,0),'to':(200,0)})
            engine = MicroscopicPlayback({'f':[Operation('a',0,0),Operation('b',0,0)]},
                                         {'a':road,'b':next_road}, focal=True,dt=.5)
            frames = list(engine.frames(start_time=0,end_time=180))
            self.assertEqual(engine.completed,1)
            if stop:
                events = engine.intersection_log
                self.assertEqual([e[3] for e in events],['stop','release'])
                self.assertGreaterEqual(events[1][0]-events[0][0],1)
                stopped = [s for _,f in frames for s in f.values() if s.source=='intersection']
                self.assertTrue(stopped)
                self.assertTrue(all(s.speed==0 and abs(s.distance-96.75)<1e-6 for s in stopped))
            else:
                self.assertEqual(engine.intersection_log,[])

if __name__ == '__main__':
    unittest.main()
