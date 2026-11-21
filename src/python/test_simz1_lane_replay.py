import gzip
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from simz1_lane_replay import LaneEventReplay
import visualizador_z1 as viewer


class LaneReplayTests(unittest.TestCase):
    def setUp(self):
        self.links = {'a': {'from': [0, 0], 'to': [1, 0], 'length': 100, 'freespeed': 10},
                      'b': {'from': [1, 0], 'to': [2, 0], 'length': 100, 'freespeed': 10}}

    @staticmethod
    def event(kind, time, lane='a.original', link='a', vehicle='v'):
        return dict(type=kind, time=str(time), vehicle=vehicle, link=link, lane=lane)

    def test_native_insertion_exit_does_not_invent_an_entry(self):
        replay = LaneEventReplay(self.links)
        replay.add(self.event('vehicle enters traffic', 2))
        replay.add(self.event('left lane', 2))
        replay.add(self.event('entered lane', 2, 'a.lane.0'))
        replay.add(self.event('left lane', 8, 'a.lane.0'))
        result = replay.payload()
        self.assertEqual(result['event_count'], 3)
        self.assertEqual(result['distinct_observed_queues'], 2)
        self.assertEqual(result['exits_without_observed_entry'], 1)
        self.assertFalse(result['events'][0]['entry_observed'])
        self.assertTrue(result['events'][-1]['entry_observed'])
        self.assertEqual(result['events'][0]['type'], 'left lane')
        self.assertFalse(result['longitudinal_position_observed'])
        self.assertFalse(result['lateral_position_observed'])
        self.assertNotIn('position', result['events'][0])

    def test_traffic_exit_clears_membership_without_faking_lane_exit(self):
        replay = LaneEventReplay(self.links)
        replay.add(self.event('entered lane', 0))
        replay.add(self.event('vehicle leaves traffic', 5))
        replay.add(self.event('vehicle enters traffic', 30))
        replay.add(self.event('entered lane', 30, 'b.original', 'b'))
        result = replay.payload()
        self.assertEqual(result['left_lane_events'], 0)
        self.assertEqual(result['entries_without_observed_lane_exit'], 1)
        self.assertEqual(result['open_entries_at_end'], 1)
        self.assertEqual(result['events'][1],
                         dict(type='vehicle leaves traffic', time=5.0, vehicle='v'))
        self.assertEqual(result['events'][-1]['link'], 'b')

    def test_repeated_link_queues_and_incomplete_history_remain_explicit(self):
        replay = LaneEventReplay(self.links)
        for event in (self.event('entered lane', 1), self.event('left lane', 3),
                      self.event('entered lane', 3, 'b.original', 'b'),
                      self.event('left lane', 6, 'b.original', 'b'),
                      self.event('entered lane', 6), self.event('entered lane', 8, 'a.lane.0')):
            replay.add(event)
        result = replay.payload()
        self.assertEqual(result['entries_without_observed_lane_exit'], 1)
        self.assertEqual(result['open_entries_at_end'], 1)
        self.assertEqual([e['time'] for e in result['events']], [1, 3, 3, 6, 6, 8])
        self.assertEqual(result['vehicles_with_events'], 1)

    def test_unknown_links_and_invalid_times_are_not_silently_rendered(self):
        replay = LaneEventReplay(self.links)
        for event in (self.event('entered lane', 0, link='other-run'),
                      self.event('entered lane', 'nan'), self.event('entered lane', 0, lane=''),
                      self.event('entered lane', 0, vehicle=None)):
            with self.assertRaises(ValueError):
                replay.add(event)
        replay.add(self.event('entered lane', 5))
        with self.assertRaises(ValueError):
            replay.add(self.event('left lane', 4))

    def test_absent_lane_events_export_empty_evidence_not_assigned_lanes(self):
        replay = LaneEventReplay(self.links)
        replay.add(self.event('vehicle enters traffic', 0))
        replay.add(self.event('entered link', 0))
        replay.add(self.event('left link', 5))
        replay.add(self.event('vehicle leaves traffic', 5))
        result = replay.payload()
        self.assertEqual(result['event_count'], 0)
        self.assertEqual(result['events'], [])
        self.assertEqual(result['drawing'], 'interpolated_link_centerline_without_lane_offsets')

    def test_same_event_stream_supplies_replay_and_sampled_lane_evidence(self):
        source_text = '''<events>
        <event type="departure" person="p" link="a" time="0"/>
        <event type="vehicle enters traffic" person="p" vehicle="v" link="a" time="0"/>
        <event type="entered link" vehicle="v" link="a" time="0"/>
        <event type="entered lane" vehicle="v" link="a" lane="a.original" time="0"/>
        <event type="left lane" vehicle="v" link="a" lane="a.original" time="5"/>
        <event type="entered lane" vehicle="v" link="a" lane="a.lane.0" time="5"/>
        <event type="left lane" vehicle="v" link="a" lane="a.lane.0" time="12"/>
        <event type="left link" vehicle="v" link="a" time="12"/>
        <event type="vehicle leaves traffic" person="p" vehicle="v" link="a" time="12"/>
        <event type="arrival" person="p" link="a" time="12"/>
        </events>'''
        with tempfile.TemporaryDirectory(prefix='SimZ1 lane replay ') as folder:
            source = Path(folder)/'events.xml.gz'
            output = Path(folder)/'lane replay.html'
            with gzip.open(source, 'wt') as stream:
                stream.write(source_text)
            for rate, count in [(1, 4), (0, 0)]:
                replay = LaneEventReplay(self.links)
                with patch.object(viewer, 'EVENTS_FILE', source), patch.object(viewer, 'SAMPLE_RATE', rate):
                    segments = viewer.extraer_trayectorias(self.links, lane_replay=replay)
                    viewer.generar_html_animado(segments, self.links, output=output, lane_replay=replay)
                html = output.read_text(encoding='utf-8')
                result = json.loads(html.split('<script id="replay-data" type="application/json">')[1]
                                    .split('</script>')[0])
                self.assertEqual(result['lane_replay']['event_count'], count)
                self.assertEqual(result['lane_replay']['sample_rate'], rate)
                self.assertEqual(result['hud']['reconstructed_vehicles'], rate)
                if rate:
                    self.assertEqual(segments[0]['timestamps'], [0, 12])
                    self.assertEqual([e['lane'] for e in result['lane_replay']['events']],
                                     ['a.original', 'a.original', 'a.lane.0', 'a.lane.0'])
                self.assertIn('sin cambio lateral ni car-following continuo', html)


if __name__ == '__main__':
    unittest.main()
