import gzip
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import visualizador_z1 as viewer

class WebReplayTests(unittest.TestCase):
    def test_payload_injection_rejects_errors_and_preserves_json(self):
        template='<script type="application/json">__PAYLOAD__</script><script>__CONTROLS__</script>'
        replay={'layers':[{'id':'trips','data':[{'vehicle':'</script>& auditor'}]},
                          {'id':'incidents','data':[]}]}
        html=viewer.render_replay_html(template,'render();',replay)
        self.assertNotIn('__PAYLOAD__',html)
        self.assertNotIn('__CONTROLS__',html)
        self.assertEqual(json.loads(html.split('>',1)[1].split('</script>',1)[0]),replay)
        for invalid in ('', 'Error al leer eventos', {}, None, {'layers':[]}):
            with self.assertRaises(ValueError): viewer.render_replay_html(template,'',invalid)
        with self.assertRaises(ValueError): viewer.render_replay_html('sin marcador','',replay)
        with self.assertRaises(ValueError): viewer.generar_html_animado('Error al leer eventos',{})

    def test_all_signal_approaches_and_horizontal_rotation(self):
        center = [-90.513, 14.636]
        links = {}
        for bearing in (0, 90, 180, 270):
            start = list(viewer.GEOD.fwd(*center, bearing + 180, 100)[:2])
            links[str(bearing)] = {'from': start, 'to': center, 'to_node': 'signal'}
        links['outgoing'] = {'from': center, 'to': [-90.51, 14.64], 'to_node': 'other'}
        links['zero'] = {'from': center, 'to': center, 'to_node': 'signal'}
        links['disconnected'] = {'from': [-90.51, 14.64], 'to': center, 'to_node': 'other'}
        signals = viewer.preparar_semaforos([{'node': 'signal', 'position': center}]*2, links)
        self.assertEqual(len(signals), 8)  # No coordinate deduplication.
        for signal in signals:
            self.assertEqual(signal['angle'], 90 if signal['Link_ID'] in ('90','270') else 0)
        isolated = viewer.preparar_semaforos([{'node':'isolated','position':center}], {})
        self.assertEqual(len(isolated),1)
        self.assertEqual(isolated[0]['angle'],0)
        self.assertEqual(viewer.preparar_semaforos([], links), [])

    def test_arrival_does_not_fabricate_missing_entry_after_traffic_exit(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'events.gz'
            prefix='''<event type="departure" person="p" link="a" time="0"/>
            <event type="vehicle enters traffic" person="p" vehicle="v" link="a" time="0"/>
            <event type="entered link" vehicle="v" link="a" time="1"/>
            <event type="left link" vehicle="v" link="a" time="10"/>
            <event type="vehicle leaves traffic" person="p" vehicle="v" link="b" time="20"/>'''
            links={'a':dict(length=100, **{'from':[-90.518,14.64], 'to':[-90.517,14.64]}),
                   'b':dict(length=100, **{'from':[-90.517,14.64], 'to':[-90.516,14.64]})}
            for arrival in ('', '<event type="arrival" person="p" link="b" time="20"/>'):
                with gzip.open(source,'wt') as stream:
                    stream.write('<events>'+prefix+arrival+'</events>')
                with patch.object(viewer,'EVENTS_FILE',source):
                    stats={}
                    segments=viewer.extraer_trayectorias(links,stats=stats)
                self.assertEqual(len(segments),1)
                self.assertEqual(stats['unpaired_traffic_exits'],1)
                self.assertFalse(segments[-1]['Inferred'])
                if arrival:
                    self.assertEqual(segments[-1]['Trip']['Arrival'],20)

    def test_full_event_range_survives_extraction_and_export(self):
        # Incluye madrugada, ambos picos y un viaje que cruza medianoche.
        windows = [(0, 30), (21600, 21660), (45000, 45090),
                   (64800, 64920), (86390, 86420)]
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'events.gz'
            output = Path(folder) / 'replay.html'
            events = ['<events>']
            for i, (start, end) in enumerate(windows):
                events.extend([
                    f'<event type="departure" person="p{i}" link="l" time="{start}"/>',
                    f'<event type="vehicle enters traffic" person="p{i}" vehicle="v{i}" link="l" time="{start}"/>',
                    f'<event type="entered link" vehicle="v{i}" link="l" time="{start}"/>',
                    f'<event type="left link" vehicle="v{i}" link="l" time="{end}"/>',
                    f'<event type="arrival" person="p{i}" link="l" time="{end}"/>'])
            events.append('</events>')
            with gzip.open(source, 'wt') as stream:
                stream.write('\n'.join(events))
            links = {'l': {'from': [0, 0], 'to': [1, 1], 'length': 100,
                           'from_node': 'n1', 'to_node': 'n2'}}
            with patch.object(viewer, 'EVENTS_FILE', source), \
                 patch.object(viewer, 'SAMPLE_RATE', 1), \
                 patch.object(viewer, 'OUTPUT_HTML', output):
                segments = viewer.extraer_trayectorias(links)
                viewer.generar_html_animado(segments + segments, links)
            self.assertEqual([s['timestamps'] for s in segments], [list(w) for w in windows])
            html = output.read_text(encoding='utf-8')
            payload = json.loads(html.split('<script id="replay-data" type="application/json">')[1].split('</script>')[0])
            exported = next(layer['data'] for layer in payload['layers'] if layer['id'] == 'trips')
            self.assertEqual(exported, segments + segments)
            self.assertEqual(payload['hud']['reconstructed_vehicles'],len({s['vehicle'] for s in exported}))
            self.assertLess(payload['hud']['reconstructed_vehicles'],len(exported))

    def test_incident_intervals_without_sample_dependency(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'events.gz'
            with gzip.open(source,'wt') as stream:
                stream.write('''<events>
                <event type="zona1IncidentStart" link="l" time="10" capacityPerHour="400" freespeedMps="3"/>
                <event type="zona1IncidentRecovered" link="l" time="30"/>
                <event type="zona1IncidentStart" link="l" time="40" capacityPerHour="200" freespeedMps="2"/>
                </events>''')
            incidents=[]
            with patch.object(viewer,'EVENTS_FILE',source),patch.object(viewer,'SAMPLE_RATE',0):
                viewer.extraer_trayectorias({'l':{'from':[0,2],'to':[2,4]}},incidents)
            self.assertEqual(len(incidents),2)
            self.assertEqual(incidents[0]['position'],[1,3])
            self.assertEqual(incidents[0]['end'],30)
            self.assertIsNone(incidents[1]['end'])
            self.assertEqual(incidents[0]['capacity'],400)

    def test_paired_events_speed_identity_and_sampling(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'events.gz'
            with gzip.open(source,'wt') as stream:
                stream.write('''<events>
                <event type="departure" person="person_1" link="l" time="0"/>
                <event type="vehicle enters traffic" person="person_1" vehicle="car_9" link="l" time="0"/>
                <event type="entered link" vehicle="car_9" link="l" time="10"/>
                <event type="left link" vehicle="car_9" link="l" time="20"/>
                <event type="entered link" vehicle="car_9" link="l" time="21"/>
                <event type="left link" vehicle="car_9" link="l" time="61"/>
                <event type="entered link" vehicle="car_9" link="l" time="62"/>
                <event type="arrival" person="person_1" link="l" time="70"/>
                </events>''')
            links={'l':{'from':[0,0],'to':[1,1],'length':100,'freespeed':10,'from_node':'n1','to_node':'n2'}}
            with patch.object(viewer,'EVENTS_FILE',source),patch.object(viewer,'SAMPLE_RATE',0):
                self.assertEqual(viewer.extraer_trayectorias(links),[])
            with patch.object(viewer,'EVENTS_FILE',source),patch.object(viewer,'SAMPLE_RATE',1):
                from simz1_motion import MotionContext
                trips=viewer.extraer_trayectorias(links,motion=MotionContext({'car_9':10}))
                self.assertEqual(len(trips),3)
                self.assertTrue(trips[2]['Inferred'])
                self.assertEqual(trips[2]['timestamps'],[62,70])
                self.assertEqual(trips[2]['path'][-1],links['l']['to'])
                self.assertEqual(trips[0]['Agent_ID'],'person_1')
                self.assertEqual(trips[0]['Speed_kmh'],36)
                self.assertEqual(trips[1]['Speed_kmh'],9)
                self.assertEqual(trips[1]['Movement_End'],31)
                self.assertEqual(trips[1]['Motion_Speed_kmh'],36)
                self.assertEqual(trips[0]['color'],[255,210,40])
                self.assertEqual(trips[1]['color'],[245,65,65])
                self.assertEqual(trips[0]['Trip'], {'Departure':0,'Arrival':70,'Trip_ID':'person_1:trip:0001',
                    'Person_ID':'person_1','Trip_Index':1,'Status':'completed','Abort':None,'Last_Observed_Time':70,
                    'Observation_End':70,'Observation_End_Provenance':'last_event_in_stream',
                    'Origin_Node':'n1','Destination_Node':'n2','Origin_Position':[0,0],'Destination_Position':[1,1]})

    def test_color_boundaries(self):
        self.assertEqual(viewer.color_velocidad(0),[255,255,255])
        self.assertEqual(viewer.color_velocidad(14.99),[245,65,65])
        self.assertEqual(viewer.color_velocidad(15),[255,210,40])
        self.assertEqual(viewer.color_velocidad(40),[255,210,40])
        self.assertEqual(viewer.color_velocidad(40.01),[40,210,95])

    def test_stationary_measured_and_inferred_segments_export_white(self):
        events = '''<events>
        <event type="departure" person="p" link="l" time="0"/>
        <event type="vehicle enters traffic" person="p" vehicle="v" link="l" time="0"/>
        <event type="entered link" vehicle="v" link="l" time="1"/>
        <event type="left link" vehicle="v" link="l" time="11"/>
        <event type="arrival" person="p" link="l" time="16"/>
        </events>'''
        position = [-90.517, 14.64]
        links = {'l': {'from': position, 'to': position, 'length': 100, 'freespeed': 10}}
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder)/'events.gz'
            with gzip.open(source, 'wt') as stream:
                stream.write(events)
            with patch.object(viewer, 'EVENTS_FILE', source):
                segments = viewer.extraer_trayectorias(links)
        self.assertEqual(len(segments), 2)
        self.assertTrue(segments[1]['Inferred'])
        for segment in segments:
            self.assertEqual(segment['color'], [255,255,255])
            self.assertEqual(segment['Motion_Speed_kmh'], 0)
            self.assertEqual(segment['Movement_End'], segment['timestamps'][0])
        # Preserve the measured link speed; visual speed reflects the fixed position.
        self.assertEqual(segments[0]['Speed_kmh'], 36)

    def test_signal_metadata_survives_streaming(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'network.gz'
            with gzip.open(source,'wt') as stream:
                stream.write('''<network><nodes><node id="1" x="770000" y="1619000"><attributes>
                <attribute name="osm:highway" class="java.lang.String">traffic_signals</attribute>
                </attributes></node><node id="2" x="770100" y="1619000"/></nodes>
                <links><link id="l" from="1" to="2" length="100"/></links></network>''')
            with patch.object(viewer,'NETWORK_FILE',source):links,signals=viewer.extraer_red()
            self.assertEqual(len(signals),1)
            self.assertEqual(signals[0]['position'],links['l']['from'])
            self.assertEqual(links['l']['length'],100)

    def test_html_layers_and_time_controls(self):
        with tempfile.TemporaryDirectory() as folder:
            output=Path(folder)/'replay.html'
            with patch.object(viewer,'OUTPUT_HTML',output):
                viewer.generar_html_animado([],{'l':{'from':[0,0],'to':[1,1]}},[])
            html=output.read_text(encoding='utf-8')
            self.assertGreater(html.index('function animate'),html.index('const deckInstance'))
            self.assertNotIn('deckInstance.props',html)
            self.assertNotIn('deckgl.props',html)
            self.assertNotIn('createDeck(',html)
            self.assertIn('new deck.Deck(',html)
            self.assertIn('getFillColor: d => d.color',html)
            payload=json.loads(html.split('<script id="replay-data" type="application/json">')[1].split('</script>')[0])
            self.assertEqual(payload['hud']['reconstructed_vehicles'],0)
            self.assertEqual(payload['layers'][0]['getColor'],[110,120,130])
            self.assertEqual(next(l for l in payload['layers'] if l['id']=='trips')['radiusUnits'],'pixels')
            self.assertEqual(next(l for l in payload['layers'] if l['id']=='signals')['sizeUnits'],'pixels')
            self.assertEqual(next(l for l in payload['layers'] if l['id']=='signals')['getPixelOffset'],[0,0])
            self.assertNotIn('signal-directions',html)
            self.assertNotIn('data:image/svg+xml',html)
            self.assertEqual(next(l for l in payload['layers'] if l['id']=='signals')['getAngle'],'@@=angle')
            self.assertIn('getAngle: d => d.angle',html)
            self.assertNotIn('@@=pixels',html)
            self.assertTrue(next(l for l in payload['layers'] if l['id']=='signals')['iconAtlas'].startswith('data:image/png;base64,'))
            self.assertTrue(next(l for l in payload['layers'] if l['id']=='incidents')['iconAtlas'].startswith('data:image/png;base64,'))
            self.assertIn('IconLayer',html)
            self.assertIn('activeSegment',html)
            self.assertIn('data: markers, visible: true',html)
            self.assertIn('selected-history',html)
            origin=next(l for l in payload['layers'] if l['id']=='selected-origin')
            self.assertEqual(origin['getFillColor'],[255,255,255])
            destination=next(l for l in payload['layers'] if l['id']=='selected-destination')
            self.assertEqual(destination['@@type'],'IconLayer')
            self.assertTrue(destination['iconAtlas'].startswith('data:image/png;base64,'))
            self.assertEqual(destination['iconMapping']['finish']['anchorY'],60)
            for ident, color in [('selected-history', [0,139,184]), ('selected-future', [135,225,255])]:
                layer = next(l for l in payload['layers'] if l['id']==ident)
                self.assertEqual(layer['@@type'], 'PathLayer')
                self.assertEqual(layer['getColor'], color)
            self.assertIn('getTooltip: null',html)
            self.assertIn('toggle.onclick',html)

if __name__=='__main__':unittest.main()
