import gzip
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
import visualizador_z1 as viewer
from procesar_eventos_z1 import movement_end_time
from simz1_motion import MotionContext, read_vehicles


class MotionTests(unittest.TestCase):
    def context(self, **kwargs):
        return MotionContext({'v':20/3.6},{'p':'Tortuga'},{'v':'p'},**kwargs)

    def extract(self, events, context=None, choose=1):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'events.xml.gz'
            with gzip.open(path,'wt') as f:f.write('<events>'+events+'</events>')
            stats={}
            with patch.object(viewer,'EVENTS_FILE',path),patch.object(viewer,'SAMPLE_RATE',choose):
                segments=viewer.extraer_trayectorias({'l':dict(length=1000,freespeed=50/3.6,
                    **{'from':[0,0],'to':[.01,0],'from_node':'a','to_node':'b'})},motion=context,stats=stats)
            return segments,stats

    def paired(self, start, end, extra=''):
        return (f'<event type="departure" person="p" link="l" time="{start}"/>'
            f'<event type="vehicle enters traffic" person="p" vehicle="v" link="l" time="{start}"/>'
            f'<event type="entered link" vehicle="v" link="l" time="{start}"/>'+extra+
            f'<event type="left link" vehicle="v" link="l" time="{end}"/>'
            f'<event type="arrival" person="p" link="l" time="{end}"/>')

    def test_turtle_free_link_no_false_queue_and_profile_loaded_first(self):
        segments,_=self.extract(self.paired(0,180),self.context())
        segment=segments[0]
        self.assertEqual(segment['Movement_End'],180)
        self.assertEqual(segment['Motion_Speed_kmh'],20)
        self.assertEqual(segment['Speed_kmh'],20)
        self.assertEqual(segment['Profile'],'Tortuga')
        self.assertEqual(segment['timestamps'],[0,180])

    def test_real_signal_wait_boundary_separate_from_measured_average(self):
        events=self.paired(0,210,'<event type="simz1NativeDecision" time="181" vehicle="v" link="l" decision="WAIT" reason="signal_red"/>')
        segments,_=self.extract(events,self.context())
        segment=segments[0]
        self.assertEqual(segment['Movement_End'],181)
        self.assertEqual(segment['Wait_Evidence'],'native_wait_observation')
        self.assertAlmostEqual(segment['Speed_kmh'],1000/210*3.6)
        self.assertEqual(segment['timestamps'],[0,210])
        self.assertEqual(segment['Observed_Waits']['signal_red']['first'],181)

    def test_residual_not_assigned_to_signal(self):
        segments,_=self.extract(self.paired(0,220),self.context())
        self.assertEqual(segments[0]['Movement_End'],180)
        self.assertEqual(segments[0]['Wait_Evidence'],'estimated_residual_unknown_cause')
        self.assertEqual(segments[0]['Observed_Waits'],{})

    def test_incident_at_entry_and_recovery_exact_boundary(self):
        context=self.context(lanes=False)
        context.change('l',0,10/3.6);context.change('l',360,50/3.6)
        link=dict(freespeed=50/3.6)
        a=context.estimate('v','l',link,0,360,1000)
        b=context.estimate('v','l',link,360,540,1000)
        self.assertEqual(a['Movement_End'],360)
        self.assertEqual(b['Movement_End'],540)
        self.assertEqual(a['Motion_Speed_kmh'],10)
        self.assertEqual(b['Motion_Speed_kmh'],20)

    def test_temporal_changes_inside_link_qsim_queue_snapshot_and_lane_fallback(self):
        for lanes,expected in ((False,180),(True,220),(None,220)):
            context=self.context(lanes=lanes);context.change('l',50,2)
            result=context.estimate('v','l',dict(freespeed=50/3.6),0,220,1000)
            self.assertEqual(result['Movement_End'],expected)
            self.assertEqual(result['Motion_Provenance']['changes_inside_interval'],True)
            if lanes is not False:self.assertIn('unknown_internal_queue',result['Motion_Provenance']['fallback_reason'])

    def test_incident_event_changes_link_limit_before_extraction(self):
        incident='<event type="zona1IncidentStart" time="0" link="l" freespeedMps="2.7777777777777777" capacityPerHour="100"/>'
        segments,_=self.extract(incident+self.paired(1,361),self.context())
        self.assertEqual(segments[0]['Movement_End'],361)
        self.assertEqual(segments[0]['Motion_Speed_kmh'],10)

    def test_same_timestamp_incident_after_entry_does_not_change_queue_snapshot(self):
        incident='<event type="zona1IncidentStart" time="0" link="l" freespeedMps="2.7777777777777777" capacityPerHour="100"/>'
        segments,_=self.extract(self.paired(0,210,incident),self.context(lanes=False))
        self.assertEqual(segments[0]['Movement_End'],180)
        segments,_=self.extract(incident+self.paired(0,360),self.context(lanes=False))
        self.assertEqual(segments[0]['Movement_End'],360)

    def test_missing_vehicle_speed_recovery_or_external_changes_do_not_invent_wait(self):
        for context in (MotionContext(),self.context(dynamic_known=False)):
            self.assertEqual(context.estimate('v','l',dict(freespeed=10),0,500,1000)['Movement_End'],500)
        context=self.context();context.change('l',5,None)
        self.assertEqual(context.estimate('v','l',dict(freespeed=10),6,500,1000)['Movement_End'],500)
        self.assertEqual(movement_end_time(0,500,1000,10),500)

    def test_null_interval_and_midnight_keep_absolute_times(self):
        for start,end in ((9,9),(86390,86570)):
            segments,stats=self.extract(self.paired(start,end),self.context())
            self.assertEqual(segments[0]['timestamps'],[start,end])
            self.assertEqual(segments[0]['Movement_End'],end)
            if start==end:
                self.assertIsNone(segments[0]['Speed_kmh'])
                self.assertEqual(stats['zero_duration_intervals'],1)
                self.assertEqual(stats['drawable_vehicles'],0)
                self.assertEqual(stats['vehicles_without_drawable_segments'],1)

    def test_single_link_relative_positions_without_entered_left_events(self):
        events='''<event type="departure" person="p" link="l" time="0"/>
        <event type="vehicle enters traffic" person="p" vehicle="v" link="l" time="1" relativePosition="0.25"/>
        <event type="vehicle leaves traffic" person="p" vehicle="v" link="l" time="91" relativePosition="0.75"/>
        <event type="arrival" person="p" link="l" time="92"/>'''
        segments,stats=self.extract(events,self.context())
        self.assertEqual(len(segments),1)
        segment=segments[0]
        self.assertEqual(segment['path'],[[.0025,0],[.0075,0]])
        self.assertEqual(segment['timestamps'],[1,91])
        self.assertEqual(segment['Speed_kmh'],20)
        self.assertEqual(segment['Trip']['Departure'],0)
        self.assertEqual(segment['Trip']['Arrival'],92)
        self.assertEqual(segment['Trip']['Destination_Position'],[.0075,0])
        self.assertFalse(segment['Inferred'])

    def test_no_interpolation_after_traffic_exit_even_without_pending_entry(self):
        events='''<event type="departure" person="p" link="l" time="0"/>
        <event type="vehicle enters traffic" person="p" vehicle="v" link="l" time="0"/>
        <event type="entered link" vehicle="v" link="l" time="1"/>
        <event type="left link" vehicle="v" link="l" time="181"/>
        <event type="vehicle leaves traffic" vehicle="v" person="p" link="l" time="182" relativePosition="1"/>
        <event type="arrival" person="p" link="l" time="185"/>'''
        segments,stats=self.extract(events,self.context())
        self.assertEqual(len(segments),1)
        self.assertEqual(segments[0]['timestamps'],[1,181])
        self.assertEqual(segments[0]['Trip']['Arrival'],185)
        self.assertEqual(stats['unpaired_traffic_exits'],1)

    def test_unpaired_or_unsampled_vehicles_remain_in_counts(self):
        events='''<event type="departure" person="p" link="l" time="1"/>
        <event type="vehicle enters traffic" person="p" vehicle="v" link="l" time="1"/>
        <event type="vehicle leaves traffic" person="p" vehicle="v" link="l" time="2"/>
        <event type="arrival" person="p" link="l" time="2"/>'''
        for rate in (0,1):
            segments,stats=self.extract(events,self.context(),rate)
            self.assertFalse(segments)
            self.assertEqual(stats['observed_persons'],1)
            self.assertEqual(stats['observed_vehicles'],1)
            self.assertEqual(stats['vehicles_without_segments'],1)
        _,stats=self.extract('<event type="vehicle enters traffic" time="1" person="p" vehicle="v" link="l"/>',self.context(),0)
        self.assertEqual(stats['observed_persons'],1)
        self.assertEqual(stats['observed_departures'],0)

    def test_namespace_vehicle_types_are_authoritative_not_profile_guesses(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'vehicles.xml'
            path.write_text('''<vehicleDefinitions xmlns="http://www.matsim.org/files/dtd">
              <vehicleType id="Tortuga"><maximumVelocity meterPerSecond="4"/></vehicleType>
              <vehicle id="v" type="Tortuga"/></vehicleDefinitions>''')
            types,vehicles=read_vehicles(path)
            self.assertEqual(types,{'Tortuga':4})
            self.assertEqual(vehicles,{'v':'Tortuga'})
            path.write_text('<vehicleDefinitions><vehicle id="v" type="missing"/></vehicleDefinitions>')
            with self.assertRaisesRegex(ValueError,'tipo de vehiculo'):read_vehicles(path)
            for invalid in ('<vehicle type="a"/>', '<vehicleType id="a"><maximumVelocity meterPerSecond="0"/></vehicleType>',
                            '<vehicleType id="a"/><vehicleType id="a"/>'):
                path.write_text('<vehicleDefinitions>'+invalid+'</vehicleDefinitions>')
                with self.assertRaises(ValueError): read_vehicles(path)

    def test_invalid_boundary_positions_and_negative_intervals_fail(self):
        with self.assertRaises(ValueError):self.extract('<event type="vehicle enters traffic" time="1" vehicle="v" link="l" relativePosition="1.2"/>')
        with self.assertRaises(ValueError):self.extract(self.paired(2,1))
        for start,end,distance,speed in ((2,1,5,10),(0,1,-1,10),(0,1,10,float('nan'))):
            with self.assertRaises(ValueError):MotionContext().estimate('v','l',dict(freespeed=speed),start,end,distance)


if __name__=='__main__':unittest.main()
