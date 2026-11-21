"""Disposable synthetic cache fixtures; no existing replay is rewritten."""
import gzip
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from simz1_window_cache import WindowCache


class WindowCacheTests(unittest.TestCase):
    def test_renderer_change_invalidates_persisted_capsule_window(self):
        from simz1_window_cache import reader_version
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);module=root/'simz1_window_cache.py';module.write_text('fixture')
            renderer=root/'simz1_visual_queues.js';renderer.write_text('before')
            helper=root/'simz1_queue_checkpoint.cjs';helper.write_text('before')
            with patch('simz1_window_cache.__file__',str(module)):
                original=reader_version()
                raw=b'capsule-fixture';compressed=gzip.compress(raw)
                cache=WindowCache(root/'cache',{}, {},version=original)
                cache.put(0,compressed,len(raw),{},hashlib.sha256(raw).hexdigest())
                for path in (renderer,helper):
                    path.write_text('after')
                    changed=reader_version()
                    self.assertNotEqual(changed,original)
                    self.assertIsNone(WindowCache(root/'cache',{}, {},version=changed).get(0))
                    path.write_text('before')
                    self.assertEqual(reader_version(),original)

    def test_restart_identity_version_integrity_and_disk_budget(self):
        with tempfile.TemporaryDirectory() as folder:
            identity=dict(run_id='synthetic',iteration=0,source_version='source-v1')
            manifest=dict(window_seconds=120)
            raw=json.dumps(dict(**identity,index=161,segments=[{'complete':'synthetic'}])).encode()
            compressed=gzip.compress(raw);sha=hashlib.sha256(raw).hexdigest()
            cache=WindowCache(folder,identity,manifest,version='reader-v1')
            self.assertTrue(cache.put(161,compressed,len(raw),{},sha))
            restarted=WindowCache(folder,identity,manifest,version='reader-v1')
            self.assertEqual(restarted.get(161),(compressed,len(raw),{},sha))
            for changed in (dict(identity,iteration=1),dict(identity,run_id='another'),dict(identity,source_version='source-v2')):
                self.assertIsNone(WindowCache(folder,changed,manifest,version='reader-v1').get(161))
            self.assertIsNone(WindowCache(folder,identity,manifest,version='reader-v2').get(161))
            self.assertIsNone(WindowCache(folder,identity,dict(window_seconds=60),version='reader-v1').get(161))
            path=cache.paths(161);original=path.read_bytes();path.write_bytes(original[:-1])
            self.assertIsNone(cache.get(161))
            self.assertEqual(cache.summary()['invalid_entries'],1)
            self.assertTrue(cache.put(161,compressed,len(raw),{},sha))
            self.assertEqual(cache.get(161)[0],compressed)
            limited=WindowCache(folder,identity,manifest,version='budget',max_bytes=1)
            self.assertFalse(limited.put(161,compressed,len(raw),{},sha))
            self.assertFalse(limited.paths(161).exists())
            self.assertEqual(path.read_bytes(),original,'another namespace cannot alter existing cache')

    def test_wrong_header_and_expanding_payload_are_not_reused(self):
        with tempfile.TemporaryDirectory() as folder:
            cache=WindowCache(folder,{}, {},version='fixture')
            raw=b'x'*100000;data=gzip.compress(raw);sha=hashlib.sha256(raw).hexdigest()
            cache.put(0,data,len(raw),{},sha)
            path=cache.paths(0);head,body=path.read_bytes().split(b'\n',1)
            meta=json.loads(head);meta['json_bytes']=10
            path.write_bytes(json.dumps(meta).encode()+b'\n'+body)
            self.assertIsNone(cache.get(0),'bounded inflation must reject an inconsistent size')
            meta['json_bytes']=len(raw);meta['namespace']='wrong'
            path.write_bytes(json.dumps(meta).encode()+b'\n'+body)
            self.assertIsNone(cache.get(0))


if __name__=='__main__':unittest.main()
