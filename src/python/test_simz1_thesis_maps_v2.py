import csv
import gzip
from pathlib import Path
import tempfile
import unittest

import simz1_thesis_maps_v2 as maps


class MapsEvidenceTests(unittest.TestCase):
    def test_modes_are_unordered_but_speed_and_direction_matter(self):
        xml='''<network><attributes><attribute name="coordinateReferenceSystem">EPSG:32615</attribute></attributes>
        <nodes><node id="a" x="1" y="2"/><node id="b" x="3" y="4"/></nodes>
        <links><link id="l" from="a" to="b" length="3" permlanes="1" freespeed="10" capacity="2000" modes="{}"/></links></network>'''
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'network.xml'
            path.write_text(xml.format('bus,car'));first=maps.read_network(path)
            path.write_text(xml.format('car,bus'));self.assertEqual(first,maps.read_network(path))
            path.write_text(xml.format('car,bus').replace('freespeed="10"','freespeed="11"'))
            self.assertNotEqual(first,maps.read_network(path))
            path.write_text(xml.format('car,bus').replace('from="a" to="b"','from="b" to="a"'))
            self.assertNotEqual(first,maps.read_network(path))

    def test_ab_common_pair_ranking_excludes_censor_bus_and_same_link(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            runs=[]
            fields=['run_id','iteration','person_id','vehicle_id','status','departure_link','arrival_link',
                    'profile','departure','arrival','duration_seconds']
            for label,rid,count in [('run1000','one',2),('run10000','ten',3)]:
                path=root/(label+'.csv.gz')
                base=dict(run_id=rid,iteration='0',person_id='z1_1',vehicle_id='z1_1',status='completed',
                          departure_link='A',arrival_link='B',profile='Conductor',departure='5',arrival='15',duration_seconds='10')
                rows=[dict(base) for _ in range(count)]
                rows.extend([{**base,'status':'censored'},{**base,'person_id':'pt_driver'},
                             {**base,'arrival_link':'A'},{**base,'arrival_link':'C'}])
                with gzip.open(path,'wt',encoding='utf-8',newline='') as stream:
                    writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader();writer.writerows(rows)
                runs.append(dict(label=label,run_id=rid,trips=path))
            result=maps.select_ab(runs,{'A':{},'B':{},'C':{}},root)
            self.assertEqual(result[0]['destination_link'],'B')
            self.assertEqual((result[0]['n_run1000'],result[0]['n_run10000']),(2,3))
            self.assertEqual(result[1]['selection_score'],1)
            self.assertTrue((root/'ab-pares-comunes.csv').is_file())
            runs[1]['run_id']='foreign'
            with self.assertRaisesRegex(ValueError,'identity'):
                maps.select_ab(runs,{'A':{},'B':{},'C':{}},root)


if __name__=='__main__':
    unittest.main()
