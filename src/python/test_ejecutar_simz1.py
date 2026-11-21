import json
from pathlib import Path
import io
import os
import tempfile
import subprocess
import sys
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
from ejecutar_simz1 import ejecutar, heap_para_ram, diagnostico_log, ejecutar_con_salida_en_vivo
from generate_montecarlo_z1 import generar, SCENARIO

class RunnerTests(unittest.TestCase):
    def test_live_interrupt_stops_process_tree(self):
        # A real parent + grandchild process, no Maven or large simulation.
        pids = []
        class InterruptingLog:
            def write(self, line):
                pids.extend(map(int, line.split()))
                raise KeyboardInterrupt()
            def flush(self):
                pass
        program = ("import subprocess,sys,time,os; "
                   "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(120)']); "
                   "print(os.getpid(),child.pid,flush=True); time.sleep(120)")
        details = {}
        with self.assertRaises(KeyboardInterrupt):
            ejecutar_con_salida_en_vivo([sys.executable, '-u', '-c', program], InterruptingLog(),
                                       cwd=Path.cwd(), env=os.environ.copy(), process_state=details)
        self.assertEqual(details['returncode_origin'], 'terminated_after_exception')
        self.assertIsInstance(details['returncode'], int)
        self.assertEqual(len(pids), 2)
        if os.name == 'nt':
            import ctypes
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel.OpenProcess.restype = ctypes.c_void_p
            kernel.CloseHandle.argtypes = [ctypes.c_void_p]
            kernel.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
            for pid in pids:
                handle = kernel.OpenProcess(0x1000, False, pid)
                if handle:
                    try:
                        code = ctypes.c_ulong()
                        self.assertTrue(kernel.GetExitCodeProcess(handle, ctypes.byref(code)))
                        self.assertNotEqual(code.value, 259, f'Process {pid} still active')
                    finally:
                        kernel.CloseHandle(handle)

    def test_live_stdout_stderr_and_exit_code(self):
        console, log = io.StringIO(), io.StringIO()
        lines = ['[INFO] avance', 'ITERATION 2', '[INFO] MemoryObserver: heap',
                 '[WARN] aviso', '[ERROR] fallo', 'detalle sin palabra clave', '']
        command = [sys.executable, '-u', '-c',
                   f"import sys; lines={lines!r}; "
                   "[(print(line,file=sys.stdout if i%2==0 else sys.stderr,flush=True)) "
                   "for i,line in enumerate(lines)]; sys.exit(7)"]
        with patch('sys.stdout', console):
            code = ejecutar_con_salida_en_vivo(command, log, cwd=Path.cwd(), env=os.environ.copy())
        self.assertEqual(code, 7)
        self.assertEqual(log.getvalue(), '\n'.join(lines)+'\n')
        self.assertEqual(console.getvalue(), '\n'.join(lines[1:5])+'\n')

    def test_iteration_end_and_warnings_do_not_imply_success(self):
        console, log, details, phases = io.StringIO(), io.StringIO(), {}, []
        lines = ['WARN QueueWithBuffer: not fatal', 'WARN CharyparNagelActivityScoring',
                 '### ITERATION 0 ENDS', 'S H U T D O W N --- start shutdown.',
                 'Exception during shutdown', '[ERROR] BUILD FAILURE']
        command = [sys.executable, '-u', '-c',
                   f"import sys; [print(s,flush=True) for s in {lines!r}]; sys.exit(7)"]
        with patch('sys.stdout', console):
            code = ejecutar_con_salida_en_vivo(command, log, cwd=Path.cwd(), env=os.environ.copy(),
                                               process_state=details, on_phase=phases.append)
        self.assertEqual(code, 7)
        self.assertEqual(details['returncode'], 7)
        self.assertEqual(details['returncode_origin'], 'natural_exit')
        self.assertEqual(phases, ['shutdown'])
        self.assertIn('todavia NO esta validada', console.getvalue())
        self.assertIn('Exception during shutdown', log.getvalue())

    def test_heap_thresholds(self):
        self.assertEqual(heap_para_ram(16*1024**3),12)
        self.assertEqual(heap_para_ram(32*1024**3),12)
        self.assertEqual(heap_para_ram(16*1024**3-1),8)
        self.assertEqual(heap_para_ram(None),8)

    def test_oom_outside_tail(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'run.log'
            path.write_text('java.lang.OutOfMemoryError: Java heap space\n'+'line\n'*30000)
            oom,tail=diagnostico_log(path)
            self.assertTrue(oom)
            self.assertEqual(len(tail.splitlines()),20)

    def test_failure_status_and_config_paths_with_spaces(self):
        with tempfile.TemporaryDirectory() as folder:
            directory=Path(folder)/'run with spaces'
            generar(SCENARIO/'config-simz1.xml',directory,17,agents=1,corridor_policy='redistribute',qsim_threads=4)
            executable=Path(folder)/'fake-maven.cmd';executable.write_text('')
            def failure(command,log,**kwargs):
                self.assertIn('--errors', command)
                self.assertIn('-Dexec.mainClass=gt.edu.uvg.sim.zona1.RunZona1Simulation', command)
                active = json.loads((directory/'run-manifest.json').read_text())['admission_execution']
                self.assertEqual(active['storage_policy'], 'strict-receiver-v1')
                self.assertEqual(active['qsim_threads'], 4)
                self.assertEqual(active['verification'], 'requested_config_only')
                self.assertFalse(active['force_after_stuck_time'])
                self.assertEqual(kwargs['env']['MAVEN_OPTS'],'-Xmx12G')
                log.write('java.lang.OutOfMemoryError: Java heap space\n')
                log.write(''.join(f'log-line-{i}\n' for i in range(30)))
                self.assertEqual(kwargs['env']['SIMZ1_CONFIG'],str(directory/'config-simz1.xml'))
                self.assertFalse(any('exec.args' in arg for arg in command))
                return 9
            error_console=io.StringIO()
            with patch('ejecutar_simz1.ejecutar_con_salida_en_vivo',side_effect=failure), patch('ejecutar_simz1.memoria_fisica_bytes',return_value=16*1024**3), patch.dict(os.environ,{'MAVEN_OPTS':'-Xmx1G'}), patch('sys.stderr',error_console):
                with self.assertRaisesRegex(RuntimeError,'codigo 9'):
                    ejecutar(directory,executable,iterations=2,latest_path=Path(folder)/'latest-successful.json')
                self.assertEqual(os.environ['MAVEN_OPTS'],'-Xmx1G')
            self.assertIn('OutOfMemoryError',error_console.getvalue())
            self.assertNotIn('log-line-9\n',error_console.getvalue())
            self.assertTrue(error_console.getvalue().endswith(''.join(f'log-line-{i}\n' for i in range(10,30))))
            status=json.loads((directory/'run-manifest.json').read_text())
            self.assertEqual(status['status'],'failed')
            self.assertEqual(status['returncode'],9)
            self.assertEqual(status['iterations']['requested'],2)
            self.assertEqual(status['heap_gib'],12)
            self.assertTrue(status['out_of_memory_detected'])
            root=ET.parse(directory/'config-simz1.xml').getroot()
            plans=root.find("module[@name='plans']/param[@name='inputPlansFile']").get('value')
            self.assertEqual(Path(plans),directory/'plans.xml')
            (directory/'output').mkdir()
            with self.assertRaisesRegex(ValueError,'sobrescriben'):ejecutar(directory,executable)

    def test_zero_exit_without_artifacts_is_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            directory=Path(folder)/'run'
            generar(SCENARIO/'config-simz1.xml',directory,18,agents=1,corridor_policy='redistribute')
            executable=Path(folder)/'fake.cmd';executable.write_text('')
            def success(command,log,**kwargs):
                self.assertEqual(kwargs['env']['MAVEN_OPTS'],'-Xmx8G')
                return 0
            with patch('ejecutar_simz1.ejecutar_con_salida_en_vivo',side_effect=success), patch('ejecutar_simz1.memoria_fisica_bytes',return_value=8*1024**3):
                with self.assertRaisesRegex(RuntimeError,'salidas esperadas'):
                    ejecutar(directory,executable,iterations=2,latest_path=Path(folder)/'latest-successful.json')
            self.assertEqual(json.loads((directory/'run-manifest.json').read_text())['status'],'failed')

if __name__=='__main__':unittest.main()
