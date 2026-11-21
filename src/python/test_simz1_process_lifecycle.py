"""Lifecycle fixtures and inert children only: this suite never starts QSim."""
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import gzip

from ejecutar_simz1 import ejecutar_con_salida_en_vivo
from simz1_resource_monitor import (reconcile_processes,process_snapshot,ProcessLedger,
    EventReaderLease,same_process,native_identity,record_process,observe_launch)
from simz1_run import atomic_json, read_atomic_json
from simz1_balanced_launch_report import GrowingEvents


class ProcessLifecycle(unittest.TestCase):
    def setUp(self):
        self.row = dict(pid=900, parent_pid=800, created_utc='2026-11-03T12:00:00.123Z',
                        executable='java.exe', command='java SimZ1 fixture', name='java.exe', role='native_jvm')
        self.manifest = dict(status='running', phase='running', returncode=None)

    def observe(self, rows, complete=True, saved=None):
        return reconcile_processes(self.manifest, dict(identities=saved or [self.row]),
            dict(processes=rows, complete=complete, observed_at='fixture', error=None), Path('fixture'))

    def test_writer_alive_without_movement(self):
        self.assertEqual(self.observe([self.row])['observed_status'], 'writer_alive')

    def test_light_observer_is_not_a_writer_of_its_argument(self):
        observer=dict(self.row,pid=901,name='python.exe',executable='python.exe',
            command='python simz1_resource_monitor.py --observe-run "'+str(Path('fixture').resolve())+'"')
        self.assertEqual(self.observe([observer])['observed_status'],'orphaned/incomplete')

    def test_maven_identity_is_not_native_writer(self):
        maven=dict(self.row,role='maven')
        value=self.observe([maven],saved=[maven])
        self.assertFalse(value['writer_alive'])
        self.assertFalse(value['stream_final'])

    def test_native_gone_with_postprocess_alive_finishes_reader(self):
        owner=dict(self.row,pid=901,role='executor',name='python.exe')
        self.manifest['phase']='validating'
        value=self.observe([owner],saved=[self.row,owner])
        self.assertTrue(value['stream_final'])
        self.assertEqual(value['observed_status'],'postprocessing_alive')

    def test_unknown_never_finalizes_stream(self):
        value=self.observe([],False)
        self.assertIsNone(value['stream_final'])

    def test_terminal_persisted_does_not_close_a_live_native_writer(self):
        self.manifest.update(status='completed',phase='completed',returncode=0)
        value=self.observe([self.row])
        self.assertTrue(value['writer_alive'])
        self.assertFalse(value['stream_final'])

    def test_cross_provider_command_format_is_retained(self):
        java=dict(self.row,identity_source='java_ProcessHandle',command='java SimZ1 fixture')
        cim=dict(self.row,identity_source='Win32_CIM',command='"java" SimZ1 fixture')
        self.assertTrue(same_process(java,cim))
        self.assertFalse(same_process(java,dict(cim,parent_pid=801)))
        value=self.observe([cim],saved=[java])
        self.assertEqual(len(value['command_observations']),1)

    def test_native_birth_is_persisted_without_waiting_for_a_poll(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger=ProcessLedger(tmp,'run-fixture','launch-fixture')
            doc=dict(schema_version=1,run_id='run-fixture',launch_id='launch-fixture',identity=self.row)
            with patch('simz1_resource_monitor.process_snapshot',side_effect=AssertionError('No OS poll needed')):
                ledger.record_native(doc)
            saved=read_atomic_json(Path(tmp)/'process-identities.json')
            self.assertEqual(saved['identities'][0]['pid'],900)
            self.assertEqual(saved['identities'][0]['run_id'],'run-fixture')
            with self.assertRaises(ValueError):ledger.record_native(dict(doc,run_id='foreign'))
            self.assertEqual(read_atomic_json(Path(tmp)/'process-identities.json'),saved)

    def test_native_birth_file_rejects_foreign_launch(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'native-process.json'
            atomic_json(path,dict(schema_version=1,run_id='r',launch_id='l',identity=self.row))
            self.assertEqual(native_identity(tmp,'r','l')['pid'],900)
            with self.assertRaises(ValueError):native_identity(tmp,'r','other')

    def test_pre_manifest_birth_is_atomic_and_does_not_create_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            launch=Path(tmp)/('a'*32);launch.mkdir();run=Path(tmp)/'uncreated-run'
            atomic_json(launch/'request.json',dict(launch_id=launch.name,run_directory=str(run)))
            atomic_json(launch/'state.json',dict(launch_id=launch.name,run_directory=str(run),status='running',phase='prepare',process=dict(self.row,role='launcher')))
            snapshot=dict(processes=[self.row],complete=True,observed_at='fixture',error=None)
            with patch('simz1_resource_monitor.process_snapshot',return_value=snapshot):
                recorded=record_process(900,launch,launch.name,'pipeline')
                observed=observe_launch(launch)
            self.assertFalse(run.exists())
            self.assertIsNone(recorded['run_id'])
            self.assertEqual(len(list((launch/'processes').glob('*.json'))),1)
            self.assertEqual(observed['observed_status'],'supervisor_alive')
            self.assertIsNone(observed['run_id'])
            with patch('simz1_resource_monitor.process_snapshot',return_value=dict(snapshot,complete=False)):
                with self.assertRaises(ValueError):record_process(900,launch,launch.name,'pipeline')
            self.assertEqual(len(list((launch/'processes').glob('*.json'))),1)

    def test_pid_reuse_cannot_adopt_an_older_child(self):
        with tempfile.TemporaryDirectory() as tmp:
            owner=dict(self.row,pid=os.getpid(),created_utc='2026-11-03T12:01:00.000Z')
            older=dict(self.row,pid=999,parent_pid=os.getpid(),created_utc='2026-11-03T12:00:00.000Z')
            snapshot=dict(processes=[owner,older],complete=True,observed_at='fixture',error=None)
            ledger=ProcessLedger(tmp,'r')
            with patch('simz1_resource_monitor.process_snapshot',return_value=snapshot),patch.dict(os.environ,{},clear=True):ledger.capture()
            self.assertEqual([r['pid'] for r in ledger.value['identities']],[os.getpid()])

    def test_missing_writer_and_supervisor_unknown_exit(self):
        value = self.observe([])
        self.assertEqual(value['observed_status'], 'orphaned/incomplete')
        self.assertIsNone(value['returncode'])
        self.assertIsNone(value['death_time_utc'])
        self.assertEqual(self.manifest['status'], 'running')

    def test_reused_pid_is_not_same_process(self):
        value = self.observe([dict(self.row, created_utc='2026-11-03T12:01:00.123Z')])
        self.assertEqual(value['reused_pids'], [900])
        self.assertFalse(value['writer_alive'])

    def test_denied_partial_and_ambiguous_enumeration(self):
        for rows, complete in [([],False), ([dict(self.row,command=None)],True),
                                ([dict(self.row,executable='different.exe')],True)]:
            self.assertEqual(self.observe(rows,complete)['observed_status'], 'unknown')

    def test_postprocessing_lives_after_jvm(self):
        owner = dict(self.row, pid=901, role='executor', name='python.exe')
        self.manifest['phase'] = 'validating'
        value = self.observe([owner], saved=[self.row,owner])
        self.assertEqual(value['observed_status'], 'postprocessing_alive')
        self.assertFalse(value['tree_absent'])

    def test_real_codes_immediate_atomic_pid(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'state.json'
            for expected in (0,7):
                state = {}
                persisted = []
                def save():
                    atomic_json(path,state)
                    persisted.append(json.loads(path.read_text()))
                code = ejecutar_con_salida_en_vivo([sys.executable,'-c',f'import sys;sys.exit({expected})'],
                    io.StringIO(), cwd=tmp, env=os.environ.copy(), process_state=state, on_process=save)
                self.assertEqual(code,expected)
                self.assertIsNone(persisted[0]['returncode'])
                self.assertGreater(persisted[0]['pid'],0)
                self.assertEqual(persisted[-1]['returncode'],expected)

    def test_atomic_state_never_partial(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'state.json'
            atomic_json(path,dict(index=0,payload='x'*10000))
            failures=[]
            stop=threading.Event()
            def read():
                while not stop.is_set():
                    try: self.assertEqual(read_atomic_json(path)['payload'],'x'*10000)
                    except Exception as error: failures.append(str(error))
            thread=threading.Thread(target=read);thread.start()
            try:
                for i in range(30):atomic_json(path,dict(index=i,payload='x'*10000))
            finally:stop.set();thread.join()
            self.assertFalse(failures)

    def test_provisional_eof_then_closed_or_definitively_truncated(self):
        data=gzip.compress(b'<events><event time="1" type="fixture"/></events>')
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'events.gz';path.write_bytes(data[:-12])
            reader=GrowingEvents(path)
            try:
                list(reader.poll())
                self.assertEqual(reader.integrity(True),'provisional_eof')
                self.assertEqual(reader.integrity(False),'truncated_incomplete')
                with path.open('ab') as stream:stream.write(data[-12:])
                list(reader.poll())
                self.assertEqual(reader.integrity(False),'closed_gzip_xml')
            finally:reader.close()

    @unittest.skipUnless(os.name=='nt','Windows process identity')
    def test_observation_client_exit_does_not_own_writer(self):
        # Writer exits by itself after its bounded inert lifetime. No IDE is closed.
        with subprocess.Popen([sys.executable,'-c','import time;time.sleep(4)']) as writer:
            client=subprocess.run([sys.executable,'-c','print("observation client closed")'],capture_output=True)
            self.assertEqual(client.returncode,0)
            self.assertIsNone(writer.poll())
            snapshot=process_snapshot()
            self.assertTrue(snapshot['complete'])
            self.assertTrue(any(r['pid']==writer.pid and r['created_utc'] and r['command'] for r in snapshot['processes']))
            self.assertEqual(writer.wait(timeout=10),0)

    @unittest.skipUnless(os.name=='nt','Windows kernel ownership')
    def test_heavy_reader_exclusive_and_released_on_client_exit(self):
        with tempfile.TemporaryDirectory() as tmp:
            command=[sys.executable,'-B','-c',
                'from simz1_resource_monitor import EventReaderLease\n'
                'import sys\ntry:\n with EventReaderLease(sys.argv[1],0): pass\n'
                'except RuntimeError: sys.exit(7)',tmp]
            # unittest discovery adds python/ only to this interpreter's path.
            # The child must resolve the production module independently of an
            # inherited PYTHONPATH or the parent's working directory.
            module_directory=Path(__file__).resolve().parent
            with EventReaderLease(tmp,0):
                child=subprocess.run(command,cwd=module_directory,capture_output=True,text=True,timeout=10)
                self.assertEqual(child.returncode,7,child.stdout+'\n'+child.stderr)
            child=subprocess.run(command,cwd=module_directory,capture_output=True,text=True,timeout=10)
            self.assertEqual(child.returncode,0,child.stdout+'\n'+child.stderr)

    @unittest.skipUnless(os.name=='nt','Windows process identity')
    def test_inert_supervisor_exit_does_not_invent_writer_death(self):
        # Neither process runs QSim. The orphan writer has a bounded natural life.
        program=('import subprocess,sys\n'
                 'p=subprocess.Popen([sys.executable,"-c","import time;time.sleep(5)"],'
                 'stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)\nprint(p.pid,flush=True)')
        supervisor=subprocess.run([sys.executable,'-c',program],capture_output=True,text=True)
        self.assertEqual(supervisor.returncode,0)
        writer_id=int(supervisor.stdout.strip())
        snapshot=process_snapshot()
        row=next(r for r in snapshot['processes'] if r['pid']==writer_id)
        surrogate=dict(row,role='native_jvm')
        result=self.observe(snapshot['processes'],snapshot['complete'],[surrogate])
        self.assertTrue(result['writer_alive'])
        time.sleep(5)
        after=process_snapshot()
        result=self.observe(after['processes'],after['complete'],[surrogate])
        self.assertEqual(result['observed_status'],'orphaned/incomplete')
        self.assertIsNone(result['death_time_utc']);self.assertIsNone(result['returncode'])


if __name__=='__main__':unittest.main()
