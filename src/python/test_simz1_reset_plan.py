"""Reset regressions: every writable/deletable fixture is in TemporaryDirectory.

These tests do not inspect real processes or Git, and never target a real run.
"""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

SPEC=importlib.util.spec_from_file_location('reset_plan_tests',Path(__file__).resolve().parents[1]/'scripts/maintenance/reset_simz1_runs.py')
reset=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(reset)


class ResetPlanTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).absolute()
        self.protected=self.root/reset.PROTECTED
        self.write(self.protected/'run-manifest.json',dict(run_id=reset.PROTECTED_ID,folder=str(self.protected),status='failed'))
        (self.protected/'events.gz').write_bytes(b'protected failed evidence')
        self.old,self.manifest=self.make_run_fixture('run-old')

    def write(self,path,value):
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(value),encoding='utf-8')

    def make_run_fixture(self,name):
        folder=self.root/'scenarios/zona1/montecarlo'/name
        value=dict(run_id='simz1-'+hashlib.sha256(name.encode()).hexdigest()[:32],folder=str(folder),status='completed')
        self.write(folder/'run-manifest.json',value)
        (folder/'events.gz').write_bytes(b'fixture events')
        return folder,value

    def large_side_fixture(self,folder,tail=None):
        path=folder/'webgl-source/sqlite-source/source-side.json'
        path.parent.mkdir(parents=True,exist_ok=True)
        # A real >16 MiB JSON document, without allocating a giant fixture string.
        with path.open('wb') as stream:
            stream.write(b'{"padding":"')
            for _ in range(16):stream.write(b'x'*(1024*1024))
            stream.write(b'","tail":'+json.dumps(tail).encode('utf-8')+b'}')
        return path

    def plan(self,**kwargs):return reset.inventory(self.root,set(),**kwargs)
    def apply(self,plan,**kwargs):
        return reset.apply(self.root,plan,reset.CONFIRM,git_files=set(),process_rows=kwargs.get('process_rows',[]))

    def browser_profile_fixture(self,relative=None):
        profile=self.root/(relative or 'runtime/replay/browser-profile-12345678-1234-4234-8234-123456789abc')
        self.write(profile/'Local State',{})
        (profile/'Default').mkdir()
        (profile/'DevToolsActivePort').write_text('12345\n/devtools/browser/test',encoding='utf-8')
        internal=profile/'FirstPartySetsPreloaded/2025.7.24.0/sets.json'
        internal.parent.mkdir(parents=True)
        internal.write_text('{"primary":"https://example.test"}\n{"primary":"https://other.test"}\n',encoding='utf-8')
        return profile,internal

    def test_browser_profile_retained_with_neighbor_transitive_dependencies(self):
        profile,internal=self.browser_profile_fixture()
        original=internal.read_bytes()
        dependency,dep_manifest=self.make_run_fixture('run-profile-dependency')
        discard,_=self.make_run_fixture('run-profile-discard')
        self.write(self.old/'dependency.json',dict(source=dep_manifest['run_id']))
        receipt=self.root/'runtime/replay/launch-test.jsonl'
        receipt.write_text(json.dumps(dict(run_directory=str(self.old),run_id=self.manifest['run_id']))+'\n',encoding='utf-8')
        self.write(self.root/'runtime/replay/replay-sidecar.json',dict(run_id=self.manifest['run_id']))
        plan=self.plan()
        self.assertEqual([r['path'] for r in plan['runs']],[str(discard)])
        self.assertTrue({str(self.old),str(dependency)}<={r['path'] for r in plan['skipped']})
        records={r['path']:r for r in plan['dependency_metadata']}
        self.assertIn(str(receipt),records)
        self.assertIn(str(receipt.parent/'replay-sidecar.json'),records)
        self.assertNotIn(str(internal),records)
        retained=records[str(profile)]
        self.assertEqual(retained['classification'],'retained_third_party_browser_profile')
        self.assertFalse(retained['content_validated_as_simz1_metadata'])
        self.assertGreater(retained['snapshot_entries'],0)
        result=self.apply(plan)
        self.assertEqual(result['status'],'completed')
        self.assertFalse(discard.exists())
        self.assertTrue(self.old.exists() and dependency.exists())
        self.assertEqual(internal.read_bytes(),original)

    def test_browser_profile_does_not_hide_invalid_neighbor(self):
        self.browser_profile_fixture()
        path=self.root/'runtime/replay/replay-sidecar.json'
        path.write_text('{"source":',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'Invalid JSON document'):self.plan()
        self.assertTrue((self.old/'events.gz').exists())
        self.assertFalse((self.root/'runtime/maintenance').exists())

    def test_browser_profile_requires_exact_namespace_and_markers(self):
        for relative in ('runtime/replay/browser-profile-not-a-uuid',
                         'runtime/other/browser-profile-12345678-1234-4234-8234-123456789abc',
                         'runtime/replay/browser-profile-12345678-1234-4234-8234-123456789abc-copy'):
            with self.subTest(relative=relative):
                self.browser_profile_fixture(relative)
                self.assertEqual(reset.browser_profiles(self.root),[])
                with patch.object(reset,'DEPENDENCY_ROOTS',(relative,)):
                    with self.assertRaisesRegex(ValueError,'Invalid JSON document'):self.plan()
        profile,internal=self.browser_profile_fixture()
        (profile/'DevToolsActivePort').unlink()  # Temporary fixture only.
        self.assertEqual(reset.browser_profiles(self.root),[])
        with patch.object(reset,'DEPENDENCY_ROOTS',(str(profile),)):
            with self.assertRaisesRegex(ValueError,'Invalid JSON document'):self.plan()

    def test_browser_profile_explicit_cross_reference_fails_closed(self):
        profile,internal=self.browser_profile_fixture()
        reference=self.root/'runtime/replay/replay-sidecar.json'
        for target in (internal,profile/'missing-source.json'):
            with self.subTest(target=target.name):
                # Duplicate keys and Unicode escapes must not hide the crossing.
                value=json.dumps(str(target)).replace('browser','\\u0062rowser')
                reference.write_text('{"source":'+value+',"source":"none"}',encoding='utf-8')
                with self.assertRaisesRegex(ValueError,'Unresolved explicit SimZ1 reference.*browser profile'):self.plan()
                self.assertTrue((self.old/'events.gz').exists())
                self.assertFalse((self.root/'runtime/maintenance').exists())

    def test_browser_profile_reparse_descendant_is_rejected(self):
        profile,internal=self.browser_profile_fixture()
        original=reset.guards.is_link
        with patch.object(reset.guards,'is_link',side_effect=lambda p:p==internal or original(p)):
            with self.assertRaisesRegex(ValueError,'Symlink/junction/reparse'):self.plan()
        self.assertTrue(self.old.exists() and profile.exists())

    def test_browser_profile_snapshot_change_invalidates_plan(self):
        profile,internal=self.browser_profile_fixture()
        plan=self.plan()
        internal.write_bytes(internal.read_bytes()+b'{}\n')
        with self.assertRaisesRegex(ValueError,'changed since plan'):self.apply(plan)
        self.assertTrue(self.old.exists())
        self.assertFalse((self.root/'runtime/maintenance').exists())

    def test_large_offline_frame_runtime_dependency(self):
        path=self.root/'runtime/simz1-conflict-inspection-2099-01-01/frame-input.json'
        path.parent.mkdir(parents=True)
        dependency,dep_manifest=self.make_run_fixture('run-frame-dependency')
        discard,_=self.make_run_fixture('run-frame-discard')
        self.write(self.old/'source.json',dict(run_id=dep_manifest['run_id']))
        with path.open('wb') as stream:
            stream.write(b'{"schema":"simz1-offline-frame-input-v1","padding":"')
            for _ in range(16):stream.write(b'x'*(1024*1024))
            stream.write(b'","provenance":'+json.dumps(dict(run_directory=str(self.old))).encode()+b'}')
        before=reset.sha(path)
        plan=self.plan()
        self.assertEqual([r['path'] for r in plan['runs']],[str(discard)])
        record=next(r for r in plan['dependency_metadata'] if r['path']==str(path))
        self.assertEqual(record['references'],[str(self.old)])
        self.assertLess(len(json.dumps(record)),2000)
        self.assertEqual(record['sha256'],before)
        self.assertEqual(self.apply(plan)['status'],'completed')
        self.assertEqual(reset.sha(path),before)
        self.assertTrue(self.old.exists() and dependency.exists())

    def test_offline_frame_budget_invalid_json_and_snapshot(self):
        path=self.root/'runtime/another-inspection/frame-input.json'
        self.write(path,dict(schema='simz1-offline-frame-input-v1'))
        for value,error in ((b'{"padding":"xxxxxxxxxxxxxxxx"}','Oversized'),(b'{"bad":','Invalid JSON')):
            with self.subTest(error=error):
                path.write_bytes(value)
                with patch.object(reset,'OFFLINE_FRAME_METADATA_BYTES',16):
                    with self.assertRaisesRegex(ValueError,error):self.plan()
                self.assertTrue(self.old.exists())
                self.assertFalse((self.root/'runtime/maintenance').exists())
        self.write(path,dict(schema='simz1-offline-frame-input-v1'))
        plan=self.plan()
        self.write(path,dict(schema='simz1-offline-frame-input-v1',changed=True))
        with self.assertRaisesRegex(ValueError,'changed since plan'):self.apply(plan)
        self.assertTrue(self.old.exists())
        self.assertEqual(reset.dependency_metadata_limit(self.root,path.with_name('other.json')),16*1024*1024)
        self.assertEqual(reset.dependency_metadata_limit(self.root,self.old/'frame-input.json'),16*1024*1024)

    def test_large_browser_report_runtime_dependencies(self):
        folder=self.root/'runtime/validation/new-browser-audit'
        dependency,dep_manifest=self.make_run_fixture('run-browser-report-dependency')
        self.write(self.old/'source.json',dict(run_id=dep_manifest['run_id']))
        source=self.large_side_fixture(folder,dict(run_id=self.manifest['run_id']))
        path=source.rename(folder/'browser-results.json')  # Temporary fixture only.
        plan=self.plan()
        self.assertEqual(plan['runs'],[])
        self.assertTrue({str(self.old),str(dependency)}<={r['path'] for r in plan['skipped']})
        record=next(r for r in plan['dependency_metadata'] if r['path']==str(path))
        self.assertEqual(record['references'],[str(self.old)])
        self.assertLess(len(json.dumps(record)),2000)
        with patch.object(reset,'DIAGNOSTIC_METADATA_BYTES',8):
            with self.assertRaisesRegex(ValueError,'Oversized'):self.plan()
        path.write_text('{"incomplete":',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'Invalid JSON'):self.plan()
        self.assertTrue(self.old.exists())
        self.assertFalse((self.root/'runtime/maintenance').exists())
        self.assertEqual(reset.dependency_metadata_limit(self.root,self.root/'runtime/other/browser-results.json'),16*1024*1024)

    def test_runtime_validation_utf16_jsonl_remains_rejected(self):
        path=self.root/'runtime/validation/diagnostic-records.jsonl'
        path.parent.mkdir(parents=True)
        raw=('['+json.dumps(dict(run_id=self.manifest['run_id']))+']\n{}\n').encode('utf-16')
        path.write_bytes(raw)
        with self.assertRaisesRegex(ValueError,'line=1.*utf-8'):self.plan()
        self.assertEqual(path.read_bytes(),raw)
        self.assertTrue(self.old.exists())
        self.assertFalse((self.root/'runtime/maintenance').exists())

    def journal_denial(self,code=5):
        # Deterministic fault injection, NOT a reproduction of the historical cause.
        error=PermissionError('injected journal replacement denial');error.winerror=code
        return error

    def test_journal_transient_replace_retries_same_bytes_without_repeating_deletes(self):
        plan=self.plan();replace=Path.replace;unlink=Path.unlink
        attempts=[];deleted=[];recovered=False
        def publish(path,destination):
            nonlocal recovered
            raw=path.read_bytes();value=json.loads(raw)
            if not recovered and value['status']=='deleting' and value['removed_file_count']==1:
                attempts.append((path,raw))
                if len(attempts)<3:raise self.journal_denial()
                recovered=True
            return replace(path,destination)
        def remove(path,*args,**kwargs):
            deleted.append(path);return unlink(path,*args,**kwargs)
        with patch.object(Path,'replace',publish), patch.object(Path,'unlink',remove), patch.object(reset.time,'sleep') as sleep:
            result=self.apply(plan)
        self.assertTrue(recovered)
        self.assertEqual(len(attempts),3)
        self.assertTrue(all(item==attempts[0] for item in attempts))
        self.assertEqual([call.args for call in sleep.call_args_list],[(0.05,),(0.10,)])
        self.assertEqual(len(deleted),len(set(deleted)))
        self.assertEqual(result['removed_file_count'],len(deleted))
        self.assertEqual(result['removed_bytes'],plan['bytes'])
        published=json.loads((Path(result['backups'])/'result.json').read_bytes())
        self.assertEqual(published,result);self.assertEqual(published['status'],'completed')

    def test_journal_persistent_replace_keeps_previous_receipt_and_unique_pending_files(self):
        log=self.root/'journal/result.json';self.write(log,dict(status='previous'))
        previous=log.read_bytes();pending=[]
        for _ in range(2):
            denial=self.journal_denial()
            with patch.object(Path,'replace',side_effect=denial) as replace, patch.object(reset.time,'sleep') as sleep:
                with self.assertRaises(reset.JournalPersistenceError) as caught:
                    reset.publish_journal(log,dict(status='pending'))
            error=caught.exception;pending.append(error.temporary)
            self.assertIs(error.__cause__,denial)
            self.assertEqual(error.attempts,4);self.assertEqual(replace.call_count,4)
            self.assertEqual([call.args for call in sleep.call_args_list],[(0.05,),(0.10,),(0.20,)])
            self.assertTrue(all(call.args==(log,) for call in replace.call_args_list))
            self.assertEqual(error.temporary.parent,log.parent)
            self.assertEqual(json.loads(error.temporary.read_bytes()),dict(status='pending'))
            self.assertEqual(log.read_bytes(),previous)
            for detail in ('operation=replace',str(log),str(error.temporary),'winerror=5','attempts=4'):
                self.assertIn(detail,str(error))
        self.assertEqual(len(set(pending)),2)
        self.assertTrue(all(path.exists() for path in pending))

    def test_initial_journal_failure_never_starts_deletion_or_a_second_save_cycle(self):
        plan=self.plan();stderr=io.StringIO()
        with patch.object(Path,'replace',side_effect=self.journal_denial()) as replace, \
                patch.object(Path,'unlink') as unlink, patch.object(Path,'rmdir') as rmdir, \
                patch.object(reset.time,'sleep') as sleep, patch.object(reset.sys,'stderr',stderr):
            with self.assertRaises(reset.JournalPersistenceError) as caught:self.apply(plan)
        self.assertEqual(replace.call_count,4);self.assertEqual(sleep.call_count,3)
        unlink.assert_not_called();rmdir.assert_not_called()
        self.assertTrue(self.old.exists())
        pending=caught.exception.temporary
        self.assertEqual(json.loads(pending.read_bytes())['status'],'preparing')
        self.assertFalse((pending.parent/'result.json').exists())
        self.assertFalse((pending.parent/'file-operations.jsonl').exists())
        self.assertIn('uncommitted temporary is not a receipt',stderr.getvalue())

    def test_journal_failure_after_delete_stops_and_preserves_actual_operation_evidence(self):
        plan=self.plan();replace=Path.replace;unlink=Path.unlink;rmdir=Path.rmdir
        attempts=[];deleted=[];previous=[];stderr=io.StringIO()
        def publish(path,destination):
            value=json.loads(path.read_bytes())
            if value['status']=='deleting' and value['removed_file_count']==1:
                attempts.append(path);previous.append(destination.read_bytes())
                raise self.journal_denial()
            return replace(path,destination)
        def remove(path,*args,**kwargs):
            self.assertFalse(attempts,'Deletion continued after journal failure')
            deleted.append(path);return unlink(path,*args,**kwargs)
        def remove_directory(path,*args,**kwargs):
            self.assertFalse(attempts,'Directory deletion continued after journal failure')
            return rmdir(path,*args,**kwargs)
        with patch.object(Path,'replace',publish), patch.object(Path,'unlink',remove), \
                patch.object(Path,'rmdir',remove_directory), patch.object(reset.time,'sleep'), \
                patch.object(reset.sys,'stderr',stderr):
            with self.assertRaises(reset.JournalPersistenceError) as caught:self.apply(plan)
        self.assertEqual(len(attempts),4);self.assertEqual(len(deleted),1)
        self.assertFalse(deleted[0].exists());self.assertTrue(self.old.exists())
        error=caught.exception
        self.assertEqual(error.destination.read_bytes(),previous[0])
        self.assertTrue(all(raw==previous[0] for raw in previous))
        pending=json.loads(error.temporary.read_bytes())
        self.assertEqual(pending['removed_file_count'],1)
        operations=[json.loads(line) for line in Path(pending['file_operations']).read_text().splitlines()]
        removed=[r for r in operations if r['state']=='removed']
        self.assertEqual([r['path'] for r in removed],[str(deleted[0])])
        self.assertEqual(pending['removed_bytes'],sum(r['bytes'] for r in removed))

    def test_final_journal_failure_cannot_return_completed_receipt(self):
        plan=self.plan();replace=Path.replace;attempts=[];stderr=io.StringIO()
        def publish(path,destination):
            if json.loads(path.read_bytes())['status']=='completed':
                attempts.append(path);raise self.journal_denial()
            return replace(path,destination)
        with patch.object(Path,'replace',publish), patch.object(reset.time,'sleep'), patch.object(reset.sys,'stderr',stderr):
            with self.assertRaises(reset.JournalPersistenceError) as caught:self.apply(plan)
        self.assertEqual(len(attempts),4);self.assertFalse(self.old.exists())
        error=caught.exception
        published=json.loads(error.destination.read_bytes());pending=json.loads(error.temporary.read_bytes())
        self.assertEqual(published['status'],'deleting');self.assertEqual(pending['status'],'completed')
        self.assertEqual(published['removed'],[str(self.old)])
        self.assertEqual(published['removed_bytes'],plan['bytes'])
        self.assertEqual(pending['removed_bytes'],plan['bytes'])
        self.assertIn('uncommitted temporary is not a receipt',stderr.getvalue())

    def test_non_retryable_journal_errors_propagate_immediately(self):
        log=self.root/'journal/result.json';self.write(log,dict(status='previous'));previous=log.read_bytes()
        for original in (PermissionError('no Windows error code'),self.journal_denial(87),OSError(28,'injected disk full')):
            with self.subTest(error=original), patch.object(Path,'replace',side_effect=original) as replace, \
                    patch.object(reset.time,'sleep') as sleep:
                with self.assertRaises(reset.JournalPersistenceError) as caught:
                    reset.publish_journal(log,dict(status='pending'))
                self.assertIs(caught.exception.__cause__,original)
                self.assertEqual(caught.exception.attempts,1);self.assertEqual(replace.call_count,1)
                sleep.assert_not_called();self.assertEqual(log.read_bytes(),previous)
        original=OSError(28,'injected write failure')
        with patch.object(Path,'open',side_effect=original), patch.object(Path,'replace') as replace, \
                patch.object(reset.time,'sleep') as sleep:
            with self.assertRaises(reset.JournalPersistenceError) as caught:
                reset.publish_journal(log,dict(status='pending'))
            self.assertIs(caught.exception.__cause__,original)
            self.assertEqual(caught.exception.operation,'write')
            self.assertEqual(caught.exception.attempts,0)
            replace.assert_not_called();sleep.assert_not_called()
        self.assertEqual(log.read_bytes(),previous)

    def test_diagnostic_save_failure_preserves_original_application_exception(self):
        plan=self.plan();replace=Path.replace;original=PermissionError('original deletion error')
        failures=[];stderr=io.StringIO()
        def publish(path,destination):
            if json.loads(path.read_bytes())['status']=='stopped_partial':
                failures.append(path);raise self.journal_denial()
            return replace(path,destination)
        with patch.object(Path,'unlink',side_effect=original) as unlink, patch.object(Path,'replace',publish), \
                patch.object(reset.time,'sleep'), patch.object(reset.sys,'stderr',stderr):
            with self.assertRaises(PermissionError) as caught:self.apply(plan)
        self.assertIs(caught.exception,original);self.assertEqual(unlink.call_count,1)
        self.assertEqual(len(failures),4);self.assertEqual(len(set(failures)),1)
        pending=json.loads(failures[0].read_bytes())
        self.assertEqual(pending['status'],'stopped_partial');self.assertEqual(pending['removed_file_count'],0)
        self.assertTrue((self.old/'events.gz').exists());self.assertTrue((self.old/'run-manifest.json').exists())
        self.assertIn('original deletion error',stderr.getvalue())
        self.assertIn('diagnostic save also failed',stderr.getvalue())
        self.assertIn('attempts=4',stderr.getvalue())

    def test_json_unicode_runtime_dependency_and_preserved_checks(self):
        dependency,_=self.make_run_fixture('run-unicode-dependency')
        # Both run manifests/read_json and per-run dependency metadata use the
        # same decoder as the external runtime document that blocked C.
        (self.old/'run-manifest.json').write_bytes(b'\xff\xfe'+json.dumps(self.manifest).encode('utf-16-le'))
        (self.old/'dependency.json').write_bytes(b'\xfe\xff'+json.dumps(dict(source=str(dependency))).encode('utf-16-be'))
        source=self.root/'runtime/freight-preflight.json';source.parent.mkdir(parents=True)
        text='{"source":'+json.dumps(str(self.old))+',"source":null,"note":"camión"}'
        formats=(('utf-8',b''),('utf-8',b'\xef\xbb\xbf'),
                 ('utf-16-le',b'\xff\xfe'),('utf-16-be',b'\xfe\xff'))
        for index,(encoding,bom) in enumerate(formats):
            with self.subTest(encoding=encoding,bom=bom):
                raw=bom+text.encode(encoding);source.write_bytes(raw)
                discard,_=self.make_run_fixture('run-unicode-discard-'+str(index))
                plan=self.plan()
                self.assertEqual(reset.read_json(source),json.loads(text))  # duplicate-key behavior unchanged
                row=next(r for r in plan['dependency_metadata'] if r['path']==str(source))
                self.assertEqual(row['sha256'],hashlib.sha256(raw).hexdigest())
                self.assertEqual(row['bytes'],len(raw));self.assertEqual(row['limit_bytes'],16*1024*1024)
                self.assertEqual(row['references'],[str(self.old)])  # escaped Windows path before duplicate key
                self.assertNotIn('text',row)
                self.assertEqual(source.read_bytes(),raw)
                self.assertEqual([r['path'] for r in plan['runs']],[str(discard)])
                self.apply(plan)  # includes check_preserved on the external UTF-16 document
                self.assertFalse(discard.exists())
                self.assertTrue(self.old.exists());self.assertTrue(dependency.exists())
                self.assertEqual(source.read_bytes(),raw)

    def test_json_encoding_or_syntax_errors_never_publish_or_delete(self):
        source=self.root/'runtime/freight-preflight.json';self.write(source,{})
        plan=self.plan();destination=self.root/'runtime/maintenance/unusable-plan.json'
        cases=(
            (b'{"x":"\xe9"}', 'Invalid JSON encoding'),  # no cp1252 fallback
            (b'\xff', 'Invalid JSON encoding'),
            (b'\xef\xbb', 'Invalid JSON encoding'),
            (b'\xff\xfe{\x00x', 'Invalid JSON encoding'),  # odd UTF-16 byte count
            (b'\xfe\xff\xd8\x00', 'Invalid JSON encoding'),  # unpaired surrogate
            (b'\xef\xbb\xbf', 'Invalid JSON document'),
            (b'\xff\xfe'+ '{"x":'.encode('utf-16-le'), 'Invalid JSON document'),
            (b'\xfe\xff'+ '{"x":NaN}'.encode('utf-16-be'), 'Invalid JSON document'),
            ('{"x":1}'.encode('utf-16-le'), 'Invalid JSON document'),  # no BOM: strict UTF-8
            (b'\xff\xfe\x00\x00'+'{}'.encode('utf-32-le'), 'Unsupported JSON encoding: UTF-32 BOM'),
            (b'\x00\x00\xfe\xff'+'{}'.encode('utf-32-be'), 'Unsupported JSON encoding: UTF-32 BOM'),
        )
        for raw,reason in cases:
            with self.subTest(raw=raw):
                source.write_bytes(raw)
                with self.assertRaises(ValueError) as caught:self.apply(plan)
                message=str(caught.exception)
                self.assertIn(reason,message);self.assertIn(str(source),message)
                self.assertIn(f'size={len(raw)} bytes',message)
                self.assertIn('limit=16777216 bytes',message)
                with patch.object(reset,'tracked',return_value=set()):
                    self.assertEqual(reset.main(['--project',str(self.root),'--plan',str(destination)]),1)
                self.assertFalse(destination.exists());self.assertTrue(self.old.exists())
                self.assertFalse((self.root/'runtime/maintenance').exists())

    def test_equivalent_json_reencoding_invalidates_plan_and_original_hash(self):
        source=self.root/'runtime/freight-preflight.json';source.parent.mkdir(parents=True)
        text='{"note":"same logical JSON"}'
        original=b'\xff\xfe'+text.encode('utf-16-le')
        replacement=b'\xfe\xff'+text.encode('utf-16-be')
        source.write_bytes(original);plan=self.plan();before=source.stat()
        source.write_bytes(replacement)
        os.utime(source,ns=(before.st_atime_ns,before.st_mtime_ns))
        self.assertEqual(source.stat().st_size,before.st_size)
        self.assertEqual(source.stat().st_mtime_ns,before.st_mtime_ns)
        self.assertEqual(reset.read_json(source),json.loads(text))
        row=next(r for r in plan['dependency_metadata'] if r['path']==str(source))
        self.assertNotEqual(row['sha256'],reset.sha(source))
        with self.assertRaisesRegex(ValueError,'changed'):self.apply(plan)
        self.assertTrue(self.old.exists());self.assertFalse((self.root/'runtime/maintenance').exists())

    def test_utf16_change_during_reading_rejected(self):
        source=self.root/'runtime/freight-preflight.json';source.parent.mkdir(parents=True)
        raw=b'\xff\xfe'+'{"marker":"change-during-decode"}'.encode('utf-16-le')
        source.write_bytes(raw);decode=reset.decode_json_document;changed=False
        def mutate(content):
            nonlocal changed
            text=decode(content)
            if content==raw and not changed:
                with source.open('ab') as stream:stream.write(b' \x00')
                changed=True
            return text
        with patch.object(reset,'decode_json_document',side_effect=mutate):
            with self.assertRaisesRegex(ValueError,'Metadata changed during reading'):self.plan()
        self.assertTrue(changed);self.assertTrue(self.old.exists())

    def test_json_bom_support_does_not_extend_jsonl(self):
        source=self.protected/'unicode.jsonl'
        self.assertEqual(reset.JSONL_LINE_BYTES,1024*1024)
        self.assertEqual(reset.JSONL_TOTAL_BYTES,256*1024*1024)
        for encoding,bom in (('utf-8',b'\xef\xbb\xbf'),('utf-16-le',b'\xff\xfe'),
                             ('utf-16-be',b'\xfe\xff'),('utf-32-le',b'\xff\xfe\x00\x00'),
                             ('utf-32-be',b'\x00\x00\xfe\xff')):
            source.write_bytes(bom+'{}\n'.encode(encoding))
            with self.subTest(encoding=encoding), self.assertRaises(ValueError):self.plan()
        source.write_bytes(b'{}\n')
        with patch.object(reset,'decode_json_document',side_effect=AssertionError('JSONL used JSON decoder')):
            row=reset.read_jsonl_metadata(source,[],total_limit=reset.JSONL_TOTAL_BYTES,line_limit=reset.JSONL_LINE_BYTES)
        self.assertEqual(row['records'],1)

    def test_plan_read_only_absolute_and_apply_only_selected(self):
        protected=(self.protected/'events.gz').read_bytes()
        base=self.root/'scenarios/zona1/network.xml';base.write_text('<network/>')
        plan=self.plan()
        self.assertEqual([r['path'] for r in plan['runs']],[str(self.old)])
        self.assertEqual(plan['runs'][0]['run_id'],self.manifest['run_id'])
        self.assertTrue(all(Path(row['path']).is_absolute() for row in plan['runs'][0]['entries']))
        self.assertFalse((self.root/'runtime').exists())
        result=self.apply(plan)
        self.assertFalse(self.old.exists())
        self.assertEqual((self.protected/'events.gz').read_bytes(),protected)
        self.assertEqual(base.read_text(),'<network/>')
        self.assertEqual(result['removed_bytes'],plan['bytes'])
        self.assertEqual(result['observed_free_delta_bytes'],result['free_bytes_after']-result['free_bytes_before'])
        self.assertIn('cannot restore',result['warning'])

    def test_missing_or_changed_mandatory_exclusion_prevents_plan(self):
        path=self.protected/'run-manifest.json'
        value=json.loads(path.read_text());value['run_id']='simz1-'+'f'*32;self.write(path,value)
        with self.assertRaisesRegex(ValueError,'protected'):self.plan()
        path.unlink()
        with self.assertRaises(OSError):self.plan()
        self.assertTrue(self.old.exists())

    def test_plan_cannot_remove_default_exclusion(self):
        plan=self.plan();plan['exclusions']=[]
        with self.assertRaisesRegex(ValueError,'changed'):self.apply(plan)
        self.assertTrue(self.old.exists())

    def test_confirmation_and_obsolete_schema_rejected(self):
        plan=self.plan()
        with self.assertRaisesRegex(ValueError,'Confirmation'):
            reset.apply(self.root,plan,'yes',git_files=set(),process_rows=[])
        for version in (1,2,3):
            plan['schema_version']=version
            with self.assertRaisesRegex(ValueError,'obsolete'):self.apply(plan)

    def test_large_valid_replay_metadata_is_compact_and_plan_is_read_only(self):
        source=self.large_side_fixture(self.old)
        before=reset.snapshot(self.root,self.root/'scenarios')
        digest=reset.sha(source)
        self.assertGreater(source.stat().st_size,reset.DEFAULT_METADATA_BYTES)
        self.assertLess(source.stat().st_size,reset.SQLITE_METADATA_BYTES)
        plan=self.plan()
        self.assertEqual(plan['schema_version'],4)
        self.assertEqual(reset.snapshot(self.root,self.root/'scenarios'),before)
        self.assertEqual(reset.sha(source),digest)
        row=next(row for row in plan['dependency_metadata'] if row['path']==str(source))
        self.assertEqual(row['sha256'],digest)
        self.assertEqual(row['limit_bytes'],128*1024*1024)
        self.assertEqual(row['references'],[])
        self.assertTrue(all('text' not in item for item in plan['dependency_metadata']))
        self.assertLess(len(json.dumps(plan)),64*1024)
        self.assertEqual([r['path'] for r in plan['runs']],[str(self.old)])
        result=self.apply(plan)
        self.assertEqual(result['removed'],[str(self.old)])
        self.assertFalse(source.exists())
        self.assertEqual((self.protected/'events.gz').read_bytes(),b'protected failed evidence')

    def test_large_physical_contract_runtime_diagnostic_dependency(self):
        dependency,_=self.make_run_fixture('run-physical-dependency')
        discard,_=self.make_run_fixture('run-physical-discard')
        self.write(self.old/'dependency.json',dict(source=str(dependency)))
        source=self.large_side_fixture(self.root/'fixture-staging')
        destination=self.root/'runtime/physical-contract-20990101/raw-final-ledger-run-new.json'
        destination.parent.mkdir(parents=True);source.replace(destination)
        escaped=self.manifest['run_id'].replace('simz1-',r'\u0073imz1\u002d')
        with destination.open('r+b') as stream:
            stream.seek(-1,os.SEEK_END)
            stream.write((',"source":"'+escaped+'","source":null}').encode('utf-8'))
        before=reset.sha(destination)
        plan=self.plan()  # Same metadata/inventory route as C, only in this temporary repository.
        row=next(r for r in plan['dependency_metadata'] if r['path']==str(destination))
        self.assertGreater(row['bytes'],16*1024*1024)
        self.assertEqual(row['limit_bytes'],128*1024*1024)
        self.assertEqual(row['sha256'],before)
        self.assertEqual(row['references'],[str(self.old)])
        self.assertLess(len(json.dumps(plan)),64*1024)
        self.assertEqual([r['path'] for r in plan['runs']],[str(discard)])
        self.apply(plan)
        self.assertFalse(discard.exists());self.assertTrue(self.old.exists());self.assertTrue(dependency.exists())
        self.assertEqual(reset.sha(destination),before)

    def test_physical_contract_budget_scope_corruption_and_changes(self):
        source=self.root/'runtime/physical-contract-20990101/independent-another-run.json'
        self.write(source,dict(note='original'));plan=self.plan()
        self.assertEqual(reset.dependency_metadata_limit(self.root,source),128*1024*1024)
        for relative in ('runtime/generic.json','runtime/other/independent-another-run.json',
                         'runtime/physical-contract-not-a-date/ledger.json'):
            self.assertEqual(reset.dependency_metadata_limit(self.root,self.root/relative),16*1024*1024)
        self.assertEqual(reset.DEFAULT_METADATA_BYTES,16*1024*1024)
        destination=self.root/'runtime/maintenance/unusable-plan.json'
        for raw in (b'{"note":',b'{} trailing',b'{"note":NaN}'):
            source.write_bytes(raw)
            with self.assertRaisesRegex(ValueError,'Invalid JSON document'):self.apply(plan)
            with patch.object(reset,'tracked',return_value=set()):
                self.assertEqual(reset.main(['--project',str(self.root),'--plan',str(destination)]),1)
            self.assertFalse(destination.exists());self.assertTrue(self.old.exists())
        self.write(source,dict(note='original'));plan=self.plan();before=source.stat()
        self.write(source,dict(note='modified'))
        os.utime(source,ns=(before.st_atime_ns,before.st_mtime_ns))
        self.assertEqual(source.stat().st_size,before.st_size)
        with self.assertRaisesRegex(ValueError,'changed'):self.apply(plan)
        self.assertTrue(self.old.exists())
        with patch.object(reset,'DIAGNOSTIC_METADATA_BYTES',8):
            with self.assertRaisesRegex(ValueError,'limit=8 bytes.*Oversized'):self.plan()
            with patch.object(reset,'tracked',return_value=set()):
                self.assertEqual(reset.main(['--project',str(self.root),'--plan',str(destination)]),1)
        self.assertFalse(destination.exists());self.assertTrue(self.old.exists())

    def test_reference_after_old_limit_protects_transitive_dependency_during_apply(self):
        dependency,_=self.make_run_fixture('run-dependency')
        discard,_=self.make_run_fixture('run-discard')
        source=self.large_side_fixture(self.protected,dict(source=self.manifest['run_id']))
        self.write(self.old/'dependency.json',dict(source=str(dependency/'events.gz')))
        digest=reset.sha(source)
        plan=self.plan()
        row=next(row for row in plan['dependency_metadata'] if row['path']==str(source))
        self.assertEqual(row['references'],[str(self.old)])
        self.assertEqual([r['path'] for r in plan['runs']],[str(discard)])
        self.assertTrue(any(edge['target']==str(dependency) for edge in plan['dependencies']))
        # check_preserved must rescan the large retained document with the same
        # identity universe and compare references, hash and snapshot coherently.
        self.apply(plan)
        self.assertFalse(discard.exists())
        self.assertTrue(self.old.exists())
        self.assertTrue(dependency.exists())
        self.assertEqual(reset.sha(source),digest)

    def test_oversized_sqlite_metadata_rejected_before_payload_read(self):
        path=self.root/'output/replay/sqlite-source/source-side.json'
        path.parent.mkdir(parents=True)
        # Sparse/zero-filled temporary file: rejection is by size, before JSON.
        size=reset.SQLITE_METADATA_BYTES+1
        with path.open('wb') as stream:stream.truncate(size)
        with self.assertRaises(ValueError) as caught:self.plan()
        message=str(caught.exception)
        self.assertIn(str(path),message)
        self.assertIn(f'size={size} bytes',message)
        self.assertIn(f'limit={reset.SQLITE_METADATA_BYTES} bytes',message)
        self.assertIn('Oversized',message)
        self.assertTrue(self.old.exists())
        self.assertFalse((self.root/'runtime').exists())

    def test_large_budget_does_not_raise_generic_or_read_json_limits(self):
        source=self.large_side_fixture(self.old)
        with self.assertRaisesRegex(ValueError,f'limit={reset.DEFAULT_METADATA_BYTES} bytes'):
            reset.read_json(source)
        # Both files are actually published by _write_metadata; unrelated JSON
        # (including run/ownership manifests and plans) retains the 16 MiB limit.
        config=source.with_name('source-config.json');source.rename(config)
        self.assertEqual(len(self.plan()['runs']),1)
        ordinary=config.with_name('unrelated.json');config.rename(ordinary)
        with self.assertRaisesRegex(ValueError,f'limit={reset.DEFAULT_METADATA_BYTES} bytes'):
            self.plan()
        self.assertTrue(self.old.exists())

    def test_invalid_or_truncated_metadata_fails_without_deletion(self):
        source=self.large_side_fixture(self.protected)
        plan=self.plan()
        # Invalid suffix after 16 MiB cannot be hidden by a header-only scan.
        with source.open('r+b') as stream:stream.truncate(source.stat().st_size-1)
        with self.assertRaises(ValueError) as caught:self.plan()
        self.assertIn(str(source),str(caught.exception))
        self.assertIn(f'limit={reset.SQLITE_METADATA_BYTES} bytes',str(caught.exception))
        self.assertNotIn('Oversized',str(caught.exception))
        with self.assertRaises(ValueError):self.apply(plan)
        for raw in (b'{"source":',b'{"source":true} trailing',b'{"value":NaN}',b'{"bad":"\xff"}'):
            with self.subTest(raw=raw):
                source.write_bytes(raw)
                with self.assertRaises(ValueError):self.plan()
                with self.assertRaises(ValueError):self.apply(plan)
                self.assertTrue(self.old.exists())
                self.assertFalse((self.root/'runtime').exists())

    def test_large_metadata_changed_between_plan_and_apply_rejected(self):
        source=self.large_side_fixture(self.root/'output/kept-replay','a')
        plan=self.plan();before=source.stat()
        with source.open('r+b') as stream:
            stream.seek(-3,os.SEEK_END);stream.write(b'b')
        os.utime(source,ns=(before.st_atime_ns,before.st_mtime_ns))
        self.assertEqual(source.stat().st_size,before.st_size)
        self.assertEqual(source.stat().st_mtime_ns,before.st_mtime_ns)
        with self.assertRaisesRegex(ValueError,'changed'):self.apply(plan)
        self.assertTrue(self.old.exists())
        self.assertFalse((self.root/'runtime').exists())

    def test_metadata_changed_while_decoding_or_resolving_references_rejected(self):
        source=self.root/'output/replay/source-side.json'
        for phase in ('decode','references'):
            with self.subTest(phase=phase):
                self.write(source,dict(marker='mutate-this-document'))
                changed=False
                loads=reset.json.loads;refers=reset.refers
                def mutate_once(text):
                    nonlocal changed
                    if not changed and 'mutate-this-document' in text:
                        with source.open('ab') as stream:stream.write(b' ')
                        changed=True
                def decode(text,*args,**kwargs):
                    value=loads(text,*args,**kwargs);mutate_once(text);return value
                def resolve(text,*args,**kwargs):
                    value=refers(text,*args,**kwargs);mutate_once(text);return value
                target=reset.json if phase=='decode' else reset
                name='loads' if phase=='decode' else 'refers'
                with patch.object(target,name,side_effect=decode if phase=='decode' else resolve):
                    with self.assertRaisesRegex(ValueError,'changed'):self.plan()
                self.assertTrue(changed)
                self.assertTrue(self.old.exists())
                self.assertFalse((self.root/'runtime').exists())

    def test_large_jsonl_late_escaped_reference_compact_plan_and_transitive_apply(self):
        dependency,_=self.make_run_fixture('run-jsonl-dependency')
        discard,_=self.make_run_fixture('run-jsonl-discard')
        self.write(self.old/'dependency.json',dict(source=str(dependency)))
        source=self.protected/'agent-types.jsonl'
        record=(json.dumps(dict(padding='x'*65536))+'\n').encode('utf-8')
        count=0
        with source.open('wb') as stream:
            while stream.tell()<=reset.DEFAULT_METADATA_BYTES:
                stream.write(record);count+=1
            tail=json.dumps(dict(source=self.manifest['run_id'])).replace('simz1-',r'\u0073imz1\u002d')
            stream.write((tail+'\n').encode('utf-8'));count+=1
        digest=reset.sha(source);before=reset.snapshot(self.root,self.root/'scenarios')
        plan=self.plan()
        self.assertEqual(reset.snapshot(self.root,self.root/'scenarios'),before)
        row=next(r for r in plan['dependency_metadata'] if r['path']==str(source))
        self.assertGreater(row['bytes'],16*1024*1024)
        self.assertEqual(row['limit_bytes'],256*1024*1024)
        self.assertEqual(row['line_limit_bytes'],1024*1024)
        self.assertEqual(row['records'],count)
        self.assertEqual(row['sha256'],digest)
        self.assertEqual(row['references'],[str(self.old)])
        self.assertNotIn('text',row)
        self.assertLess(len(json.dumps(plan)),64*1024)
        self.assertEqual([r['path'] for r in plan['runs']],[str(discard)])
        self.apply(plan)
        self.assertFalse(discard.exists())
        self.assertTrue(self.old.exists());self.assertTrue(dependency.exists())
        self.assertEqual(reset.sha(source),digest)

    def test_jsonl_valid_last_record_no_newline_paths_and_duplicate_escaped_keys(self):
        source=self.protected/'references.jsonl'
        # Raw Windows paths, uppercase normalization, CRLF, non-ASCII UTF-8,
        # escaped names/IDs and duplicate keys all retain conservative references.
        path=str(self.old).replace('/','\\').upper()
        escaped=self.manifest['run_id'].replace('simz1-',r'\u0073imz1\u002d')
        raw=(json.dumps({'ruta':path,'nota':'camión'},ensure_ascii=False)+'\r\n'+
             '{"source":"'+escaped+'","source":null}').encode('utf-8')
        source.write_bytes(raw)
        plan=self.plan()
        row=next(r for r in plan['dependency_metadata'] if r['path']==str(source))
        self.assertEqual(row['records'],2)
        self.assertEqual(row['sha256'],hashlib.sha256(raw).hexdigest())
        self.assertEqual(row['references'],[str(self.old)])
        self.assertEqual(plan['runs'],[])
        # The duplicate escaped value must also work without the plain path row.
        source.write_bytes(raw.split(b'\r\n',1)[1])
        self.assertEqual(self.plan()['runs'],[])

    def test_jsonl_bad_record_after_valid_prefix_never_publishes_or_deletes(self):
        source=self.protected/'records.jsonl';prefix=b'{"ok":1}\n'
        source.write_bytes(prefix);plan=self.plan()
        destination=self.root/'runtime/maintenance/invalid-plan.json'
        for suffix in (b'{"incomplete":',b'{} trailing\n',b'\n',b' \t\r\n',
                       b'{"bad":"\xff"}\n',b'\xef\xbb\xbf{}\n',b'{"bad":NaN}\n'):
            with self.subTest(suffix=suffix):
                source.write_bytes(prefix+suffix)
                with self.assertRaises(ValueError) as caught:self.apply(plan)
                self.assertIn(str(source),str(caught.exception))
                self.assertIn('line=2',str(caught.exception))
                self.assertIn('total_limit=',str(caught.exception))
                with patch.object(reset,'tracked',return_value=set()):
                    self.assertEqual(reset.main(['--project',str(self.root),'--plan',str(destination)]),1)
                self.assertFalse(destination.exists());self.assertTrue(self.old.exists())
                self.assertFalse((self.root/'runtime').exists())
        source.write_bytes(b'\xef\xbb\xbf{}\n')
        with self.assertRaisesRegex(ValueError,'line=1'):self.plan()

    def test_jsonl_small_parameterized_budgets_bound_reads(self):
        source=self.protected/'records.jsonl'
        source.write_bytes(b'{"padding":"'+b'x'*64+b'"}\n')
        with source.open('rb') as real:
            bounded=MagicMock(wraps=real)
            bounded.__enter__.return_value=bounded
            bounded.__exit__.return_value=False
            with patch.object(Path,'open',return_value=bounded):
                with self.assertRaisesRegex(ValueError,'line=1.*line exceeds'):
                    reset.read_jsonl_metadata(source,[],total_limit=128,line_limit=32)
            bounded.readline.assert_called_once_with(33)
        with patch.object(Path,'open') as opening:
            with self.assertRaisesRegex(ValueError,'total_limit=32.*Oversized JSONL'):
                reset.read_jsonl_metadata(source,[],total_limit=32,line_limit=16)
            opening.assert_not_called()
        with patch.object(reset,'JSONL_LINE_BYTES',32):
            with self.assertRaisesRegex(ValueError,'line_limit=32'):self.plan()
        with patch.object(reset,'JSONL_TOTAL_BYTES',32):
            with self.assertRaisesRegex(ValueError,'total_limit=32'):self.plan()
        self.assertTrue(self.old.exists())

    def test_jsonl_changed_during_read_or_between_plan_and_apply(self):
        source=self.root/'output/records.jsonl';source.parent.mkdir(parents=True)
        raw=b'{"marker":"jsonl-mutate"}\n';source.write_bytes(raw)
        loads=reset.json.loads;changed=False
        def mutate(text,*args,**kwargs):
            nonlocal changed
            value=loads(text,*args,**kwargs)
            if not changed and 'jsonl-mutate' in text:
                with source.open('ab') as stream:stream.write(b'{}\n')
                changed=True
            return value
        with patch.object(reset.json,'loads',side_effect=mutate):
            with self.assertRaisesRegex(ValueError,'JSONL changed'):self.plan()
        self.assertTrue(changed);self.assertTrue(self.old.exists())
        source.write_bytes(raw);plan=self.plan();before=source.stat()
        source.write_bytes(raw.replace(b'mutate',b'MUTATE'))
        os.utime(source,ns=(before.st_atime_ns,before.st_mtime_ns))
        with self.assertRaisesRegex(ValueError,'changed'):self.apply(plan)
        self.assertTrue(self.old.exists());self.assertFalse((self.root/'runtime').exists())

    def test_jsonl_new_reference_during_apply_is_checked_before_deletion(self):
        source=self.root/'output/records.jsonl';source.parent.mkdir(parents=True)
        source.write_bytes(b'{}\n');plan=self.plan();idle=reset.idle;calls=0
        def mutate(*args,**kwargs):
            nonlocal calls
            calls+=1
            if calls==2:source.write_text(json.dumps(dict(source=str(self.old)))+'\n',encoding='utf-8')
            return idle(*args,**kwargs)
        with patch.object(reset,'idle',side_effect=mutate):
            with self.assertRaisesRegex(ValueError,'dependency/pointer added'):self.apply(plan)
        self.assertTrue((self.old/'events.gz').exists())

    def test_snapshot_identity_exclusion_and_pointer_changes_rejected(self):
        mutations=(lambda:(self.old/'events.gz').write_bytes(b'changed'),
            lambda:self.write(self.old/'run-manifest.json',dict(self.manifest,status='failed')),
            lambda:(self.protected/'events.gz').write_bytes(b'changed protected evidence'),
            lambda:self.write(self.root/'runtime/workflow/trial.json',dict(run_id=self.manifest['run_id'])))
        for mutation in mutations:
            plan=self.plan();mutation()
            with self.assertRaisesRegex(ValueError,'changed'):self.apply(plan)
            self.assertTrue(self.old.exists())

    def test_transitive_dependencies_of_retained_runs_and_external_replay(self):
        dependency,_=self.make_run_fixture('run-dependency')
        self.write(self.protected/'dependency.json',dict(source=str(self.old/'events.gz')))
        self.write(self.old/'dependency.json',dict(source=str(dependency/'events.gz')))
        plan=self.plan()
        self.assertEqual(plan['runs'],[])
        self.assertTrue(any(e['target']==str(dependency) for e in plan['dependencies']))
        other,_=self.make_run_fixture('run-external')
        self.write(self.root/'output/kept-replay/continuous-manifest.json',dict(run_directory=str(other)))
        self.assertEqual(self.plan()['runs'],[])

    def test_latest_replay_trial_invalidated_without_replacement(self):
        pointers=[self.old.parent/'latest-successful.json',self.old.parent/'latest-attempt.json',
                  self.root/'runtime/replay/latest-replay.json',self.root/'runtime/workflow/trial.json']
        for path in pointers:self.write(path,dict(run_id=self.manifest['run_id'],folder=str(self.old),status='accepted'))
        keep=self.old.parent/'latest-protected.json';self.write(keep,dict(run_id=reset.PROTECTED_ID,folder=str(self.protected)))
        original=keep.read_bytes();plan=self.plan();result=self.apply(plan)
        self.assertTrue(all(not p.exists() for p in pointers))
        self.assertEqual(keep.read_bytes(),original)
        self.assertEqual(len(result['pointer_changes']),4)
        self.assertTrue(all(Path(p['backup']).exists() for p in result['pointer_changes']))

    def test_tracked_pointer_protects_dependency(self):
        trial=self.root/'runtime/workflow/trial.json';self.write(trial,dict(run_id=self.manifest['run_id']))
        plan=reset.inventory(self.root,{'runtime/workflow/trial.json'})
        self.assertEqual(plan['runs'],[])
        self.assertEqual(plan['pointers'],[])

    def test_process_rejection_and_unreadable_process_inventory(self):
        plan=self.plan()
        for row in (dict(ProcessId=999999,Name='python.exe',CommandLine='python server.py '+str(self.old)),
                    dict(ProcessId=999999,Name='java.exe',CommandLine=None),
                    dict(ProcessId=999999,Name='python.exe',CommandLine='python ejecutar_simz1.py')):
            with self.assertRaises(ValueError):self.apply(plan,process_rows=[row])
        self.assertTrue(self.old.exists())

    def test_locks_and_held_files_reject_before_delete(self):
        plan=self.plan()
        with patch.object(reset.guards,'check_file_unused',side_effect=ValueError('Locked fixture')):
            with self.assertRaisesRegex(ValueError,'Locked'):self.apply(plan)
        self.assertTrue((self.old/'run-manifest.json').exists())
        (self.old/'replay.sqlite-wal').write_bytes(b'active')
        self.assertEqual(self.plan()['runs'],[])
        with self.assertRaisesRegex(ValueError,'changed'):self.apply(plan)

    def test_unsafe_paths_reparse_and_hardlinks_are_never_deleted(self):
        for value in ('../outside','scenarios/zona1/bad:stream','scenarios/zona1/ambiguous.','C:relative'):
            with self.assertRaises(ValueError):reset.safe(self.root,value)
        original=reset.guards.is_link
        with patch.object(reset.guards,'is_link',side_effect=lambda p: p==self.old or original(p)):
            with self.assertRaises(ValueError):self.plan()
        os.link(self.old/'events.gz',self.root/'keep-hardlink.gz')
        self.assertEqual(self.plan()['runs'],[])

    def test_sources_tracked_files_and_only_proven_replay_js(self):
        (self.old/'script.js').write_text('source')
        self.assertEqual(self.plan()['runs'],[])
        (self.old/'script.js').unlink()
        replay=self.old/'webgl-continuo';replay.mkdir()
        js=replay/'generated.js';js.write_text('generated payload')
        owner=replay/'continuous-manifest.json'
        self.write(owner,dict(status='complete',run_id=self.manifest['run_id'],
            run_manifest_sha256=reset.sha(self.old/'run-manifest.json'),files=[dict(file=js.name,sha256=reset.sha(js))]))
        self.assertEqual(len(self.plan()['runs']),1)
        js.write_text('changed unowned JS')
        self.assertEqual(self.plan()['runs'],[])
        self.assertEqual(reset.inventory(self.root,{str(js.relative_to(self.root).as_posix())})['runs'],[])

    def test_partial_failure_journal_and_trial_remain_invalid(self):
        trial=self.root/'runtime/workflow/trial.json';self.write(trial,dict(run_id=self.manifest['run_id'],status='accepted'))
        plan=self.plan();unlink=Path.unlink
        def failure(path,*args,**kwargs):
            if path==self.old/'events.gz':raise PermissionError('Injected temporary fixture deletion failure')
            return unlink(path,*args,**kwargs)
        with patch.object(Path,'unlink',failure):
            with self.assertRaises(PermissionError):self.apply(plan)
        journals=list((self.root/'runtime/maintenance').glob('reset-*/result.json'))
        self.assertEqual(len(journals),1)
        result=json.loads(journals[0].read_text())
        self.assertEqual(result['status'],'stopped_partial')
        self.assertEqual(result['pending_operation']['path'],str(self.old/'events.gz'))
        operations=[json.loads(line) for line in Path(result['file_operations']).read_text().splitlines()]
        removed=[row for row in operations if row['state']=='removed' and row['action']=='unlink']
        self.assertEqual(result['removed_bytes'],sum(r['bytes'] for r in removed))
        self.assertEqual(result['removed_file_count'],len(removed))
        self.assertFalse(trial.exists())
        self.assertTrue((self.old/'events.gz').exists())
        self.assertTrue((self.protected/'events.gz').exists())

    def test_new_retained_dependency_during_apply_stops_before_target_deletion(self):
        plan=self.plan();idle=reset.idle;calls=0
        def add_dependency(*args,**kwargs):
            nonlocal calls
            calls+=1
            if calls==2:
                self.write(self.root/'output/retained.json',dict(source=str(self.old)))
            return idle(*args,**kwargs)
        with patch.object(reset,'idle',side_effect=add_dependency):
            with self.assertRaisesRegex(ValueError,'dependency/pointer added'):self.apply(plan)
        self.assertTrue((self.old/'run-manifest.json').exists())

    def test_cli_requires_reviewed_plan_hash_and_cannot_change_exclusions(self):
        plan=self.root/'runtime/maintenance/plan.json';self.write(plan,self.plan())
        with patch.object(reset,'apply') as apply:
            self.assertEqual(reset.main(['--project',str(self.root),'--plan',str(plan),'--apply',
                '--confirm',reset.CONFIRM,'--plan-sha256','0'*64]),1)
            self.assertEqual(reset.main(['--project',str(self.root),'--plan',str(plan),'--apply',
                '--confirm',reset.CONFIRM,'--plan-sha256',reset.sha(plan),'--exclude',str(self.old)]),1)
            apply.assert_not_called()


if __name__=='__main__':unittest.main()
