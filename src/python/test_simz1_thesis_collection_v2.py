import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image
import simz1_thesis_collection_v2 as c


class CollectionGuards(unittest.TestCase):
    def test_historical_tree_is_never_imported(self):
        with tempfile.TemporaryDirectory() as td,patch.object(c,'OUT',Path(td)):
            root=Path(td);(root/'auditoria-existente.json').write_text('{"figures":[]}')
            (root/'mapas-red-vial').mkdir();(root/'mapas-red-vial/manifest.json').write_text('{"figures":[]}')
            (root/'historical-run').mkdir();(root/'historical-run/figures-manifest.json').write_text('This must never be read')
            self.assertEqual(c.figures(),[])

    def test_wrong_run_inside_allowed_folder_rejected(self):
        with tempfile.TemporaryDirectory() as td,patch.object(c,'OUT',Path(td)):
            root=Path(td);(root/'auditoria-existente.json').write_text('{"figures":[]}')
            folder=root/c.RUNS[0][0];folder.mkdir()
            (folder/'figures-manifest.json').write_text('{"identities":[{"run_id":"wrong","iteration":0}],"figures":[]}')
            with self.assertRaisesRegex(ValueError,'unrequested native identity'):c.figures()

    def test_os_writer_lock_rejects_second_process_and_releases(self):
        with tempfile.TemporaryDirectory() as td,patch.object(c,'OUT',Path(td)):
            code='import pathlib,sys; sys.path.insert(0,sys.argv[1]); import simz1_thesis_collection_v2 as c; c.OUT=pathlib.Path(sys.argv[2]);\nwith c.collection_lock(): print("acquired")'
            args=[sys.executable,'-X','utf8','-B','-c',code,str(c.ROOT/'python'),td]
            with c.collection_lock():
                blocked=subprocess.run(args,capture_output=True,text=True)
                self.assertNotEqual(blocked.returncode,0)
                self.assertIn('Another thesis collection writer',blocked.stderr)
            available=subprocess.run(args,capture_output=True,text=True)
            self.assertEqual(available.returncode,0,available.stderr)

    def fixture(self,folder):
        Image.new('RGB',(600,600),'white').save(folder/'figure.png')
        (folder/'figure.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
        (folder/'figure.csv').write_text('a\n1\n')
        (folder/'figure.json').write_text('{}')
        (folder/'source.csv').write_text('native\n1\n')
        files=[dict(path='figure'+suffix,sha256=c.sha(folder/('figure'+suffix))) for suffix in ('.png','.svg','.csv','.json')]
        return dict(files=files,sources=[dict(path='source.csv',sha256=c.sha(folder/'source.csv'))])

    def test_positive_artifacts_and_mutation_rejected(self):
        with tempfile.TemporaryDirectory() as td,patch.object(c,'OUT',Path(td)),patch.object(c,'native_integrity',return_value={'status':'passed'}):
            row=self.fixture(Path(td));self.assertEqual(c.verify([row],[])['artifacts_checked'],4)
            (Path(td)/'figure.csv').write_text('a\n2\n')
            with self.assertRaisesRegex(ValueError,'Artifact hash'):c.verify([row],[])

    def test_missing_source_rejected(self):
        with tempfile.TemporaryDirectory() as td,patch.object(c,'OUT',Path(td)),patch.object(c,'native_integrity',return_value={'status':'passed'}):
            row=self.fixture(Path(td));(Path(td)/'source.csv').unlink()
            with self.assertRaisesRegex(ValueError,'Missing/changed source'):c.verify([row],[])


if __name__=='__main__':unittest.main()
